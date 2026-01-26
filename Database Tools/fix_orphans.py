#!/usr/bin/env python3
"""
Fix orphan torrents by linking them to seasons
"""

import sys
from pathlib import Path

# Add all subdirectories to Python path for imports
script_dir = Path(__file__).parent.parent
sys.path.insert(0, str(script_dir / "Core Application"))
sys.path.insert(0, str(script_dir))

from db import get_connection


def fix_orphans():
    """Link orphan torrents to their series' seasons"""
    conn = get_connection()
    if not conn:
        print("Failed to connect to database")
        return False

    cursor = conn.cursor()

    try:
        # Check orphan count first
        cursor.execute('SELECT COUNT(*) FROM torrents WHERE season_id IS NULL')
        orphan_count = cursor.fetchone()[0]
        print(f"Found {orphan_count} orphan torrents")

        if orphan_count == 0:
            print("No orphans to fix!")
            return True

        # Link orphans to their series' season
        cursor.execute('''
            UPDATE torrents t
            INNER JOIN seasons s ON t.series_id = s.series_id
            SET t.season_id = s.id
            WHERE t.season_id IS NULL
        ''')

        conn.commit()
        print(f"✓ Fixed {cursor.rowcount} orphan torrents")

        # Verify
        cursor.execute('SELECT COUNT(*) FROM torrents WHERE season_id IS NULL')
        remaining = cursor.fetchone()[0]
        print(f"Remaining orphans: {remaining}")

        return remaining == 0

    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
        return False

    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    success = fix_orphans()
    sys.exit(0 if success else 1)
