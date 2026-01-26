#!/usr/bin/env python3
"""
Run database migrations to update schema and populate new fields
"""

import sys
import re
from db import get_connection


def run_migration():
    """Execute the migration SQL"""
    conn = get_connection()
    if not conn:
        print("Failed to connect to database")
        return False

    cursor = conn.cursor()

    try:
        # Read migration file
        with open('migrations/001_add_series_metadata.sql', 'r') as f:
            sql = f.read()

        # Split by semicolon and execute each statement
        statements = [s.strip() for s in sql.split(';') if s.strip()]

        for statement in statements:
            if statement:
                print(f"Executing: {statement[:60]}...")
                cursor.execute(statement)

        conn.commit()
        print("\n✓ Migration completed successfully!")
        return True

    except Exception as e:
        print(f"Migration error: {e}")
        conn.rollback()
        return False

    finally:
        cursor.close()
        conn.close()


def backfill_data():
    """Update existing series with extracted metadata"""
    from db import get_all_series, extract_year_from_title, extract_season_from_title
    from db import get_series_with_torrents, extract_episode_count_from_torrents

    conn = get_connection()
    if not conn:
        print("Failed to connect to database")
        return False

    cursor = conn.cursor()

    try:
        series_list = get_all_series()
        print(f"\nBackfilling {len(series_list)} series...")

        updated = 0
        for series in series_list:
            # Extract metadata
            year = extract_year_from_title(series['title'])
            season = extract_season_from_title(series['title'])

            # Get series with torrents to calculate actual episode count from names
            series_with_torrents = get_series_with_torrents(series['id'])
            torrents = series_with_torrents.get('torrents', []) if series_with_torrents else []

            # Calculate episode count from torrent names (not just counting torrents)
            episode_count = extract_episode_count_from_torrents(torrents)

            # Calculate total size
            total_size = sum(t.get('size_bytes', 0) for t in torrents)

            # Get best quality - use CASE WHEN for MySQL compatibility
            cursor.execute('''
                SELECT DISTINCT quality FROM torrents
                WHERE series_id = %s
                ORDER BY CASE quality
                    WHEN '4k' THEN 1
                    WHEN '1080p' THEN 2
                    WHEN '720p' THEN 3
                    WHEN '480p' THEN 4
                    WHEN '360p' THEN 5
                    ELSE 6
                END
            ''', (series['id'],))
            qualities = [row[0] for row in cursor.fetchall()]
            quality = qualities[0] if qualities else None

            # Update series (without languages as it's not needed)
            cursor.execute('''
                UPDATE series
                SET year = %s, season = %s, episode_count = %s, total_size = %s, quality = %s
                WHERE id = %s
            ''', (year, season, episode_count, total_size, quality, series['id']))

            updated += 1
            if updated <= 5:
                size_gb = f"{total_size / (1024**3):.1f} GB"
                print(f"  {series['title'][:40]:<40} -> Y:{year} S:{season} Q:{quality} EPs:{episode_count} Size:{size_gb}")

        conn.commit()
        print(f"\n✓ Backfilled {updated} series successfully!")
        return True

    except Exception as e:
        print(f"Backfill error: {e}")
        conn.rollback()
        return False

    finally:
        cursor.close()
        conn.close()


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="Run database migrations")
    parser.add_argument("--backfill", action="store_true", help="Backfill existing data after migration")
    args = parser.parse_args()

    print("=" * 60)
    print("DATABASE MIGRATION")
    print("=" * 60)

    # Run migration
    if not run_migration():
        sys.exit(1)

    # Optionally backfill data
    if args.backfill:
        if not backfill_data():
            sys.exit(1)
    else:
        print("\nTip: Run with --backfill to populate new fields with existing data")

    print("\nDone!")


if __name__ == "__main__":
    main()
