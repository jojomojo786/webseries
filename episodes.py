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

                episodes.append({
                    'series': series_name,
                    'season': season,
                    'episode': episode,
                    'quality': quality,
                    'size': size,
                    'size_human': format_size(size),
                    'filename': filename,
                    'path': rel_path
                })

    return episodes


def extract_series_name(filename: str) -> str:
    """Extract series name from filename"""
    # Remove extension
    name = Path(filename).stem

    # Remove quality tags
    name = re.sub(r'\[?\d{3,4}[ip]\]?', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\[?(?:480p|720p|1080p|2160p|4K|UHD|FHD|HD|SD)\]?', '', name, flags=re.IGNORECASE)

    # Remove codec and audio tags
    name = re.sub(r'\[?(?:x264|x265|h264|h265|hevc|avc|DDP?|AAC|AC3|DTS)\]?', '', name, flags=re.IGNORECASE)

    # Remove year in parentheses
    name = re.sub(r'\s*\(\d{4}\)', '', name)

    # Remove source tags (www.1TamilMV.*)
    name = re.sub(r'www\.[^\s]+\s*-\s*', '', name)

    # Clean up
    name = re.sub(r'[._\-]+', ' ', name)
    name = ' '.join(name.split())

    # Remove episode pattern for series name
    name = re.sub(r'[Ss]\d+[Ee]\d+', '', name)
    name = re.sub(r'\d+x\d+', '', name)

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


@click.command()
@click.option('--scan', is_flag=True, help='Scan completed folder for episodes')
@click.option('--series', help='Filter by series name')
@click.option('--season', type=int, help='Filter by season number')
@click.option('--missing', is_flag=True, help='Show missing episodes')
@click.option('--completed-dir', default=DEFAULT_COMPLETED_DIR, help='Completed downloads folder')
@click.pass_context
def episodes(ctx, scan, series, season, missing, completed_dir):
    """Find and list episodes from completed downloads"""

    if scan:
        # Scan completed folder
        logger.info(f"Scanning completed folder: {completed_dir}")
        eps = scan_completed_folder(completed_dir)

        if not eps:
            logger.warning("No episodes found")
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
