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
        assert blocker.args == [True]

    def test_operation_started_emits_cancellable_false_by_default(self, qtbot, bridge) -> None:
        async def _noop() -> None:
            pass

        with qtbot.waitSignal(bridge.operation_started, timeout=1000) as blocker:
            bridge.run_async(_noop())
        assert blocker.args == [False]


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
