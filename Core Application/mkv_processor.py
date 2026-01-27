"""
MKV Processor - Process MKV files with mkvmerge to filter audio tracks
"""

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from logger import get_logger

logger = get_logger(__name__)


# Tamil language detection patterns
TAMIL_LANGUAGE_CODES = {'tam', 'ta'}
TAMIL_NAME_PATTERNS = {'tamil', 'tam', 'தமிழ்'}


@dataclass
class AudioTrack:
    """Represents an audio track in an MKV file"""
    track_id: int
    codec: str
    language_code: Optional[str] = None
    track_name: Optional[str] = None

    def __repr__(self):
        lang = self.language_code or 'unknown'
        name = self.track_name or ''
        return f"Track {self.track_id}: {self.codec} (lang={lang}, name={name})"


@dataclass
class ProcessResult:
    """Result of processing an MKV file"""
    success: bool
    input_path: str
    output_path: Optional[str]
    tamil_tracks_found: int
    total_audio_tracks: int
    error: Optional[str]
    processing_time: float


class MKVProcessor:
    """Process MKV files with mkvmerge to filter audio tracks"""

    def __init__(self, completed_dir: str, processing_dir: str, processed_dir: str,
                 mkvmerge_path: str = '/usr/bin/mkvmerge', timeout: int = 600,
                 keep_first_audio_as_fallback: bool = True):
        """
        Initialize MKV processor

        Args:
            completed_dir: Directory containing completed downloads (input)
            processing_dir: Directory for files being processed
            processed_dir: Directory for finished processed files (output)
            mkvmerge_path: Path to mkvmerge executable
            timeout: Processing timeout in seconds
            keep_first_audio_as_fallback: If True, keep first audio track when no Tamil detected
        """
        self.completed_dir = completed_dir
        self.processing_dir = processing_dir
        self.processed_dir = processed_dir
        self.mkvmerge_path = mkvmerge_path
        self.timeout = timeout
        self.keep_first_audio_as_fallback = keep_first_audio_as_fallback

        # Ensure directories exist
        self._ensure_directories()

        # Check mkvmerge availability
        if not os.path.exists(mkvmerge_path):
            logger.critical(f"mkvmerge not found at: {mkvmerge_path}")
            logger.critical("Install with: apt install mkvtoolnix")

    def _ensure_directories(self):
        """Create processing directories if they don't exist"""
        for dir_path in [self.processing_dir, self.processed_dir]:
            os.makedirs(dir_path, exist_ok=True)
            logger.debug(f"Ensured directory exists: {dir_path}")

    def identify_audio_tracks(self, mkv_path: str) -> list[AudioTrack]:
        """
        Parse mkvmerge --identify output to extract audio track information

        Args:
            mkv_path: Path to MKV file

        Returns:
            List of AudioTrack objects
        """
        cmd = [self.mkvmerge_path, '--identify', '--verbose', mkv_path]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                logger.error(f"mkvmerge identify failed: {result.stderr}")
                return []

            audio_tracks = []
            lines = result.stdout.split('\n')

            current_track_id = None
            current_codec = None

            for line in lines:
                line = line.strip()

                # Match track ID and type: "Track ID 1: audio (AAC)"
                track_match = re.match(r'Track ID (\d+): audio \(([^)]+)\)', line)
                if track_match:
                    # Save previous track if exists
                    if current_track_id is not None:
                        audio_tracks.append(AudioTrack(
                            track_id=current_track_id,
                            codec=current_codec or 'unknown'
                        ))

                    current_track_id = int(track_match.group(1))
                    current_codec = track_match.group(2)
                    continue

                # Look for language code in the same line or subsequent lines
                # Format: "language: tam" or "Language: tam"
                lang_match = re.search(r'(?:language|Language)\s*:\s*(\w+)', line)
                if lang_match and current_track_id is not None:
                    lang_code = lang_match.group(1).lower()
                    # Find or create track for this ID
                    track = next((t for t in audio_tracks if t.track_id == current_track_id), None)
                    if track:
                        track.language_code = lang_code
                    else:
                        # We haven't added this track yet, add it now
                        audio_tracks.append(AudioTrack(
                            track_id=current_track_id,
                            codec=current_codec or 'unknown',
                            language_code=lang_code
                        ))

                # Look for track name: "Name: Tamil" or "name: Tamil"
                name_match = re.search(r'(?:Name|name)\s*:\s*(.+)$', line)
                if name_match and current_track_id is not None:
                    track_name = name_match.group(1).strip()
                    track = next((t for t in audio_tracks if t.track_id == current_track_id), None)
                    if track:
                        track.track_name = track_name
                    else:
                        audio_tracks.append(AudioTrack(
                            track_id=current_track_id,
                            codec=current_codec or 'unknown',
                            track_name=track_name
                        ))

            # Don't forget the last track
            if current_track_id is not None:
                track = next((t for t in audio_tracks if t.track_id == current_track_id), None)
                if not track:
                    audio_tracks.append(AudioTrack(
                        track_id=current_track_id,
                        codec=current_codec or 'unknown'
                    ))

            logger.debug(f"Identified {len(audio_tracks)} audio tracks in {mkv_path}")
            return audio_tracks

        except subprocess.TimeoutExpired:
            logger.error(f"mkvmerge identify timeout for: {mkv_path}")
            return []
        except FileNotFoundError:
            logger.critical(f"mkvmerge executable not found at: {self.mkvmerge_path}")
            return []
        except Exception as e:
            logger.error(f"Error identifying tracks: {e}")
            return []

    def find_tamil_tracks(self, audio_tracks: list[AudioTrack]) -> list[int]:
        """
        Find Tamil audio tracks by language code or track name

        Args:
            audio_tracks: List of AudioTrack objects

        Returns:
            List of track IDs to keep
        """
        tamil_tracks = []

        for track in audio_tracks:
            # Check language code first (most reliable)
            if track.language_code in TAMIL_LANGUAGE_CODES:
                tamil_tracks.append(track.track_id)
                logger.debug(f"Found Tamil track by language code: {track}")
                continue

            # Check track name
            if track.track_name:
                track_name_lower = track.track_name.lower()
                if any(pattern in track_name_lower for pattern in TAMIL_NAME_PATTERNS):
                    tamil_tracks.append(track.track_id)
                    logger.debug(f"Found Tamil track by name: {track}")
                    continue

        # Fallback: if no Tamil tracks found and fallback is enabled, keep first audio track
        # This is useful for releases like 1TamilMV where Tamil is typically the first track
        if not tamil_tracks and self.keep_first_audio_as_fallback and audio_tracks:
            first_track = audio_tracks[0]
            tamil_tracks.append(first_track.track_id)
            logger.info(f"No Tamil tracks identified by language/name, using first track as fallback: {first_track}")

        return tamil_tracks

    def build_mkvmerge_command(self, input_path: str, output_path: str,
                               tamil_track_ids: list[int]) -> list[str]:
        """
        Build mkvmerge command to keep only Tamil audio tracks

        Args:
            input_path: Input MKV file path
            output_path: Output MKV file path
            tamil_track_ids: List of Tamil audio track IDs to keep

        Returns:
            List of command arguments
        """
        cmd = [self.mkvmerge_path, '-o', output_path]

        # Specify which audio tracks to keep
        if tamil_track_ids:
            audio_track_spec = ','.join(map(str, tamil_track_ids))
            cmd.extend(['--audio-tracks', audio_track_spec])

        # Input file
        cmd.append(input_path)

        return cmd

    def _move_to_processing(self, source_path: str) -> str:
        """Move file from completed/ to processing/"""
        filename = os.path.basename(source_path)
        dest = os.path.join(self.processing_dir, filename)
        shutil.move(source_path, dest)
        logger.debug(f"Moved to processing/: {filename}")
        return dest

    def _move_to_processed(self, source_path: str) -> str:
        """Move file to processed/ preserving original folder structure"""
        # Determine relative path based on where the source is
        if source_path.startswith(self.processing_dir):
            # Source is in processing/, get relative path from there
            rel_path = os.path.relpath(source_path, self.processing_dir)
        elif source_path.startswith(self.completed_dir):
            # Source is in completed/, get relative path from there
            rel_path = os.path.relpath(source_path, self.completed_dir)
        else:
            # Source is somewhere else, just use filename
            rel_path = os.path.basename(source_path)

        dest = os.path.join(self.processed_dir, rel_path)

        # Create parent directory if it doesn't exist
        dest_dir = os.path.dirname(dest)
        if dest_dir and not os.path.exists(dest_dir):
            os.makedirs(dest_dir, exist_ok=True)
            logger.debug(f"Created directory: {dest_dir}")

        if os.path.exists(source_path):
            shutil.move(source_path, dest)
            logger.debug(f"Moved to processed/: {rel_path}")
        return dest

    def _move_back_to_completed(self, source_path: str, status: str = 'failed'):
        """Rename failed file with status suffix (if in completed/) or move from processing/"""
        filename = os.path.basename(source_path)
        name, ext = os.path.splitext(filename)
        new_filename = f"{name}.{status}{ext}"

        # If source is in completed/, just rename it
        if os.path.dirname(source_path) == self.completed_dir or os.path.dirname(source_path) == '':
            dest = os.path.join(self.completed_dir, new_filename)
            if os.path.exists(source_path):
                os.rename(source_path, dest)
                logger.debug(f"Renamed in completed/ with status '{status}': {filename}")
        else:
            # Source is in processing/, move to completed/
            dest = os.path.join(self.completed_dir, new_filename)
            if os.path.exists(source_path):
                shutil.move(source_path, dest)
                logger.debug(f"Moved to completed/ with status '{status}': {filename}")
        return dest

    def process_file(self, input_path: str, dry_run: bool = False) -> ProcessResult:
        """
        Process a single MKV file to keep only Tamil audio tracks

        Args:
            input_path: Path to input MKV file (must be in completed/)
            dry_run: If True, show what would be done without processing

        Returns:
            ProcessResult with outcome details
        """
        start_time = time.time()
        filename = os.path.basename(input_path)

        try:
            # Step 1: Identify audio tracks
            logger.info(f"Analyzing: {filename}")
            audio_tracks = self.identify_audio_tracks(input_path)

            if not audio_tracks:
                logger.warning(f"No audio tracks found in: {filename}")
                # Move to processed/ as-is, preserving folder structure
                rel_path = os.path.relpath(input_path, self.completed_dir)
                output_path = os.path.join(self.processed_dir, rel_path)
                if not dry_run:
                    self._move_to_processed(input_path)
                return ProcessResult(
                    success=True,
                    input_path=input_path,
                    output_path=output_path,
                    tamil_tracks_found=0,
                    total_audio_tracks=0,
                    error="No audio tracks found",
                    processing_time=time.time() - start_time
                )

            # Step 2: Find Tamil tracks
            tamil_track_ids = self.find_tamil_tracks(audio_tracks)

            if not tamil_track_ids:
                logger.warning(f"No Tamil audio tracks found in: {filename}")
                logger.info(f"Audio tracks: {audio_tracks}")
                # Move to processed/ as-is, preserving folder structure
                rel_path = os.path.relpath(input_path, self.completed_dir)
                output_path = os.path.join(self.processed_dir, rel_path)
                if not dry_run:
                    self._move_to_processed(input_path)
                return ProcessResult(
                    success=True,
                    input_path=input_path,
                    output_path=output_path,
                    tamil_tracks_found=0,
                    total_audio_tracks=len(audio_tracks),
                    error="No Tamil audio found",
                    processing_time=time.time() - start_time
                )

            logger.info(f"Found {len(tamil_track_ids)} Tamil track(s): {tamil_track_ids}")

            # Step 3: Build paths preserving folder structure
            rel_path = os.path.relpath(input_path, self.completed_dir)
            processing_path = os.path.join(self.processing_dir, rel_path)

            # Create parent directory in processing/ if needed
            processing_dir = os.path.dirname(processing_path)
            if processing_dir and not os.path.exists(processing_dir):
                os.makedirs(processing_dir, exist_ok=True)

            # Step 4: Build mkvmerge command
            cmd = self.build_mkvmerge_command(input_path, processing_path, tamil_track_ids)

            if dry_run:
                logger.info(f"[DRY RUN] Would process: {filename}")
                logger.info(f"  Tamil tracks: {tamil_track_ids} of {len(audio_tracks)} total")
                logger.info(f"  Output: {processing_path}")
                return ProcessResult(
                    success=True,
                    input_path=input_path,
                    output_path=processing_path,
                    tamil_tracks_found=len(tamil_track_ids),
                    total_audio_tracks=len(audio_tracks),
                    error=None,
                    processing_time=time.time() - start_time
                )

            # Step 5: Execute mkvmerge (read from input_path, write to processing/)
            logger.info(f"Processing {filename} with mkvmerge...")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )

            if result.returncode != 0:
                error_msg = result.stderr or "Unknown mkvmerge error"
                logger.error(f"mkvmerge failed: {error_msg}")
                # Move original file back to completed/ with failed suffix
                self._move_back_to_completed(input_path, 'failed')
                return ProcessResult(
                    success=False,
                    input_path=input_path,
                    output_path=None,
                    tamil_tracks_found=len(tamil_track_ids),
                    total_audio_tracks=len(audio_tracks),
                    error=error_msg,
                    processing_time=time.time() - start_time
                )

            # Step 6: Verify output
            if not os.path.exists(processing_path) or os.path.getsize(processing_path) == 0:
                error = "Output file not created or empty"
                logger.error(error)
                # Move original back to completed/ with failed suffix
                self._move_back_to_completed(input_path, 'failed')
                return ProcessResult(
                    success=False,
                    input_path=input_path,
                    output_path=None,
                    tamil_tracks_found=len(tamil_track_ids),
                    total_audio_tracks=len(audio_tracks),
                    error=error,
                    processing_time=time.time() - start_time
                )

            # Step 7: Move to processed/ (from processing/)
            final_path = self._move_to_processed(processing_path)

            # Step 8: Delete original from completed/
            os.remove(input_path)

            logger.info(f"Successfully processed: {filename}")
            return ProcessResult(
                success=True,
                input_path=input_path,
                output_path=final_path,
                tamil_tracks_found=len(tamil_track_ids),
                total_audio_tracks=len(audio_tracks),
                error=None,
                processing_time=time.time() - start_time
            )

        except subprocess.TimeoutExpired:
            error = "mkvmerge processing timeout"
            logger.error(f"{error} for {input_path}")
            return ProcessResult(
                success=False,
                input_path=input_path,
                output_path=None,
                tamil_tracks_found=0,
                total_audio_tracks=0,
                error=error,
                processing_time=time.time() - start_time
            )
        except Exception as e:
            error = str(e)
            logger.error(f"Processing error: {error}")
            return ProcessResult(
                success=False,
                input_path=input_path,
                output_path=None,
                tamil_tracks_found=0,
                total_audio_tracks=0,
                error=error,
                processing_time=time.time() - start_time
            )


class FolderWatcher:
    """Monitor completed/ folder for new MKV files"""

    def __init__(self, folder_path: str, callback, interval: int = 30):
        """
        Initialize folder watcher

        Args:
            folder_path: Path to folder to watch
            callback: Function to call with new file paths
            interval: Check interval in seconds
        """
        self.folder_path = folder_path
        self.callback = callback
        self.interval = interval
        self._seen_files: set[str] = set()
        self._running = False
        self._scan_existing_files()

    def _scan_existing_files(self):
        """Initialize with files already in folder (don't process them)"""
        if os.path.exists(self.folder_path):
            for entry in os.listdir(self.folder_path):
                if entry.endswith('.mkv'):
                    self._seen_files.add(entry)
            logger.info(f"Found {len(self._seen_files)} existing MKV files in {self.folder_path}")

    def check_once(self) -> list[str]:
        """
        Check for new files and return them

        Returns:
            List of new file paths
        """
        new_files = []

        if not os.path.exists(self.folder_path):
            logger.warning(f"Watch folder does not exist: {self.folder_path}")
            return new_files

        current_files = set()

        try:
            for entry in os.listdir(self.folder_path):
                if entry.endswith('.mkv') or entry.endswith('.mkv.') or '.mkv' in entry.lower():
                    current_files.add(entry)

                    if entry not in self._seen_files:
                        filepath = os.path.join(self.folder_path, entry)
                        new_files.append(filepath)
                        self._seen_files.add(entry)

            # Remove files that are no longer present
            self._seen_files = current_files

        except PermissionError as e:
            logger.error(f"Permission error accessing watch folder: {e}")

        return new_files

    def start(self):
        """Start continuous watching"""
        self._running = True
        logger.info(f"Watching folder: {self.folder_path} (interval: {self.interval}s)")
        logger.info("Press Ctrl+C to stop")

        try:
            while self._running:
                new_files = self.check_once()

                for filepath in new_files:
                    logger.info(f"New file detected: {os.path.basename(filepath)}")
                    try:
                        self.callback(filepath)
                    except Exception as e:
                        logger.error(f"Error processing {filepath}: {e}")

                if new_files:
                    logger.info(f"Processed {len(new_files)} new file(s)")

                time.sleep(self.interval)

        except KeyboardInterrupt:
            logger.info("Watch stopped by user")
        finally:
            self._running = False

    def stop(self):
        """Stop watching"""
        self._running = False
