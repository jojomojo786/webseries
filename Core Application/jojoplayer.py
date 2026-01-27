"""
JojoPlayer integration for episodes
Fetches streaming links from embedojo.net API for processed episodes
"""

import os
import sys
import json
import random
import requests
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, quote
from urllib.request import urlopen
from requests.packages.urllib3.exceptions import InsecureRequestWarning

# Add parent directory to Python path
script_dir = Path(__file__).parent.parent
sys.path.insert(0, str(script_dir / "Core Application"))

from db import get_connection
from logger import get_logger

logger = get_logger(__name__)

# Disable SSL warnings
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# API configuration
JOJOPLAYER_API_KEY = os.getenv('JOJOPLAYER_API_KEY', 'psFx3j6O3')
JOJOPLAYER_DOMAIN = os.getenv('JOJOPLAYER_DOMAIN', 'http://jojo.ovoh/')
EMBEDOJO_API_BASE = 'https://embedojo.net/api'
EMBEDOJO_MEMBER_ID = os.getenv('EMBEDOJO_MEMBER_ID', '254')

# User agents for API requests
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
]


def get_headers():
    """Get random user agent headers"""
    return {'User-Agent': random.choice(USER_AGENTS)}


def get_video_url_from_file_path(file_path: str) -> str:
    """
    Convert file_path to jojo.ovoh video URL

    Args:
        file_path: Path like 'processed/www.1TamilMV.band - Knight (2026) S01 EP01 - 1080p.mkv'

    Returns:
        URL like 'http://jojo.ovoh/www.1TamilMV.band%20-%20Knight%20(2026)%20S01%20EP01%20-%201080p.mkv'
    """
    # Remove 'processed/' prefix if present
    if file_path.startswith('processed/'):
        file_path = file_path[len('processed/'):]

    # URL encode the filename
    encoded_filename = quote(file_path)

    return f"{JOJOPLAYER_DOMAIN}{encoded_filename}"


def fetch_jojoplayer_link(video_url: str, year: int = None) -> str | None:
    """
    Fetch streaming link from embedojo.net API

    Args:
        video_url: The jojo.ovoh video URL
        year: Year of the series (2026 gets priority 1)

    Returns:
        Streaming URL or None if failed
    """
    headers = get_headers()

    # Build API URL with priority for 2026 content
    if year == 2026:
        api_url = f"{EMBEDOJO_API_BASE}/addVideo.php?key={JOJOPLAYER_API_KEY}&url={video_url}&priority=1&member={EMBEDOJO_MEMBER_ID}&server=rand&disk=rand"
        logger.debug(f"Using priority 1 for year 2026 content")
    else:
        api_url = f"{EMBEDOJO_API_BASE}/addVideo.php?key={JOJOPLAYER_API_KEY}&url={video_url}&member={EMBEDOJO_MEMBER_ID}&server=rand&disk=rand"

    try:
        # Step 1: Add video to embedojo
        logger.debug(f"Adding video: {video_url}")
        response = requests.get(api_url, headers=headers, verify=False, timeout=30)
        result = json.loads(response.text)

        if result.get('status') != 'success':
            logger.error(f"API returned non-success: {result}")
            return None

        video_id = result.get('id')
        logger.debug(f"Video added with ID: {video_id}")

        # Step 2: Get video details with streaming URL
        get_url = f"{EMBEDOJO_API_BASE}/getVideo.php?key={JOJOPLAYER_API_KEY}&id={video_id}"
        response = requests.get(get_url, headers=headers, verify=False, timeout=30)
        result = json.loads(response.text)

        streaming_url = result.get('data', {}).get('url-list', {}).get('url')

        if streaming_url and streaming_url != 'None':
            logger.info(f"Got streaming URL: {streaming_url}")
            return streaming_url
        else:
            logger.warning(f"No streaming URL returned: {result}")
            return None

    except requests.exceptions.Timeout:
        logger.error("API request timed out")
        return None
    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        return None
    except Exception as e:
        logger.error(f"Error fetching jojoplayer link: {e}")
        return None


def fetch_episodes_for_jojoplayer(limit: int = 10) -> list[dict]:
    """
    Fetch episodes that need jojoplayer links

    Args:
        limit: Maximum number of episodes to fetch

    Returns:
        List of episode dicts
    """
    conn = get_connection()
    if not conn:
        return []

    cursor = conn.cursor(dictionary=True)

    try:
        # Get episodes with season and series info
        query = '''
            SELECT
                e.id as episode_id,
                e.episode_number,
                e.file_path,
                e.jojoplayer,
                s.title as series_title,
                sea.season_number,
                sea.year as year
            FROM episodes e
            JOIN seasons sea ON e.season_id = sea.id
            JOIN series s ON sea.series_id = s.id
            WHERE e.jojoplayer_fetched = 0
            AND e.file_path IS NOT NULL
            AND e.status = 1
            ORDER BY e.id DESC
            LIMIT %s
        '''
        cursor.execute(query, (limit,))
        episodes = cursor.fetchall()
        logger.info(f"Found {len(episodes)} episodes needing jojoplayer links")
        return episodes

    except Exception as e:
        logger.error(f"Error fetching episodes: {e}")
        return []
    finally:
        cursor.close()
        conn.close()


def update_episode_jojoplayer(episode_id: int, streaming_url: str) -> bool:
    """
    Update episode with jojoplayer streaming link

    Args:
        episode_id: Episode ID
        streaming_url: Streaming URL from API

    Returns:
        True if successful
    """
    conn = get_connection()
    if not conn:
        return False

    cursor = conn.cursor()

    try:
        query = '''
            UPDATE episodes
            SET jojoplayer = %s,
                jojoplayer_fetched = 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        '''
        cursor.execute(query, (streaming_url, episode_id))
        conn.commit()
        logger.info(f"Updated episode {episode_id} with jojoplayer link")
        return True

    except Exception as e:
        logger.error(f"Error updating episode {episode_id}: {e}")
        return False
    finally:
        cursor.close()
        conn.close()


def process_episode_jojoplayer(episode: dict, dry_run: bool = False) -> bool:
    """
    Process a single episode to fetch jojoplayer link

    Args:
        episode: Episode dict from database
        dry_run: If True, don't actually update database

    Returns:
        True if successful
    """
    episode_id = episode['episode_id']
    series_title = episode['series_title']
    season_num = episode['season_number']
    episode_num = episode['episode_number']
    file_path = episode['file_path']
    year = episode.get('year')

    episode_desc = f"{series_title} S{season_num:02d}E{episode_num:02d}"
    logger.info(f"Processing: {episode_desc}")

    # Build video URL
    video_url = get_video_url_from_file_path(file_path)
    logger.debug(f"Video URL: {video_url}")

    # Fetch streaming link
    streaming_url = fetch_jojoplayer_link(video_url, year)

    if not streaming_url:
        logger.warning(f"Failed to fetch link for {episode_desc}")
        return False

    if dry_run:
        logger.info(f"[DRY RUN] Would update {episode_desc} with: {streaming_url}")
        return True

    # Update database
    return update_episode_jojoplayer(episode_id, streaming_url)


def run_jojoplayer_fetch(limit: int = 10, dry_run: bool = False, watch: bool = False, interval: int = 60):
    """
    Main entry point to fetch jojoplayer links for episodes

    Args:
        limit: Max episodes to process per batch
        dry_run: Preview without updating
        watch: Continuous watch mode
        interval: Check interval in seconds (for watch mode)
    """
    logger.info("JojoPlayer fetch started")

    if watch:
        logger.info(f"Watch mode enabled (interval: {interval}s)")
        logger.info("Press Ctrl+C to stop")

        try:
            while True:
                episodes = fetch_episodes_for_jojoplayer(limit)

                if not episodes:
                    logger.info("No new episodes to process")
                else:
                    logger.info(f"Processing {len(episodes)} episode(s)")

                    for episode in episodes:
                        process_episode_jojoplayer(episode, dry_run)

                import time
                time.sleep(interval)

        except KeyboardInterrupt:
            logger.info("Watch mode stopped by user")
    else:
        # Single run
        episodes = fetch_episodes_for_jojoplayer(limit)

        if not episodes:
            logger.info("No episodes need jojoplayer links")
            return

        logger.info(f"Processing {len(episodes)} episode(s)")
        success_count = 0

        for episode in episodes:
            if process_episode_jojoplayer(episode, dry_run):
                success_count += 1

        logger.info(f"Completed: {success_count}/{len(episodes)} successful")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Fetch JojoPlayer streaming links for episodes')
    parser.add_argument('--limit', type=int, default=10, help='Max episodes to process')
    parser.add_argument('--dry-run', action='store_true', help='Preview without updating')
    parser.add_argument('--watch', action='store_true', help='Continuous watch mode')
    parser.add_argument('--interval', type=int, default=60, help='Watch interval in seconds')

    args = parser.parse_args()

    run_jojoplayer_fetch(
        limit=args.limit,
        dry_run=args.dry_run,
        watch=args.watch,
        interval=args.interval
    )


# Click command for CLI integration
try:
    import click

    @click.command()
    @click.option('--limit', type=int, default=10, help='Max episodes to process per batch')
    @click.option('--dry-run', is_flag=True, help='Preview without updating database')
    @click.option('--watch', is_flag=True, help='Continuous watch mode')
    @click.option('--interval', type=int, default=60, help='Watch check interval in seconds')
    @click.pass_context
    def jojoplayer(ctx, limit, dry_run, watch, interval):
        """Fetch JojoPlayer streaming links for processed episodes"""
        run_jojoplayer_fetch(
            limit=limit,
            dry_run=dry_run,
            watch=watch,
            interval=interval
        )

except ImportError:
    pass  # Click not available, standalone mode only
