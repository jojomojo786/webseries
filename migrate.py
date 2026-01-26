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


# Note: Backfill function removed since scraper now handles the new structure correctly
# The series table is now clean - only title, url, created_at, updated_at
# All metadata (year, season, episode_count, etc.) is stored in the seasons table


def main():
    """Main entry point"""
    print("=" * 60)
    print("DATABASE MIGRATION")
    print("=" * 60)
    print("\nNote: With the new normalized structure, all data is populated")
    print("      automatically by the scraper. No backfill needed.")
    print("\nDone!")


if __name__ == "__main__":
    main()
