"""
Database module for webseries scraper
"""

import os
import mysql.connector
from mysql.connector import Error
from datetime import datetime
from urllib.parse import urlparse

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
        print(f"Configuration error: {e}")
        return None
    except Error as e:
        print(f"Database connection error: {e}")
        return None


def save_to_database(data: list[dict]) -> tuple[int, int]:
    """
    Save scraped data to database

    Args:
        data: List of scraped items with title, url, torrents

    Returns:
        tuple: (series_count, torrent_count) inserted
    """
    conn = get_connection()
    if not conn:
        return 0, 0

    cursor = conn.cursor()
    series_count = 0
    torrent_count = 0

    try:
        for item in data:
            # Insert or update series
            cursor.execute('''
                INSERT INTO series (title, url, scraped_at)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    title = VALUES(title),
                    scraped_at = VALUES(scraped_at)
            ''', (
                item['title'],
                item['url'],
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

            if series_id and item.get('torrents'):
                # Delete existing torrents for this series (to avoid duplicates on re-scrape)
                cursor.execute('DELETE FROM torrents WHERE series_id = %s', (series_id,))

                # Insert torrents
                for torrent in item['torrents']:
                    # Determine quality from name
                    name_lower = torrent.get('name', '').lower()
                    if '2160p' in name_lower or '4k' in name_lower:
                        quality = '4k'
                    elif '1080p' in name_lower:
                        quality = '1080p'
                    elif '720p' in name_lower:
                        quality = '720p'
                    elif '480p' in name_lower:
                        quality = '480p'
                    elif '360p' in name_lower:
                        quality = '360p'
                    else:
                        quality = 'unknown'

                    cursor.execute('''
                        INSERT INTO torrents (series_id, type, name, link, size_bytes, size_human, quality)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ''', (
                        series_id,
                        torrent.get('type', 'magnet'),
                        torrent.get('name', ''),
                        torrent.get('link', ''),
                        torrent.get('size_bytes', 0),
                        torrent.get('size_human', 'unknown'),
                        quality
                    ))
                    torrent_count += 1

        conn.commit()
        print(f"Database: Saved {series_count} new series, {torrent_count} torrents")

    except Error as e:
        print(f"Database error: {e}")
        conn.rollback()

    finally:
        cursor.close()
        conn.close()

    return series_count, torrent_count


def get_all_series() -> list[dict]:
    """Get all series from database"""
    conn = get_connection()
    if not conn:
        return []

    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute('''
            SELECT s.*, COUNT(t.id) as torrent_count
            FROM series s
            LEFT JOIN torrents t ON s.id = t.series_id
            GROUP BY s.id
            ORDER BY s.scraped_at DESC
        ''')
        return cursor.fetchall()

    finally:
        cursor.close()
        conn.close()


def get_series_with_torrents(series_id: int) -> dict | None:
    """Get a series with all its torrents"""
    conn = get_connection()
    if not conn:
        return None

    cursor = conn.cursor(dictionary=True)

    try:
        cursor.execute('SELECT * FROM series WHERE id = %s', (series_id,))
        series = cursor.fetchone()

        if series:
            cursor.execute('SELECT * FROM torrents WHERE series_id = %s ORDER BY size_bytes DESC', (series_id,))
            series['torrents'] = cursor.fetchall()

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
        # Delete all torrents first (foreign key constraint)
        cursor.execute('DELETE FROM torrents')
        torrents_deleted = cursor.rowcount

        # Delete all series
        cursor.execute('DELETE FROM series')
        series_deleted = cursor.rowcount

        conn.commit()
        print(f"Cleared {series_deleted} series and {torrents_deleted} torrents from database")
        return True

    except Error as e:
        print(f"Database error: {e}")
        conn.rollback()
        return False

    finally:
        cursor.close()
        conn.close()
