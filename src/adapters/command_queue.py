"""
WiiM command queue - single-consumer FIFO with inter-command delay.

Serializes write commands to the WiiM device to avoid overwhelming its
httpapi endpoint. Read-only GET calls bypass the queue entirely.

Requirements: 5.4, 18.1
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.adapters.wiim_http import WiiMHttpClient
from src.models.errors import WiiMConnectionError, WiiMTimeoutError

logger = logging.getLogger("wiim_rew_sync.wiim_api")


class WiiMCommandQueue:
    """Async FIFO command queue with inter-command delay and retry logic.

    Write commands are serialized through a single background consumer task
    with a configurable delay between each command. Read-only GET calls
    bypass the queue and are executed immediately.

    Args:
        client: The HTTP client used to issue commands.
        delay: Seconds to wait between processing consecutive commands.
        max_retries: Maximum retry attempts per command on transient failures.
    """

    def __init__(
        self,
        client: WiiMHttpClient,
        delay: float = 0.1,
        max_retries: int = 3,
    ) -> None:
        if max_retries <= 0:
            raise ValueError(f"max_retries must be positive, got {max_retries}")
        self._client = client
        self._delay = delay
        self._max_retries = max_retries
        self._queue: asyncio.Queue[
            tuple[str, asyncio.Future[dict[str, Any] | str]]
        ] = asyncio.Queue()
        self._consumer_task: asyncio.Task[None] | None = None
        self._running = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background consumer task."""
        if self._running:
            return
        self._running = True
        self._consumer_task = asyncio.create_task(self._consume())

    async def drain_and_stop(self) -> None:
        """Wait for all queued commands to complete, then stop."""
        if not self._running:
            return
        # Wait until the queue is fully processed
        await self._queue.join()
        self._running = False
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None

    async def cancel(self) -> None:
        """Cancel all pending commands and stop immediately."""
        self._running = False
        if self._consumer_task is not None:
            self._consumer_task.cancel()
            try:
                await self._consumer_task
            except asyncio.CancelledError:
                pass
            self._consumer_task = None
        # Discard all pending items and resolve their futures with CancelledError
        while not self._queue.empty():
            try:
                _command, future = self._queue.get_nowait()
                if not future.done():
                    future.cancel()
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def enqueue(self, command: str) -> dict[str, Any] | str:
        """Add a write command to the queue. Returns the response when processed.

        Args:
            command: The WiiM API command string to execute.

        Returns:
            The parsed response from the device once the command is processed.

        Raises:
            WiiMConnectionError: After max retries exhausted due to connection failures.
            WiiMTimeoutError: After max retries exhausted due to timeouts.
            asyncio.CancelledError: If the queue is cancelled before processing.
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any] | str] = loop.create_future()
        await self._queue.put((command, future))
        return await future

    async def read(self, command: str) -> dict[str, Any] | str:
        """Execute a read-only GET command immediately, bypassing the queue.

        Args:
            command: The WiiM API command string (read-only).

        Returns:
            The parsed response from the device.
        """
        return await self._client.command(command)

    # ------------------------------------------------------------------
    # Internal consumer
    # ------------------------------------------------------------------

    async def _consume(self) -> None:
        """Background consumer loop processing commands one at a time."""
        while self._running:
            try:
                command, future = await asyncio.wait_for(
                    self._queue.get(), timeout=0.5
                )
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            try:
                result = await self._execute_with_retry(command)
                if not future.done():
                    future.set_result(result)
            except (WiiMConnectionError, WiiMTimeoutError) as exc:
                if not future.done():
                    future.set_exception(exc)
            except asyncio.CancelledError:
                if not future.done():
                    future.cancel()
                break
            finally:
                self._queue.task_done()

            # Inter-command delay
            if self._running:
                await asyncio.sleep(self._delay)

    async def _execute_with_retry(self, command: str) -> dict[str, Any] | str:
        """Execute a command with retry logic on transient failures.

        Args:
            command: The WiiM API command string.

        Returns:
            The parsed response on success.

        Raises:
            WiiMConnectionError: After max_retries exhausted.
            WiiMTimeoutError: After max_retries exhausted.
        """
        last_exc: WiiMConnectionError | WiiMTimeoutError | None = None
        for attempt in range(self._max_retries):
            try:
                return await self._client.command(command)
            except (WiiMConnectionError, WiiMTimeoutError) as exc:
                last_exc = exc
                logger.warning(
                    "Command %r failed (attempt %d/%d): %s",
                    command,
                    attempt + 1,
                    self._max_retries,
                    exc,
                )
                if attempt + 1 < self._max_retries:
                    await asyncio.sleep(0.1 * (attempt + 1))
        # All retries exhausted
        assert last_exc is not None  # loop always executes >=1 time (max_retries > 0)
        raise last_exc
