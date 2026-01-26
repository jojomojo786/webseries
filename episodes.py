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
                size = os.path.getsize(filepath)
                duration = get_video_duration(filepath)

                episodes.append({
                    'series': series_name,
                    'season': season,
                    'episode': episode,
                    'quality': quality,
                    'size': size,
                    'size_human': format_size(size),
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
        cursor.execute('''
            SELECT id, name FROM torrents
            WHERE season_id = %s
        ''', (season_id,))
        torrents = cursor.fetchall()

        for torrent in torrents:
            # Extract episode from torrent name
            _, t_ep = extract_season_episode(torrent['name'])
            if t_ep == episode_num:
                torrent_id = torrent['id']
                break

            # Check for batch torrent pattern "EP (01-03)" or "EP(01-03)"
            batch_match = re.search(r'[Ee][Pp]?\s*\(?(\d+)\s*-\s*(\d+)\)?', torrent['name'])
            if batch_match:
                start_ep = int(batch_match.group(1))
                end_ep = int(batch_match.group(2))
                if start_ep <= episode_num <= end_ep:
                    torrent_id = torrent['id']
                    break

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
                            INSERT INTO episodes (season_id, episode_number, status, file_path, file_size, quality, torrent_id, duration)
                            VALUES (%s, %s, 'available', %s, %s, %s, %s, %s)
                        ''', (season_id, episode_num, ep['path'], ep['size_human'], ep['quality'], torrent_id, duration))
                    else:
                        cursor.execute('''
                            INSERT INTO episodes (season_id, episode_number, status, file_path, file_size, quality, torrent_id)
                            VALUES (%s, %s, 'available', %s, %s, %s, %s)
                        ''', (season_id, episode_num, ep['path'], ep['size_human'], ep['quality'], torrent_id))
                else:
                    if duration is not None:
                        cursor.execute('''
                            INSERT INTO episodes (season_id, episode_number, status, file_path, file_size, quality, duration)
                            VALUES (%s, %s, 'available', %s, %s, %s, %s)
                        ''', (season_id, episode_num, ep['path'], ep['size_human'], ep['quality'], duration))
                    else:
                        cursor.execute('''
                            INSERT INTO episodes (season_id, episode_number, status, file_path, file_size, quality)
                            VALUES (%s, %s, 'available', %s, %s, %s)
                        ''', (season_id, episode_num, ep['path'], ep['size_human'], ep['quality']))
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
@click.option('--dry-run', is_flag=True, help='Show what would be imported without actually importing')
@click.option('--series', help='Filter by series name')
@click.option('--season', type=int, help='Filter by season number')
@click.option('--missing', is_flag=True, help='Show missing episodes')
@click.option('--completed-dir', default=DEFAULT_COMPLETED_DIR, help='Completed downloads folder')
@click.pass_context
def episodes(ctx, scan, import_db, dry_run, series, season, missing, completed_dir):
    """Find and list episodes from completed downloads"""

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
                status_icon = "✓" if ep['status'] == 'available' else "?"
                e_str = f"S{ep['season_number']:02d}E{ep['episode_number']:02d}"
                quality = ep.get('quality', 'Unknown')
                size = ep.get('size_human', 'Unknown')
                click.echo(f"  {status_icon} {e_str} - {quality} - {size}")

    if missing:
        # Show missing episodes logic could go here
        click.echo("\n(Missing episodes feature - requires episode count from seasons table)")
