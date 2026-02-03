#!/usr/bin/env python3
"""
Main CLI entry point for webseries scraper
"""

import sys
from pathlib import Path

# Add all subdirectories to Python path for imports
script_dir = Path(__file__).parent.parent
sys.path.insert(0, str(script_dir / "Core Application"))
sys.path.insert(0, str(script_dir / "Episode Management"))
sys.path.insert(0, str(script_dir / "Database Tools"))
sys.path.insert(0, str(script_dir / "Metadata Fetching"))
sys.path.insert(0, str(script_dir))

import click
from config import load_config
from logger import setup_logging


@click.group(invoke_without_command=True)
@click.option('--config', default='config.yaml', help='Config file path')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@click.option('--finder', type=int, help='Match a series using AI poster analysis by series ID')
@click.option('--finder-all', is_flag=True, help='Match all series without tmdb_id using AI poster analysis')
@click.option('--finder-seasons', type=int, help='Create seasons for a series using AI torrent analysis by series ID')
@click.option('--finder-seasons-all', is_flag=True, help='Create seasons for all series with orphaned torrents using AI')
@click.option('--dry-run', is_flag=True, help='Show what would be done without making changes')
@click.pass_context
def cli(ctx, config, debug, finder, finder_all, finder_seasons, finder_seasons_all, dry_run):
    """Webseries scraper - Download, process, and catalog web series torrents

Features:
    • Download torrents via qBittorrent
    • Process MKV files with mkvmerge (keep only Tamil audio)
    • Scan and import episodes to database
    • Fetch metadata from TMDB
    """
    # Load configuration
    ctx.ensure_object(dict)
    ctx.obj['config'] = load_config(config)

    # Override log level if debug
    if debug:
        ctx.obj['config']['logging']['level'] = 'DEBUG'

    # Setup logging
    setup_logging(ctx.obj['config'])

    # If no subcommand is invoked, handle finder options
    if ctx.invoked_subcommand is None:
        if finder or finder_all:
            import series_ai_matcher

            if finder:
                click.echo(f"🔍 AI Matching series ID: {finder}")
                result = series_ai_matcher.match_series_with_ai(finder, dry_run=dry_run)
                if result:
                    click.echo(f"✓ AI matched series {finder}")
                else:
                    click.echo(f"✗ AI matching failed for series {finder}")
            elif finder_all:
                click.echo("🔍 AI Matching all series without TMDB IDs...")
                results = series_ai_matcher.match_all_series_with_ai(dry_run=dry_run)

                click.echo("\n" + "=" * 80)
                click.echo("AI MATCHING SUMMARY")
                click.echo("=" * 80)
                click.echo(f"Total series: {results.get('total', 0)}")
                click.echo(f"Matched: ✓ {results.get('matched', 0)}")
                click.echo(f"Failed: ✗ {results.get('failed', 0)}")
                click.echo("=" * 80)

                if dry_run:
                    click.echo("DRY RUN - No changes were made")
            ctx.exit()

        # Handle seasons finder options
        if finder_seasons or finder_seasons_all:
            import seasons_ai_matcher

            if finder_seasons:
                click.echo(f"🔍 AI Creating seasons for series ID: {finder_seasons}")
                result = seasons_ai_matcher.match_seasons_for_series(finder_seasons, dry_run=dry_run)

                if 'error' not in result:
                    click.echo("\n" + "=" * 80)
                    click.echo("SEASONS CREATED")
                    click.echo("=" * 80)
                    click.echo(f"Series: {result.get('series_name', 'Unknown')}")
                    click.echo(f"Torrents found: {result.get('torrents_found', 0)}")
                    click.echo(f"Seasons created: {result.get('seasons_created', 0)}")
                    click.echo(f"Torrents linked: {result.get('torrents_linked', 0)}")
                    click.echo("=" * 80)

                    if dry_run:
                        click.echo("DRY RUN - No changes were made")
                else:
                    click.echo(f"✗ Error: {result['error']}")

            elif finder_seasons_all:
                click.echo("🔍 AI Creating seasons for all series with orphaned torrents...")
                results = seasons_ai_matcher.match_all_seasons_with_ai(dry_run=dry_run)

                if 'error' not in results:
                    click.echo("\n" + "=" * 80)
                    click.echo("SEASONS MATCHING SUMMARY")
                    click.echo("=" * 80)
                    click.echo(f"Series with orphans: {results.get('total', 0)}")
                    click.echo(f"Series processed: {results.get('processed', 0)}")
                    click.echo(f"Seasons created: {results.get('seasons_created', 0)}")
                    click.echo(f"Torrents linked: {results.get('torrents_linked', 0)}")
                    click.echo("=" * 80)

                    if dry_run:
                        click.echo("DRY RUN - No changes were made")
                else:
                    click.echo(f"✗ Error: {results['error']}")
            ctx.exit()


# Import subcommands
from commands.run import run
from commands.db import db_group
from commands.download import download, move_completed
from commands.process import process, process_watch
from commands.status import check_status, status_cmd
from episodes import episodes

# Import jojoplayer (may fail if dependencies missing)
try:
    import jojoplayer
    jojoplayer.jojoplayer
    HAS_JOJOPLAYER = True
except ImportError as e:
    HAS_JOJOPLAYER = False
    import warnings
    warnings.warn(f"jojoplayer module not available: {e}")

# Register commands
cli.add_command(run)
cli.add_command(db_group)
cli.add_command(download)
cli.add_command(move_completed)
cli.add_command(process)
cli.add_command(process_watch)
cli.add_command(check_status)
cli.add_command(status_cmd)
cli.add_command(episodes)
if HAS_JOJOPLAYER:
    cli.add_command(jojoplayer.jojoplayer)


if __name__ == '__main__':
    cli(obj={})
