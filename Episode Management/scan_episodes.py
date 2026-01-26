#!/usr/bin/env python3
"""
Episode Auto-Detection Scanner

Scans downloaded video files and automatically populates the episodes table.

Usage:
    python scan_episodes.py                    # Scan default folder
    python scan_episodes.py --folder /path     # Scan specific folder
    python scan_episodes.py --dry-run          # Preview changes
    python scan_episodes.py --update           # Update existing episodes
    python scan_episodes.py --limit 10         # Process first 10 series

Typical folder structures supported:
    /Series Name/Season 1/Series.S01E01.1080p.mkv
    /Series Name/Series.S01E01.mkv
    /Downloads/My.Series.S01E05.1080p.mkv
"""

import sys
from pathlib import Path

# Add all subdirectories to Python path for imports
script_dir = Path(__file__).parent.parent
sys.path.insert(0, str(script_dir / "Core Application"))
sys.path.insert(0, str(script_dir))

import os
import re
import argparse
from datetime import datetime

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from db import get_connection, add_episode, get_season_episodes, get_seasons_for_series

# Setup basic logging
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)-8s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Video file extensions
VIDEO_EXTENSIONS = {
    '.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv',
    '.webm', '.m4v', '.mpg', '.mpeg', '.ts', '.m2ts'
}

# Patterns to extract season/episode from filenames
PATTERNS = [
    # Standard: Series.Name.S01E01
    re.compile(r'[Ss](\d+)[Ee](\d+)', re.IGNORECASE),
    # Alternative: Series.Name.1x01
    re.compile(r'(\d+)x(\d+)', re.IGNORECASE),
    # Episode: Episode.01 or Ep.01
    re.compile(r'[Ee]p(?:isode)?[.\s]*(\d+)', re.IGNORECASE),
    # Just numbers in pattern: Series.Name.101.1080p (1x01)
    re.compile(r'[.\s](\d{2,3})(?=[.\s]|\d{3,4}[ip])', re.IGNORECASE),
]


def get_file_size(filepath: str) -> int:
    """Get file size in bytes"""
    try:
        return os.path.getsize(filepath)
    except OSError:
        return 0


def get_file_duration(filepath: str) -> int | None:
    """
    Get video duration in seconds using ffprobe

    Returns: duration in seconds or None
    """
    try:
        import subprocess
        cmd = [
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', filepath
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            return int(float(result.stdout.strip()))
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    return None


def extract_quality(filename: str) -> str | None:
    """Extract quality from filename"""
    quality_match = re.search(r'(?:\b|_)(\d{3,4}[ip])(?:\b|_)', filename, re.IGNORECASE)
    if quality_match:
        return quality_match.group(1).upper()

    # Check for common quality indicators
    if re.search(r'4k|uhd|2160p', filename, re.IGNORECASE):
        return '2160p'
    elif re.search(r'1080p?|fhd|fullhd', filename, re.IGNORECASE):
        return '1080p'
    elif re.search(r'720p?|hd', filename, re.IGNORECASE):
        return '720p'
    elif re.search(r'480p?|sd', filename, re.IGNORECASE):
        return '480p'

    return None


def parse_season_episode(filename: str, folder_hint: int = None) -> tuple | None:
    """
    Extract season and episode numbers from filename

    Returns: (season_number, episode_number) or None
    """
    filename_lower = filename.lower()

    # Try each pattern
    for pattern in PATTERNS:
        matches = pattern.finditer(filename_lower)
        for match in matches:
            if pattern.groups == 2:
                season = int(match.group(1))
                episode = int(match.group(2))
                return (season, episode)
            elif pattern.groups == 1:
                # Single number - use folder hint or default to season 1
                episode = int(match.group(1))
                season = folder_hint or 1
                return (season, episode)

    # Try to extract from folder structure: "Season 1", "Season01", "S01"
    parent_folder = os.path.basename(os.path.dirname(filename))
    season_match = re.search(r'[Ss]eason?\s*(\d+)', parent_folder)
    if season_match:
        season = int(season_match.group(1))

        # Look for episode number in filename
        for pattern in PATTERNS:
            match = pattern.search(filename_lower)
            if match:
                if pattern.groups == 2:
                    return (int(match.group(1)), int(match.group(2)))
                elif pattern.groups == 1:
                    return (season, int(match.group(1)))

    return None


def clean_series_name(filename: str) -> str:
    """
    Extract series name from filename by removing common patterns

    Returns: cleaned series name
    """
    # Remove extension
    name = Path(filename).stem

    # Remove quality tags
    name = re.sub(r'\[?\d{3,4}[ip]\]?', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\[?(?:480p|720p|1080p|2160p|4K|UHD|FHD|HD|SD)\]?', '', name, flags=re.IGNORECASE)

    # Remove codec tags
    name = re.sub(r'\[?(?:x264|x265|h264|h265|hevc|avc)\]?', '', name, flags=re.IGNORECASE)

    # Remove audio tags
    name = re.sub(r'\[?(?:DDP?|AAC|AC3|DTS|MP3)\]?', '', name, flags=re.IGNORECASE)

    # Remove release group tags
    name = re.sub(r'\[?\w+-?(?:Rip|Encoder|Release)\]?', '', name, flags=re.IGNORECASE)

    # Remove season/episode patterns (keep for now, used for matching)
    # name = re.sub(r'[Ss]\d+[Ee]\d+', '', name)
    # name = re.sub(r'\d+x\d+', '', name)

    # Remove year in parentheses
    name = re.sub(r'\s*\(\d{4}\)', '', name)

    # Clean up dots, dashes, underscores
    name = re.sub(r'[._\-]+', ' ', name)

    # Remove extra whitespace
    name = ' '.join(name.split())

    return name.strip()


def find_series_by_name(conn, cursor, filename: str, folder_path: str) -> dict | None:
    """
    Find matching series in database by filename or folder structure

    Returns: dict with series_id, title or None
    """
    # Try to extract series name from folder structure first
    folder_name = os.path.basename(os.path.dirname(folder_path))

    # Clean the filename
    clean_name = clean_series_name(filename)

    # Try exact match on folder name first
    cursor.execute('SELECT id, title FROM series')
    all_series = cursor.fetchall()

    for series_id, title in all_series:
        # Try exact match on folder name
        if folder_name.lower() in title.lower() or title.lower() in folder_name.lower():
            return {'series_id': series_id, 'title': title, 'match_type': 'folder'}

        # Try partial match on cleaned name
        if clean_name and len(clean_name) > 5:
            # Remove season info for comparison
            compare_name = re.sub(r'[Ss]\d+[Ee]\d+', '', clean_name)
            compare_name = re.sub(r'\d+x\d+', '', compare_name)
            compare_name = compare_name.strip()

            if compare_name and compare_name.lower() in title.lower()[:len(compare_name) + 10]:
                return {'series_id': series_id, 'title': title, 'match_type': 'filename'}

    return None


def find_season_for_series(conn, cursor, series_id: int, season_number: int) -> int | None:
    """Find season_id for a series by season number"""
    cursor.execute(
        'SELECT id FROM seasons WHERE series_id = %s AND season_number = %s',
        (series_id, season_number)
    )
    result = cursor.fetchone()
    return result[0] if result else None


def scan_folder(folder_path: str, dry_run: bool = False, update: bool = False) -> dict:
    """
    Scan folder for video files and populate episodes table

    Returns: dict with scan results
    """
    if not os.path.exists(folder_path):
        logger.error(f"Folder not found: {folder_path}")
        return {'error': f'Folder not found: {folder_path}'}

    logger.info(f"Scanning folder: {folder_path}")

    results = {
        'scanned': 0,
        'matched': 0,
        'added': 0,
        'updated': 0,
        'skipped': 0,
        'errors': []
    }

    # Find all video files
    video_files = []
    for root, dirs, files in os.walk(folder_path):
        for file in files:
            if Path(file).suffix.lower() in VIDEO_EXTENSIONS:
                video_files.append(os.path.join(root, file))

    logger.info(f"Found {len(video_files)} video files")

    conn = get_connection()
    if not conn:
        return {'error': 'Database connection failed'}

    cursor = conn.cursor(dictionary=True)

    for filepath in video_files:
        results['scanned'] += 1
        filename = os.path.basename(filepath)

        logger.debug(f"Processing: {filename}")

        # Extract season and episode
        se = parse_season_episode(filename)
        if not se:
            logger.debug(f"  Could not parse season/episode: {filename}")
            results['skipped'] += 1
            continue

        season_num, episode_num = se
        logger.debug(f"  Found: Season {season_num}, Episode {episode_num}")

        # Find matching series
        series_match = find_series_by_name(conn, cursor, filename, filepath)
        if not series_match:
            logger.debug(f"  No series match: {filename}")
            results['skipped'] += 1
            continue

        series_id = series_match['series_id']
        logger.debug(f"  Matched series: {series_match['title']} (ID: {series_id})")

        # Find season
        season_id = find_season_for_series(conn, cursor, series_id, season_num)
        if not season_id:
            logger.debug(f"  Season {season_num} not found in database, skipping")
            results['skipped'] += 1
            continue

        logger.debug(f"  Season ID: {season_id}")

        # Check if episode already exists
        existing = get_season_episodes(season_id)
        existing_eps = {ep['episode_number']: ep for ep in existing}

        file_size = get_file_size(filepath)
        quality = extract_quality(filename)
        duration = get_file_duration(filepath)

        status = 'available'

        if episode_num in existing_eps:
            results['matched'] += 1
            existing_ep = existing_eps[episode_num]

            if not update:
                logger.debug(f"  Episode {episode_num} already exists, skipping (use --update to overwrite)")
                results['skipped'] += 1
                continue

            # Update existing episode
            logger.info(f"  Updating episode {episode_num}: {filename}")

            if dry_run:
                logger.info(f"    [DRY RUN] Would update: file_path={filepath[:50]}..., quality={quality}")
                continue

            # Update in database
            cursor.execute('''
                UPDATE episodes SET
                    file_path = %s,
                    file_size = %s,
                    quality = %s,
                    duration = %s,
                    status = %s,
                    updated_at = %s
                WHERE season_id = %s AND episode_number = %s
            ''', (filepath, file_size, quality, duration, status, datetime.now(), season_id, episode_num))

            results['updated'] += 1
        else:
            # Add new episode
            logger.info(f"  Adding episode {episode_num}: {filename}")

            if dry_run:
                logger.info(f"    [DRY RUN] Would add: episode={episode_num}, file={filepath[:50]}..., quality={quality}")
                continue

            episode_id = add_episode(
                season_id=season_id,
                episode_number=episode_num,
                file_path=filepath,
                file_size=file_size,
                quality=quality,
                duration=duration,
                status=status
            )

            if episode_id:
                results['added'] += 1
            else:
                results['errors'].append(f"Failed to add episode {episode_num} for season {season_id}")

    conn.commit()
    cursor.close()
    conn.close()

    return results


def scan_by_series_id(series_id: int, downloads_folder: str, dry_run: bool = False, update: bool = False) -> dict:
    """
    Scan downloads folder for a specific series

    Returns: dict with scan results
    """
    conn = get_connection()
    if not conn:
        return {'error': 'Database connection failed'}

    cursor = conn.cursor(dictionary=True)

    # Get series info
    cursor.execute('SELECT id, title FROM series WHERE id = %s', (series_id,))
    series = cursor.fetchone()

    if not series:
        cursor.close()
        conn.close()
        return {'error': f'Series {series_id} not found'}

    logger.info(f"Scanning for series: {series['title']}")

    results = {
        'series_id': series_id,
        'series_title': series['title'],
        'scanned': 0,
        'matched': 0,
        'added': 0,
        'updated': 0,
        'skipped': 0,
        'errors': []
    }

    # Get all seasons for this series
    seasons = get_seasons_for_series(series_id)

    if not seasons:
        cursor.close()
        conn.close()
        return {'error': 'No seasons found for this series'}

    # Find all video files
    video_files = []
    for root, dirs, files in os.walk(downloads_folder):
        for file in files:
            if Path(file).suffix.lower() in VIDEO_EXTENSIONS:
                video_files.append(os.path.join(root, file))

    logger.info(f"Found {len(video_files)} video files in downloads folder")

    # Get existing episodes for each season
    existing_by_season = {}
    for season in seasons:
        existing_eps = get_season_episodes(season['id'])
        existing_by_season[season['id']] = {ep['episode_number']: ep for ep in existing_eps}

    for filepath in video_files:
        results['scanned'] += 1
        filename = os.path.basename(filepath)

        # Extract season and episode
        se = parse_season_episode(filename)
        if not se:
            continue

        season_num, episode_num = se

        # Find matching season
        matching_season = None
        for season in seasons:
            if season['season_number'] == season_num:
                matching_season = season
                break

        if not matching_season:
            continue

        season_id = matching_season['id']

        # Check if episode exists
        if episode_num in existing_by_season.get(season_id, {}):
            results['matched'] += 1

            if not update:
                continue

            # Update
            file_size = get_file_size(filepath)
            quality = extract_quality(filename)
            duration = get_file_duration(filepath)

            if not dry_run:
                cursor.execute('''
                    UPDATE episodes SET
                        file_path = %s,
                        file_size = %s,
                        quality = %s,
                        duration = %s,
                        updated_at = %s
                    WHERE season_id = %s AND episode_number = %s
                ''', (filepath, file_size, quality, duration, datetime.now(), season_id, episode_num))
                results['updated'] += 1
            else:
                logger.info(f"[DRY RUN] Would update S{season_num:02d}E{episode_num:02d}: {filename[:50]}...")
        else:
            # Add new episode
            file_size = get_file_size(filepath)
            quality = extract_quality(filename)
            duration = get_file_duration(filepath)

            if not dry_run:
                episode_id = add_episode(
                    season_id=season_id,
                    episode_number=episode_num,
                    file_path=filepath,
                    file_size=file_size,
                    quality=quality,
                    duration=duration,
                    status='available'
                )
                if episode_id:
                    results['added'] += 1
                    logger.info(f"Added S{season_num:02d}E{episode_num:02d}: {filename[:50]}...")
            else:
                logger.info(f"[DRY RUN] Would add S{season_num:02d}E{episode_num:02d}: {filename[:50]}...")

    conn.commit()
    cursor.close()
    conn.close()

    return results


def main():
    parser = argparse.ArgumentParser(description='Auto-detect episodes from downloaded files')
    parser.add_argument('--folder', '-f', help='Folder to scan (default: ./downloads)')
    parser.add_argument('--series-id', '-s', type=int, help='Only scan for specific series ID')
    parser.add_argument('--dry-run', '-d', action='store_true', help='Preview changes without saving')
    parser.add_argument('--update', '-u', action='store_true', help='Update existing episodes')
    parser.add_argument('--downloads', default='./downloads', help='Downloads folder path (default: ./downloads)')

    args = parser.parse_args()

    if args.dry_run:
        logger.info("=" * 60)
        logger.info("DRY RUN MODE - No changes will be made")
        logger.info("=" * 60)

    if args.series_id:
        # Scan for specific series
        results = scan_by_series_id(
            series_id=args.series_id,
            downloads_folder=args.downloads,
            dry_run=args.dry_run,
            update=args.update
        )
    else:
        # Scan entire folder
        folder = args.folder or './downloads'
        results = scan_folder(
            folder_path=folder,
            dry_run=args.dry_run,
            update=args.update
        )

    if 'error' in results:
        logger.error(results['error'])
        return

    # Print summary
    logger.info("\n" + "=" * 60)
    logger.info("SCAN SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Scanned:      {results['scanned']} files")
    logger.info(f"Matched:      {results['matched']} existing episodes")
    logger.info(f"Added:        {results['added']} new episodes")
    logger.info(f"Updated:      {results['updated']} episodes")
    logger.info(f"Skipped:      {results['skipped']} files")

    if results['errors']:
        logger.warning(f"Errors:       {len(results['errors'])}")
        for error in results['errors']:
            logger.warning(f"  - {error}")

    if args.dry_run:
        logger.info("\nDRY RUN - No changes were made")

    logger.info("=" * 60)


if __name__ == '__main__':
    main()
