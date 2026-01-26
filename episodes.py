#!/usr/bin/env python3
"""
Episodes command - Find and list episodes from completed downloads

Usage:
    python3 cli.py episodes                    # List all episodes
    python3 cli.py episodes --series "Knight"  # Filter by series name
    python3 cli.py episodes --season 1         # Filter by season
    python3 cli.py episodes --missing           # Show missing episodes
"""

import os
import re
import click
from pathlib import Path
from db import get_connection
from logger import get_logger

logger = get_logger(__name__)

# TMDB API key
TMDB_API_KEY = os.environ.get('TMDB_API_KEY', '')

# Default completed folder
DEFAULT_COMPLETED_DIR = '/home/webseries/downloads/completed'

# Video file extensions
VIDEO_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v'}


def scan_completed_folder(completed_dir: str = DEFAULT_COMPLETED_DIR) -> list[dict]:
    """
    Scan completed folder for video files and extract episode info

    Args:
        completed_dir: Path to completed downloads folder

    Returns:
        List of episode dicts
    """
    episodes = []

    if not os.path.exists(completed_dir):
        logger.warning(f"Completed folder not found: {completed_dir}")
        return episodes

    for root, dirs, files in os.walk(completed_dir):
        for file in files:
            if Path(file).suffix.lower() in VIDEO_EXTENSIONS:
                filepath = os.path.join(root, file)
                filename = os.path.basename(filepath)
                rel_path = os.path.relpath(filepath, completed_dir)

                # Extract series name and episode info
                series_name = extract_series_name(filename)
                season, episode = extract_season_episode(filename)
                quality = extract_quality(filename)
                size_bytes = os.path.getsize(filepath)
                size_mb = int(size_bytes / (1024 * 1024))
                duration = get_video_duration(filepath)

                episodes.append({
                    'series': series_name,
                    'season': season,
                    'episode': episode,
                    'quality': quality,
                    'size_bytes': size_bytes,
                    'size_mb': size_mb,
                    'duration': duration,
                    'filename': filename,
                    'path': rel_path,
                    'full_path': filepath
                })

    return episodes


def extract_series_name(filename: str) -> str:
    """Extract series name from filename"""
    # Remove extension
    name = Path(filename).stem

    # Remove source tags (www.1TamilMV.*)
    name = re.sub(r'www\.[^\s]+\s*-\s*', '', name)

    # Remove year in parentheses
    name = re.sub(r'\s*\(\d{4}\)', '', name)

    # Truncate at episode pattern (everything after S01E01, S01 EP01, etc.)
    # This removes episode titles and technical tags after the episode identifier
    for pattern in [
        r'[Ss]\d+\s*[Ee][Pp]?\s*\d+',  # S01E01 or S01 EP01
        r'\d+x\d+',  # 1x01 pattern
        r'[Ee][Pp]\s*\d+',  # EP01 pattern
    ]:
        match = re.search(pattern, name)
        if match:
            name = name[:match.start()].strip()
            break

    # Remove quality tags
    name = re.sub(r'\[?\d{3,4}[ip]\]?', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\[?(?:480p|720p|1080p|2160p|4K|UHD|FHD|HD|SD)\]?', '', name, flags=re.IGNORECASE)

    # Remove codec and audio tags
    name = re.sub(r'\[?(?:x264|x265|h264|h265|hevc|avc|DDP?|AAC|AC3|DTS)\]?', '', name, flags=re.IGNORECASE)

    # Clean up
    name = re.sub(r'[._\-]+', ' ', name)
    name = ' '.join(name.split())

    return name.strip()


def extract_season_episode(filename: str) -> tuple:
    """Extract (season, episode) from filename, defaults to (1, None)"""
    # Try S01E01 pattern
    match = re.search(r'[Ss](\d+)[Ee](\d+)', filename)
    if match:
        return (int(match.group(1)), int(match.group(2)))

    # Try S01 EP01 pattern (with space)
    match = re.search(r'[Ss](\d+)\s*[Ee][Pp]\s*(\d+)', filename)
    if match:
        return (int(match.group(1)), int(match.group(2)))

    # Try EP01 pattern (just episode)
    match = re.search(r'[Ee][Pp]\s*(\d+)', filename)
    if match:
        return (1, int(match.group(1)))

    # Try 1x01 pattern
    match = re.search(r'(\d+)x(\d+)', filename)
    if match:
        return (int(match.group(1)), int(match.group(2)))

    # Default to season 1
    return (1, None)


def extract_quality(filename: str) -> str:
    """Extract quality from filename"""
    match = re.search(r'(?:\b|_)(\d{3,4}[ip])(?:\b|_)', filename, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return 'Unknown'


def format_size(size_bytes: int) -> str:
    """Format bytes to human readable"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.0f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.0f} PB"


def get_video_duration(filepath: str) -> float:
    """
    Get video duration in minutes using ffprobe

    Args:
        filepath: Path to video file

    Returns:
        float: Duration in minutes, or None if failed
    """
    import subprocess
    import json

    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'json', filepath],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            duration_seconds = float(data.get('format', {}).get('duration', 0))
            # Convert to minutes
            duration_minutes = round(duration_seconds / 60, 2)
            return duration_minutes if duration_minutes > 0 else None
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, ValueError) as e:
        logger.debug(f"Failed to get duration for {filepath}: {e}")
    except FileNotFoundError:
        logger.warning("ffprobe not found. Install ffmpeg to get video durations.")

    return None


def format_duration(minutes: float) -> str:
    """Format minutes to whole number (e.g., '45', '52')"""
    if not minutes:
        return 'N/A'
    return f"{int(minutes)}"


def fetch_tmdb_episode(tmdb_id: int, season_number: int, episode_number: int) -> dict | None:
    """
    Fetch detailed episode data from TMDB

    Args:
        tmdb_id: TMDB series ID
        season_number: Season number (1-based)
        episode_number: Episode number (1-based)

    Returns:
        dict with episode data or None
    """
    if not TMDB_API_KEY:
        logger.warning("TMDB_API_KEY not set, skipping episode metadata fetch")
        return None

    import requests

    base_url = f'https://api.themoviedb.org/3/tv/{tmdb_id}'
    result = {}

    try:
        # 1. Get basic episode details
        response = requests.get(
            f'{base_url}/season/{season_number}/episode/{episode_number}',
            params={'api_key': TMDB_API_KEY},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()

        result.update({
            'tmdb_id': data.get('id'),
            'name': data.get('name'),
            'overview': data.get('overview'),
            'air_date': data.get('air_date'),
            'runtime': data.get('runtime'),
            'still_path': data.get('still_path'),
            'vote_average': data.get('vote_average'),
            'vote_count': data.get('vote_count'),
        })

        # Build still URL
        if result.get('still_path'):
            result['still_url'] = f"https://image.tmdb.org/t/p/original{result['still_path']}"

        logger.info(f"Fetched episode data: S{season_number:02d}E{episode_number:02d} - {result.get('name', 'N/A')}")

    except requests.RequestException as e:
        logger.error(f"Error fetching episode S{season_number:02d}E{episode_number:02d}: {e}")
        return None

    try:
        # 2. Get credits (director, writer, guest stars)
        response = requests.get(
            f'{base_url}/season/{season_number}/episode/{episode_number}/credits',
            params={'api_key': TMDB_API_KEY},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()

        # Get crew (director, writer)
        crew_list = data.get('crew', [])
        directors = [c['name'] for c in crew_list if c.get('job') == 'Director']
        writers = [c['name'] for c in crew_list if c.get('job') in ['Writer', 'Screenplay', 'Teleplay', 'Story']]

        if directors:
            result['director'] = ', '.join(directors)
        if writers:
            result['writer'] = ', '.join(writers)

        # Get guest stars (limit to top 5)
        guest_stars = data.get('guest_stars', [])
        if guest_stars:
            star_names = [
                gs.get('person', {}).get('name', '')
                for gs in guest_stars[:5]
                if gs.get('person', {}).get('name')
            ]
            if star_names:
                result['guest_stars'] = ', '.join(star_names)

    except requests.RequestException as e:
        logger.debug(f"Error fetching episode credits: {e}")

    try:
        # 3. Get external IDs
        response = requests.get(
            f'{base_url}/season/{season_number}/episode/{episode_number}/external_ids',
            params={'api_key': TMDB_API_KEY},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()

        result['imdb_id'] = data.get('imdb_id')
        result['tvdb_id'] = data.get('tvdb_id')

    except requests.RequestException as e:
        logger.debug(f"Error fetching external_ids: {e}")

    return result


def update_episode_metadata(episode_id: int, metadata: dict, dry_run: bool = False) -> bool:
    """
    Update episodes table with TMDB metadata

    Args:
        episode_id: Database episode ID
        metadata: Dict with episode metadata from TMDB
        dry_run: If True, don't make changes

    Returns:
        True on success
    """
    if dry_run:
        logger.info(f"[DRY RUN] Would update episode {episode_id}")
        for key, value in metadata.items():
            if value is not None:
                display_val = str(value)[:50] + '...' if len(str(value)) > 50 else value
                logger.info(f"  {key}: {display_val}")
        return True

    conn = get_connection()
    if not conn:
        return False

    cursor = conn.cursor()

    try:
        # Build dynamic UPDATE query
        fields = []
        values = []

        for field in [
            'imdb_id', 'name', 'overview', 'air_date', 'still_url',
            'vote_average', 'vote_count', 'director', 'writer', 'guest_stars'
        ]:
            if field in metadata and metadata[field] is not None:
                fields.append(f"{field} = %s")
                values.append(metadata[field])

        if not fields:
            logger.warning(f"No metadata to update for episode {episode_id}")
            return False

        values.append(episode_id)
        sql = f"UPDATE episodes SET {', '.join(fields)} WHERE id = %s"
        cursor.execute(sql, values)
        conn.commit()

        logger.info(f"Updated episode {episode_id} with {len(fields)} fields")
        return True

    except Exception as e:
        logger.error(f"Database error updating episode {episode_id}: {e}")
        conn.rollback()
        return False

    finally:
        cursor.close()
        conn.close()


def fetch_and_update_episode_metadata(series_id: int = None, limit: int = 50, dry_run: bool = False) -> int:
    """
    Fetch and update episode metadata from TMDB

    Args:
        series_id: Specific series ID to process (or None for all)
        limit: Max number of episodes to process
        dry_run: If True, don't make changes

    Returns:
        Number of episodes updated
    """
    import requests

    conn = get_connection()
    if not conn:
        return 0

    cursor = conn.cursor(dictionary=True)

    try:
        # Find episodes that need metadata (no name or no imdb_id)
        query = '''
            SELECT e.id, e.episode_number, e.imdb_id, e.name,
                   s.tmdb_id, s.id as series_id, s.title as series_title,
                   sea.season_number
            FROM episodes e
            JOIN seasons sea ON e.season_id = sea.id
            JOIN series s ON sea.series_id = s.id
            WHERE s.tmdb_id IS NOT NULL AND s.tmdb_id != ''
            AND (e.name IS NULL OR e.name = '' OR e.imdb_id IS NULL OR e.imdb_id = '')
        '''

        params = []
        if series_id:
            query += ' AND s.id = %s'
            params.append(series_id)

        query += ' ORDER BY e.id DESC'
        if limit:
            query += ' LIMIT %s'
            params.append(limit)

        cursor.execute(query, tuple(params) if params else ())
        episodes = cursor.fetchall()

        if not episodes:
            logger.info("No episodes found that need metadata")
            return 0

        logger.info(f"Found {len(episodes)} episodes to process")

        updated = 0

        for ep in episodes:
            tmdb_id = ep['tmdb_id']
            season_num = ep['season_number']
            ep_num = ep['episode_number']

            logger.info(f"\nProcessing: {ep['series_title'][:50]}... S{season_num:02d}E{ep_num:02d}")

            # Fetch from TMDB
            metadata = fetch_tmdb_episode(tmdb_id, season_num, ep_num)
            if not metadata:
                logger.warning(f"Could not fetch metadata for S{season_num:02d}E{ep_num:02d}")
                continue

            # Update database
            if update_episode_metadata(ep['id'], metadata, dry_run):
                updated += 1

        return updated

    finally:
        cursor.close()
        conn.close()


def get_episodes_from_db(series_filter: str = None, season_filter: int = None) -> list[dict]:
    """Fetch episodes from database"""
    conn = get_connection()
    if not conn:
        return []

    cursor = conn.cursor(dictionary=True)

    try:
        query = '''
            SELECT
                e.*,
                s.title as series_title,
                sea.season_number,
                sea.year
            FROM episodes e
            JOIN seasons sea ON e.season_id = sea.id
            JOIN series s ON sea.series_id = s.id
            WHERE 1=1
        '''
        params = []

        if series_filter:
            query += ' AND s.title LIKE %s'
            params.append(f'%{series_filter}%')

        if season_filter:
            query += ' AND sea.season_number = %s'
            params.append(season_filter)

        query += ' ORDER BY s.title, sea.season_number, e.episode_number'

        cursor.execute(query, tuple(params) if params else ())
        return cursor.fetchall()

    except Exception as e:
        logger.error(f"Database error: {e}")
        return []

    finally:
        cursor.close()
        conn.close()


def import_episodes_to_db(episodes: list[dict], dry_run: bool = False) -> tuple[int, int]:
    """
    Import scanned episodes into the database

    Args:
        episodes: List of episode dicts from scan_completed_folder
        dry_run: If True, don't actually insert into database

    Returns:
        tuple: (imported_count, skipped_count)
    """
    conn = get_connection()
    if not conn:
        return 0, len(episodes)

    cursor = conn.cursor(dictionary=True)

    # Fetch all seasons for matching
    cursor.execute('''
        SELECT s.id as series_id, s.title, sea.id as season_id, sea.season_number
        FROM series s
        JOIN seasons sea ON s.id = sea.series_id
    ''')
    seasons_data = cursor.fetchall()

    # Build a searchable index: (normalized_series_name, season_number) -> season_id
    from difflib import SequenceMatcher

    def clean_title(name: str) -> str:
        """Clean title by removing technical details and season/episode info"""
        # Remove year in parentheses
        name = re.sub(r'\s*\(\d{4}\)', '', name)

        # Truncate at season/episode pattern (S01, S01 EP, etc.)
        for pattern in [
            r'\s+[Ss]\d+\s*[Ee][Pp]?\s*\(?\d+',  # S01 EP(01-02)
            r'\s+[Ss]\d+\s+[Ee][Pp]',  # S01 EP
            r'\s+TRUE\s+WEB-DL',  # TRUE WEB-DL marker
            r'\s+WEBRip',  # WEBRip marker
        ]:
            match = re.search(pattern, name)
            if match:
                name = name[:match.start()].strip()
                break

        # Remove quality tags
        name = re.sub(r'\[?\d{3,4}[ip]\]?', '', name, flags=re.IGNORECASE)
        name = re.sub(r'\[?(?:480p|720p|1080p|2160p|4K|UHD|FHD|HD|SD)\]?', '', name, flags=re.IGNORECASE)

        # Remove codec and audio tags
        name = re.sub(r'\[?(?:x264|x265|h264|h265|hevc|avc|DDP?|AAC|AC3|DTS)\]?', '', name, flags=re.IGNORECASE)

        # Remove bracketed content at end
        name = re.sub(r'\s*\[.*?\]', '', name)

        # Clean up
        name = re.sub(r'[._\-]+', ' ', name)
        name = ' '.join(name.split())

        return name.strip()

    def normalize(name: str) -> str:
        return re.sub(r'[^a-z0-9]', '', name.lower())

    seasons_index = {}
    for season in seasons_data:
        cleaned = clean_title(season['title'])
        norm_title = normalize(cleaned)
        seasons_index[(norm_title, season['season_number'])] = season['season_id']

    imported = 0
    skipped = 0
    errors = 0

    for ep in episodes:
        series_name = ep['series']
        season_num = ep['season']
        episode_num = ep['episode']

        if not episode_num:
            logger.debug(f"Skipping (no episode number): {ep['filename']}")
            skipped += 1
            continue

        # Try to find matching season
        norm_series = normalize(series_name)
        season_id = None

        # Direct match
        if (norm_series, season_num) in seasons_index:
            season_id = seasons_index[(norm_series, season_num)]
        else:
            # Try fuzzy match
            best_match = None
            best_ratio = 0.7  # Minimum similarity threshold
            for (norm_title, sn), sid in seasons_index.items():
                if sn == season_num:
                    ratio = SequenceMatcher(None, norm_series, norm_title).ratio()
                    if ratio > best_ratio:
                        best_ratio = ratio
                        best_match = sid
            season_id = best_match

        if not season_id:
            logger.warning(f"No matching season found: {series_name} S{season_num:02d}")
            skipped += 1
            continue

        # Find matching torrent by episode number
        torrent_id = None
        torrent_quality = None
        cursor.execute('''
            SELECT id, name, quality FROM torrents
            WHERE season_id = %s
        ''', (season_id,))
        torrents = cursor.fetchall()

        for torrent in torrents:
            # Extract episode from torrent name
            _, t_ep = extract_season_episode(torrent['name'])
            if t_ep == episode_num:
                torrent_id = torrent['id']
                torrent_quality = torrent['quality']
                break

            # Check for batch torrent pattern "EP (01-03)" or "EP(01-03)"
            batch_match = re.search(r'[Ee][Pp]?\s*\(?(\d+)\s*-\s*(\d+)\)?', torrent['name'])
            if batch_match:
                start_ep = int(batch_match.group(1))
                end_ep = int(batch_match.group(2))
                if start_ep <= episode_num <= end_ep:
                    torrent_id = torrent['id']
                    torrent_quality = torrent['quality']
                    break

        # Use torrent quality if available, otherwise fall back to extracted quality
        quality = torrent_quality if torrent_quality else ep['quality']

        # Check if episode already exists
        cursor.execute(
            'SELECT id FROM episodes WHERE season_id = %s AND episode_number = %s',
            (season_id, episode_num)
        )
        if cursor.fetchone():
            logger.debug(f"Already exists: S{season_num:02d}E{episode_num:02d}")
            skipped += 1
            continue

        if dry_run:
            t_info = f", torrent_id={torrent_id}" if torrent_id else ""
            d_info = f", duration={ep.get('duration')}" if ep.get('duration') else ""
            logger.info(f"Would insert: S{season_num:02d}E{episode_num:02d} -> season_id={season_id}{t_info}{d_info}")
            imported += 1
        else:
            try:
                duration = ep.get('duration')
                if torrent_id:
                    if duration is not None:
                        cursor.execute('''
                            INSERT INTO episodes (season_id, episode_number, status, file_path, file_size_mb, quality, torrent_id, duration_min)
                            VALUES (%s, %s, 1, %s, %s, %s, %s, %s)
                        ''', (season_id, episode_num, ep['path'], ep['size_mb'], quality, torrent_id, duration))
                    else:
                        cursor.execute('''
                            INSERT INTO episodes (season_id, episode_number, status, file_path, file_size_mb, quality, torrent_id)
                            VALUES (%s, %s, 1, %s, %s, %s, %s)
                        ''', (season_id, episode_num, ep['path'], ep['size_mb'], quality, torrent_id))
                else:
                    if duration is not None:
                        cursor.execute('''
                            INSERT INTO episodes (season_id, episode_number, status, file_path, file_size_mb, quality, duration_min)
                            VALUES (%s, %s, 1, %s, %s, %s, %s)
                        ''', (season_id, episode_num, ep['path'], ep['size_mb'], quality, duration))
                    else:
                        cursor.execute('''
                            INSERT INTO episodes (season_id, episode_number, status, file_path, file_size_mb, quality)
                            VALUES (%s, %s, 1, %s, %s, %s)
                        ''', (season_id, episode_num, ep['path'], ep['size_mb'], quality))
                conn.commit()
                imported += 1
                logger.info(f"Imported: S{season_num:02d}E{episode_num:02d}")
            except Exception as e:
                logger.error(f"Failed to insert S{season_num:02d}E{episode_num:02d}: {e}")
                errors += 1

    cursor.close()
    conn.close()

    logger.info(f"Import complete: {imported} imported, {skipped} skipped" + (f", {errors} errors" if errors else ""))
    return imported, skipped


@click.command()
@click.option('--scan', is_flag=True, help='Scan completed folder for episodes')
@click.option('--import-db', is_flag=True, help='Import scanned episodes into database')
@click.option('--fetch-metadata', is_flag=True, help='Fetch episode metadata from TMDB')
@click.option('--dry-run', is_flag=True, help='Show what would be imported without actually importing')
@click.option('--series-id', type=int, help='Process specific series by ID (for --fetch-metadata)')
@click.option('--limit', type=int, default=50, help='Max episodes to process (for --fetch-metadata)')
@click.option('--series', help='Filter by series name')
@click.option('--season', type=int, help='Filter by season number')
@click.option('--missing', is_flag=True, help='Show missing episodes')
@click.option('--completed-dir', default=DEFAULT_COMPLETED_DIR, help='Completed downloads folder')
@click.pass_context
def episodes(ctx, scan, import_db, fetch_metadata, dry_run, series_id, limit, series, season, missing, completed_dir):
    """Find and list episodes from completed downloads"""

    # Fetch metadata from TMDB
    if fetch_metadata:
        if dry_run:
            logger.info("=" * 60)
            logger.info("DRY RUN MODE - No changes will be made")
            logger.info("=" * 60)

        updated = fetch_and_update_episode_metadata(
            series_id=series_id,
            limit=limit,
            dry_run=dry_run
        )

        logger.info(f"Updated {updated} episodes")
        if dry_run:
            logger.info("DRY RUN - No changes were made")
        return

    # Scan completed folder (needed for both --scan and --import-db)
    if scan or import_db:
        logger.info(f"Scanning completed folder: {completed_dir}")
        eps = scan_completed_folder(completed_dir)

        if not eps:
            logger.warning("No episodes found")
            return

        # Import to database if requested
        if import_db:
            if dry_run:
                logger.info("Dry run mode - showing what would be imported:")
            import_episodes_to_db(eps, dry_run=dry_run)
            return

        # Group by series
        series_eps = {}
        for ep in eps:
            key = ep['series']
            if key not in series_eps:
                series_eps[key] = []
            series_eps[key].append(ep)

        # Display results
        for series_name, episodes_list in sorted(series_eps.items()):
            # Apply filters
            if series and series.lower() not in series_name.lower():
                continue
            if season and any(e['season'] != season for e in episodes_list):
                continue

            click.echo(f"\n{series_name}")
            click.echo("-" * 50)

            # Sort by season, episode
            episodes_list.sort(key=lambda x: (x['season'], x['episode'] or 999))

            for ep in episodes_list:
                s_num = ep['season']
                e_num = ep['episode']
                e_str = f"S{s_num:02d}E{e_num:02d}" if e_num else f"S{s_num:02d}"
                click.echo(f"  {e_str} - {ep['quality']} - {ep['size_human']}")
    else:
        # Query from database
        eps = get_episodes_from_db(series, season)

        if not eps:
            logger.warning("No episodes found in database")
            logger.info("Use --scan to scan completed folder")
            return

        # Group by series
        series_eps = {}
        for ep in eps:
            key = f"{ep['series_title']} ({ep.get('year', 'N/A')})"
            if key not in series_eps:
                series_eps[key] = []
            series_eps[key].append(ep)

        # Display results
        for series_name, episodes_list in sorted(series_eps.items()):
            click.echo(f"\n{series_name}")
            click.echo("-" * 50)

            for ep in episodes_list:
                status_icon = "✓" if ep['status'] == 1 else "?"
                e_str = f"S{ep['season_number']:02d}E{ep['episode_number']:02d}"
                quality = ep.get('quality', 'Unknown')
                size_mb = ep.get('file_size_mb')
                size_str = f"{size_mb} MB" if size_mb else "Unknown"
                click.echo(f"  {status_icon} {e_str} - {quality} - {size_str}")

    if missing:
        # Show missing episodes logic could go here
        click.echo("\n(Missing episodes feature - requires episode count from seasons table)")
