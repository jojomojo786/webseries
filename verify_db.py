#!/usr/bin/env python3
"""
Verify database structure integrity
"""

from db import get_connection, get_stats


def verify_structure():
    """Check for data integrity issues"""
    conn = get_connection()
    if not conn:
        print("Failed to connect to database")
        return

    cursor = conn.cursor(dictionary=True)

    print("=" * 60)
    print("DATABASE STRUCTURE VERIFICATION")
    print("=" * 60)

    try:
        # Get overall stats
        stats = get_stats()
        print(f"\n📊 Overall Stats:")
        print(f"   Series: {stats.get('total_series', 0)}")
        print(f"   Seasons: {stats.get('total_seasons', 0)}")
        print(f"   Torrents: {stats.get('total_torrents', 0)}")

        # Check for issues
        issues_found = False

        # 1. Series without seasons
        cursor.execute('''
            SELECT COUNT(*) as count
            FROM series s
            LEFT JOIN seasons seas ON s.id = seas.series_id
            WHERE seas.id IS NULL
        ''')
        series_without_seasons = cursor.fetchone()['count']
        if series_without_seasons > 0:
            print(f"\n⚠️  Series without seasons: {series_without_seasons}")
            issues_found = True

        # 2. Seasons without torrents
        cursor.execute('''
            SELECT COUNT(*) as count
            FROM seasons s
            LEFT JOIN torrents t ON s.id = t.season_id
            WHERE t.id IS NULL
        ''')
        seasons_without_torrents = cursor.fetchone()['count']
        if seasons_without_torrents > 0:
            print(f"\n⚠️  Seasons without torrents: {seasons_without_torrents}")
            issues_found = True

        # 3. Torrents without season_id
        cursor.execute('SELECT COUNT(*) as count FROM torrents WHERE season_id IS NULL')
        torrents_without_season = cursor.fetchone()['count']
        if torrents_without_season > 0:
            print(f"\n⚠️  Torrents without season_id: {torrents_without_season}")
            issues_found = True

        # 4. Quality distribution
        print(f"\n📺 Quality Distribution:")
        for quality, count in sorted(stats.get('quality_distribution', {}).items()):
            print(f"   {quality}: {count}")

        if not issues_found:
            print("\n✅ All checks passed! Database structure is clean.")
        else:
            print("\n❌ Issues found in database structure.")

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    verify_structure()
