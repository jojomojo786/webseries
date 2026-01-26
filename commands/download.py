"""
Download command - Send magnet links to qBittorrent
"""

import os
import shutil
import time
import click
from db import get_connection
from logger import get_logger
from mysql.connector import Error

logger = get_logger(__name__)

try:
    from qbittorrentapi import Client
    QBITTORRENT_AVAILABLE = True
except ImportError:
    QBITTORRENT_AVAILABLE = False


# Default paths
DEFAULT_DOWNLOADS_DIR = '/home/webseries/downloads'
DEFAULT_TEMP_DIR = os.path.join(DEFAULT_DOWNLOADS_DIR, 'temp')
DEFAULT_COMPLETED_DIR = os.path.join(DEFAULT_DOWNLOADS_DIR, 'completed')


def get_qbittorrent_client(host='localhost', port=8090, username=None, password=None):
    """
    Get qBittorrent client connection
    Tries without credentials first, then with credentials if provided

    Args:
        host: qBittorrent Web UI host
        port: qBittorrent Web UI port
        username: qBittorrent username (optional)
        password: qBittorrent password (optional)

    Returns:
        Client instance or None
    """
    if not QBITTORRENT_AVAILABLE:
        logger.error("qbittorrent-api package not installed. Run: pip install qbittorrent-api")
        return None

    # Try without credentials first (for local installations with no auth)
    if not username or not password:
        try:
            client = Client(
                host=f'http://{host}:{port}',
                username=None,
                password=None,
                SIMPLE_RESPONSES=True
            )
            # Test connection
            client.auth_log_in()
            logger.info(f"Connected to qBittorrent at {host}:{port} (no auth)")
            return client
        except Exception as e:
            if username and password:
                logger.debug(f"No-auth connection failed, trying with credentials...")
            else:
                logger.error(f"Failed to connect to qBittorrent: {e}")
                logger.error(f"Try: --username admin --password adminadmin")
                return None

    # Try with credentials
    try:
        client = Client(
            host=f'http://{host}:{port}',
            username=username,
            password=password
        )
        # Test connection
        client.auth_log_in()
        logger.info(f"Connected to qBittorrent at {host}:{port}")
        return client
    except Exception as e:
        logger.error(f"Failed to connect to qBittorrent: {e}")
        return None


def get_torrents_from_db(series_id=None, season_id=None, quality=None, limit=None):
    """
    Fetch torrents from database (excludes already successful downloads)

    Args:
        series_id: Filter by series ID
        season_id: Filter by season ID
        quality: Filter by quality (e.g., '1080p', '720p')
        limit: Maximum number of torrents to fetch

    Returns:
        List of torrent dicts
    """
    conn = get_connection()
    if not conn:
        return []

    cursor = conn.cursor(dictionary=True)

    try:
        query = '''
            SELECT t.*, s.title as series_title, sea.season_number
            FROM torrents t
            JOIN seasons sea ON t.season_id = sea.id
            JOIN series s ON sea.series_id = s.id
            WHERE t.link IS NOT NULL AND t.link != ''
            AND (t.status IS NULL OR t.status = 0)
        '''
        params = []

        if series_id:
            query += ' AND s.id = %s'
            params.append(series_id)

        if season_id:
            query += ' AND sea.id = %s'
            params.append(season_id)

        if quality:
            query += ' AND t.quality = %s'
            params.append(quality)

        query += ' ORDER BY s.title, sea.season_number, t.id DESC'

        if limit:
            query += ' LIMIT %s'
            params.append(limit)

        cursor.execute(query, tuple(params) if params else ())
        return cursor.fetchall()

    except Error as e:
        logger.error(f"Database error: {e}")
        return []

    finally:
        cursor.close()
        conn.close()


def update_torrent_status(torrent_id: int, status: int) -> bool:
    """
    Update torrent status in database

    Args:
        torrent_id: ID of the torrent
        status: 0 = failed/pending, 1 = success

    Returns:
        bool: True if successful
    """
    conn = get_connection()
    if not conn:
        return False

    cursor = conn.cursor()

    try:
        cursor.execute('UPDATE torrents SET status = %s WHERE id = %s', (status, torrent_id))
        conn.commit()
        return True

    except Error as e:
        logger.error(f"Failed to update torrent status: {e}")
        return False

    finally:
        cursor.close()
        conn.close()


def move_completed_torrents(client, temp_dir=DEFAULT_TEMP_DIR, completed_dir=DEFAULT_COMPLETED_DIR):
    """
    Move completed torrents from temp to completed folder

    Args:
        client: qBittorrent client
        temp_dir: Temporary download folder
        completed_dir: Completed downloads folder

    Returns:
        tuple: (moved_count, skipped_count)
    """
    if not os.path.exists(temp_dir):
        logger.warning(f"Temp directory does not exist: {temp_dir}")
        return 0, 0

    if not os.path.exists(completed_dir):
        os.makedirs(completed_dir)
        logger.info(f"Created completed directory: {completed_dir}")

    moved_count = 0
    skipped_count = 0

    try:
        torrents = client.torrents_info()

        for torrent in torrents:
            # Check if torrent is completed and in temp directory
            if torrent.get('progress') == 1.0:  # 100% complete
                save_path = torrent.get('save_path', '')
                content_path = torrent.get('content_path', '')
                magnet_uri = torrent.get('magnet_uri', '')

                if temp_dir in save_path:
                    torrent_name = torrent.get('name', 'unknown')

                    # Determine source path (could be file or folder)
                    if content_path and os.path.exists(content_path):
                        source = content_path
                    else:
                        source = os.path.join(save_path, torrent_name)

                    if not os.path.exists(source):
                        logger.debug(f"Source not found: {source}")
                        skipped_count += 1
                        continue

                    # Destination path
                    dest = os.path.join(completed_dir, torrent_name)

                    # Check if already exists in completed
                    if os.path.exists(dest):
                        logger.info(f"Already in completed: {torrent_name}")
                        skipped_count += 1
                        continue

                    # Move the file/folder
                    try:
                        shutil.move(source, dest)
                        logger.info(f"Moved: {torrent_name}")
                        moved_count += 1

                        # Update status in database
                        if magnet_uri:
                            update_torrent_status_by_magnet(magnet_uri, 1)

                        # Remove torrent from qBittorrent (optional - keeps list clean)
                        # client.torrents_delete(torrent_hashes=torrent['hash'])
                    except Exception as e:
                        logger.error(f"Failed to move '{torrent_name}': {e}")
                        skipped_count += 1

    except Exception as e:
        logger.error(f"Error moving completed torrents: {e}")

    return moved_count, skipped_count


def update_torrent_status_by_magnet(magnet_link: str, status: int) -> bool:
    """
    Update torrent status in database by magnet link

    Args:
        magnet_link: Magnet link of the torrent
        status: 0 = failed/pending, 1 = success

    Returns:
        bool: True if successful
    """
    conn = get_connection()
    if not conn:
        return False

    cursor = conn.cursor()

    try:
        cursor.execute('UPDATE torrents SET status = %s WHERE link = %s', (status, magnet_link))
        conn.commit()
        if cursor.rowcount > 0:
            logger.debug(f"Updated status for torrent (status={status})")
        return True

    except Error as e:
        logger.error(f"Failed to update torrent status by magnet: {e}")
        return False

    finally:
        cursor.close()
        conn.close()


def watch_and_move_completed(client, temp_dir=DEFAULT_TEMP_DIR, completed_dir=DEFAULT_COMPLETED_DIR,
                             interval=30, max_iterations=None):
    """
    Continuously watch for completed torrents and move them

    Args:
        client: qBittorrent client
        temp_dir: Temporary download folder
        completed_dir: Completed downloads folder
        interval: Check interval in seconds
        max_iterations: Maximum number of checks (None = infinite)
    """
    logger.info(f"Watching for completed torrents (interval: {interval}s)...")
    logger.info(f"Temp: {temp_dir} -> Completed: {completed_dir}")

    iteration = 0
    try:
        while True:
            if max_iterations and iteration >= max_iterations:
                logger.info("Max iterations reached, stopping watch")
                break

            moved, skipped = move_completed_torrents(client, temp_dir, completed_dir)

            if moved > 0:
                logger.info(f"Moved {moved} torrent(s), {skipped} skipped")

            iteration += 1
            time.sleep(interval)

    except KeyboardInterrupt:
        logger.info("Watch stopped by user")


@click.command()
@click.option('--host', default='localhost', help='qBittorrent Web UI host')
@click.option('--port', default=8090, type=int, help='qBittorrent Web UI port')
@click.option('--username', help='qBittorrent username')
@click.option('--password', help='qBittorrent password')
@click.option('--series-id', type=int, help='Download torrents for specific series ID')
@click.option('--season-id', type=int, help='Download torrents for specific season ID')
@click.option('--quality', help='Filter by quality (e.g., 1080p, 720p)')
@click.option('--limit', type=int, help='Maximum number of torrents to download')
@click.option('--save-path', help='Custom save path for downloads (default: ./downloads/temp)')
@click.option('--temp-dir', default=DEFAULT_TEMP_DIR, help='Temp download folder')
@click.option('--completed-dir', default=DEFAULT_COMPLETED_DIR, help='Completed downloads folder')
@click.option('--category', help='Torrent category in qBittorrent')
@click.option('--dry-run', is_flag=True, help='Show what would be downloaded without actually downloading')
@click.pass_context
def download(ctx, host, port, username, password, series_id, season_id, quality,
             limit, save_path, temp_dir, completed_dir, category, dry_run):
    """Download torrents from database using qBittorrent"""
    config = ctx.obj.get('config', {})

    # Use config values if not provided via CLI
    qb_config = config.get('qbittorrent', {})
    host = host or qb_config.get('host', 'localhost')
    port = port or qb_config.get('port', 8090)
    username = username or qb_config.get('username')
    password = password or qb_config.get('password')

    # Default to temp directory if no custom save path
    if not save_path:
        save_path = temp_dir

    # Fetch torrents from database
    logger.info("Fetching torrents from database...")
    torrents = get_torrents_from_db(
        series_id=series_id,
        season_id=season_id,
        quality=quality,
        limit=limit
    )

    if not torrents:
        logger.warning("No torrents found matching criteria")
        return

    logger.info(f"Found {len(torrents)} torrents")
    logger.info(f"Downloads will be saved to: {save_path}")

    if dry_run:
        logger.info("Dry run - would download the following torrents:")
        for t in torrents:
            logger.info(f"  - [{t['series_title']} S{t['season_number']}] {t['name'][:60]}... ({t['quality']})")
        return

    # Connect to qBittorrent
    client = get_qbittorrent_client(host, port, username, password)
    if not client:
        return

    # Download torrents
    success_count = 0
    skip_count = 0
    error_count = 0

    for t in torrents:
        magnet_link = t['link']
        name = f"{t['series_title']} S{t['season_number']} - {t['name']}"

        try:
            # Check if torrent already exists
            torrents_info = client.torrents_info()
            existing = [tr for tr in torrents_info if tr['magnet_uri'] == magnet_link]

            if existing:
                logger.info(f"Skipping (already exists): {name[:60]}...")
                skip_count += 1
                continue

            # Add torrent
            options = {'save_path': save_path}
            if category:
                options['category'] = category

            client.torrents.add(
                urls=magnet_link,
                **options
            )
            logger.info(f"Added: {name[:60]}... ({t['quality']})")
            success_count += 1

        except Exception as e:
            logger.error(f"Failed to add '{name[:50]}...': {e}")
            error_count += 1

    logger.info(f"Download complete: {success_count} added, {skip_count} skipped, {error_count} failed")
    logger.info(f"Files will be stored in: {save_path}")
    logger.info(f"Run 'move-completed' command to move finished files to: {completed_dir}")


@click.command()
@click.option('--host', default='localhost', help='qBittorrent Web UI host')
@click.option('--port', default=8090, type=int, help='qBittorrent Web UI port')
@click.option('--username', help='qBittorrent username')
@click.option('--password', help='qBittorrent password')
@click.option('--temp-dir', default=DEFAULT_TEMP_DIR, help='Temp download folder')
@click.option('--completed-dir', default=DEFAULT_COMPLETED_DIR, help='Completed downloads folder')
@click.option('--watch', is_flag=True, help='Continuously watch and move completed torrents')
@click.option('--interval', default=30, type=int, help='Watch interval in seconds')
@click.pass_context
def move_completed(ctx, host, port, username, password, temp_dir, completed_dir, watch, interval):
    """Move completed torrents from temp to completed folder"""
    config = ctx.obj.get('config', {})

    # Use config values if not provided via CLI
    qb_config = config.get('qbittorrent', {})
    host = host or qb_config.get('host', 'localhost')
    port = port or qb_config.get('port', 8090)
    username = username or qb_config.get('username')
    password = password or qb_config.get('password')

    # Connect to qBittorrent
    client = get_qbittorrent_client(host, port, username, password)
    if not client:
        return

    if watch:
        watch_and_move_completed(client, temp_dir, completed_dir, interval)
    else:
        moved, skipped = move_completed_torrents(client, temp_dir, completed_dir)
        logger.info(f"Move complete: {moved} moved, {skipped} skipped")
