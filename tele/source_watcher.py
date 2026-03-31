"""Source file watcher for detecting changes in incoming data files.

Implements a two-layer file monitoring system:
1. Watchdog event monitoring (primary, real-time)
2. Polling fallback (always active, catches missed events)
"""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Set

from tele.source_state import SourceStateManager, STATE_DIR_DEFAULT

logger = logging.getLogger(__name__)

# Try to import watchdog, but don't fail if not available
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    Observer = None
    FileSystemEventHandler = object
    FileModifiedEvent = None
    FileCreatedEvent = None


@dataclass(frozen=True)
class WatcherEvent:
    """Immutable event representing a file change detected by the watcher.

    Attributes:
        source_name: Name of the data source that changed
        file_path: Path to the file that changed
    """
    source_name: str
    file_path: str


class SourceEventHandler(FileSystemEventHandler if WATCHDOG_AVAILABLE else object):
    """Watchdog event handler for file system events.

    Handles file modification and creation events, pushing them to an async queue
    for processing by the SourceWatcher.
    """

    def __init__(self, source_name: str, queue: asyncio.Queue, sources_dir: Path, loop: asyncio.AbstractEventLoop = None):
        """Initialize the event handler.

        Args:
            source_name: Name of the source being watched
            queue: Async queue to push events to
            sources_dir: Root directory containing source subdirectories
            loop: Event loop reference for thread-safe queue operations
        """
        if WATCHDOG_AVAILABLE:
            super().__init__()
        self.source_name = source_name
        self.queue = queue
        self.sources_dir = sources_dir
        self.loop = loop

    def on_modified(self, event):
        """Handle file modification events."""
        if event.is_directory:
            return
        self._push_event(event.src_path)

    def on_created(self, event):
        """Handle file creation events."""
        if event.is_directory:
            return
        self._push_event(event.src_path)

    def _push_event(self, file_path: str):
        """Push an event to the async queue."""
        # Only care about incoming.*.jsonl files
        path = Path(file_path)
        if not path.name.startswith("incoming.") or not path.name.endswith(".jsonl"):
            return

        try:
            event = WatcherEvent(
                source_name=self.source_name,
                file_path=str(path)
            )
            # Use call_soon_threadsafe to push from watchdog thread to async
            if self.loop is not None and not self.loop.is_closed():
                self.loop.call_soon_threadsafe(self.queue.put_nowait, event)
        except Exception as e:
            logger.warning("Failed to push watcher event: %s", e)


class SourceWatcher:
    """Watches source directories for file changes.

    Combines real-time watchdog monitoring with polling fallback for
    reliable change detection across platforms.
    """

    WATCHDOG_AVAILABLE = WATCHDOG_AVAILABLE

    def __init__(
        self,
        state_dir: Optional[Path] = None,
        poll_interval: float = 30.0,
        watch_enabled: bool = True
    ):
        """Initialize the source watcher.

        Args:
            state_dir: Directory for state files (default: ~/.tele/state)
            poll_interval: Seconds between polling checks
            watch_enabled: Whether to attempt watchdog monitoring
        """
        self.state_dir = state_dir or STATE_DIR_DEFAULT
        self.state_manager = SourceStateManager(state_dir=self.state_dir)
        self.poll_interval = poll_interval
        self.watch_enabled = watch_enabled

        self._observer: Optional[Observer] = None
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._handlers: dict = {}  # source_name -> handler
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def start_watchdog(self) -> bool:
        """Start the watchdog observer.

        Returns:
            True if watchdog started successfully, False otherwise
        """
        if not WATCHDOG_AVAILABLE or not self.watch_enabled:
            logger.debug("Watchdog not available or disabled")
            return False

        if self._observer is not None:
            logger.debug("Watchdog already running")
            return True

        try:
            # Store the current event loop for thread-safe queue operations
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                logger.debug("No running event loop, watchdog events will be queued")
                self._loop = None

            self._observer = Observer()
            # Watch each existing source directory
            for source_name in self.state_manager.list_sources():
                self._add_source_watch(source_name)
            self._observer.start()
            logger.info("Started watchdog observer for %d sources", len(self._handlers))
            return True
        except Exception as e:
            logger.warning("Failed to start watchdog: %s", e)
            self._observer = None
            return False

    def _add_source_watch(self, source_name: str):
        """Add a watch for a source directory."""
        if self._observer is None:
            return

        source_dir = self.state_manager.get_source_dir(source_name)
        if not source_dir.exists():
            return

        handler = SourceEventHandler(
            source_name=source_name,
            queue=self._event_queue,
            sources_dir=self.state_manager.sources_dir,
            loop=self._loop
        )
        self._observer.schedule(handler, str(source_dir), recursive=False)
        self._handlers[source_name] = handler

    def stop_watchdog(self):
        """Stop the watchdog observer."""
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=5.0)
            except Exception as e:
                logger.warning("Error stopping watchdog: %s", e)
            finally:
                self._observer = None
                self._handlers.clear()

    def get_sources_with_changes(self) -> Set[str]:
        """Poll all sources and detect which have changes.

        Compares current file size with recorded offset to detect new content.
        Also checks for newer files when current file is exhausted.

        Returns:
            Set of source names that have detectable changes
        """
        sources_with_changes: Set[str] = set()

        for source_name in self.state_manager.list_sources():
            if self._source_has_changes(source_name):
                sources_with_changes.add(source_name)

        return sources_with_changes

    def _source_has_changes(self, source_name: str) -> bool:
        """Check if a specific source has changes.

        Args:
            source_name: Name of the source to check

        Returns:
            True if the source has new content to consume
        """
        state = self.state_manager.load(source_name)
        current_file = state.current_file
        byte_offset = state.byte_offset

        # Get incoming files
        incoming_files = self.state_manager.get_incoming_files(source_name)
        if not incoming_files:
            return False

        if not current_file:
            # No current file recorded - check if first file has content
            first_file = incoming_files[0]
            try:
                if first_file.stat().st_size > 0:
                    return True
            except FileNotFoundError:
                logger.debug("File disappeared: %s", first_file)
            # First file is empty, check if there are more files
            if len(incoming_files) > 1:
                return True
            return False

        # Find current file in the list
        current_path = None
        for f in incoming_files:
            if f.name == current_file:
                current_path = f
                break

        if current_path is None:
            # Current file not found (deleted?) - check if other files exist
            # and if they have content
            for f in incoming_files:
                try:
                    if f.stat().st_size > 0:
                        return True
                except FileNotFoundError:
                    logger.debug("File disappeared: %s", f)
                    continue
            return False

        # Check if current file has grown
        try:
            current_size = current_path.stat().st_size
        except FileNotFoundError:
            logger.debug("Current file disappeared: %s", current_path)
            return False
        if current_size > byte_offset:
            return True

        # Check if there are newer files with content
        next_file = self.state_manager.get_next_file(source_name, current_file)
        if next_file is not None:
            try:
                if next_file.stat().st_size > 0:
                    return True
            except FileNotFoundError:
                logger.debug("Next file disappeared: %s", next_file)

        return False

    async def wait_for_event(self, timeout: float = None) -> Optional[WatcherEvent]:
        """Wait for a file change event from any source.

        Uses watchdog events if available, otherwise falls back to polling.

        Args:
            timeout: Maximum seconds to wait (None for no timeout)

        Returns:
            WatcherEvent if detected, None on timeout
        """
        # First check if there are any pending events
        try:
            return self._event_queue.get_nowait()
        except asyncio.QueueEmpty:
            pass

        # Poll loop
        deadline = asyncio.get_event_loop().time() + timeout if timeout else None

        while True:
            # Check for changes via polling
            sources = self.get_sources_with_changes()
            if sources:
                # Return event for first changed source
                source_name = next(iter(sources))
                state = self.state_manager.load(source_name)

                # Determine which file has changes
                file_path = self._get_changed_file_path(source_name, state)
                if file_path:
                    return WatcherEvent(source_name=source_name, file_path=str(file_path))

            # Check for watchdog events
            try:
                return await asyncio.wait_for(
                    self._event_queue.get(),
                    timeout=min(self.poll_interval, timeout or self.poll_interval)
                )
            except asyncio.TimeoutError:
                pass

            # Check overall timeout
            if deadline is not None:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    return None

    async def poll_for_event(self, source_name: str, timeout: float = 30.0) -> Optional[WatcherEvent]:
        """Poll a specific source for changes.

        Args:
            source_name: Name of the source to poll
            timeout: Maximum seconds to wait

        Returns:
            WatcherEvent if change detected, None on timeout
        """
        deadline = asyncio.get_event_loop().time() + timeout
        poll_interval = min(self.poll_interval, timeout)

        while True:
            # Check for changes
            if self._source_has_changes(source_name):
                state = self.state_manager.load(source_name)
                file_path = self._get_changed_file_path(source_name, state)
                if file_path:
                    return WatcherEvent(source_name=source_name, file_path=str(file_path))

            # Check for watchdog events for this source
            try:
                event = self._event_queue.get_nowait()
                if event.source_name == source_name:
                    return event
                # Put back events for other sources
                await self._event_queue.put(event)
            except asyncio.QueueEmpty:
                pass

            # Check timeout
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                return None

            # Wait before next poll
            wait_time = min(poll_interval, remaining)
            if wait_time > 0:
                await asyncio.sleep(wait_time)

    def _get_changed_file_path(self, source_name: str, state) -> Optional[Path]:
        """Get the path to the file that has changes.

        Args:
            source_name: Name of the source
            state: Current SourceState for the source

        Returns:
            Path to the changed file, or None if no changes
        """
        current_file = state.current_file
        incoming_files = self.state_manager.get_incoming_files(source_name)

        if not incoming_files:
            return None

        if not current_file:
            # No current file - return first incoming file that has content
            for f in incoming_files:
                if f.stat().st_size > 0:
                    return f
            return None

        # Find current file
        for f in incoming_files:
            if f.name == current_file:
                # Check if current file has more content
                if f.stat().st_size > state.byte_offset:
                    return f
                break

        # Check for newer file with content
        next_file = self.state_manager.get_next_file(source_name, current_file)
        if next_file and next_file.stat().st_size > 0:
            return next_file

        return None