"""
Download command - Send magnet links to qBittorrent
"""

import sys
from pathlib import Path

# Add all subdirectories to Python path for imports
script_dir = Path(__file__).parent.parent
sys.path.insert(0, str(script_dir / "Core Application"))
sys.path.insert(0, str(script_dir))

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


# Default paths (relative to new directory structure)
script_dir = Path(__file__).parent.parent
DEFAULT_DOWNLOADS_DIR = str(script_dir / 'Data & Cache' / 'downloads')
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
        torrents = cursor.fetchall()

        # Extract info_hash from magnet links for duplicate detection
        for t in torrents:
            t['info_hash'] = extract_info_hash(t.get('link', ''))

        return torrents

    except Error as e:
        logger.error(f"Database error: {e}")
        return []

    finally:
        cursor.close()
        conn.close()


def extract_info_hash(magnet_link: str) -> str:
    """
    Extract info_hash from magnet link
    Format: magnet:?xt=urn:btih:<hash>&...
    """
    import re
    match = re.search(r'xt=urn:btih:([a-fA-F0-9]{40})', magnet_link)
    if match:
        return match.group(1).lower()
    return ''


def update_torrent_status(torrent_id: int, status: int) -> bool:
    """
    Update torrent status in database

    Args:
        torrent_id: ID of the torrent
        status: 0 = failed/pending, 1 = downloading (added to qBittorrent), 2 = completed

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
    Move completed torrents from temp to completed folder and remove them from qBittorrent
    Auto-removes all completed torrents regardless of state (STOPPED, STOPPEDUP, etc.)

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
    removed_count = 0

    try:
        torrents = client.torrents_info()

        for torrent in torrents:
            # Handle both dict and object access (qbittorrentapi returns dicts)
            progress = torrent.get('progress', 0) if isinstance(torrent, dict) else getattr(torrent, 'progress', 0)
            save_path = torrent.get('save_path', '') if isinstance(torrent, dict) else getattr(torrent, 'save_path', '')
            content_path = torrent.get('content_path', '') if isinstance(torrent, dict) else getattr(torrent, 'content_path', '')
            magnet_uri = torrent.get('magnet_uri', '') if isinstance(torrent, dict) else getattr(torrent, 'magnet_uri', '')
            torrent_name = torrent.get('name', 'unknown') if isinstance(torrent, dict) else getattr(torrent, 'name', 'unknown')
            torrent_hash = torrent.get('hash', '') if isinstance(torrent, dict) else getattr(torrent, 'hash', '')

            # Check if torrent is completed (100% progress) - handle any state
            if progress >= 1.0:
                # ALWAYS update status to 2 when torrent completes downloading
                if magnet_uri:
                    update_torrent_status_by_magnet(magnet_uri, 2)
                    logger.info(f"Updated status=2 (completed) for: {torrent_name}")

                # Handle torrents in temp directory
                if temp_dir in save_path:
                    dest = os.path.join(completed_dir, torrent_name)

                    # Check if already exists in completed
                    if os.path.exists(dest):
                        logger.info(f"Already in completed, removing from qBittorrent: {torrent_name}")
                    else:
                        # Determine source path
                        if content_path and os.path.exists(content_path):
                            source = content_path
                        else:
                            source = os.path.join(save_path, torrent_name)

                        # Move the file/folder
                        if os.path.exists(source):
                            try:
                                shutil.move(source, dest)
                                logger.info(f"Moved: {torrent_name}")
                                moved_count += 1
                            except Exception as e:
                                logger.error(f"Failed to move '{torrent_name}': {e}")
                                skipped_count += 1
                                continue
                        else:
                            logger.debug(f"Source not found: {torrent_name}")

                # Remove from qBittorrent (keep files!)
                try:
                    # delete_files=False keeps the downloaded files
                    client.torrents_delete(delete_files=False, torrent_hashes=[torrent_hash])
                    removed_count += 1
                    logger.info(f"Removed from qBittorrent (files kept): {torrent_name}")
                except Exception as e:
                    logger.error(f"Failed to delete torrent from qBittorrent: {e}")

            # Handle torrents that are seeding/completed in completed folder
            # (files already moved but torrent still in qBittorrent)
            # Note: Status already updated above for all completed torrents
                    try:
                        # delete_files=False keeps the downloaded files
                        client.torrents_delete(delete_files=False, torrent_hashes=[torrent_hash])
                        removed_count += 1
                        logger.info(f"Removed from qBittorrent (files kept): {torrent_name}")
                    except Exception as e:
                        logger.error(f"Failed to delete torrent from qBittorrent: {e}")

    except Exception as e:
        logger.error(f"Error moving completed torrents: {e}")

    logger.info(f"Torrents removed from qBittorrent: {removed_count}")
    return moved_count, skipped_count


def update_torrent_status_by_magnet(magnet_link: str, status: int) -> bool:
    """
    Update torrent status in database by magnet link

    Args:
        magnet_link: Magnet link of the torrent
        status: 0 = failed/pending, 1 = downloading (added to qBittorrent), 2 = completed

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


def check_torrent_status(host='localhost', port=8090, username=None, password=None):
    """
    Check completion status of torrents in qBittorrent vs database

    Args:
        host: qBittorrent host
        port: qBittorrent port
        username: qBittorrent username
        password: qBittorrent password
    """
    import re

    # Connect to qBittorrent
    client = get_qbittorrent_client(host, port, username, password)
    if not client:
        return

    # Get torrents from qBittorrent
    torrents = client.torrents_info()

    if not torrents:
        click.echo("ℹ️  No torrents in qBittorrent")
        return

    # Get database connection
    conn = get_connection()
    if not conn:
        logger.error("Failed to connect to database")
        return

    cursor = conn.cursor(dictionary=True)

    click.echo("\n" + "=" * 100)
    click.echo("📊 TORRENT STATUS: qBittorrent vs Database")
    click.echo("=" * 100)

    completed_count = 0
    downloading_count = 0
    stalled_count = 0

    for t in torrents:
        # Handle both dict and object access
        progress = (t.get('progress', 0) if isinstance(t, dict) else getattr(t, 'progress', 0)) * 100
        state = (t.get('state', '') if isinstance(t, dict) else getattr(t, 'state', '')).upper()
        size_gb = (t.get('size', 0) if isinstance(t, dict) else getattr(t, 'size', 0)) / (1024**3)
        magnet_uri = t.get('magnet_uri', '') if isinstance(t, dict) else (getattr(t, 'magnet_uri', '') if hasattr(t, 'magnet_uri') else '')
        name = t.get('name', '') if isinstance(t, dict) else getattr(t, 'name', '')

        # Extract info_hash from magnet URI
        info_hash_match = re.search(r'xt=urn:btih:([a-fA-F0-9]{40})', magnet_uri)
        info_hash = info_hash_match.group(1).lower() if info_hash_match else ''

        # Find in database
        cursor.execute('SELECT id, status, series_id FROM torrents WHERE link LIKE %s', (f'%{info_hash}%',))
        db_record = cursor.fetchone()

        if db_record:
            db_status = db_record['status']
            # Determine status text
            if progress >= 100.0 or 'COMPLETED' in state or 'STOPPEDUP' in state:
                qbit_status = "✅ COMPLETED"
                status_icon = "✅"
                completed_count += 1
                expected_db_status = 2
            elif 'DOWNLOADING' in state or 'METADL' in state:
                qbit_status = "⬇️  DOWNLOADING"
                status_icon = "⬇️"
                downloading_count += 1
                expected_db_status = 1
            else:
                qbit_status = f"⏸️  {state}"
                status_icon = "⏸️"
                stalled_count += 1
                expected_db_status = 1

            # Check if DB status matches
            if db_status == expected_db_status:
                match_status = "✓ Match"
            elif db_status is None and expected_db_status == 1:
                match_status = "⚠ Needs update (should be 1)"
            elif progress >= 100.0 and db_status != 2:
                match_status = f"⚠ Needs update (should be 2, is {db_status})"
            else:
                match_status = f"? DB={db_status}"

            db_status_text = {
                None: 'Pending',
                0: 'Pending',
                1: 'Downloading',
                2: 'Completed'
            }.get(db_status, f'Unknown({db_status})')

            click.echo(f"{status_icon} {qbit_status:15s} | {progress:5.1f}% | {size_gb:5.2f} GB | DB: {db_status_text:12s} | {match_status}")
            click.echo(f"   {name[:80]}")
        else:
            click.echo(f"❌ NOT IN DB | {progress:5.1f}% | {size_gb:5.2f} GB | {state:15s}")
            click.echo(f"   {name[:80]}")

    click.echo("\n" + "-" * 100)

    # Summary
    cursor.execute('''
        SELECT
          CASE COALESCE(status, 0)
            WHEN 0 THEN 'Pending'
            WHEN 1 THEN 'Downloading'
            WHEN 2 THEN 'Completed'
            ELSE 'Unknown'
          END as status_text,
          COUNT(*) as count
        FROM torrents
        GROUP BY status_text
        ORDER BY status_text
    ''')

    click.echo("📈 DATABASE SUMMARY:")
    for row in cursor.fetchall():
        click.echo(f"   {row['status_text']:15s} : {row['count']} torrents")

    click.echo(f"\n📈 QBITTORRENT SUMMARY:")
    click.echo(f"   {'Completed':15s} : {completed_count} torrents")
    click.echo(f"   {'Downloading':15s} : {downloading_count} torrents")
    click.echo(f"   {'Other/Stalled':15s} : {stalled_count} torrents")

    click.echo("=" * 100)

    cursor.close()
    conn.close()


@click.command()
@click.option('--host', default='localhost', help='qBittorrent Web UI host')
@click.option('--port', default=8090, type=int, help='qBittorrent Web UI port')
@click.option('--username', help='qBittorrent username')
@click.option('--password', help='qBittorrent password')
@click.option('--series-id', type=int, help='Download torrents for specific series ID')
@click.option('--season-id', type=int, help='Download torrents for specific season ID')
@click.option('--quality', help='Filter by quality (e.g., 1080p, 720p)')
@click.option('--limit', type=int, help='Maximum number of torrents to download')
@click.option('--max-active', default=5, type=int, help='Maximum active torrents in qBittorrent')
@click.option('--save-path', help='Custom save path for downloads (default: ./downloads/temp)')
@click.option('--temp-dir', default=DEFAULT_TEMP_DIR, help='Temp download folder')
@click.option('--completed-dir', default=DEFAULT_COMPLETED_DIR, help='Completed downloads folder')
@click.option('--category', help='Torrent category in qBittorrent')
@click.option('--no-auto-move', is_flag=True, help='Disable automatic move of completed torrents')
@click.option('--dry-run', is_flag=True, help='Show what would be downloaded without actually downloading')
@click.option('--check-status', 'check_status', is_flag=True, help='Check completion status of torrents in qBittorrent vs database')
@click.pass_context
def download(ctx, host, port, username, password, series_id, season_id, quality,
             limit, max_active, save_path, temp_dir, completed_dir, category, no_auto_move, dry_run, check_status):
    """Download torrents from database using qBittorrent"""
    config = ctx.obj.get('config', {})

    # Handle --check-status flag
    if check_status:
        check_torrent_status(host, port, username, password)
        return

    # Use config values if not provided via CLI
    qb_config = config.get('qbittorrent', {})
    host = host or qb_config.get('host', 'localhost')
    port = port or qb_config.get('port', 8090)
    username = username or qb_config.get('username')
    password = password or qb_config.get('password')
    max_active = max_active or qb_config.get('max_active', 5)

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

    # Check current active torrents
    torrents_info = client.torrents_info()
    active_count = len(torrents_info)
    logger.info(f"Current active torrents in qBittorrent: {active_count}/{max_active}")

    if active_count >= max_active:
        logger.warning(f"Maximum active torrents ({max_active}) reached. Use move-completed to clear finished torrents.")
        return

    # Download torrents
    success_count = 0
    skip_count = 0
    error_count = 0

    for t in torrents:
        magnet_link = t['link']
        info_hash = t.get('info_hash', '')
        name = f"{t['series_title']} S{t['season_number']} - {t['name']}"

        try:
            # Refresh torrents list and check if torrent already exists
            torrents_info = client.torrents_info()
            # Compare by info_hash instead of full magnet URI
            existing = [tr for tr in torrents_info if tr.get('hash', '') == info_hash]

            if existing:
                logger.info(f"Skipping (already in qBittorrent): {name[:60]}...")
                skip_count += 1
                continue

            # Check if we've reached max active
            if len(torrents_info) >= max_active:
                logger.info(f"Maximum active torrents ({max_active}) reached. Stopping.")
                break

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

            # Set status=1 when torrent is added to qBittorrent
            update_torrent_status(t['id'], 1)
            logger.debug(f"Updated status=1 (added to qBittorrent) for: {name}")

            # Small delay to let qBittorrent register the new torrent
            time.sleep(0.1)

        except Exception as e:
            logger.error(f"Failed to add '{name[:50]}...': {e}")
            error_count += 1

    logger.info(f"Download complete: {success_count} added, {skip_count} skipped, {error_count} failed")
    logger.info(f"Files will be stored in: {save_path}")

    # Auto-move completed torrents (enabled by default)
    if not no_auto_move:
        logger.info("Auto-moving completed torrents...")
        moved, skipped = move_completed_torrents(client, temp_dir, completed_dir)
        logger.info(f"Auto-move complete: {moved} moved, {skipped} skipped")
    else:
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
