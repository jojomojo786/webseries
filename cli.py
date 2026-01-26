#!/usr/bin/env python3
"""
Main CLI entry point for webseries scraper
"""

import click
from config import load_config
from logger import setup_logging


@click.group()
@click.option('--config', default='config.yaml', help='Config file path')
@click.option('--debug', is_flag=True, help='Enable debug logging')
@click.pass_context
def cli(ctx, config, debug):
    """Webseries scraper - Download and catalog web series torrents"""
    # Load configuration
    ctx.ensure_object(dict)
    ctx.obj['config'] = load_config(config)

    # Override log level if debug
    if debug:
        ctx.obj['config']['logging']['level'] = 'DEBUG'

    # Setup logging
    setup_logging(ctx.obj['config'])


# Import subcommands
from commands.run import run
from commands.db import db_group
from commands.download import download, move_completed
from episodes import episodes

# Register commands
cli.add_command(run)
cli.add_command(db_group)
cli.add_command(download)
cli.add_command(move_completed)
cli.add_command(episodes)


if __name__ == '__main__':
    cli(obj={})
