"""
Database commands group
"""

import sys
from pathlib import Path

# Add all subdirectories to Python path for imports
script_dir = Path(__file__).parent.parent
sys.path.insert(0, str(script_dir / "Core Application"))
sys.path.insert(0, str(script_dir))

import click
from db import get_stats, clear_database, get_connection
from logger import get_logger


@click.group(name='db')
def db_group():
    """Database management commands"""
    pass


@db_group.command()
def check():
    """Verify database integrity"""
    logger = get_logger(__name__)
    logger.info("Checking database integrity...")

    conn = get_connection()
    if not conn:
        logger.error("Failed to connect to database")
        return

    cursor = conn.cursor(dictionary=True)

    try:
        # Get overall stats
        stats = get_stats()
        click.echo("\n📊 Database Statistics:")
        click.echo(f"   Series: {stats['total_series']}")
        click.echo(f"   Seasons: {stats['total_seasons']}")
        click.echo(f"   Torrents: {stats['total_torrents']}")

        click.echo("\n📺 Quality Distribution:")
        for quality, count in sorted(stats['quality_distribution'].items()):
            click.echo(f"   {quality}: {count}")

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
            click.echo(f"\n⚠️  Series without seasons: {series_without_seasons}")
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
            click.echo(f"\n⚠️  Seasons without torrents: {seasons_without_torrents}")
            issues_found = True

        # 3. Torrents without season_id
        cursor.execute('SELECT COUNT(*) as count FROM torrents WHERE season_id IS NULL')
        torrents_without_season = cursor.fetchone()['count']
        if torrents_without_season > 0:
            click.echo(f"\n⚠️  Torrents without season_id: {torrents_without_season}")
            issues_found = True

        if not issues_found:
            click.echo("\n✅ Database structure is clean")
        else:
            click.echo("\n❌ Issues found in database structure")

    finally:
        cursor.close()
        conn.close()


@db_group.command()
def stats():
    """Show database statistics"""
    logger = get_logger(__name__)
    stats = get_stats()

    click.echo("\n📊 Database Statistics:")
    click.echo(f"   Series: {stats['total_series']}")
    click.echo(f"   Seasons: {stats['total_seasons']}")
    click.echo(f"   Torrents: {stats['total_torrents']}")

    click.echo("\n📺 Quality Distribution:")
    for quality, count in sorted(stats['quality_distribution'].items()):
        click.echo(f"   {quality}: {count}")


@db_group.command()
@click.confirmation_option(prompt='Are you sure you want to clear all data?')
def clear():
    """Clear all data from database"""
    logger = get_logger(__name__)
    logger.warning("Clearing all database data...")
    success = clear_database()
    if success:
        logger.info("Database cleared")
    else:
        logger.error("Failed to clear database")


@db_group.command(name='migrate')
def migrate():
    """Run database migrations"""
    logger = get_logger(__name__)
    logger.info("Running migrations...")
    click.echo("Migration functionality - run migration scripts from migrations/ directory manually")


@db_group.command(name='fix-orphans')
def fix_orphans():
    """Fix orphaned torrent records"""
    logger = get_logger(__name__)
    logger.info("Fixing orphaned torrents...")

    conn = get_connection()
    if not conn:
        logger.error("Failed to connect to database")
        return

    cursor = conn.cursor()

    try:
        # Check orphan count first
        cursor.execute('SELECT COUNT(*) FROM torrents WHERE season_id IS NULL')
        orphan_count = cursor.fetchone()[0]
        logger.info(f"Found {orphan_count} orphan torrents")

        if orphan_count == 0:
            logger.info("No orphans to fix!")
            return

        # Link orphans to their series' season
        cursor.execute('''
            UPDATE torrents t
            INNER JOIN seasons s ON t.series_id = s.series_id
            SET t.season_id = s.id
            WHERE t.season_id IS NULL
        ''')

        conn.commit()
        logger.info(f"Fixed {cursor.rowcount} orphan torrents")

        # Verify
        cursor.execute('SELECT COUNT(*) FROM torrents WHERE season_id IS NULL')
        remaining = cursor.fetchone()[0]
        if remaining > 0:
            logger.warning(f"Remaining orphans: {remaining}")
        else:
            logger.info("All orphans fixed successfully")

    except Exception as e:
        logger.error(f"Error fixing orphans: {e}")
        conn.rollback()

    finally:
        cursor.close()
        conn.close()
