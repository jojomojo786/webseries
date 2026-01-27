"""
Database module for webseries scraper
"""

import sys
from pathlib import Path

# Add parent directory to Python path for imports
script_dir = Path(__file__).parent.parent
sys.path.insert(0, str(script_dir / "Core Application"))
sys.path.insert(0, str(script_dir))

import os
import re
import mysql.connector
from mysql.connector import Error
from datetime import datetime
from urllib.parse import urlparse

from logger import get_logger

logger = get_logger(__name__)

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, use system env vars

# Database configuration from environment variable
# Format: mysql://user:password@host:port/database
DATABASE_URL = os.environ.get('DATABASE_URL', '')


def get_db_config():
    """Parse DATABASE_URL environment variable"""
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable not set")

    parsed = urlparse(DATABASE_URL)
    return {
        'host': parsed.hostname,
        'port': parsed.port or 3306,
        'user': parsed.username,
        'password': parsed.password,
        'database': parsed.path.lstrip('/')
    }


def get_connection():
    """Get database connection"""
    try:
        config = get_db_config()
        conn = mysql.connector.connect(**config)
        return conn
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return None
    except Error as e:
        logger.error(f"Database connection error: {e}")
        return None


def extract_year_from_title(title: str) -> int | None:
    """Extract year from series title (e.g., 2026)"""
    match = re.search(r'\b(20\d{2})\b', title)
    return int(match.group(1)) if match else None


def extract_season_from_title(title: str) -> int | None:
    """Extract season from series title (e.g., S01 -> 1, S02 -> 2)"""
    match = re.search(r'\bS(\d+)\b', title, re.IGNORECASE)
    return int(match.group(1)) if match else None


def extract_languages_from_title(title: str) -> str | None:
    """Extract languages from series title"""
    # Common language codes found in titles
    language_patterns = {
        'Tamil': ['Tamil', 'Tam'],
        'Telugu': ['Telugu', 'Tel'],
        'Hindi': ['Hindi', 'Hin'],
        'Malayalam': ['Malayalam', 'Mal'],
        'Kannada': ['Kannada', 'Kan'],
        'English': ['English', 'Eng'],
    }

    found_languages = []
    title_upper = title.upper()

    for lang_name, patterns in language_patterns.items():
        for pattern in patterns:
            if pattern.upper() in title_upper:
                if lang_name not in found_languages:
                    found_languages.append(lang_name)
                break

    return ', '.join(found_languages) if found_languages else None


def get_best_quality(torrents: list[dict]) -> str | None:
    """Get best quality from list of torrents"""
    if not torrents:
        return None

    quality_priority = ['4k', '1080p', '720p', '480p', '360p', 'unknown']

    for quality in quality_priority:
        for torrent in torrents:
            name_lower = torrent.get('name', '').lower()
            if quality == '4k' and ('2160p' in name_lower or '4k' in name_lower):
                return '4k'
            elif f'{quality}' in name_lower:
                return quality

    return None


def format_size(size_bytes: int) -> str:
    """Format bytes to human readable size"""
    if size_bytes >= 1024**4:
        return f"{size_bytes / 1024**4:.2f} TB"
    elif size_bytes >= 1024**3:
        return f"{size_bytes / 1024**3:.2f} GB"
    elif size_bytes >= 1024**2:
        return f"{size_bytes / 1024**2:.2f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.2f} KB"
    return f"{size_bytes} B"


def extract_episode_count_from_torrents(torrents: list[dict]) -> int:
    """Calculate actual episode count from torrent names"""
    if not torrents:
        return 0

    total_episodes = 0

    for torrent in torrents:
        name = torrent.get('name', '')

        # Check for episode ranges like "EP (01-07)" or "EP01-08"
        range_match = re.search(r'EP\s*\((\d+)-(\d+)\)', name, re.IGNORECASE)
        if not range_match:
            range_match = re.search(r'EP(\d+)-(\d+)', name, re.IGNORECASE)

        if range_match:
            # Count episodes in range
            start, end = int(range_match.group(1)), int(range_match.group(2))
            total_episodes += (end - start + 1)
        else:
            # Check for single episodes like "EP01" or "S01E01"
            single_match = re.search(r'(?:S\d+)?[Ee]?P(\d+)', name)
            if single_match:
                total_episodes += 1
            else:
                # No episode info, count as 1 (could be a full season batch)
                total_episodes += 1

    return total_episodes


def save_to_database(data: list[dict]) -> tuple[int, int, int]:
    """
    Save scraped data to database with normalized structure:
    series → seasons → torrents

    Args:
        data: List of scraped items with title, url, torrents

    Returns:
        tuple: (series_count, season_count, torrent_count) inserted
    """
    conn = get_connection()
    if not conn:
        return 0, 0, 0

    cursor = conn.cursor()
    series_count = 0
    season_count = 0
    torrent_count = 0

    try:
        for item in data:
            # Extract metadata
            year = extract_year_from_title(item.get('title', ''))
            season_number = extract_season_from_title(item.get('title', ''))
            torrents = item.get('torrents', [])

            # Calculate episode count from torrent names
            episode_count = extract_episode_count_from_torrents(torrents)
            total_size_bytes = sum(t.get('size_bytes', 0) for t in torrents)
            total_size_human = format_size(total_size_bytes) if total_size_bytes > 0 else None
            quality = get_best_quality(torrents)

            # Parse forum_date from ISO format if available
            forum_date = None
            if item.get('forum_date'):
                try:
                    forum_date = datetime.fromisoformat(item['forum_date'].replace('Z', '+00:00'))
                except ValueError:
                    pass  # Invalid date format, leave as None

            # Step 1: Insert or update series (base info only)
            cursor.execute('''
                INSERT INTO series (title, url, poster_url, forum_date, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    title = VALUES(title),
                    poster_url = COALESCE(VALUES(poster_url), poster_url),
                    forum_date = COALESCE(VALUES(forum_date), forum_date),
                    created_at = VALUES(created_at)
            ''', (
                item['title'],
                item['url'],
                item.get('poster_url'),
                forum_date,
                datetime.fromisoformat(item['scraped_at']) if item.get('scraped_at') else datetime.now()
            ))

            # Get series ID
            if cursor.lastrowid:
                series_id = cursor.lastrowid
                series_count += 1
            else:
                cursor.execute('SELECT id FROM series WHERE url = %s', (item['url'],))
                result = cursor.fetchone()
                series_id = result[0] if result else None

            if series_id:
                # Step 2: Insert or update season
                cursor.execute('''
                    INSERT INTO seasons (series_id, season_number, year, episode_count, total_size_human, quality, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        year = VALUES(year),
                        episode_count = VALUES(episode_count),
                        total_size_human = VALUES(total_size_human),
                        quality = VALUES(quality),
                        updated_at = CURRENT_TIMESTAMP
                ''', (
                    series_id,
                    season_number,
                    year,
                    episode_count,
                    total_size_human,
                    quality,
                    datetime.fromisoformat(item['scraped_at']) if item.get('scraped_at') else datetime.now()
                ))

                # Get season ID
                if cursor.lastrowid:
                    season_id = cursor.lastrowid
                    season_count += 1
                else:
                    cursor.execute('SELECT id FROM seasons WHERE series_id = %s AND season_number = %s', (series_id, season_number))
                    result = cursor.fetchone()
                    season_id = result[0] if result else None

                if season_id and torrents:
                    # Step 3: Delete existing torrents for this season
                    cursor.execute('DELETE FROM torrents WHERE season_id = %s', (season_id,))

                    # Step 4: Insert torrents linked to season
                    for torrent in torrents:
                        # Determine quality from name
                        name_lower = torrent.get('name', '').lower()
                        if '2160p' in name_lower or '4k' in name_lower:
                            torrent_quality = '4k'
                        elif '1080p' in name_lower:
                            torrent_quality = '1080p'
                        elif '720p' in name_lower:
                            torrent_quality = '720p'
                        elif '480p' in name_lower:
                            torrent_quality = '480p'
                        elif '360p' in name_lower:
                            torrent_quality = '360p'
                        else:
                            torrent_quality = 'unknown'

                        cursor.execute('''
                            INSERT INTO torrents (series_id, season_id, type, name, link, size_human, quality)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ''', (
                            series_id,
                            season_id,
                            torrent.get('type', 'magnet'),
                            torrent.get('name', ''),
                            torrent.get('link', ''),
                            torrent.get('size_human', 'unknown'),
                            torrent_quality
                        ))
                        torrent_count += 1

        conn.commit()
        logger.info(f"Database: Saved {series_count} series, {season_count} seasons, {torrent_count} torrents")

    except Error as e:
        logger.error(f"Database error: {e}")
        conn.rollback()

    finally:
        cursor.close()
        conn.close()

    return series_count, season_count, torrent_count


def get_all_series() -> list[dict]:
    """Get all series from database"""
    conn = get_connection()
    if not conn:
        return []

    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute('''
            SELECT s.*, COUNT(DISTINCT seas.id) as season_count
            FROM series s
            LEFT JOIN seasons seas ON s.id = seas.series_id
            GROUP BY s.id
            ORDER BY s.created_at DESC
        ''')
        return cursor.fetchall()

    finally:
        cursor.close()
        conn.close()


def get_series_with_torrents(series_id: int) -> dict | None:
    """Get a series with all its seasons and torrents"""
    conn = get_connection()
    if not conn:
        return None

    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute('SELECT * FROM series WHERE id = %s', (series_id,))
        series = cursor.fetchone()

        if series:
            # Get all seasons for this series
            cursor.execute('SELECT * FROM seasons WHERE series_id = %s ORDER BY season_number', (series_id,))
            series['seasons'] = cursor.fetchall()

            # Get torrents for each season
            for season in series['seasons']:
                cursor.execute('SELECT * FROM torrents WHERE season_id = %s ORDER BY id DESC', (season['id'],))
                season['torrents'] = cursor.fetchall()

        return series

    finally:
        cursor.close()
        conn.close()


def get_stats() -> dict:
    """Get database statistics"""
    conn = get_connection()
    if not conn:
        return {}

    cursor = conn.cursor(dictionary=True)

    try:
        stats = {}

        cursor.execute('SELECT COUNT(*) as count FROM series')
        stats['total_series'] = cursor.fetchone()['count']

        cursor.execute('SELECT COUNT(*) as count FROM seasons')
        stats['total_seasons'] = cursor.fetchone()['count']

        cursor.execute('SELECT COUNT(*) as count FROM torrents')
        stats['total_torrents'] = cursor.fetchone()['count']

        cursor.execute('SELECT quality, COUNT(*) as count FROM torrents GROUP BY quality')
        stats['quality_distribution'] = {row['quality']: row['count'] for row in cursor.fetchall()}

        return stats

    finally:
        cursor.close()
        conn.close()


def clear_database() -> bool:
    """Clear all data from database tables"""
    conn = get_connection()
    if not conn:
        return False

    cursor = conn.cursor()

    try:
        # Delete in order due to foreign key constraints
        cursor.execute('DELETE FROM episodes')
        episodes_deleted = cursor.rowcount

        cursor.execute('DELETE FROM torrents')
        torrents_deleted = cursor.rowcount

        cursor.execute('DELETE FROM seasons')
        seasons_deleted = cursor.rowcount

        cursor.execute('DELETE FROM series')
        series_deleted = cursor.rowcount

        conn.commit()
        logger.info(f"Cleared {series_deleted} series, {seasons_deleted} seasons, {torrents_deleted} torrents, {episodes_deleted} episodes from database")
        return True

    except Error as e:
        logger.error(f"Database error: {e}")
        conn.rollback()
        return False

    finally:
        cursor.close()
        conn.close()


# ============== Episode Management Functions ==============

def add_episode(season_id: int, episode_number: int, file_path: str = None,
                file_size: int = None, quality: str = None, duration: int = None,
                torrent_id: int = None, status: str = 'available') -> int | None:
    """
    Add or update an episode record

    Returns: episode ID or None on failure
    """
    conn = get_connection()
    if not conn:
        return None

    cursor = conn.cursor()

    try:
        cursor.execute('''
            INSERT INTO episodes (season_id, episode_number, status, file_path, file_size, quality, duration, torrent_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                status = VALUES(status),
                file_path = VALUES(file_path),
                file_size = VALUES(file_size),
                quality = COALESCE(VALUES(quality), quality),
                duration = COALESCE(VALUES(duration), duration),
                torrent_id = COALESCE(VALUES(torrent_id), torrent_id),
                updated_at = CURRENT_TIMESTAMP
        ''', (season_id, episode_number, status, file_path, file_size, quality, duration, torrent_id))

        conn.commit()

        if cursor.lastrowid:
            return cursor.lastrowid
        else:
            cursor.execute('SELECT id FROM episodes WHERE season_id = %s AND episode_number = %s',
                          (season_id, episode_number))
            result = cursor.fetchone()
            return result[0] if result else None

    except Error as e:
        logger.error(f"Error adding episode: {e}")
        conn.rollback()
        return None

    finally:
        cursor.close()
        conn.close()


def add_episodes_bulk(season_id: int, episodes: list[dict]) -> int:
    """
    Add multiple episodes at once

    Args:
        season_id: The season ID
        episodes: List of dicts with keys: episode_number, file_path, file_size, quality, duration, status

    Returns: Number of episodes added/updated
    """
    conn = get_connection()
    if not conn:
        return 0

    cursor = conn.cursor()
    count = 0

    try:
        for ep in episodes:
            cursor.execute('''
                INSERT INTO episodes (season_id, episode_number, status, file_path, file_size, quality, duration)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    status = VALUES(status),
                    file_path = VALUES(file_path),
                    file_size = VALUES(file_size),
                    quality = COALESCE(VALUES(quality), quality),
                    duration = COALESCE(VALUES(duration), duration),
                    updated_at = CURRENT_TIMESTAMP
            ''', (
                season_id,
                ep.get('episode_number'),
                ep.get('status', 'available'),
                ep.get('file_path'),
                ep.get('file_size'),
                ep.get('quality'),
                ep.get('duration')
            ))
            count += 1

        conn.commit()
        logger.info(f"Added/updated {count} episodes for season {season_id}")
        return count

    except Error as e:
        logger.error(f"Error adding episodes: {e}")
        conn.rollback()
        return 0

    finally:
        cursor.close()
        conn.close()


def get_season_episodes(season_id: int) -> list[dict]:
    """Get all episodes for a season"""
    conn = get_connection()
    if not conn:
        return []

    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute('''
            SELECT * FROM episodes
            WHERE season_id = %s
            ORDER BY episode_number
        ''', (season_id,))
        return cursor.fetchall()

    finally:
        cursor.close()
        conn.close()


def get_seasons_for_series(series_id: int) -> list[dict]:
    """Get all seasons for a series"""
    conn = get_connection()
    if not conn:
        return []

    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute('''
            SELECT id, series_id, season_number, episode_count,
                   total_size_human, quality, year
            FROM seasons
            WHERE series_id = %s
            ORDER BY season_number
        ''', (series_id,))
        return cursor.fetchall()

    finally:
        cursor.close()
        conn.close()


def get_missing_episodes(season_id: int, total_episodes: int) -> list[int]:
    """
    Get list of missing episode numbers for a season

    Args:
        season_id: The season ID
        total_episodes: Expected total number of episodes

    Returns: List of missing episode numbers
    """
    conn = get_connection()
    if not conn:
        return []

    cursor = conn.cursor()

    try:
        cursor.execute('''
            SELECT episode_number FROM episodes
            WHERE season_id = %s AND status = 'available'
        ''', (season_id,))

        available = {row[0] for row in cursor.fetchall()}
        all_episodes = set(range(1, total_episodes + 1))
        missing = sorted(all_episodes - available)

        return missing

    finally:
        cursor.close()
        conn.close()


def update_episode_status(season_id: int, episode_number: int, status: str) -> bool:
    """Update the status of an episode"""
    conn = get_connection()
    if not conn:
        return False

    cursor = conn.cursor()

    try:
        cursor.execute('''
            UPDATE episodes SET status = %s, updated_at = CURRENT_TIMESTAMP
            WHERE season_id = %s AND episode_number = %s
        ''', (status, season_id, episode_number))

        conn.commit()
        return cursor.rowcount > 0

    except Error as e:
        logger.error(f"Error updating episode status: {e}")
        conn.rollback()
        return False

    finally:
        cursor.close()
        conn.close()


def get_episodes_summary(series_id: int = None) -> list[dict]:
    """
    Get summary of episodes per season

    Returns list of dicts with: series_title, season_number, total_episodes,
                                available, missing, corrupted
    """
    conn = get_connection()
    if not conn:
        return []

    cursor = conn.cursor(dictionary=True)

    try:
        query = '''
            SELECT
                s.title as series_title,
                s.id as series_id,
                sea.id as season_id,
                sea.season_number,
                sea.episode_count as expected_episodes,
                COUNT(e.id) as total_tracked,
                SUM(CASE WHEN e.status = 'available' THEN 1 ELSE 0 END) as available,
                SUM(CASE WHEN e.status = 'missing' THEN 1 ELSE 0 END) as missing,
                SUM(CASE WHEN e.status = 'corrupted' THEN 1 ELSE 0 END) as corrupted,
                SUM(CASE WHEN e.status = 'encoding' THEN 1 ELSE 0 END) as encoding
            FROM series s
            JOIN seasons sea ON s.id = sea.series_id
            LEFT JOIN episodes e ON sea.id = e.season_id
        '''

        if series_id:
            query += ' WHERE s.id = %s'
            query += ' GROUP BY s.id, sea.id ORDER BY s.title, sea.season_number'
            cursor.execute(query, (series_id,))
        else:
            query += ' GROUP BY s.id, sea.id ORDER BY s.title, sea.season_number'
            cursor.execute(query)

        return cursor.fetchall()

    finally:
        cursor.close()
        conn.close()
