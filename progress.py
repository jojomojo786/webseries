#!/usr/bin/env python3
"""
Progress Indicator Module

Provides progress tracking and display for long-running operations.
"""

import sys
import time
from typing import Optional
from logger import get_logger

logger = get_logger(__name__)


class ProgressTracker:
    """
    Track and display progress for long-running operations.

    Supports multiple display modes:
    - bar: Visual progress bar with percentage
    - simple: Simple counter (5/21)
    - silent: No progress display (useful for scripts/logs)
    """

    def __init__(
        self,
        total: int,
        description: str = "Processing",
        mode: str = "bar",
        show_eta: bool = True,
        update_interval: float = 0.1
    ):
        """
        Initialize progress tracker.

        Args:
            total: Total number of items to process
            description: Description of the operation
            mode: Display mode - 'bar', 'simple', or 'silent'
            show_eta: Whether to show estimated time remaining
            update_interval: Minimum seconds between display updates
        """
        self.total = total
        self.current = 0
        self.description = description
        self.mode = mode
        self.show_eta = show_eta
        self.update_interval = update_interval

        self.start_time = time.time()
        self.last_update_time = 0
        self.last_item = None

    def update(self, n: int = 1, item: str = None) -> None:
        """
        Update progress by n items.

        Args:
            n: Number of items completed (default 1)
            item: Optional description of the last completed item
        """
        self.current += n
        self.last_item = item

        # Throttle updates based on interval
        current_time = time.time()
        if current_time - self.last_update_time < self.update_interval:
            # Still update internal state, but don't display
            return

        self.last_update_time = current_time
        self._display()

    def _display(self) -> None:
        """Display progress based on mode."""
        if self.mode == "silent":
            return

        percentage = (self.current / self.total * 100) if self.total > 0 else 100

        if self.mode == "bar":
            self._display_bar(percentage)
        elif self.mode == "simple":
            self._display_simple(percentage)

    def _display_bar(self, percentage: float) -> None:
        """Display visual progress bar."""
        # Build progress bar
        bar_width = 30
        filled = int(bar_width * self.current / self.total) if self.total > 0 else bar_width
        bar = "█" * filled + "░" * (bar_width - filled)

        # Calculate ETA
        eta_str = ""
        if self.show_eta and self.current > 0 and self.total > 0:
            elapsed = time.time() - self.start_time
            rate = self.current / elapsed if elapsed > 0 else 0
            remaining = self.total - self.current
            eta = remaining / rate if rate > 0 else 0
            eta_str = f" | ETA: {self._format_time(eta)}"

        # Build status line
        status = f"\r{self.description}: [{bar}] {percentage:.0f}% ({self.current}/{self.total}){eta_str}"

        # Add last item if available and fits
        if self.last_item:
            max_item_length = 40
            item_str = self.last_item[:max_item_length]
            if len(self.last_item) > max_item_length:
                item_str += "..."
            status += f"\n  → {item_str}"

        # Clear line and write status (use stderr to not interfere with pipes)
        sys.stderr.write("\r" + " " * 100 + "\r")  # Clear line
        sys.stderr.write(status + "\r")
        sys.stderr.flush()

        # New line when complete
        if self.current >= self.total:
            sys.stderr.write("\n")

    def _display_simple(self, percentage: float) -> None:
        """Display simple counter."""
        status = f"{self.description}: {self.current}/{self.total} ({percentage:.0f}%)"

        if self.last_item:
            status += f" - {self.last_item}"

        logger.info(status)

    def _format_time(self, seconds: float) -> str:
        """Format seconds into human-readable time."""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds / 3600)
            minutes = int((seconds % 3600) / 60)
            return f"{hours}h {minutes}m"

    def finish(self, message: str = None) -> None:
        """
        Mark progress as complete and display final message.

        Args:
            message: Optional completion message
        """
        self.current = self.total
        elapsed = time.time() - self.start_time

        if self.mode == "bar":
            # Clear the progress line
            sys.stderr.write("\r" + " " * 100 + "\r")
            sys.stderr.flush()

        if message:
            logger.info(message)
        else:
            logger.info(f"{self.description} complete: {self.total} items in {self._format_time(elapsed)}")

    def error(self, item: str = None) -> None:
        """
        Log an error for the current item.

        Args:
            item: Optional item description
        """
        if item:
            logger.error(f"✗ Failed: {item}")
        else:
            logger.error("✗ Failed")

    def success(self, item: str = None) -> None:
        """
        Log success for the current item.

        Args:
            item: Optional item description
        """
        if item:
            logger.info(f"✓ {item}")


class MultiProgress:
    """
    Track multiple progress bars simultaneously.
    Useful for nested operations (e.g., matching series → fetching episodes).
    """

    def __init__(self):
        self.trackers = []

    def add_tracker(self, tracker: ProgressTracker) -> None:
        """Add a progress tracker."""
        self.trackers.append(tracker)

    def update_all(self) -> None:
        """Update all trackers."""
        # For now, just update each tracker
        for tracker in self.trackers:
            tracker._display()


def create_progress(total: int, description: str = "Processing", **kwargs) -> ProgressTracker:
    """
    Convenience function to create a progress tracker.

    Args:
        total: Total number of items
        description: Operation description
        **kwargs: Additional arguments for ProgressTracker

    Returns:
        ProgressTracker instance
    """
    return ProgressTracker(total, description, **kwargs)
