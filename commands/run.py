"""
Run command - Execute the scraper
"""

import click
from scraper import scrape_forum, save_to_json
from db import save_to_database
from logger import get_logger


@click.command()
@click.option('--pages', type=int, help='Number of pages to scrape')
@click.option('--all-torrents', '-a', is_flag=True, help='Include all torrents (no quality filtering)')
@click.option('--no-torrents', is_flag=True, help='Skip topic page scraping')
@click.option('--no-json', is_flag=True, help='Skip JSON output')
@click.option('--no-db', is_flag=True, help='Skip database save')
@click.option('--output', help='Custom JSON output path')
@click.pass_context
def run(ctx, pages, all_torrents, no_torrents, no_json, no_db, output):
    """Run the web series scraper"""
    logger = get_logger(__name__)
    config = ctx.obj['config']

    logger.info("Starting scraper...")

    # Get settings from config or CLI override
    pages = pages or config['scraper'].get('pages')

    # Run scraper
    data = scrape_forum(
        max_pages=pages,
        include_torrents=not no_torrents,
        highest_quality=not all_torrents
    )

    if not data:
        logger.warning("No data scraped")
        return

    # Save to database
    if not no_db:
        logger.info("Saving to database...")
        save_to_database(data)

    # Save to JSON
    if not no_json:
        output_path = output or config['output']['json_file']
        logger.info(f"Saving to {output_path}...")
        save_to_json(data, output_path)

    logger.info(f"Completed! Scraped {len(data)} series")
