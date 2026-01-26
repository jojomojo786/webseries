"""
Database module for webseries scraper
"""

import os
import re
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
            # Extract metadata
            year = extract_year_from_title(item.get('title', ''))
            season = extract_season_from_title(item.get('title', ''))

            torrents = item.get('torrents', [])

            # Calculate episode count from torrent names (not just counting torrents)
            episode_count = extract_episode_count_from_torrents(torrents)
            total_size_bytes = sum(t.get('size_bytes', 0) for t in torrents)
            total_size_human = format_size(total_size_bytes) if total_size_bytes > 0 else None
            quality = get_best_quality(torrents)

            # Insert or update series with metadata
            cursor.execute('''
                INSERT INTO series (title, url, created_at, year, season, episode_count, total_size_human, quality)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    title = VALUES(title),
                    created_at = VALUES(created_at),
                    year = VALUES(year),
                    season = VALUES(season),
                    episode_count = VALUES(episode_count),
                    total_size_human = VALUES(total_size_human),
                    quality = VALUES(quality)
            ''', (
                item['title'],
                item['url'],
                datetime.fromisoformat(item['scraped_at']) if item.get('scraped_at') else datetime.now(),
                year,
                season,
                episode_count,
                total_size_human,
                quality
            ))

            # Get series ID
            if cursor.lastrowid:
                series_id = cursor.lastrowid
                series_count += 1
            else:
                cursor.execute('SELECT id FROM series WHERE url = %s', (item['url'],))
                result = cursor.fetchone()
                series_id = result[0] if result else None

            if series_id and torrents:
                # Delete existing torrents for this series (to avoid duplicates on re-scrape)
                cursor.execute('DELETE FROM torrents WHERE series_id = %s', (series_id,))

                # Insert torrents
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
                        INSERT INTO torrents (series_id, type, name, link, size_bytes, size_human, quality)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ''', (
                        series_id,
                        torrent.get('type', 'magnet'),
                        torrent.get('name', ''),
                        torrent.get('link', ''),
                        torrent.get('size_bytes', 0),
                        torrent.get('size_human', 'unknown'),
                        torrent_quality
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
