#!/usr/bin/env python3
"""
Image Downloader - Download poster and backdrop images from TMDB/IMDB

Downloads images to /home/webseries/Data & Cache/downloads/images/
with filename format: Series-Name-Year-Webseries-Poster.jpg / Series-Name-Year-Webseries-Cover.jpg

Stores only filename in database (not full path)
Uploads to R2 bucket and stores CDN URL in database
"""

import os
import sys
import re
import time
import requests
import boto3
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

# Default images directory (fallback when no poster found)
DEFAULT_IMAGES_DIR = Path('/home/webseries/Data & Cache/downloads/default')

# Load R2 Configuration from .env file
def load_env():
    """Load environment variables from .env file"""
    env_path = script_dir / '.env'
    env_vars = {}
    if env_path.exists():
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    # Handle both KEY=VALUE and KEY = VALUE formats
                    if ' = ' in line:
                        key, value = line.split(' = ', 1)
                    else:
                        key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip()
    return env_vars

env_vars = load_env()

# R2 Configuration
R2_ACCOUNT_ID = env_vars.get('r2AccountId', '')
R2_ACCESS_KEY = env_vars.get('r2AccessKey', '')
R2_SECRET_KEY = env_vars.get('r2SecretKey', '')
R2_BUCKET = env_vars.get('r2Bucket', '')
R2_CUSTOM_DOMAIN = env_vars.get('customDomain', '')
R2_UPLOAD_PATH = env_vars.get('uploadPath', '/wp-content/uploads/').strip('/')
R2_ENDPOINT = f'https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com'

# OpenRouter API for image validation
OPENROUTER_API_KEY = env_vars.get('OPENROUTER_API_KEY', '')

# Cloudflare API for cache purging
CLOUDFLARE_API_TOKEN = env_vars.get('cloudflareApiToken', '')
CLOUDFLARE_ZONE_ID = env_vars.get('cloudflareZoneId', '')


def validate_image_dimensions(image_url: str, expected_type: str = 'poster') -> Dict[str, any]:
    """
    Validate if an image has the correct dimensions for the expected type (poster or cover)

    Uses OpenRouter's gpt-5-nano to analyze the image dimensions and aspect ratio.

    Args:
        image_url: URL of the image to validate
        expected_type: 'poster' or 'cover'

    Returns:
        Dict with:
            - is_valid: bool - True if dimensions match expected type
            - actual_type: str - Detected type ('poster', 'cover', or 'unknown')
            - dimensions: str - Image dimensions like "1920x1080"
            - reasoning: str - Explanation of the classification
    """
    try:
        # Download image to analyze
        response = requests.get(image_url, timeout=15)
        response.raise_for_status()

        # Get image dimensions from Content-Type or by analyzing
        import base64
        base64_image = base64.b64encode(response.content).decode('utf-8')

        # Detect mime type
        if image_url.lower().endswith('.png'):
            mime_type = 'image/png'
        else:
            mime_type = 'image/jpeg'

        data_url = f"data:{mime_type};base64,{base64_image}"

        # Build prompt for dimension validation
        prompt = f"""Analyze this image and determine if it's a POSTER or a COVER/BACKDROP image based on its dimensions and aspect ratio.

EXPECTED TYPE: {expected_type.upper()}

DIMENSION GUIDELINES:
- POSTER: Vertical orientation (portrait), typically 2:3 aspect ratio (e.g., 600x900, 800x1200)
- COVER/BACKDROP: Horizontal orientation (landscape), typically 16:9 aspect ratio (e.g., 1920x1080, 1280x720)

YOUR TASK:
1. Check if image is vertical (poster) or horizontal (cover/backdrop)
2. Report the approximate dimensions
3. Determine if it matches the EXPECTED TYPE
4. Consider the visual composition (poster shows character/portrait, cover shows scene/landscape)

Return JSON:
{{
    "is_valid": true/false,
    "actual_type": "poster" or "cover",
    "dimensions": "width x height",
    "aspect_ratio": "approximate ratio like 2:3 or 16:9",
    "orientation": "vertical" or "horizontal",
    "reasoning": "brief explanation"
}}"""

        payload = {
            'model': 'openai/gpt-5-nano',
            'messages': [
                {
                    'role': 'user',
                    'content': [
                        {'type': 'text', 'text': prompt},
                        {'type': 'image_url', 'image_url': {'url': data_url}}
                    ]
                }
            ],
            'temperature': 0.1,
            'max_tokens': 3000
        }

        api_response = requests.post(
            'https://openrouter.ai/api/v1/chat/completions',
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {OPENROUTER_API_KEY}'
            },
            json=payload,
            timeout=30
        )

        api_response.raise_for_status()
        result = api_response.json()

        if 'choices' not in result or not result['choices']:
            logger.warning("OpenRouter validation: No response from API")
            return {'is_valid': True, 'actual_type': 'unknown', 'reasoning': 'API validation failed, allowing anyway'}

        content = result['choices'][0]['message']['content'].strip()

        # Extract JSON from response
        import json
        json_match = re.search(r'\{[^{}]*"is_valid"[^{}]*\}', content, re.DOTALL)
        if json_match:
            validation_result = json.loads(json_match.group())

            logger.info(f"  📐 Image validation: {validation_result.get('actual_type')} ({validation_result.get('dimensions')}) - {validation_result.get('reasoning')}")

            return validation_result

        logger.warning(f"OpenRouter validation: Could not parse response: {content[:200]}")
        return {'is_valid': True, 'actual_type': 'unknown', 'reasoning': 'Could not parse, allowing anyway'}

    except Exception as e:
        logger.warning(f"OpenRouter validation failed: {e}")
        # If validation fails, allow the image anyway (fail open)
        return {'is_valid': True, 'actual_type': 'unknown', 'reasoning': f'Validation error: {e}'}


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


def copy_default_image(save_path: Path, image_type: str) -> bool:
    """
    Copy default poster/cover image from default images directory

    Args:
        save_path: Local path to save the image
        image_type: 'poster' or 'cover'

    Returns:
        True if copy succeeded
    """
    try:
        # Create directory if needed
        save_path.parent.mkdir(parents=True, exist_ok=True)

        # Default image filenames
        default_files = {
            'poster': 'poster.jpg',
            'cover': 'cover.jpg',
            'backdrop': 'cover.jpg'  # backdrop uses cover.jpg
        }

        default_file = default_files.get(image_type, 'poster.jpg')
        source_path = DEFAULT_IMAGES_DIR / default_file

        if not source_path.exists():
            logger.error(f"Default image not found: {source_path}")
            return False

        import shutil
        shutil.copy2(source_path, save_path)
        logger.info(f"✓ Used default {image_type}: {save_path.name}")
        return True

    except Exception as e:
        logger.error(f"Failed to copy default {image_type}: {e}")
        return False


def download_image(url: str, save_path: Path, timeout: int = 30, retries: int = 3) -> bool:
    """
    Download image from URL to local path with retry logic

    Args:
        url: Image URL
        save_path: Local path to save image
        timeout: Request timeout in seconds
        retries: Number of retry attempts (default: 3)

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

        # Try downloading with retries
        for attempt in range(1, retries + 1):
            try:
                logger.debug(f"Downloading (attempt {attempt}/{retries}): {url}")
                response = requests.get(url, timeout=timeout)
                response.raise_for_status()

                with open(save_path, 'wb') as f:
                    f.write(response.content)

                logger.info(f"✓ Downloaded: {save_path.name}")
                return True

            except requests.RequestException as e:
                if attempt < retries:
                    logger.warning(f"  Attempt {attempt}/{retries} failed: {e}")
                    time.sleep(10)  # Wait 10 seconds before retry
                else:
                    logger.error(f"Failed to download {url} after {retries} attempts: {e}")
                    return False

    except IOError as e:
        logger.error(f"Failed to save {save_path}: {e}")
        return False


def get_r2_client():
    """
    Get boto3 S3 client configured for Cloudflare R2

    Returns:
        S3 client configured for R2
    """
    return boto3.client(
        's3',
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY,
        aws_secret_access_key=R2_SECRET_KEY,
        region_name='auto'
    )


def upload_to_r2(local_path: Path, filename: str) -> Optional[str]:
    """
    Upload image to R2 bucket and return CDN URL

    Args:
        local_path: Local path to the image file
        filename: Filename to use in R2 bucket

    Returns:
        CDN URL (https://customDomain/uploadPath/filename) or None if failed
    """
    try:
        s3_client = get_r2_client()

        # Upload to R2 with folder path from .env
        r2_key = f'{R2_UPLOAD_PATH}/{filename}'
        s3_client.upload_file(
            str(local_path),
            R2_BUCKET,
            r2_key,
            ExtraArgs={'ContentType': 'image/jpeg'}
        )

        cdn_url = f'https://{R2_CUSTOM_DOMAIN}/{R2_UPLOAD_PATH}/{filename}'
        logger.info(f"✓ Uploaded to R2: {cdn_url}")
        return cdn_url

    except Exception as e:
        logger.error(f"Failed to upload {filename} to R2: {e}")
        return None


def purge_cloudflare_cache(urls: list) -> bool:
    """
    Purge Cloudflare cache for specific URLs

    Args:
        urls: List of URLs to purge from cache

    Returns:
        True if purge succeeded
    """
    if not CLOUDFLARE_API_TOKEN or not CLOUDFLARE_ZONE_ID:
        logger.warning("Cloudflare API token or zone ID not configured, skipping cache purge")
        return False

    if not urls:
        return False

    try:
        purge_url = f'https://api.cloudflare.com/client/v4/zones/{CLOUDFLARE_ZONE_ID}/purge_cache'

        payload = {
            'files': urls
        }

        response = requests.post(
            purge_url,
            headers={
                'Authorization': f'Bearer {CLOUDFLARE_API_TOKEN}',
                'Content-Type': 'application/json'
            },
            json=payload,
            timeout=30
        )

        response.raise_for_status()
        result = response.json()

        if result.get('success'):
            logger.info(f"✓ Purged {len(urls)} URL(s) from Cloudflare cache")
            return True
        else:
            errors = result.get('errors', [])
            logger.error(f"Failed to purge cache: {errors}")
            return False

    except Exception as e:
        logger.error(f"Error purging Cloudflare cache: {e}")
        return False


def download_series_images(series_id: int, series_data: Dict, force: bool = False) -> Dict[str, Optional[str]]:
    """
    Download poster and backdrop images for a series and upload to R2

    Poster download fallback order:
    1. poster_url (from TMDB)
    2. original_poster_url (from original scrape, if TMDB fails)
    3. Default poster.jpg (if all else fails)

    Args:
        series_id: Series database ID
        series_data: Dict with series info (name, year, poster_url, original_poster_url, backdrop_url)
        force: Re-download even if files exist

    Returns:
        Dict with 'poster_path', 'cover_path', 'r2_poster', 'r2_cover' keys
        (r2_poster/r2_cover: 1=success, 0=failed, None=not attempted)
    """
    series_name = series_data.get('name') or series_data.get('title', 'Unknown')
    year = series_data.get('year')

    result = {
        'poster_path': None,
        'cover_path': None,
        'r2_poster': None,  # Track R2 upload status
        'r2_cover': None   # Track R2 upload status
    }

    # Track successfully uploaded URLs for cache purging
    uploaded_urls = []

    # Download poster with fallback chain
    poster_filename = generate_image_filename(series_name, year, 'poster')
    poster_path = IMAGES_DIR / poster_filename

    if force or not poster_path.exists():
        poster_downloaded = False

        # Try poster_url (from TMDB) first
        poster_url = series_data.get('poster_url')
        if poster_url:
            logger.debug(f"  Trying poster_url (TMDB): {poster_url}")
            if download_image(poster_url, poster_path):
                poster_downloaded = True
            else:
                logger.warning(f"  ⚠ TMDB poster_url failed")

        # If TMDB failed, try original_poster_url (from scrape)
        if not poster_downloaded:
            original_poster_url = series_data.get('original_poster_url')
            if original_poster_url and original_poster_url != poster_url:
                logger.info(f"  Trying original_poster_url: {original_poster_url}")

                # Validate if image is actually a poster (not a cover) using OpenRouter
                validation = validate_image_dimensions(original_poster_url, expected_type='poster')

                if validation.get('is_valid') and validation.get('actual_type') == 'poster':
                    logger.info(f"  ✓ Validation passed: Image is a poster")
                    if download_image(original_poster_url, poster_path):
                        poster_downloaded = True
                        logger.info(f"  ✓ Downloaded from original_poster_url")
                    else:
                        logger.warning(f"  ⚠ original_poster_url download failed")
                else:
                    logger.warning(f"  ⚠ original_poster_url is not a poster image")
                    logger.warning(f"     Detected: {validation.get('actual_type')} - {validation.get('reasoning')}")
                    logger.warning(f"     Dimensions: {validation.get('dimensions', 'unknown')}")
                    # Skip this source, will use default poster

        # If both failed, use default poster
        if not poster_downloaded:
            logger.warning(f"  ⚠ All poster sources failed, using default")
            copy_default_image(poster_path, 'poster')

    # Upload to R2 (whether downloaded, original, or default)
    cdn_url = upload_to_r2(poster_path, poster_filename)
    result['poster_path'] = poster_filename
    result['r2_poster'] = 1 if cdn_url else 0  # Track R2 upload status
    if cdn_url:
        uploaded_urls.append(cdn_url)

    # Download backdrop/cover (only if backdrop_url exists, no fallback)
    backdrop_url = series_data.get('backdrop_url')
    if backdrop_url:
        cover_filename = generate_image_filename(series_name, year, 'cover')
        cover_path = IMAGES_DIR / cover_filename

        if force or not cover_path.exists():
            if download_image(backdrop_url, cover_path):
                # Upload to R2
                cdn_url = upload_to_r2(cover_path, cover_filename)
                result['cover_path'] = cover_filename
                result['r2_cover'] = 1 if cdn_url else 0  # Track R2 upload status
                if cdn_url:
                    uploaded_urls.append(cdn_url)
        elif cover_path.exists():
            # File exists, upload to R2
            cdn_url = upload_to_r2(cover_path, cover_filename)
            result['cover_path'] = cover_filename
            result['r2_cover'] = 1 if cdn_url else 0  # Track R2 upload status
            if cdn_url:
                uploaded_urls.append(cdn_url)
    # If no backdrop_url, cover_path remains None

    # Purge Cloudflare cache for all uploaded URLs
    if uploaded_urls:
        logger.info(f"  🔄 Purging Cloudflare cache for {len(uploaded_urls)} URL(s)...")
        purge_cloudflare_cache(uploaded_urls)

    return result


def update_series_image_paths(series_id: int, image_paths: Dict[str, Optional[str]]) -> bool:
    """
    Update series table with local image filenames and R2 upload status

    Args:
        series_id: Series database ID
        image_paths: Dict with 'poster_path', 'cover_path', 'r2_poster', 'r2_cover' keys

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

        # Check which columns exist
        cursor.execute('''
            SHOW COLUMNS FROM series LIKE 'local_%'
        ''')
        existing_columns = {row[0] for row in cursor.fetchall()}

        cursor.execute('''
            SHOW COLUMNS FROM series LIKE 'r2_%'
        ''')
        r2_columns = {row[0] for row in cursor.fetchall()}

        existing_columns.update(r2_columns)

        # Add local_poster_path if not exists
        if 'local_poster_path' not in existing_columns:
            logger.info("Adding local_poster_path column...")
            cursor.execute("ALTER TABLE series ADD COLUMN local_poster_path VARCHAR(512) NULL COMMENT 'Local poster image path'")
            conn.commit()

        # Add local_cover_path if not exists
        if 'local_cover_path' not in existing_columns:
            logger.info("Adding local_cover_path column...")
            cursor.execute("ALTER TABLE series ADD COLUMN local_cover_path VARCHAR(512) NULL COMMENT 'Local backdrop/cover image path'")
            conn.commit()

        # Add r2_poster if not exists
        if 'r2_poster' not in existing_columns:
            logger.info("Adding r2_poster column...")
            cursor.execute("ALTER TABLE series ADD COLUMN r2_poster TINYINT NULL DEFAULT NULL COMMENT 'R2 poster upload status: 1=success, 0=failed, NULL=not attempted'")
            conn.commit()

        # Add r2_cover if not exists
        if 'r2_cover' not in existing_columns:
            logger.info("Adding r2_cover column...")
            cursor.execute("ALTER TABLE series ADD COLUMN r2_cover TINYINT NULL DEFAULT NULL COMMENT 'R2 cover upload status: 1=success, 0=failed, NULL=not attempted'")
            conn.commit()

        # Update paths and R2 status
        update_fields = []
        values = []

        if image_paths.get('poster_path'):
            update_fields.append('local_poster_path = %s')
            values.append(image_paths['poster_path'])

        if image_paths.get('cover_path'):
            update_fields.append('local_cover_path = %s')
            values.append(image_paths['cover_path'])

        # Update R2 upload status
        if 'r2_poster' in image_paths and image_paths['r2_poster'] is not None:
            update_fields.append('r2_poster = %s')
            values.append(image_paths['r2_poster'])

        if 'r2_cover' in image_paths and image_paths['r2_cover'] is not None:
            update_fields.append('r2_cover = %s')
            values.append(image_paths['r2_cover'])

        if update_fields:
            values.append(series_id)
            sql = f"UPDATE series SET {', '.join(update_fields)} WHERE id = %s"
            cursor.execute(sql, values)
            conn.commit()
            logger.info(f"✓ Updated series {series_id} with local image filenames")
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
        # Note: We now process all series since we have fallback to default images
        if series_id:
            cursor.execute('''
                SELECT id, name, title, year, poster_url, original_poster_url, backdrop_url
                FROM series
                WHERE id = %s
            ''', (series_id,))
        else:
            query = '''
                SELECT id, name, title, year, poster_url, original_poster_url, backdrop_url
                FROM series
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
