#!/usr/bin/env python3
"""
Diagnostic script to check database structure and find issues
"""

import sys
from pathlib import Path

# Add all subdirectories to Python path for imports
script_dir = Path(__file__).parent.parent
sys.path.insert(0, str(script_dir / "Core Application"))
sys.path.insert(0, str(script_dir))

from db import get_connection
from logger import setup_logging, get_logger
from config import load_config

# Setup logging
config = load_config()
setup_logging(config)
logger = get_logger(__name__)

conn = get_connection()
if not conn:
    logger.error("Failed to connect to database")
    exit(1)

cursor = conn.cursor(dictionary=True)

print("=" * 60)
print("DATABASE STRUCTURE DIAGNOSTIC")
print("=" * 60)

# Check series table structure
print("\n📋 SERIES TABLE STRUCTURE:")
cursor.execute("DESCRIBE series")
for row in cursor.fetchall():
    print(f"   {row['Field']:20s} {row['Type']:20s} {row['Null']:5s} {row['Key']:5s}")

# Check seasons table structure
print("\n📋 SEASONS TABLE STRUCTURE:")
cursor.execute("DESCRIBE seasons")
for row in cursor.fetchall():
    print(f"   {row['Field']:20s} {row['Type']:20s} {row['Null']:5s} {row['Key']:5s}")

# Check torrents table structure
print("\n📋 TORRENTS TABLE STRUCTURE:")
cursor.execute("DESCRIBE torrents")
for row in cursor.fetchall():
    print(f"   {row['Field']:20s} {row['Type']:20s} {row['Null']:5s} {row['Key']:5s}")

# Check for any views
print("\n📋 VIEWS:")
cursor.execute("SHOW FULL TABLES WHERE TABLE_TYPE LIKE 'VIEW'")
views = cursor.fetchall()
if views:
    for view in views:
        print(f"   - {view['Tables_in_database']}")
        # Show view definition
        cursor.execute(f"SHOW CREATE VIEW {view['Tables_in_database']}")
        create_view = cursor.fetchone()
        print(f"     {create_view['Create View']}")
else:
    print("   No views found")

# Check series table data with simple query
print("\n📊 SERIES TABLE SAMPLE DATA:")
try:
    cursor.execute("SELECT id, title, created_at FROM series LIMIT 3")
    for row in cursor.fetchall():
        print(f"   ID {row['id']}: {row['title'][:50]}...")
except Exception as e:
    print(f"   Error: {e}")

# Try the query that might be failing
print("\n🔍 TESTING QUERY THAT MIGHT FAIL:")
try:
    # This is likely the problematic query
    cursor.execute("SELECT * FROM series ORDER BY season")
    print("   ❌ ERROR: This query should fail but didn't!")
except Exception as e:
    print(f"   ✓ Expected error caught: {e}")

# Try correct query
print("\n✓ CORRECT QUERY (with JOIN to seasons):")
try:
    cursor.execute('''
        SELECT s.*, COUNT(seas.id) as season_count
        FROM series s
        LEFT JOIN seasons seas ON s.id = seas.series_id
        GROUP BY s.id
        ORDER BY s.created_at DESC
        LIMIT 3
    ''')
    for row in cursor.fetchall():
        print(f"   ID {row['id']}: {row['title'][:50]}... (Seasons: {row['season_count']})")
except Exception as e:
    print(f"   Error: {e}")

cursor.close()
conn.close()

print("\n" + "=" * 60)
print("DIAGNOSTIC COMPLETE")
print("=" * 60)
