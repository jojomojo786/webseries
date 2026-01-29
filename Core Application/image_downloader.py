#!/usr/bin/env python3
"""
Image Downloader - Download poster and backdrop images from TMDB/IMDB

Downloads images to /home/webseries/Data & Cache/downloads/images/
with filename format: Series-Name-Year-Poster.jpg / Series-Name-Year-Cover.jpg
"""

import os
import sys
import re
import requests
from pathlib import Path
from urllib.parse import urlparse
from typing import Optional, Dict

# Add parent directory to path for imports
script_dir = Path(__file__).parent.parent
sys.path.insert(0, str(script_dir / "Core Application"))
sys.path.insert(0, str(script_dir))

from logger import get_logger

logger = get_logger(__name__)

# Image storage directory
IMAGES_DIR = Path('/home/webseries/Data & Cache/downloads/images')


def sanitize_filename(name: str) -> str:
    """
    Sanitize series name for use in filename

    Removes/replaces characters that are problematic in filenames:
    - Replaces slashes, colons, etc. with dash
    - Removes special characters
    - Limits length

    Args:
        name: Raw series name

    Returns:
        Sanitized name safe for filenames
    """
    if not name:
        return "Unknown"

    # Replace problematic characters with dash
    name = re.sub(r'[\\/:"*?<>|]', '-', name)

    # Remove special characters but keep letters, numbers, spaces, dashes, underscores
    name = re.sub(r'[^\w\s\-]', '', name)

    # Replace multiple spaces/dashes with single dash
    name = re.sub(r'[\s\-]+', '-', name)

    # Remove leading/trailing dashes
    name = name.strip('-')

    # Limit length (leave room for suffix)
    if len(name) > 100:
        name = name[:100]

    return name or "Unknown"


def generate_image_filename(series_name: str, year: int, image_type: str) -> str:
    """
    Generate filename for poster or backdrop image

    Args:
        series_name: Series name
        year: Release year
        image_type: 'poster' or 'cover'

    Returns:
        Filename like: Series-Name-Year-Webseries-Poster.jpg
    """
    sanitized = sanitize_filename(series_name)
    year_str = str(year) if year else "Unknown"

    suffix_map = {
        'poster': 'Poster',
        'cover': 'Cover',
        'backdrop': 'Cover'  # backdrop is also called cover
    }

    suffix = suffix_map.get(image_type, image_type)

    return f"{sanitized}-{year_str}-Webseries-{suffix}.jpg"


def download_image(url: str, save_path: Path, timeout: int = 30) -> bool:
    """
    Download image from URL to local path

    Args:
        url: Image URL
        save_path: Local path to save image
        timeout: Request timeout in seconds

    Returns:
        True if download succeeded
    """
    try:
        # Create directory if needed
        save_path.parent.mkdir(parents=True, exist_ok=True)

        # Skip if already exists
        if save_path.exists():
            logger.debug(f"Image already exists: {save_path}")
            return True

        logger.debug(f"Downloading: {url}")
        response = requests.get(url, timeout=timeout)
        response.raise_for_status()

        with open(save_path, 'wb') as f:
            f.write(response.content)

        logger.info(f"✓ Downloaded: {save_path.name}")
        return True

    except requests.RequestException as e:
        logger.error(f"Failed to download {url}: {e}")
        return False
    except IOError as e:
        logger.error(f"Failed to save {save_path}: {e}")
        return False


def download_series_images(series_id: int, series_data: Dict, force: bool = False) -> Dict[str, Optional[str]]:
    """
    Download poster and backdrop images for a series

    Args:
        series_id: Series database ID
        series_data: Dict with series info (name, year, poster_url, backdrop_url)
        force: Re-download even if files exist

    Returns:
        Dict with 'poster_path' and 'cover_path' keys
    """
    series_name = series_data.get('name') or series_data.get('title', 'Unknown')
    year = series_data.get('year')

    result = {
        'poster_path': None,
        'cover_path': None
    }

    # Download poster
    poster_url = series_data.get('poster_url')
    if poster_url:
        poster_filename = generate_image_filename(series_name, year, 'poster')
        poster_path = IMAGES_DIR / poster_filename

        if force or not poster_path.exists():
            if download_image(poster_url, poster_path):
                result['poster_path'] = str(poster_path)
        elif poster_path.exists():
            result['poster_path'] = str(poster_path)

    # Download backdrop/cover
    backdrop_url = series_data.get('backdrop_url')
    if backdrop_url:
        cover_filename = generate_image_filename(series_name, year, 'cover')
        cover_path = IMAGES_DIR / cover_filename

        if force or not cover_path.exists():
            if download_image(backdrop_url, cover_path):
                result['cover_path'] = str(cover_path)
        elif cover_path.exists():
            result['cover_path'] = str(cover_path)

    return result


def update_series_image_paths(series_id: int, image_paths: Dict[str, Optional[str]]) -> bool:
    """
    Update series table with local image paths

    Args:
        series_id: Series database ID
        image_paths: Dict with 'poster_path' and 'cover_path'

    Returns:
        True if update succeeded
    """
    # Check if columns exist
    try:
        sys.path.insert(0, 'Database Tools')
        from db import get_connection

        conn = get_connection()
        if not conn:
            return False

        cursor = conn.cursor()

        # Check if local_poster_path and local_cover_path columns exist
        cursor.execute('''
            SHOW COLUMNS FROM series LIKE 'local_%'
        ''')
        existing_columns = {row[0] for row in cursor.fetchall()}

        # If columns don't exist, add them
        if 'local_poster_path' not in existing_columns:
            logger.info("Adding local_poster_path column...")
            cursor.execute("ALTER TABLE series ADD COLUMN local_poster_path VARCHAR(512) NULL COMMENT 'Local poster image path'")
            conn.commit()

        if 'local_cover_path' not in existing_columns:
            logger.info("Adding local_cover_path column...")
            cursor.execute("ALTER TABLE series ADD COLUMN local_cover_path VARCHAR(512) NULL COMMENT 'Local backdrop/cover image path'")
            conn.commit()

        # Update paths
        update_fields = []
        values = []

        if image_paths.get('poster_path'):
            update_fields.append('local_poster_path = %s')
            values.append(image_paths['poster_path'])

        if image_paths.get('cover_path'):
            update_fields.append('local_cover_path = %s')
            values.append(image_paths['cover_path'])

        if update_fields:
            values.append(series_id)
            sql = f"UPDATE series SET {', '.join(update_fields)} WHERE id = %s"
            cursor.execute(sql, values)
            conn.commit()
            logger.info(f"✓ Updated series {series_id} with local image paths")
            return True

        cursor.close()
        conn.close()

    except Exception as e:
        logger.error(f"Error updating image paths: {e}")
        return False

    return False


def fetch_and_download_series_images(series_id: int = None, limit: int = None, force: bool = False) -> Dict:
    """
    Fetch series and download their images

    Args:
        series_id: Specific series ID to process
        limit: Max number of series to process
        force: Re-download even if files exist

    Returns:
        Dict with results
    """
    try:
        sys.path.insert(0, 'Database Tools')
        from db import get_connection

        conn = get_connection()
        if not conn:
            return {'error': 'Could not connect to database'}

        cursor = conn.cursor(dictionary=True)

        # Build query
        if series_id:
            cursor.execute('''
                SELECT id, name, title, year, poster_url, backdrop_url
                FROM series
                WHERE id = %s
            ''', (series_id,))
        else:
            query = '''
                SELECT id, name, title, year, poster_url, backdrop_url
                FROM series
                WHERE poster_url IS NOT NULL AND poster_url != ''
            '''
            if limit:
                query += ' LIMIT %s'
                cursor.execute(query, (limit,))
            else:
                cursor.execute(query)

        series_list = cursor.fetchall()
        cursor.close()
        conn.close()

        if not series_list:
            return {'total': 0, 'downloaded': 0, 'failed': 0}

        logger.info(f"Found {len(series_list)} series to process")

        downloaded = 0
        failed = 0

        for series in series_list:
            sid = series['id']
            name = series.get('name') or series.get('title', 'Unknown')

            print(f"\n{'='*60}")
            print(f"Processing: {name} (ID: {sid})")
            print(f"{'='*60}")

            # Download images
            image_paths = download_series_images(sid, series, force=force)

            # Update database with local paths
            if image_paths.get('poster_path') or image_paths.get('cover_path'):
                if update_series_image_paths(sid, image_paths):
                    downloaded += 1
                else:
                    failed += 1
            else:
                logger.warning(f"  No images downloaded for {name}")
                failed += 1

        return {
            'total': len(series_list),
            'downloaded': downloaded,
            'failed': failed
        }

    except Exception as e:
        logger.error(f"Error fetching series: {e}")
        return {'error': str(e)}


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Download series images from TMDB/IMDB')
    parser.add_argument('--series-id', type=int, help='Download images for specific series')
    parser.add_argument('--limit', type=int, help='Max number of series to process')
    parser.add_argument('--force', action='store_true', help='Re-download even if files exist')

    args = parser.parse_args()

    # Ensure images directory exists
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)

    logger.info(f"Images directory: {IMAGES_DIR}")
    logger.info("="*60)

    results = fetch_and_download_series_images(
        series_id=args.series_id,
        limit=args.limit,
        force=args.force
    )

    if 'error' not in results:
        print(f"\n{'='*60}")
        print("DOWNLOAD SUMMARY")
        print(f"{'='*60}")
        print(f"Total series: {results.get('total', 0)}")
        print(f"Downloaded: {results.get('downloaded', 0)}")
        print(f"Failed: {results.get('failed', 0)}")
        print(f"{'='*60}")
