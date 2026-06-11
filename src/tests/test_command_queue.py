"""Unit tests for WiiM command queue.

Tests cover FIFO ordering, inter-command delay, retry behaviour,
drain_and_stop lifecycle, and cancel semantics.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from src.adapters.command_queue import WiiMCommandQueue
from src.adapters.wiim_http import WiiMHttpClient
from src.models.errors import WiiMConnectionError, WiiMTimeoutError


@pytest.fixture
def mock_client() -> AsyncMock:
    """Create a mock WiiMHttpClient."""
    client = AsyncMock(spec=WiiMHttpClient)
    client.command = AsyncMock(return_value="OK")
    return client


@pytest.fixture
def queue(mock_client: AsyncMock) -> WiiMCommandQueue:
    """Create a WiiMCommandQueue with short delay for testing."""
    return WiiMCommandQueue(client=mock_client, delay=0.05, max_retries=3)


# ------------------------------------------------------------------
# FIFO order
# ------------------------------------------------------------------


async def test_fifo_order(mock_client: AsyncMock) -> None:
    """Commands enqueued A, B, C are processed in that order."""
    call_order: list[str] = []

    async def track_command(cmd: str) -> str:
        call_order.append(cmd)
        return "OK"

    mock_client.command = AsyncMock(side_effect=track_command)
    q = WiiMCommandQueue(client=mock_client, delay=0.01, max_retries=3)

    await q.start()
    # Enqueue three commands concurrently
    results = await asyncio.gather(
        q.enqueue("CommandA"),
        q.enqueue("CommandB"),
        q.enqueue("CommandC"),
    )
    await q.drain_and_stop()

    assert call_order == ["CommandA", "CommandB", "CommandC"]
    assert results == ["OK", "OK", "OK"]


# ------------------------------------------------------------------
# Inter-command delay
# ------------------------------------------------------------------


async def test_inter_command_delay(mock_client: AsyncMock) -> None:
    """Minimum delay of 100ms is enforced between consecutive commands."""
    timestamps: list[float] = []

    async def track_timing(cmd: str) -> str:
        timestamps.append(time.perf_counter())
        return "OK"

    mock_client.command = AsyncMock(side_effect=track_timing)
    q = WiiMCommandQueue(client=mock_client, delay=0.1, max_retries=3)

    await q.start()
    await asyncio.gather(
        q.enqueue("Cmd1"),
        q.enqueue("Cmd2"),
        q.enqueue("Cmd3"),
    )
    await q.drain_and_stop()

    # Verify at least 100ms between consecutive commands
    assert len(timestamps) == 3
    for i in range(1, len(timestamps)):
        delta = timestamps[i] - timestamps[i - 1]
        assert delta >= 0.09, f"Delta {delta:.4f}s is below 90ms threshold"


# ------------------------------------------------------------------
# Retry on failure
# ------------------------------------------------------------------


async def test_retry_on_connection_error(mock_client: AsyncMock) -> None:
    """Command retries on WiiMConnectionError and succeeds on subsequent attempt."""
    mock_client.command = AsyncMock(
        side_effect=[WiiMConnectionError("fail"), "OK"]
    )
    q = WiiMCommandQueue(client=mock_client, delay=0.01, max_retries=3)

    await q.start()
    result = await q.enqueue("RetryCmd")
    await q.drain_and_stop()

    assert result == "OK"
    assert mock_client.command.call_count == 2


async def test_retry_on_timeout_error(mock_client: AsyncMock) -> None:
    """Command retries on WiiMTimeoutError and succeeds on retry."""
    mock_client.command = AsyncMock(
        side_effect=[WiiMTimeoutError("timeout"), WiiMTimeoutError("timeout"), "OK"]
    )
    q = WiiMCommandQueue(client=mock_client, delay=0.01, max_retries=3)

    await q.start()
    result = await q.enqueue("TimeoutCmd")
    await q.drain_and_stop()

    assert result == "OK"
    assert mock_client.command.call_count == 3


# ------------------------------------------------------------------
# Max retries exceeded
# ------------------------------------------------------------------


async def test_max_retries_exceeded_raises(mock_client: AsyncMock) -> None:
    """After max_retries failures, the exception propagates to the caller."""
    mock_client.command = AsyncMock(
        side_effect=WiiMConnectionError("persistent failure")
    )
    q = WiiMCommandQueue(client=mock_client, delay=0.01, max_retries=3)

    await q.start()
    with pytest.raises(WiiMConnectionError, match="persistent failure"):
        await q.enqueue("FailCmd")
    await q.drain_and_stop()

    assert mock_client.command.call_count == 3


# ------------------------------------------------------------------
# drain_and_stop
# ------------------------------------------------------------------


async def test_drain_and_stop_waits_for_pending(mock_client: AsyncMock) -> None:
    """drain_and_stop waits until all enqueued commands are processed."""
    processed: list[str] = []

    async def slow_command(cmd: str) -> str:
        await asyncio.sleep(0.02)
        processed.append(cmd)
        return "OK"

    mock_client.command = AsyncMock(side_effect=slow_command)
    q = WiiMCommandQueue(client=mock_client, delay=0.01, max_retries=3)

    await q.start()
    # Fire and forget - don't await enqueue futures directly
    task1 = asyncio.create_task(q.enqueue("Drain1"))
    task2 = asyncio.create_task(q.enqueue("Drain2"))
    task3 = asyncio.create_task(q.enqueue("Drain3"))

    # Yield control so all enqueue coroutines can put items on the queue
    await asyncio.sleep(0)

    await q.drain_and_stop()

    # All should be processed after drain
    assert processed == ["Drain1", "Drain2", "Drain3"]
    # Futures should all be resolved
    assert task1.done()
    assert task2.done()
    assert task3.done()


# ------------------------------------------------------------------
# cancel
# ------------------------------------------------------------------


async def test_cancel_discards_pending(mock_client: AsyncMock) -> None:
    """cancel() discards pending commands that haven't been processed yet."""
    gate = asyncio.Event()

    async def blocking_command(cmd: str) -> str:
        if cmd == "Block":
            await gate.wait()
        return "OK"

    mock_client.command = AsyncMock(side_effect=blocking_command)
    q = WiiMCommandQueue(client=mock_client, delay=0.01, max_retries=3)

    await q.start()

    # Enqueue a blocking command followed by others
    task_block = asyncio.create_task(q.enqueue("Block"))
    # Give consumer time to pick up the blocking command
    await asyncio.sleep(0.05)
    task_pending = asyncio.create_task(q.enqueue("Pending"))
    # Let the enqueue coroutine put the item on the queue
    await asyncio.sleep(0)

    # Cancel the queue
    await q.cancel()

    # Unblock to let the test clean up
    gate.set()

    # Give tasks time to resolve after cancellation
    await asyncio.sleep(0.05)

    # The pending task should be cancelled
    assert task_pending.done()
    with pytest.raises((asyncio.CancelledError, Exception)):
        task_pending.result()
    # The blocking task should also be done
    assert task_block.done()


# ------------------------------------------------------------------
# Read bypasses queue
# ------------------------------------------------------------------


async def test_read_bypasses_queue(mock_client: AsyncMock) -> None:
    """Read-only calls go directly through the client without queuing."""
    mock_client.command = AsyncMock(return_value={"status": "ok"})
    q = WiiMCommandQueue(client=mock_client, delay=0.1, max_retries=3)

    # Don't even start the queue - read should still work
    result = await q.read("getStatusEx")

    assert result == {"status": "ok"}
    mock_client.command.assert_called_once_with("getStatusEx")


# ------------------------------------------------------------------
# Edge cases
# ------------------------------------------------------------------


async def test_start_idempotent(mock_client: AsyncMock) -> None:
    """Calling start() multiple times does not create multiple consumers."""
    q = WiiMCommandQueue(client=mock_client, delay=0.01, max_retries=3)

    await q.start()
    first_task = q._consumer_task
    await q.start()
    second_task = q._consumer_task

    assert first_task is second_task
    await q.drain_and_stop()


async def test_drain_when_not_running(mock_client: AsyncMock) -> None:
    """drain_and_stop on a non-started queue is a no-op."""
    q = WiiMCommandQueue(client=mock_client, delay=0.01, max_retries=3)
    await q.drain_and_stop()  # Should not raise
