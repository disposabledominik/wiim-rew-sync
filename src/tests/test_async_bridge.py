"""Unit tests for AsyncBridge's cancellation support.

Tests run_async()'s cancellable tracking, request_cancel()'s actual
Future.cancel() behavior, and that a cancelled operation still fires
operation_finished exactly once with no operation_error (CancelledError is a
BaseException, not caught by the standard `except Exception` error-mapping
wrapper -- see MainWindow._bridge_wrapper).
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from src.gui.async_bridge import AsyncBridge


@pytest.fixture()
def bridge(qtbot):
    """A started AsyncBridge, shut down automatically at test end."""
    b = AsyncBridge()
    b.start()
    yield b
    # A cancelled task's `finally` block can still be mid-unwind on the
    # worker thread the instant a test's assertion passes (Future.cancelled()
    # or the operation_finished signal both fire slightly before the Task
    # itself is fully done) -- a brief grace period avoids a harmless but
    # noisy "Task was destroyed but it is pending" warning from shutdown()
    # stopping the loop out from under it.
    qtbot.wait(20)
    b.shutdown()


def _slow_op(started: threading.Event):
    """A coroutine that signals `started` (thread-safe) right before
    sleeping, so a test on the GUI thread can wait for genuine "the
    coroutine is now executing" rather than polling
    concurrent.futures.Future.running() -- which run_coroutine_threadsafe's
    returned Future never actually transitions to True for, confirmed
    empirically (it goes straight from pending to done/cancelled)."""

    async def _run() -> str:
        started.set()
        await asyncio.sleep(5)
        return "should not get here"

    return _run()


class TestRunAsyncCancellableTracking:
    """run_async() tracks the current Future/cancellable flag for request_cancel()."""

    def test_operation_started_emits_cancellable_true(self, qtbot, bridge) -> None:
        async def _noop() -> None:
            pass

        with qtbot.waitSignal(bridge.operation_started, timeout=1000) as blocker:
            bridge.run_async(_noop(), cancellable=True)
        assert blocker.args[0] is True

    def test_operation_started_emits_cancellable_false_by_default(self, qtbot, bridge) -> None:
        async def _noop() -> None:
            pass

        with qtbot.waitSignal(bridge.operation_started, timeout=1000) as blocker:
            bridge.run_async(_noop())
        assert blocker.args[0] is False

    def test_successive_dispatches_get_distinct_tokens(self, qtbot, bridge) -> None:
        async def _noop() -> None:
            pass

        with qtbot.waitSignal(bridge.operation_started, timeout=1000) as first:
            bridge.run_async(_noop())
        with qtbot.waitSignal(bridge.operation_started, timeout=1000) as second:
            bridge.run_async(_noop())

        assert first.args[1] != second.args[1]


class TestIsCurrentOperation:
    """is_current_operation() -- the staleness check
    MainWindow._on_bridge_operation_finished relies on to avoid tearing
    down UI state for an operation a newer dispatch has already superseded
    (round-2 review finding: a signal handler for one operation's result,
    e.g. _on_capabilities_ready, can synchronously dispatch a second
    operation, e.g. list_presets(), before the first's own
    operation_finished has been processed)."""

    def test_true_immediately_after_dispatch(self, qtbot, bridge) -> None:
        """Uses _slow_op (not a no-op) so the operation is still genuinely
        in flight when asserting -- a coroutine that finishes instantly
        could already be cleared by the time control returns here."""
        started = threading.Event()
        with qtbot.waitSignal(bridge.operation_started, timeout=1000) as blocker:
            future = bridge.run_async(_slow_op(started), cancellable=True)
        token = blocker.args[1]
        qtbot.waitUntil(started.is_set, timeout=1000)

        assert bridge.is_current_operation(token)

        future.cancel()  # cleanup
        qtbot.waitUntil(lambda: future.cancelled() or future.done(), timeout=1000)

    def test_false_for_a_token_superseded_by_a_newer_dispatch(self, qtbot, bridge) -> None:
        """The exact scenario the token exists for: a second run_async()
        call before the first operation's own completion is processed."""
        started = threading.Event()
        with qtbot.waitSignal(bridge.operation_started, timeout=1000) as first_blocker:
            future = bridge.run_async(_slow_op(started), cancellable=True)
        first_token = first_blocker.args[1]
        qtbot.waitUntil(started.is_set, timeout=1000)

        async def _noop() -> None:
            pass

        bridge.run_async(_noop())

        assert not bridge.is_current_operation(first_token)
        # Cleanup: cancel the still-running slow op directly (it's no longer
        # AsyncBridge's tracked "current" operation, so request_cancel()
        # would target the _noop() dispatch instead).
        future.cancel()
        qtbot.waitUntil(lambda: future.cancelled() or future.done(), timeout=1000)

    def test_false_once_the_operation_completes(self, qtbot, bridge) -> None:
        """_current is cleared once its own operation genuinely finishes
        (not just overwritten by whatever the next dispatch happens to be),
        so a token from a completed operation doesn't linger as "current"."""
        async def _noop() -> None:
            pass

        with qtbot.waitSignal(bridge.operation_finished, timeout=1000) as blocker:
            bridge.run_async(_noop())
        token = blocker.args[0]

        assert not bridge.is_current_operation(token)

    def test_false_with_no_operation_dispatched(self, bridge) -> None:
        assert not bridge.is_current_operation(0)


class TestRequestCancel:
    """request_cancel() cancels the current Future only when it's cancellable."""

    def test_request_cancel_noop_with_no_operation(self, bridge) -> None:
        """No run_async() call yet -- must not raise."""
        bridge.request_cancel()  # no-op, no exception

    def test_request_cancel_cancels_a_cancellable_operation(self, qtbot, bridge) -> None:
        """A slow, cancellable operation is actually stopped by request_cancel()."""
        started = threading.Event()
        future = bridge.run_async(_slow_op(started), cancellable=True)
        qtbot.waitUntil(started.is_set, timeout=1000)

        bridge.request_cancel()

        qtbot.waitUntil(lambda: future.cancelled() or future.done(), timeout=1000)
        assert future.cancelled()

    def test_request_cancel_does_not_cancel_a_non_cancellable_operation(
        self, qtbot, bridge
    ) -> None:
        """A slow operation started without cancellable=True is unaffected."""

        async def _slow() -> str:
            await asyncio.sleep(0.2)
            return "completed"

        future = bridge.run_async(_slow())  # cancellable defaults to False
        bridge.request_cancel()

        qtbot.waitUntil(lambda: future.done(), timeout=1000)
        assert not future.cancelled()
        assert future.result() == "completed"


class TestCancelledOperationCompletesCleanly:
    """A cancelled operation still fires operation_finished exactly once and
    never fires operation_error -- asyncio.CancelledError is a BaseException
    (since Python 3.8), not caught by the `except Exception` mapping in
    MainWindow._bridge_wrapper, so it can't be mistaken for a real failure."""

    def test_cancelled_operation_fires_operation_finished_once(self, qtbot, bridge) -> None:
        finished_count = 0

        def _on_finished() -> None:
            nonlocal finished_count
            finished_count += 1

        bridge.operation_finished.connect(_on_finished)

        started = threading.Event()
        bridge.run_async(_slow_op(started), cancellable=True)
        qtbot.waitUntil(started.is_set, timeout=1000)
        bridge.request_cancel()

        qtbot.waitUntil(lambda: finished_count == 1, timeout=1000)
        assert finished_count == 1

    def test_cancelled_operation_does_not_trigger_error_mapping(self, qtbot, bridge) -> None:
        """Reproduces MainWindow._bridge_wrapper's exact try/except Exception
        shape inline (rather than requiring a full MainWindow instance) to
        prove asyncio.CancelledError passes through it uncaught -- the
        property this whole no-special-casing design decision rests on."""
        error_emissions: list[tuple[str, str]] = []
        bridge.operation_error.connect(lambda kind, msg: error_emissions.append((kind, msg)))

        async def _bridge_wrapper_shape(coro: object) -> None:
            try:
                await coro  # type: ignore[misc]
            except Exception as exc:  # mirrors the real wrapper's except Exception exactly
                error_emissions.append((type(exc).__name__, str(exc)))

        started = threading.Event()
        future = bridge.run_async(_bridge_wrapper_shape(_slow_op(started)), cancellable=True)
        qtbot.waitUntil(started.is_set, timeout=1000)
        bridge.request_cancel()

        qtbot.waitUntil(lambda: future.cancelled(), timeout=1000)
        assert error_emissions == []
