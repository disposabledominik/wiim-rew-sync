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
from typing import Any, NamedTuple

from PySide6.QtCore import QObject, Signal


class _ActiveOperation(NamedTuple):
    """The one operation AsyncBridge currently considers "current" -- see
    the class docstring's "single active operation" note for why one slot
    (not a collection) is enough, and run_async()'s *token* for why a plain
    Future/bool pair isn't."""

    future: concurrent.futures.Future[object]
    cancellable: bool
    token: int


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
    probe_abandoned = Signal(str)          # device_ip -- probe cancelled/superseded, no result
    discovery_abandoned = Signal()         # discovery cancelled before completion
    rew_list_abandoned = Signal()          # REW measurement fetch cancelled before completion

    # --- Signals for progress indication ---
    progress_update = Signal(str)          # Status message for progress indicator
    stage_changed = Signal(str)            # Safe-write stage key (see push_page._STAGES)
    push_round_changed = Signal(str, int, int)  # (source_name, index, total); push, undo, or
                                                 # auto-rollback (see rollback_state_changed)
    # Toggles PushPage's auto-rollback verb ("Rolling back" vs "Pushing to")
    # for push_round_changed above during PrimaryWorkflowManager
    # ._finalize_push_failure()'s restore of already-succeeded sources
    # (docs/backlog.md item 3). Manual Undo's equivalent mode flag is set by
    # MainWindow calling PushPage.start_undo() directly (it owns PushPage,
    # dispatched synchronously from the Undo button's own click handler) --
    # auto-rollback has no such direct-call path since it's triggered deep
    # inside PrimaryWorkflowManager, which (by design) never touches GUI
    # widgets directly, only self._bridge. This is the minimal signal that
    # gap actually needs -- push_round_changed's own (source_name, index,
    # total) payload is already fully reused as-is, unchanged, for this case.
    rollback_state_changed = Signal(bool)  # True while auto-rollback is running
    operation_started = Signal(bool, int)  # (cancellable, token) -- see run_async()'s *token*
    operation_finished = Signal(int)       # token -- see run_async()'s *token*

    def __init__(self, parent: QObject | None = None) -> None:
        """Initialize the async bridge.

        Args:
            parent: Optional Qt parent object.
        """
        super().__init__(parent)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        # Only ever set/read on the GUI thread (run_async() is the sole
        # writer and is always called synchronously from the GUI thread),
        # so no locking is needed. The feedback-manager model this backs
        # assumes a single active *displayed* operation at a time (buttons
        # are disabled for the duration), so tracking just the most
        # recently dispatched one is sufficient -- see request_cancel().
        #
        # Deliberately never cleared back to None once set -- only ever
        # overwritten by the next run_async() call. *token* exists because
        # "most recently dispatched" can still race a still-unwinding
        # earlier operation: a signal handler for one operation's own
        # result (e.g. MainWindow._on_capabilities_ready) can synchronously
        # dispatch a second, unrelated operation (e.g. list_presets())
        # *before* the first operation's own operation_finished has been
        # processed -- Qt delivers queued signals in emission order, and
        # capabilities_ready was queued before operation_finished in the
        # same _wrapped() call. Without a token, that second dispatch
        # overwrites this tracking, and the first operation's *own*
        # operation_finished then arrives, is indistinguishable from the
        # second operation's, and would incorrectly tear down
        # feedback-manager/UI state for the second operation while it's
        # still genuinely running. Each dispatch gets a unique, monotonically
        # increasing token; listeners that track per-operation UI state (see
        # MainWindow._on_bridge_operation_finished) use is_current_operation()
        # to recognize and ignore a stale one -- which, for a token that
        # already finished normally with nothing newer dispatched since,
        # correctly still reports True (an earlier design tried to also
        # self-clear _current on the operation's own finish, via a second
        # listener on this same operation_finished signal -- but Qt runs
        # queued-connection slots in *connection order*, and this bridge's
        # own listener would necessarily connect before any external
        # listener like MainWindow's, so it would always clear _current
        # first and make every external is_current_operation() check see
        # None, not just the raced case it was meant to catch. Comparing
        # tokens against the last dispatch is sufficient on its own).
        #
        # Known limitation (flagged repeatedly in review, documented here so
        # it stops costing re-review time): _current is a single slot, not a
        # stack, so it only tracks the *chained* nesting pattern above (one
        # handler's result synchronously triggers the next dispatch). It
        # does NOT protect two *sibling* dispatches fired from the same
        # handler (fan-out, not a chain) -- if the second-dispatched
        # sibling's operation_finished arrived before the first's, the first
        # sibling's own finish would then be misjudged stale while it's
        # still genuinely running. No call site does this today (every
        # nested dispatch in this codebase is a single linear chain, e.g.
        # MainWindow._on_capabilities_ready -> list_presets()); turning this
        # into a set/counter to guard a scenario nothing actually triggers
        # would be speculative hardening, not a fix for a live bug.
        self._current: _ActiveOperation | None = None
        self._next_token: int = 0

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

    def run_async(
        self, coro: Coroutine[Any, Any, Any], *, cancellable: bool = False
    ) -> concurrent.futures.Future[object]:
        """Submit a coroutine to the background loop.

        The coroutine is wrapped to emit operation_started before execution
        and operation_finished after completion (success or failure), each
        carrying this dispatch's unique *token* -- see the _current
        attribute's comment in __init__ for why.

        Args:
            coro: An awaitable coroutine to run on the async worker thread.
            cancellable: Whether request_cancel() may cancel this operation.
                Defaults to False (the safe direction) -- only pass True for
                operations confirmed to have no device-write/SafeWrite
                side effect that cancellation could leave half-done.

        Returns:
            A concurrent.futures.Future representing the pending result.

        Raises:
            RuntimeError: If the event loop has not been started.
        """
        if self._loop is None:
            raise RuntimeError("AsyncBridge has not been started. Call start() first.")

        token = self._next_token
        self._next_token += 1

        async def _wrapped() -> object:
            self.operation_started.emit(cancellable, token)
            try:
                return await coro
            finally:
                self.operation_finished.emit(token)

        future = asyncio.run_coroutine_threadsafe(_wrapped(), self._loop)
        self._current = _ActiveOperation(future=future, cancellable=cancellable, token=token)
        return future

    def is_current_operation(self, token: int) -> bool:
        """Whether *token* still refers to the most recently dispatched
        operation -- False if a newer run_async() call has since superseded
        it, True otherwise (including after that operation's own normal
        completion, as long as nothing newer has been dispatched since --
        see the _current attribute's comment in __init__ for why it's
        never explicitly cleared on finish). Lets a listener that tracks
        UI state per-operation (see MainWindow._on_bridge_operation_finished)
        recognize and ignore a stale operation_started/operation_finished
        delivered after a newer dispatch already took over.
        """
        return self._current is not None and self._current.token == token

    def request_cancel(self) -> None:
        """Cancel the current operation, if one is active and cancellable.

        No-op if there's no current operation, it isn't cancellable, or it
        has already finished (concurrent.futures.Future.cancel() safely
        returns False in that case rather than raising). GUI-thread only,
        same as run_async().
        """
        if self._current is not None and self._current.cancellable:
            self._current.future.cancel()

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


def emit_round_progress(
    bridge: AsyncBridge, verb: str, source_name: str, index: int, total: int
) -> None:
    """Emit the (progress_update, push_round_changed) pair used for every
    per-source round of a push, undo, or auto-rollback loop -- the same
    two-signal pairing was independently reimplemented at three call sites
    (PrimaryWorkflowManager's forward-push loop and its auto-rollback
    _on_rollback_round(), SecondaryWorkflowManager's multi-source undo
    on_round()), differing only by verb ("Pushing to"/"Rolling back"/
    "Restoring") -- code review finding. Plain function, not a method, so
    either manager can call it without depending on the other (they're
    siblings composed only by MainWindow, per CLAUDE.md's manager pattern).
    """
    bridge.progress_update.emit(f"{verb} {source_name} ({index} of {total})...")
    bridge.push_round_changed.emit(source_name, index, total)
