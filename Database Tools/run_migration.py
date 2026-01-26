#!/usr/bin/env python3
"""
Run a specific migration file
Usage: python3 run_migration.py <migration_file>
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

if len(sys.argv) < 2:
    logger.error("Usage: python3 run_migration.py <migration_file>")
    sys.exit(1)

migration_file = sys.argv[1]

logger.info(f"Running migration: {migration_file}")

conn = get_connection()
if not conn:
    logger.error("Failed to connect to database")
    sys.exit(1)

cursor = conn.cursor()

try:
    with open(migration_file, 'r') as f:
        sql = f.read()

    # Split by semicolon and execute each statement
    statements = [s.strip() for s in sql.split(';') if s.strip()]

    for statement in statements:
        if statement:
            logger.info(f"Executing: {statement[:60]}...")
            cursor.execute(statement)

    conn.commit()
    logger.info(f"✓ Migration completed successfully!")

except Exception as e:
    logger.error(f"Migration error: {e}")
    conn.rollback()
    sys.exit(1)

finally:
    cursor.close()
    conn.close()
