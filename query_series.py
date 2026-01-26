#!/usr/bin/env python3
"""
Query helper for series data
Usage: python3 query_series.py [view|table] [limit]
"""

import sys
from db import get_connection
from logger import setup_logging, get_logger
from config import load_config

# Setup logging
config = load_config()
setup_logging(config)
logger = get_logger(__name__)

mode = sys.argv[1] if len(sys.argv) > 1 else 'view'
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20

conn = get_connection()
if not conn:
    logger.error("Failed to connect to database")
    sys.exit(1)

cursor = conn.cursor(dictionary=True)

print("=" * 80)
print("SERIES DATA")
print("=" * 80)

if mode == 'view':
    print("\n📺 Using series_with_seasons VIEW (recommended):\n")
    cursor.execute('''
        SELECT * FROM series_with_seasons
        ORDER BY created_at DESC
        LIMIT %s
    ''', (limit,))
else:
    print("\n📺 Using series table with JOIN:\n")
    cursor.execute('''
        SELECT
            s.*,
            COUNT(seas.id) as season_count,
            GROUP_CONCAT(DISTINCT seas.quality ORDER BY seas.quality SEPARATOR ', ') as qualities
        FROM series s
        LEFT JOIN seasons seas ON s.id = seas.series_id
        GROUP BY s.id
        ORDER BY s.created_at DESC
        LIMIT %s
    ''', (limit,))

results = cursor.fetchall()

for i, row in enumerate(results, 1):
    print(f"{i}. ID {row['id']}: {row['title'][:70]}...")
    print(f"   URL: {row['url'][:60]}...")
    if 'season_count' in row:
        print(f"   Seasons: {row['season_count']}")
    if 'first_season' in row and row['first_season']:
        print(f"   Season range: S{row['first_season']} - S{row['last_season']}")
    if 'available_qualities' in row and row['available_qualities']:
        print(f"   Qualities: {row['available_qualities']}")
    print(f"   Created: {row['created_at']}")
    print()

cursor.close()
conn.close()

print("=" * 80)
print(f"Showing {len(results)} results")
print("=" * 80)
