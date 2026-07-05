"""Async bridge between Qt main thread and asyncio worker thread.

Provides thread-safe communication:
- GUI -> Async: via run_async() using asyncio.run_coroutine_threadsafe()
- Async -> GUI: via Qt Signals (QueuedConnection, thread-safe)
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
from collections.abc import Coroutine
from typing import Any

from PySide6.QtCore import QObject, Signal


class AsyncBridge(QObject):
    """Bridge between the Qt event loop (main thread) and an asyncio event loop (worker thread).

    All network I/O runs on the dedicated asyncio worker thread. Results are
    delivered back to the GUI via Qt Signals which are thread-safe.
    """

    # --- Signals for operation results ---
    discovery_complete = Signal(list)       # list[DeviceInfo]
    discovery_progress = Signal(list)       # list[DeviceInfo] — progressive updates
    capabilities_ready = Signal(object)     # DeviceCapabilities
    peq_ready = Signal(object)             # PEQSettings
    write_complete = Signal(object)        # WriteResult
    rew_measurements_ready = Signal(list)  # list[MeasurementSummary]
    rew_filters_ready = Signal(list)       # list[CanonicalFilter]
    operation_error = Signal(str, str)     # (error_type, human_readable_message)

    # --- Signals for progress indication ---
    progress_update = Signal(str)          # Status message for progress indicator
    stage_changed = Signal(str)            # Safe-write stage key (see push_page._STAGES)
    operation_started = Signal()           # Triggers progress spinner
    operation_finished = Signal()          # Hides progress spinner

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialize the async bridge.

        Args:
            parent: Optional Qt parent object.
        """
        super().__init__(parent)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the background asyncio event loop thread."""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="AsyncBridge-Worker",
            daemon=True,
        )
        self._thread.start()

    def _run_loop(self) -> None:
        """Run the asyncio event loop (executed on the worker thread)."""
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def run_async(self, coro: Coroutine[Any, Any, Any]) -> concurrent.futures.Future[object]:
        """Submit a coroutine to the background loop.

        The coroutine is wrapped to emit operation_started before execution
        and operation_finished after completion (success or failure).

        Args:
            coro: An awaitable coroutine to run on the async worker thread.

        Returns:
            A concurrent.futures.Future representing the pending result.

        Raises:
            RuntimeError: If the event loop has not been started.
        """
        if self._loop is None:
            raise RuntimeError("AsyncBridge has not been started. Call start() first.")

        async def _wrapped() -> object:
            self.operation_started.emit()
            try:
                return await coro
            finally:
                self.operation_finished.emit()

        return asyncio.run_coroutine_threadsafe(_wrapped(), self._loop)

    def shutdown(self) -> None:
        """Stop the event loop, join the thread.

        Called from MainWindow.closeEvent(). Safe to call multiple times.
        """
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        self._loop = None
        self._thread = None
