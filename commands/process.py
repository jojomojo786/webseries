"""
Process command - Process MKV files with mkvmerge to filter audio tracks
"""

import sys
from pathlib import Path

# Add all subdirectories to Python path for imports
script_dir = Path(__file__).parent.parent
sys.path.insert(0, str(script_dir / "Core Application"))
sys.path.insert(0, str(script_dir))

import os
import click
from logger import get_logger

from mkv_processor import MKVProcessor, FolderWatcher

logger = get_logger(__name__)

# Default paths (relative to new directory structure)
DEFAULT_DOWNLOADS_DIR = str(script_dir / 'Data & Cache' / 'downloads')
DEFAULT_COMPLETED_DIR = os.path.join(DEFAULT_DOWNLOADS_DIR, 'completed')
DEFAULT_PROCESSING_DIR = os.path.join(DEFAULT_DOWNLOADS_DIR, 'processing')
DEFAULT_PROCESSED_DIR = os.path.join(DEFAULT_DOWNLOADS_DIR, 'processed')


def get_mkv_groups(directory: str) -> list[dict]:
    """
    Get MKV files grouped by their parent folder or series name

    Args:
        directory: Path to directory

    Returns:
        List of groups: [{'name': folder_name or series_name, 'files': [paths]}]
    """
    import re
    groups = []
    items_in_root = []

    if not os.path.exists(directory):
        logger.warning(f"Directory does not exist: {directory}")
        return groups

    # Get all entries in completed/
    for entry in os.listdir(directory):
        entry_path = os.path.join(directory, entry)

        if os.path.isfile(entry_path) and entry.lower().endswith('.mkv'):
            # Individual MKV file at root level
            items_in_root.append(entry_path)
        elif os.path.isdir(entry_path):
            # Check if folder contains MKV files
            mkv_files = []
            for root, dirs, files in os.walk(entry_path):
                for filename in files:
                    if filename.lower().endswith('.mkv'):
                        mkv_files.append(os.path.join(root, filename))

            if mkv_files:
                groups.append({
                    'name': entry,
                    'files': mkv_files
                })

    # Group root-level files by series name
    # Pattern: www.1TamilMV.XXX - Series Name (Year) Sxx EXx ...
    series_groups = {}
    for filepath in items_in_root:
        filename = os.path.basename(filepath)

        # Extract series name using regex
        # Match: www.1TamilMV.XXX - Series Name (Year) Sxx EXx ...
        match = re.search(r'www\.1TamilMV\.\w+\s+-\s+(.+?)\s+\(\d{4}\)', filename)
        if match:
            series_name = match.group(1).strip()
            # Add episode info to distinguish
            ep_match = re.search(r'S\d+E\D\d+', filename)
            ep_info = ep_match.group(0) if ep_match else ''
            group_key = f"{series_name}"

            if group_key not in series_groups:
                series_groups[group_key] = {
                    'name': series_name,
                    'files': []
                }
            series_groups[group_key]['files'].append(filepath)
        else:
            # If no pattern match, treat as individual group
            groups.append({
                'name': filename,
                'files': [filepath]
            })

    # Add series groups to groups list
    for group_data in series_groups.values():
        groups.append(group_data)

    return groups


@click.command()
@click.option('--watch', is_flag=True, help='Watch mode - continuously monitor completed/ folder')
@click.option('--interval', default=30, type=int, help='Watch check interval in seconds (default: 30)')
@click.option('--file', '-f', type=click.Path(exists=True), help='Process specific file')
@click.option('--all', 'process_all', is_flag=True, help='Process all folders/files at once')
@click.option('--dry-run', is_flag=True, help='Show what would be done without processing')
@click.option('--no-fallback', is_flag=True, help='Disable fallback to first audio track when no Tamil detected')
@click.option('--completed-dir', default=DEFAULT_COMPLETED_DIR, help='Completed downloads folder')
@click.option('--processing-dir', default=DEFAULT_PROCESSING_DIR, help='Processing folder')
@click.option('--processed-dir', default=DEFAULT_PROCESSED_DIR, help='Processed folder')
@click.option('--mkvmerge-path', default='/usr/bin/mkvmerge', help='Path to mkvmerge executable')
@click.option('--timeout', default=600, type=int, help='Processing timeout in seconds (default: 600)')
@click.pass_context
def process(ctx, watch, interval, file, process_all, dry_run, no_fallback, completed_dir, processing_dir,
            processed_dir, mkvmerge_path, timeout):
    """Process MKV files with mkvmerge to keep only Tamil audio tracks (one folder at a time)"""
    config = ctx.obj.get('config', {})

    # Use config values if available
    vp_config = config.get('video_processing', {})
    completed_dir = completed_dir or vp_config.get('completed_dir', DEFAULT_COMPLETED_DIR)
    processing_dir = processing_dir or vp_config.get('processing_dir', DEFAULT_PROCESSING_DIR)
    processed_dir = processed_dir or vp_config.get('processed_dir', DEFAULT_PROCESSED_DIR)
    mkvmerge_path = mkvmerge_path or vp_config.get('mkvmerge_path', '/usr/bin/mkvmerge')
    interval = interval or vp_config.get('watch_interval', 30)
    keep_first_audio_as_fallback = not no_fallback

    # Create processor
    processor = MKVProcessor(
        completed_dir=completed_dir,
        processing_dir=processing_dir,
        processed_dir=processed_dir,
        mkvmerge_path=mkvmerge_path,
        timeout=timeout,
        keep_first_audio_as_fallback=keep_first_audio_as_fallback
    )

    # Handle single file processing
    if file:
        logger.info(f"Processing single file: {file}")
        result = processor.process_file(file, dry_run=dry_run)

        if result.success:
            click.echo(f"✓ Success: {os.path.basename(file)}")
            click.echo(f"  Tamil tracks: {result.tamil_tracks_found}/{result.total_audio_tracks}")
            click.echo(f"  Output: {result.output_path}")
            click.echo(f"  Time: {result.processing_time:.1f}s")
        else:
            click.echo(f"✗ Failed: {os.path.basename(file)}")
            click.echo(f"  Error: {result.error}")
        return

    # Handle watch mode
    if watch:
        def process_callback(filepath):
            result = processor.process_file(filepath, dry_run=dry_run)
            if result.success:
                click.echo(f"✓ {os.path.basename(filepath)} - "
                          f"{result.tamil_tracks_found} Tamil track(s) in {result.processing_time:.1f}s")
            else:
                click.echo(f"✗ {os.path.basename(filepath)} - {result.error}")

        watcher = FolderWatcher(
            folder_path=completed_dir,
            callback=process_callback,
            interval=interval
        )
        watcher.start()
        return

    # One-time processing - process one group at a time
    groups = get_mkv_groups(completed_dir)

    if not groups:
        logger.info(f"No MKV files found in: {completed_dir}")
        return

    # Show available groups
    click.echo("=" * 60)
    click.echo(f"Found {len(groups)} folder(s)/file(s) to process:")
    click.echo("=" * 60)
    for i, group in enumerate(groups, 1):
        file_count = len(group['files'])
        click.echo(f"  {i}. {group['name']} ({file_count} file{'s' if file_count > 1 else ''})")
    click.echo("=" * 60)

    # Process only first group unless --all is specified
    groups_to_process = groups if process_all else [groups[0]]

    if not process_all and len(groups) > 1:
        click.echo(f"\nProcessing first group: {groups[0]['name']}")
        click.echo("Use --all to process everything at once\n")

    for group in groups_to_process:
        group_name = group['name']
        files = group['files']

        click.echo("\n" + "=" * 60)
        click.echo(f"Processing: {group_name} ({len(files)} file{'s' if len(files) > 1 else ''})")
        click.echo("=" * 60)

        success_count = 0
        skip_count = 0
        error_count = 0
        total_tamil_tracks = 0

        for filepath in files:
            filename = os.path.basename(filepath)
            click.echo(f"\nProcessing: {filename}")

            result = processor.process_file(filepath, dry_run=dry_run)

            if result.success:
                if result.tamil_tracks_found > 0:
                    click.echo(f"  ✓ Success - {result.tamil_tracks_found}/{result.total_audio_tracks} "
                              f"Tamil track(s) kept ({result.processing_time:.1f}s)")
                    success_count += 1
                    total_tamil_tracks += result.tamil_tracks_found
                else:
                    click.echo(f"  ⚠ No Tamil audio found - moved as-is")
                    skip_count += 1
            else:
                click.echo(f"  ✗ Failed - {result.error}")
                error_count += 1

        # Group summary
        click.echo("\n" + "-" * 60)
        click.echo(f"GROUP SUMMARY: {group_name}")
        click.echo(f"  Files: {len(files)}, Success: {success_count}, "
                  f"No Tamil: {skip_count}, Failed: {error_count}")
        click.echo(f"  Tamil tracks kept: {total_tamil_tracks}")
        if dry_run:
            click.echo("  DRY RUN - No changes were made")
        else:
            # Remove empty folder if all files were successfully processed
            # Check if this was a folder (not a single file at root)
            first_file_path = files[0]
            parent_dir = os.path.dirname(first_file_path)

            # Only remove if it's actually a subdirectory of completed/
            if parent_dir != completed_dir and os.path.exists(parent_dir):
                try:
                    # Check if folder is empty
                    remaining_files = os.listdir(parent_dir)
                    if not remaining_files:
                        os.rmdir(parent_dir)
                        click.echo(f"  ✓ Removed empty folder: {os.path.basename(parent_dir)}")
                    else:
                        click.echo(f"  Folder not empty ({len(remaining_files)} items remaining)")
                except OSError as e:
                    logger.warning(f"Could not remove folder {parent_dir}: {e}")

    # Final summary
    click.echo("\n" + "=" * 60)
    click.echo("OVERALL SUMMARY")
    click.echo("=" * 60)

    total_files = sum(len(g['files']) for g in groups_to_process)
    click.echo(f"Groups processed: {len(groups_to_process)}/{len(groups)}")
    click.echo(f"Total files: {total_files}")

    if not process_all and len(groups) > 1:
        click.echo(f"\n{len(groups) - 1} group(s) remaining to process")
        click.echo("Run again to process the next group")

    click.echo("=" * 60)


@click.command()
@click.option('--interval', default=30, type=int, help='Watch check interval in seconds (default: 30)')
@click.option('--all', 'process_all', is_flag=True, help='Process all folders/files at once')
@click.option('--completed-dir', default=DEFAULT_COMPLETED_DIR, help='Completed downloads folder')
@click.option('--processing-dir', default=DEFAULT_PROCESSING_DIR, help='Processing folder')
@click.option('--processed-dir', default=DEFAULT_PROCESSED_DIR, help='Processed folder')
@click.option('--mkvmerge-path', default='/usr/bin/mkvmerge', help='Path to mkvmerge executable')
@click.option('--dry-run', is_flag=True, help='Show what would be done without processing')
@click.option('--no-fallback', is_flag=True, help='Disable fallback to first audio track when no Tamil detected')
@click.pass_context
def process_watch(ctx, interval, process_all, completed_dir, processing_dir, processed_dir,
                  mkvmerge_path, dry_run, no_fallback):
    """Watch mode - continuously monitor and process new MKV files"""
    # Just call process with --watch flag
    ctx.invoke(process,
               watch=True,
               interval=interval,
               file=None,
               process_all=process_all,
               dry_run=dry_run,
               no_fallback=no_fallback,
               completed_dir=completed_dir,
               processing_dir=processing_dir,
               processed_dir=processed_dir,
               mkvmerge_path=mkvmerge_path)
