#!/usr/bin/env python3
"""
Episodes command - Find and list episodes from processed downloads

Usage:
    python3 cli.py episodes                    # List all episodes
    python3 cli.py episodes --series "Knight"  # Filter by series name
    python3 cli.py episodes --season 1         # Filter by season
    python3 cli.py episodes --missing           # Show missing episodes
"""

import sys
from pathlib import Path

# Add all subdirectories to Python path for imports
script_dir = Path(__file__).parent.parent
sys.path.insert(0, str(script_dir / "Core Application"))
sys.path.insert(0, str(script_dir / "Episode Management"))
sys.path.insert(0, str(script_dir))

import os
import re
import requests
import click
from db import get_connection
from logger import get_logger
import tmdb_cache
import progress
import openrouter_client

# Import IMDB search functions for fallback
try:
    sys.path.insert(0, str(script_dir / "Metadata Fetching"))
    from imdb import search_imdb_by_title, fetch_tmdb_by_imdb
except ImportError:
    # Fallback if IMDB module not available
    def search_imdb_by_title(title, year=None):
        logger.warning("IMDB module not available")
        return None
    def fetch_tmdb_by_imdb(imdb_id):
        logger.warning("IMDB module not available")
        return None

logger = get_logger(__name__)

# TMDB API key
TMDB_API_KEY = os.environ.get('TMDB_API_KEY', '')

# OpenRouter API key for AI episode validation
OPENROUTER_API_KEY = os.environ.get('OPENROUTER_API_KEY', '')

# Default processed folder (relative to new directory structure)
script_dir = Path(__file__).parent.parent
DEFAULT_PROCESSED_DIR = str(script_dir / 'Data & Cache' / 'downloads' / 'processed')

# Video file extensions
VIDEO_EXTENSIONS = {'.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v'}


def scan_processed_folder(processed_dir: str = DEFAULT_PROCESSED_DIR, use_ai: bool = False) -> list[dict]:
    """
    Scan processed folder for video files and extract episode info

    Args:
        processed_dir: Path to processed downloads folder
        use_ai: Use AI fallback for uncertain episode numbers

    Returns:
        List of episode dicts
    """
    episodes = []

    if not os.path.exists(processed_dir):
        logger.warning(f"Processed folder not found: {processed_dir}")
        return episodes

    for root, dirs, files in os.walk(processed_dir):
        for file in files:
            if Path(file).suffix.lower() in VIDEO_EXTENSIONS:
                filepath = os.path.join(root, file)
                filename = os.path.basename(filepath)
                rel_path = os.path.relpath(filepath, processed_dir)

                # Extract series name and episode info
                series_name = extract_series_name(filename)
                season, episode = extract_season_episode(filename)

                # Use AI fallback if enabled and episode is uncertain
                if use_ai:
                    folder_context = os.path.basename(root)
                    season, episode = validate_with_ai_fallback(
                        filename=filename,
                        series_name=series_name,
                        extracted_season=season,
                        extracted_episode=episode,
                        context=f"Folder: {folder_context}"
                    )

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


def validate_with_ai_fallback(
    filename: str,
    series_name: str,
    extracted_season: int,
    extracted_episode: int = None,
    context: str = ""
) -> tuple[int, int | None]:
    """
    Use AI to validate/correct episode numbers when regex is uncertain

    Args:
        filename: Video filename
        series_name: Extracted series name
        extracted_season: Season number from regex
        extracted_episode: Episode number from regex (None if uncertain)
        context: Additional context (folder name, etc.)

    Returns:
        Tuple of (season, episode) corrected by AI if available
    """
    # Use AI as fallback when:
    # 1. No episode number was found
    # 2. Series name is very short (likely parsing error)
    # 3. Filename contains ambiguous patterns

    client = openrouter_client.get_client()
    if not client.is_available():
        return extracted_season, extracted_episode

    # Trigger AI validation for uncertain cases
    should_use_ai = (
        extracted_episode is None or  # No episode found
        len(series_name) < 3 or  # Series name too short
        re.search(r'[Ee][Pp]s?\s*$', filename) or  # Ends with "EP" ambiguously
        re.search(r'\(\d+\s*-\s*\d+\)', filename)  # Batch range without "EP"
    )

    if should_use_ai:
        logger.debug(f"Using AI fallback for: {filename}")
        return client.validate_episode_number(
            filename=filename,
            series_name=series_name,
            extracted_season=extracted_season,
            extracted_episode=extracted_episode,
            context=context
        )

    return extracted_season, extracted_episode


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


def fetch_tmdb_episode(tmdb_id: int, season_number: int, episode_number: int, use_cache: bool = True) -> dict | None:
    """
    Fetch detailed episode data from TMDB

    Args:
        tmdb_id: TMDB series ID
        season_number: Season number (1-based)
        episode_number: Episode number (1-based)
        use_cache: Whether to use cache (default True)

    Returns:
        dict with episode data or None
    """
    if not TMDB_API_KEY:
        logger.warning("TMDB_API_KEY not set, skipping episode metadata fetch")
        return None

    # Check cache first - use a unique key for this episode
    cache_key = f'/tv/{tmdb_id}/season/{season_number}/episode/{episode_number}'
    cache_params = {}  # No params for this endpoint

    if use_cache:
        cached = tmdb_cache.get(cache_key, cache_params)
        if cached is not None:
            logger.debug(f"Using cached episode data for S{season_number:02d}E{episode_number:02d}")
            return cached

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

    # Cache the complete result
    if use_cache and result:
        tmdb_cache.set(cache_key, cache_params, result)

    return result


def search_tmdb_series(query: str, year: int = None, use_cache: bool = True) -> list[dict]:
    """
    Search TMDB for TV series by name

    Args:
        query: Series name to search for
        year: Optional year to filter results
        use_cache: Whether to use cache (default True)

    Returns:
        List of matching series dicts with keys: id, name, original_name,
        first_air_date, overview, poster_path, vote_average, popularity
    """
    if not TMDB_API_KEY:
        logger.warning("TMDB_API_KEY not set, skipping series search")
        return []

    # Check cache first
    cache_params = {'query': query, 'type': 'tv'}
    if year:
        cache_params['first_air_date_year'] = year

    if use_cache:
        cached = tmdb_cache.get('/search/tv', cache_params)
        if cached is not None:
            logger.debug(f"Using cached search results for '{query}'")
            return cached

    import requests

    try:
        params = {
            'api_key': TMDB_API_KEY,
            'query': query,
            'type': 'tv',  # Only TV series
        }
        if year:
            params['first_air_date_year'] = year

        response = requests.get(
            'https://api.themoviedb.org/3/search/tv',
            params=params,
            timeout=30
        )
        response.raise_for_status()
        data = response.json()

        results = data.get('results', [])
        logger.info(f"TMDB search for '{query}' found {len(results)} results")

        # Cache the results
        if use_cache and results:
            tmdb_cache.set('/search/tv', cache_params, results)

        return results

    except requests.RequestException as e:
        logger.error(f"Error searching TMDB for '{query}': {e}")
        return []


def match_series_from_tmdb(series_id: int, dry_run: bool = False) -> dict | None:
    """
    Auto-match a series from database to TMDB and update with metadata

    Args:
        series_id: Database series ID
        dry_run: If True, don't make changes

    Returns:
        Matched TMDB series info or None
    """
    conn = get_connection()
    if not conn:
        return None

    cursor = conn.cursor(dictionary=True)

    try:
        # Get series info from database
        cursor.execute('''
            SELECT id, title, name, year
            FROM series
            WHERE id = %s
        ''', (series_id,))
        series = cursor.fetchone()

        if not series:
            logger.error(f"Series {series_id} not found in database")
            return None

        # Use title or name for search
        search_title = series.get('name') or series.get('title') or ''
        if not search_title:
            logger.warning(f"Series {series_id} has no title/name to search")
            return None

        # Clean the title for better search results
        # Simple approach: truncate at season/episode markers
        clean_title = search_title

        # Remove Web Series suffixes first
        for suffix in [' [Web Series]', ' - Web Series', ' (Web Series)', '[Web Series]']:
            clean_title = clean_title.replace(suffix, '')

        # Extract year from title if not in database
        if not series.get('year'):
            year_match = re.search(r'\((\d{4})\)', clean_title)
            if year_match:
                year = int(year_match.group(1))
                series['year'] = year
                # Remove the year from the title
                clean_title = clean_title[:year_match.start()] + clean_title[year_match.end():]

        # Find and truncate at season/episode markers
        # Look for patterns like " S01", " S01E01", " S01 EP", " Season 1"
        season_patterns = [
            r'\s+[Ss]\d+',  # S01, S02
            r'\s+Season\s+\d+',  # Season 1
            r'\s+S\d+\s*[Ee]',  # S01E
            r'\s+[Ss]\d+\s+[Ee][Pp]',  # S01 EP
        ]
        for pattern in season_patterns:
            match = re.search(pattern, clean_title)
            if match:
                clean_title = clean_title[:match.start()]
                break

        # Strip whitespace and trailing punctuation
        clean_title = clean_title.strip().rstrip(' -:,')

        logger.info(f"Searching TMDB for: '{clean_title}' (year: {series.get('year')})")

        # Search TMDB
        results = search_tmdb_series(clean_title, series.get('year'))

        if not results:
            logger.warning(f"No TMDB results found for '{clean_title}'")

            # FALLBACK: Try IMDB search via RapidAPI
            logger.info("Trying IMDB search as fallback...")
            imdb_result = search_imdb_by_title(clean_title, series.get('year'))

            if imdb_result:
                # Use IMDB ID to find TMDB data
                tmdb_from_imdb = fetch_tmdb_by_imdb(imdb_result['imdb_id'])
                if tmdb_from_imdb:
                    logger.info(f"Found via IMDB fallback: {tmdb_from_imdb.get('name') or clean_title} (TMDB ID: {tmdb_from_imdb.get('tmdb_id')})")

                    if dry_run:
                        logger.info(f"[DRY RUN] Would update series {series_id} with IMDB-sourced TMDB ID {tmdb_from_imdb.get('tmdb_id')}")
                        return {
                            'id': tmdb_from_imdb.get('tmdb_id'),
                            'name': imdb_result.get('title'),
                            'imdb_id': imdb_result['imdb_id'],
                            'from_imdb': True
                        }

                    # Update with IMDB-sourced TMDB data
                    update_fields = {
                        'tmdb_id': tmdb_from_imdb.get('tmdb_id'),
                        'imdb_id': imdb_result['imdb_id'],
                    }
                    if imdb_result.get('year'):
                        update_fields['year'] = imdb_result['year']
                    if tmdb_from_imdb.get('poster_url'):
                        update_fields['poster_url'] = tmdb_from_imdb['poster_url']
                    if tmdb_from_imdb.get('backdrop_url'):
                        update_fields['backdrop_url'] = tmdb_from_imdb['backdrop_url']
                    if tmdb_from_imdb.get('overview'):
                        update_fields['summary'] = tmdb_from_imdb['overview'][:500]
                    if tmdb_from_imdb.get('vote_average'):
                        update_fields['rating'] = tmdb_from_imdb['vote_average']

                    # Build UPDATE query (same as TMDB path)
                    set_clause = ', '.join([f"{field} = %s" for field in update_fields.keys()])
                    values = list(update_fields.values()) + [series_id]

                    cursor.execute(
                        f"UPDATE series SET {set_clause} WHERE id = %s",
                        values
                    )
                    conn.commit()

                    logger.info(f"Updated series {series_id} with IMDB-sourced TMDB ID {tmdb_from_imdb.get('tmdb_id')}")

                    # Note: Comprehensive metadata fetching is now done via --finder (series_ai_matcher.py)
                    # which fetches from both IMDB and TMDB including cast, directors, writers, etc.

                    return {
                        'id': tmdb_from_imdb.get('tmdb_id'),
                        'name': imdb_result.get('title'),
                        'imdb_id': imdb_result['imdb_id'],
                        'from_imdb': True
                    }

            return None

        # Try to find the best match
        best_match = None
        best_score = 0

        for result in results:
            score = 0
            result_name = result.get('name', '').lower()
            result_original = result.get('original_name', '').lower()
            search_lower = clean_title.lower()

            # Exact name match
            if result_name == search_lower or result_original == search_lower:
                score += 100
            # Contains match
            elif search_lower in result_name or search_lower in result_original:
                score += 50
            # Word overlap
            search_words = set(search_lower.split())
            result_words = set(result_name.split())
            overlap = len(search_words & result_words)
            if overlap > 0:
                score += overlap * 10

            # Year match (if available)
            if series.get('year'):
                result_year = result.get('first_air_date', '')[:4]
                if result_year == str(series.get('year')):
                    score += 30

            # Popularity boost
            score += min(result.get('popularity', 0) / 10, 20)

            if score > best_score:
                best_score = score
                best_match = result

        # Only accept matches with reasonable confidence
        if best_score < 30:
            logger.warning(f"TMDB match score too low ({best_score}) for '{clean_title}'")
            logger.info(f"Top result: {results[0].get('name')} (TMDB: {results[0].get('id')})")
            # Still return the top result if it's the only one
            if len(results) == 1:
                best_match = results[0]
            else:
                return None

        tmdb_id = best_match.get('id')
        logger.info(f"Matched '{clean_title}' to TMDB: {best_match.get('name')} (ID: {tmdb_id}, score: {best_score})")

        if dry_run:
            logger.info(f"[DRY RUN] Would update series {series_id} with TMDB ID {tmdb_id}")
            return best_match

        # Update series with TMDB ID and basic metadata
        update_fields = {
            'tmdb_id': tmdb_id,
        }

        # Also update other available fields if they're not set
        if best_match.get('name'):
            update_fields['name'] = best_match['name']
        if best_match.get('overview'):
            update_fields['summary'] = best_match['overview'][:500]  # Truncate to fit column
        if best_match.get('vote_average'):
            update_fields['rating'] = best_match['vote_average']
        if best_match.get('first_air_date'):
            update_fields['first_air_date'] = best_match['first_air_date']
        if best_match.get('poster_path'):
            update_fields['poster_url'] = f"https://image.tmdb.org/t/p/original{best_match['poster_path']}"

        # Build UPDATE query
        set_clause = ', '.join([f"{field} = %s" for field in update_fields.keys()])
        values = list(update_fields.values()) + [series_id]

        cursor.execute(
            f"UPDATE series SET {set_clause} WHERE id = %s",
            values
        )
        conn.commit()

        logger.info(f"Updated series {series_id} with TMDB ID {tmdb_id}")

        # Note: Comprehensive metadata fetching is now done via --finder (series_ai_matcher.py)
        # which fetches from both IMDB and TMDB including cast, directors, writers, etc.

        return best_match

    except Exception as e:
        logger.error(f"Error matching series {series_id}: {e}")
        return None

    finally:
        cursor.close()
        conn.close()


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

        # Note: Comprehensive series metadata fetching is now done via --finder (series_ai_matcher.py)
        # which fetches from both IMDB and TMDB including cast, directors, writers, etc.

        updated = 0
        failed = 0

        # Create progress tracker
        prog = progress.ProgressTracker(
            total=len(episodes),
            description="Fetching metadata",
            mode="bar",
            show_eta=True
        )

        for ep in episodes:
            tmdb_id = ep['tmdb_id']
            season_num = ep['season_number']
            ep_num = ep['episode_number']
            series_title = ep['series_title'][:30]

            # Update progress before processing
            ep_desc = f"{series_title}... S{season_num:02d}E{ep_num:02d}"
            prog.update(0, f"Fetching {ep_desc}")

            # Fetch from TMDB
            metadata = fetch_tmdb_episode(tmdb_id, season_num, ep_num)
            if not metadata:
                failed += 1
                prog.update(1, f"✗ {ep_desc}")
                continue

            # Update database
            if update_episode_metadata(ep['id'], metadata, dry_run):
                updated += 1
                prog.update(1, f"✓ {ep_desc}")
            else:
                failed += 1
                prog.update(1, f"✗ {ep_desc}")

        prog.finish(f"Summary: {updated} updated, {failed} failed")
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


def fetch_tmdb_series_details(tmdb_id: int, use_cache: bool = True) -> dict | None:
    """
    Fetch detailed series information from TMDB

    Args:
        tmdb_id: TMDB series ID
        use_cache: Whether to use cache

    Returns:
        Dict with series details including episode counts per season, or None
    """
    if not TMDB_API_KEY:
        logger.warning("TMDB_API_KEY not set, skipping series details fetch")
        return None

    # Check cache first
    cache_key = f'/tv/{tmdb_id}'
    cache_params = {}  # No params for this endpoint

    if use_cache:
        cached = tmdb_cache.get(cache_key, cache_params)
        if cached is not None:
            logger.debug(f"Using cached series details for TMDB ID {tmdb_id}")
            return cached

    import requests

    try:
        # Fetch series details
        response = requests.get(
            f'https://api.themoviedb.org/3/tv/{tmdb_id}',
            params={'api_key': TMDB_API_KEY},
            timeout=30
        )
        response.raise_for_status()
        data = response.json()

        result = {
            'tmdb_id': data.get('id'),
            'name': data.get('name'),
            'overview': data.get('overview'),
            'number_of_seasons': data.get('number_of_seasons'),
            'number_of_episodes': data.get('number_of_episodes'),
            'seasons': {}
        }

        # Get episode count per season
        for season in data.get('seasons', []):
            season_number = season.get('season_number')
            if season_number > 0:  # Skip specials (season 0)
                result['seasons'][season_number] = {
                    'episode_count': season.get('episode_count'),
                    'name': season.get('name'),
                    'air_date': season.get('air_date')
                }

        # Cache the result
        if use_cache:
            tmdb_cache.set(cache_key, cache_params, result)

        return result

    except requests.RequestException as e:
        logger.error(f"Error fetching series details for TMDB ID {tmdb_id}: {e}")
        return None


def validate_metadata(series_id: int = None) -> dict:
    """
    Validate metadata completeness and accuracy

    Args:
        series_id: Optional series ID to validate, or None for all

    Returns:
        Dict with validation results
    """
    conn = get_connection()
    if not conn:
        return {'error': 'Could not connect to database'}

    cursor = conn.cursor(dictionary=True)

    try:
        # Build query
        if series_id:
            query = '''
                SELECT s.id, s.title, s.name, s.tmdb_id, s.total_seasons, s.total_episodes,
                       COUNT(DISTINCT e.id) as episode_count
                FROM series s
                LEFT JOIN seasons sea ON s.id = sea.series_id
                LEFT JOIN episodes e ON sea.id = e.season_id
                WHERE s.id = %s
                GROUP BY s.id
            '''
            cursor.execute(query, (series_id,))
            series_list = cursor.fetchall()
        else:
            query = '''
                SELECT s.id, s.title, s.name, s.tmdb_id, s.total_seasons, s.total_episodes,
                       COUNT(DISTINCT e.id) as episode_count
                FROM series s
                LEFT JOIN seasons sea ON s.id = sea.series_id
                LEFT JOIN episodes e ON sea.id = e.season_id
                GROUP BY s.id
                ORDER BY s.title
            '''
            cursor.execute(query)
            series_list = cursor.fetchall()

        results = {
            'total_series': len(series_list),
            'valid': 0,
            'warnings': 0,
            'errors': 0,
            'infos': 0,
            'issues': []
        }

        for series in series_list:
            series_name = series.get('name') or series.get('title', 'Unknown')
            series_id_db = series.get('id')
            tmdb_id = series.get('tmdb_id')

            # Collect all issues for this series
            series_issues = []

            # Skip if no TMDB ID
            if not tmdb_id:
                series_issues.append({
                    'series_id': series_id_db,
                    'series_name': series_name,
                    'level': 'warning',
                    'message': 'No TMDB ID - cannot validate'
                })
                results['warnings'] += 1
                results['issues'].extend(series_issues)
                continue

            # Fetch TMDB details
            tmdb_details = fetch_tmdb_series_details(tmdb_id)
            if not tmdb_details:
                series_issues.append({
                    'series_id': series_id_db,
                    'series_name': series_name,
                    'level': 'error',
                    'message': 'Could not fetch details from TMDB'
                })
                results['errors'] += 1
                results['issues'].extend(series_issues)
                continue

            # Check total episode count
            db_episode_count = series.get('episode_count', 0)
            tmdb_episode_count = tmdb_details.get('number_of_episodes', 0)

            if db_episode_count != tmdb_episode_count:
                series_issues.append({
                    'series_id': series_id_db,
                    'series_name': series_name,
                    'level': 'warning',
                    'message': f'Episode count mismatch (DB: {db_episode_count}, TMDB: {tmdb_episode_count})'
                })
                results['warnings'] += 1

            # Check each season for missing episodes
            cursor.execute('''
                SELECT sea.season_number, COUNT(e.id) as episode_count
                FROM seasons sea
                LEFT JOIN episodes e ON sea.id = e.season_id
                WHERE sea.series_id = %s
                GROUP BY sea.season_number
            ''', (series_id_db,))

            db_seasons = {row['season_number']: row['episode_count'] for row in cursor.fetchall()}

            all_missing = {}  # season -> list of missing episodes
            for season_num, season_info in tmdb_details.get('seasons', {}).items():
                tmdb_season_count = season_info.get('episode_count', 0)
                db_season_count = db_seasons.get(season_num, 0)

                if db_season_count < tmdb_season_count:
                    # Find which episodes are missing
                    cursor.execute('''
                        SELECT episode_number FROM episodes e
                        JOIN seasons sea ON e.season_id = sea.id
                        WHERE sea.series_id = %s AND sea.season_number = %s
                    ''', (series_id_db, season_num))

                    db_episodes = {row['episode_number'] for row in cursor.fetchall()}
                    missing = []
                    for ep in range(1, tmdb_season_count + 1):
                        if ep not in db_episodes:
                            missing.append(ep)

                    if missing:
                        all_missing[season_num] = missing

            # Add missing episode issues (grouped by series)
            if all_missing:
                missing_parts = []
                for season_num, missing in sorted(all_missing.items()):
                    season_num_int = int(season_num)  # Convert from string to int
                    if len(missing) <= 5:
                        ep_str = ', '.join(f'E{ep:02d}' for ep in missing)
                    else:
                        ep_str = "E{:02d}-E{:02d}".format(missing[0], missing[-1])
                    missing_parts.append("S{:02d}: {}".format(season_num_int, ep_str))

                series_issues.append({
                    'series_id': series_id_db,
                    'series_name': series_name,
                    'level': 'warning',
                    'message': "Missing episodes: " + "; ".join(missing_parts)
                })
                results['warnings'] += 1

            # Check for episodes without metadata
            cursor.execute('''
                SELECT COUNT(*) as count
                FROM episodes e
                JOIN seasons sea ON e.season_id = sea.id
                WHERE sea.series_id = %s AND (e.name IS NULL OR e.name = '')
            ''', (series_id_db,))

            no_metadata = cursor.fetchone()['count']
            if no_metadata > 0:
                series_issues.append({
                    'series_id': series_id_db,
                    'series_name': series_name,
                    'level': 'info',
                    'message': f'{no_metadata} episodes without metadata'
                })
                results['infos'] += 1

            # Add all issues for this series
            results['issues'].extend(series_issues)

            # Mark as valid if no issues
            if not series_issues:
                results['valid'] += 1

        return results

    except Exception as e:
        logger.error(f"Error validating metadata: {e}")
        return {'error': str(e)}

    finally:
        cursor.close()
        conn.close()


def import_episodes_to_db(episodes: list[dict], dry_run: bool = False) -> tuple[int, int]:
    """
    Import scanned episodes into the database

    Args:
        episodes: List of episode dicts from scan_processed_folder
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

    # Create progress tracker for import
    prog = progress.ProgressTracker(
        total=len(episodes),
        description="Importing episodes",
        mode="bar",
        show_eta=True
    )

    for ep in episodes:
        series_name = ep['series']
        season_num = ep['season']
        episode_num = ep['episode']
        ep_desc = f"{series_name[:20]}... S{season_num:02d}E{episode_num:02d}"

        prog.update(0, f"Processing {ep_desc}")

        if not episode_num:
            logger.debug(f"Skipping (no episode number): {ep['filename']}")
            skipped += 1
            prog.update(1, f"⊘ {ep_desc} (no episode number)")
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
            prog.update(1, f"✗ {ep_desc} (no season match)")
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
                logger.info(f"Imported: S{season_num:02d}E{season_num:02d}")
                prog.update(1, f"✓ {ep_desc}")

            except Exception as e:
                logger.error(f"Failed to insert S{season_num:02d}E{episode_num:02d}: {e}")
                errors += 1
                prog.update(1, f"✗ {ep_desc} (error)")
                continue

            # Auto-fetch episode metadata from TMDB (moved outside try block)
            if TMDB_API_KEY:
                try:
                    # Get series ID and TMDB ID
                    cursor.execute('''
                        SELECT s.id, s.tmdb_id FROM series s
                        JOIN seasons sea ON s.id = sea.series_id
                        WHERE sea.id = %s
                    ''', (season_id,))
                    series_row = cursor.fetchone()

                    # Handle both dict and tuple result formats
                    if isinstance(series_row, dict):
                        series_id_db = series_row.get('id')
                        tmdb_id = series_row.get('tmdb_id')
                    elif series_row:
                        series_id_db = series_row[0]
                        tmdb_id = series_row[1]
                    else:
                        series_id_db = None
                        tmdb_id = None

                    # Auto-match series if no TMDB ID
                    if not tmdb_id and series_id_db:
                        logger.info(f"  → Series has no TMDB ID, attempting auto-match...")
                        match_result = match_series_from_tmdb(series_id_db, dry_run=False)
                        if match_result:
                            tmdb_id = match_result.get('id')
                            logger.info(f"  → Auto-matched to TMDB ID: {tmdb_id}")

                    # Fetch episode metadata if we have a TMDB ID
                    if tmdb_id:
                        metadata = fetch_tmdb_episode(tmdb_id, season_num, episode_num)
                        if metadata:
                            # Get the inserted episode ID
                            cursor.execute(
                                'SELECT id FROM episodes WHERE season_id = %s AND episode_number = %s',
                                (season_id, episode_num)
                            )
                            episode_row = cursor.fetchone()
                            if episode_row:
                                # Handle both dict and tuple result formats
                                episode_id = episode_row.get('id') if isinstance(episode_row, dict) else episode_row[0]
                                # Update with metadata
                                fields = []
                                values = []
                                for field in ['imdb_id', 'name', 'overview', 'air_date', 'still_url',
                                              'vote_average', 'vote_count', 'director', 'writer', 'guest_stars']:
                                    if field in metadata and metadata[field] is not None:
                                        fields.append(f"{field} = %s")
                                        values.append(metadata[field])
                                if fields:
                                    values.append(episode_id)
                                    sql = f"UPDATE episodes SET {', '.join(fields)} WHERE id = %s"
                                    cursor.execute(sql, tuple(values))
                                    conn.commit()
                                    logger.info(f"  → Fetched metadata: {metadata.get('name', 'N/A')}")
                except Exception as e:
                    logger.warning(f"  → Could not fetch metadata: {e}")

    cursor.close()
    conn.close()

    prog.finish(f"Import complete: {imported} imported, {skipped} skipped" + (f", {errors} errors" if errors else ""))
    return imported, skipped


@click.command()
@click.option('--scan', is_flag=True, help='Scan processed folder for episodes')
@click.option('--import-db', is_flag=True, help='Import scanned episodes into database')
@click.option('--fetch-metadata', is_flag=True, help='Fetch episode metadata from TMDB')
@click.option('--match-series', type=int, help='Match a series from DB to TMDB by series ID')
@click.option('--match-all-series', is_flag=True, help='Auto-match all series without TMDB IDs')
@click.option('--finder', type=int, help='Match a series using AI poster analysis by series ID')
@click.option('--finder-all', is_flag=True, help='Match all series without tmdb_id using AI poster analysis')
@click.option('--auto-import', is_flag=True, help='Run full workflow: scan → import → match → fetch-metadata')
@click.option('--validate', is_flag=True, help='Validate metadata completeness and accuracy')
@click.option('--cache-stats', is_flag=True, help='Show TMDB cache statistics')
@click.option('--cache-clear', is_flag=True, help='Clear all TMDB cache')
@click.option('--cache-cleanup', is_flag=True, help='Remove expired cache entries')
@click.option('--dry-run', is_flag=True, help='Show what would be imported without actually importing')
@click.option('--series-id', type=int, help='Process specific series by ID (for --fetch-metadata and --validate)')
@click.option('--limit', type=int, default=50, help='Max episodes to process (for --fetch-metadata)')
@click.option('--series', help='Filter by series name')
@click.option('--season', type=int, help='Filter by season number')
@click.option('--missing', is_flag=True, help='Show missing episodes')
@click.option('--use-ai', is_flag=True, help='Use AI (OpenRouter) to validate uncertain episode numbers')
@click.option('--processed-dir', default=DEFAULT_PROCESSED_DIR, help='Processed downloads folder')
@click.pass_context
def episodes(ctx, scan, import_db, fetch_metadata, match_series, match_all_series, finder, finder_all, auto_import, validate, cache_stats, cache_clear, cache_cleanup, dry_run, series_id, limit, series, season, missing, use_ai, processed_dir):
    """Find and list episodes from processed downloads"""

    # Default behavior: scan + use-ai + import-db when no action flags provided
    action_flags = [scan, import_db, fetch_metadata, match_series, match_all_series,
                    finder, finder_all, auto_import, validate, cache_stats, cache_clear, cache_cleanup]
    if not any(action_flags):
        scan = True
        use_ai = True
        import_db = True
        logger.info("Default mode: scan + AI fallback + import to DB")

    # AI validation check
    if use_ai:
        client = openrouter_client.get_client()
        if client.is_available():
            logger.info("AI episode validation enabled (OpenRouter)")
        else:
            logger.warning("AI validation requested but OpenRouter API key not set")
            logger.info("Set OPENROUTER_API_KEY environment variable to enable AI validation")

    # Cache management
    if cache_stats:
        stats = tmdb_cache.get_stats()
        click.echo("\nTMDB Cache Statistics:")
        click.echo("=" * 50)
        click.echo(f"Total cached entries: {stats['total_files']}")
        click.echo(f"Total size: {stats['total_size_bytes'] / 1024:.1f} KB")
        click.echo(f"Expired entries: {stats['expired_count']}")

        if stats['oldest_entry']:
            import time
            oldest_age = int(time.time() - stats['oldest_entry'])
            newest_age = int(time.time() - stats['newest_entry'])
            click.echo(f"Oldest entry: {oldest_age // 86400}d {oldest_age % 86400 // 3600}h ago")
            click.echo(f"Newest entry: {newest_age // 3600}h ago")
        click.echo("")
        return

    if cache_clear:
        if dry_run:
            click.echo("[DRY RUN] Would clear all cache")
        else:
            count = tmdb_cache.clear()
            click.echo(f"Cleared {count} cache entries")
        return

    if cache_cleanup:
        if dry_run:
            click.echo("[DRY RUN] Would clean up expired cache entries")
        else:
            count = tmdb_cache.cleanup_expired()
            click.echo(f"Cleaned up {count} expired cache entries")
        return

    # Auto-import workflow
    if auto_import:
        logger.info("=" * 60)
        logger.info("AUTO-IMPORT WORKFLOW")
        logger.info("=" * 60)

        results = {
            'scanned': 0,
            'imported': 0,
            'skipped': 0,
            'matched': 0,
            'match_failed': 0,
            'metadata_fetched': 0,
        }

        # Step 1: Scan processed folder
        logger.info("\n[1/4] Scanning processed folder...")
        eps = scan_processed_folder(processed_dir, use_ai=use_ai)
        results['scanned'] = len(eps)

        if eps:
            logger.info(f"Found {len(eps)} episode file(s)")
        else:
            logger.info("No new episode files found")
            return

        # Step 2: Import episodes
        logger.info("\n[2/4] Importing episodes to database...")
        if dry_run:
            logger.info("[DRY RUN] Skipping import")
        else:
            imported, skipped = import_episodes_to_db(eps, dry_run=False)
            results['imported'] = imported
            results['skipped'] = skipped

        # Step 3: Match series without TMDB IDs
        logger.info("\n[3/4] Matching series to TMDB...")
        if dry_run:
            logger.info("[DRY RUN] Skipping series matching")
        else:
            conn = get_connection()
            if conn:
                cursor = conn.cursor(dictionary=True)
                try:
                    cursor.execute('''
                        SELECT id, title, name, year
                        FROM series
                        WHERE tmdb_id IS NULL
                        ORDER BY id
                    ''')
                    series_list = cursor.fetchall()

                    if series_list:
                        logger.info(f"Found {len(series_list)} series without TMDB IDs")

                        for s in series_list:
                            series_id_db = s.get('id')
                            title = s.get('name') or s.get('title') or 'Unknown'

                            result = match_series_from_tmdb(series_id_db, dry_run=False)
                            if result:
                                results['matched'] += 1
                            else:
                                results['match_failed'] += 1

                finally:
                    cursor.close()
                    conn.close()

        # Step 4: Fetch episode metadata
        logger.info("\n[4/4] Fetching episode metadata...")
        if dry_run:
            logger.info("[DRY RUN] Skipping metadata fetch")
        else:
            updated = fetch_and_update_episode_metadata(limit=100, dry_run=False)
            results['metadata_fetched'] = updated

        # Final summary
        logger.info("\n" + "=" * 60)
        logger.info("AUTO-IMPORT SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Files scanned:     {results['scanned']}")
        logger.info(f"Episodes imported: {results['imported']}")
        logger.info(f"Episodes skipped:  {results['skipped']}")
        logger.info(f"Series matched:    {results['matched']}")
        logger.info(f"Series failed:     {results['match_failed']}")
        logger.info(f"Metadata fetched:  {results['metadata_fetched']}")
        logger.info("=" * 60)

        if dry_run:
            logger.info("DRY RUN - No changes were made")

        return

    # Validate metadata
    if validate:
        click.echo("\nValidating metadata...")
        click.echo("=" * 60)

        results = validate_metadata(series_id=series_id)

        if 'error' in results:
            logger.error(f"Validation error: {results['error']}")
            return

        # Display results
        if results.get('total_series', 0) > 0:
            click.echo(f"\nValidated {results['total_series']} series(s)\n")

        # Group issues by level
        warnings = [i for i in results.get('issues', []) if i['level'] == 'warning']
        errors = [i for i in results.get('issues', []) if i['level'] == 'error']
        infos = [i for i in results.get('issues', []) if i['level'] == 'info']

        # Display errors
        for issue in errors:
            click.echo(f"🔴 Series {issue['series_id']}: {issue['series_name']}")
            click.echo(f"   {issue['message']}")

        # Display warnings
        for issue in warnings:
            click.echo(f"⚠️  Series {issue['series_id']}: {issue['series_name']}")
            click.echo(f"   {issue['message']}")

        # Display info
        for issue in infos:
            click.echo(f"ℹ️  Series {issue['series_id']}: {issue['series_name']}")
            click.echo(f"   {issue['message']}")

        # Summary
        click.echo("\n" + "=" * 60)
        click.echo(f"Summary: {results['valid']} valid, {results['warnings']} warnings, {results['errors']} errors")

        if results['warnings'] == 0 and results['errors'] == 0:
            click.echo("✓ All metadata is complete and accurate!")

        return

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

    # Match series to TMDB
    if match_series or match_all_series:
        if dry_run:
            logger.info("=" * 60)
            logger.info("DRY RUN MODE - No changes will be made")
            logger.info("=" * 60)

        if match_series:
            # Match a specific series
            logger.info(f"Matching series ID: {match_series}")
            result = match_series_from_tmdb(match_series, dry_run=dry_run)
            if result:
                logger.info(f"✓ Matched to TMDB: {result.get('name')} (ID: {result.get('id')})")
            else:
                logger.warning("✗ Could not match series to TMDB")
        elif match_all_series:
            # Match all series without TMDB IDs
            conn = get_connection()
            if not conn:
                logger.error("Could not connect to database")
                return

            cursor = conn.cursor(dictionary=True)
            try:
                cursor.execute('''
                    SELECT id, title, name, year
                    FROM series
                    WHERE tmdb_id IS NULL
                    ORDER BY id
                ''')
                series_list = cursor.fetchall()

                if not series_list:
                    logger.info("No series found without TMDB IDs")
                    return

                logger.info(f"Found {len(series_list)} series without TMDB IDs")
                matched = 0
                failed = 0

                # Create progress tracker
                prog = progress.ProgressTracker(
                    total=len(series_list),
                    description="Matching series",
                    mode="bar",
                    show_eta=True
                )

                for s in series_list:
                    series_id = s.get('id')
                    title = s.get('name') or s.get('title') or 'Unknown'
                    short_title = title[:40] + "..." if len(title) > 40 else title

                    # Update progress before processing
                    prog.update(0, f"Matching {short_title}")

                    result = match_series_from_tmdb(series_id, dry_run=dry_run)
                    if result:
                        matched += 1
                        # Update progress with success
                        prog.update(1, f"✓ {short_title} → {result.get('name')}")
                    else:
                        failed += 1
                        # Update progress with failure
                        prog.update(1, f"✗ {short_title}")

                prog.finish(f"Summary: {matched} matched, {failed} failed")
                if dry_run:
                    logger.info("DRY RUN - No changes were made")

            finally:
                cursor.close()
                conn.close()
        return

    # AI Matching with poster analysis
    if finder or finder_all:
        # Import the AI matcher module
        import series_ai_matcher

        if finder:
            # Match a specific series using AI
            logger.info(f"AI Matching series ID: {finder}")
            result = series_ai_matcher.match_series_with_ai(finder, dry_run=dry_run)
            if result:
                logger.info(f"✓ AI matched series {finder}")
            else:
                logger.warning(f"✗ AI matching failed for series {finder}")
        elif finder_all:
            # Match all series without TMDB IDs using AI
            logger.info("AI Matching all series without TMDB IDs...")
            results = series_ai_matcher.match_all_series_with_ai(dry_run=dry_run)

            click.echo("\n" + "=" * 80)
            click.echo("AI MATCHING SUMMARY")
            click.echo("=" * 80)
            click.echo(f"Total series: {results.get('total', 0)}")
            click.echo(f"Matched: ✓ {results.get('matched', 0)}")
            click.echo(f"Failed: ✗ {results.get('failed', 0)}")
            click.echo("=" * 80)

            if dry_run:
                logger.info("DRY RUN - No changes were made")
        return

    # Scan processed folder (needed for both --scan and --import-db)
    if scan or import_db:
        logger.info(f"Scanning processed folder: {processed_dir}")
        eps = scan_processed_folder(processed_dir, use_ai=use_ai)

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
                size_str = format_size(ep.get('size_bytes', 0))
                click.echo(f"  {e_str} - {ep['quality']} - {size_str}")
    else:
        # Query from database
        eps = get_episodes_from_db(series, season)

        if not eps:
            logger.warning("No episodes found in database")
            logger.info("Use --scan to scan processed folder")
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
