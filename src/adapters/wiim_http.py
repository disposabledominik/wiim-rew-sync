"""
WiiM HTTP client adapter — thin httpx.AsyncClient wrapper.

All requests target ``https://<ip>/httpapi.asp?command=<command>`` with TLS
verification disabled (WiiM devices use self-signed certificates).

Every request/response pair is logged to ``wiim_api.log`` via the
``wiim_rew_sync.wiim_api`` logger.

Requirements: 4.6, 8.6, 14.7, 15.4
"""

from __future__ import annotations

import json
import logging
from types import TracebackType
from typing import Any, Self

import httpx

from src.models.errors import WiiMConnectionError, WiiMResponseError, WiiMTimeoutError

logger = logging.getLogger("wiim_rew_sync.wiim_api")


class WiiMHttpClient:
    """Async HTTP client for WiiM device communication.

    Wraps :class:`httpx.AsyncClient` with ``verify=False`` (self-signed certs)
    and a configurable timeout (default 5 s).  Usable as an async context manager.

    Args:
        ip: Device IP address (IPv4).
        timeout: Request timeout in seconds.
    """

    def __init__(self, ip: str, timeout: float = 5.0) -> None:
        self._ip = ip
        self._timeout = timeout
        self._client = httpx.AsyncClient(
            verify=False,  # noqa: S501 — WiiM devices use self-signed certs
            timeout=httpx.Timeout(timeout),
        )
        # Per-client request counter -- gives each REQ/RESP pair a shared
        # short ID so the response line can reference it instead of
        # repeating the full (often huge, for Set commands) request URL.
        self._request_count = 0

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def command(self, command: str) -> dict[str, Any] | str:
        """Issue a GET request to the device httpapi endpoint.

        Args:
            command: The WiiM API command string (already URL-encoded if needed).

        Returns:
            Parsed JSON ``dict`` when the response body is valid JSON,
            otherwise the raw response text.

        Raises:
            WiiMTimeoutError: Device did not respond within the timeout window.
            WiiMConnectionError: Device unreachable or connection refused.
            WiiMResponseError: Non-200 HTTP status code.
        """
        url = f"https://{self._ip}/httpapi.asp?command={command}"
        self._request_count += 1
        req_id = self._request_count

        logger.debug("REQ  #%d → GET %s", req_id, url)

        try:
            response = await self._client.get(url)
        except httpx.TimeoutException as exc:
            logger.error("TIMEOUT #%d → %s: %s", req_id, url, exc)
            raise WiiMTimeoutError(
                f"Device {self._ip} did not respond within {self._timeout}s"
            ) from exc
        except httpx.ConnectError as exc:
            logger.error("CONNECT_ERR #%d → %s: %s", req_id, url, exc)
            raise WiiMConnectionError(
                f"Cannot connect to device {self._ip}: {exc}"
            ) from exc

        # The response line intentionally omits the URL (already logged on
        # the REQ line above, identified by the same #req_id) and the body
        # is logged in full, not truncated -- a 12-band L/R read-back is
        # ~5 KB and a fixed truncation point used to cut it off mid-band.
        body = response.text
        logger.debug(
            "RESP #%d ← %d (len=%d) body=%s", req_id, response.status_code, len(body), body
        )

        if response.status_code != 200:
            logger.error("HTTP %d (#%d) from %s", response.status_code, req_id, self._ip)
            raise WiiMResponseError(
                f"HTTP {response.status_code} from {self._ip}: {body[:200]}"
            )

        # Try JSON first; fall back to raw string for non-JSON responses
        # (e.g. "OK", device name strings, etc.)
        try:
            parsed: dict[str, Any] = json.loads(body)
            return parsed
        except (json.JSONDecodeError, ValueError):
            # WiiM always returns HTTP 200, even on failure -- Set/Delete/Save
            # commands signal failure via a plain "Failed" text body instead
            # of a non-200 status. Surface that loudly, since nothing else
            # in the call chain inspects this return value for Set commands.
            if body.strip() != "OK":
                logger.warning("Non-OK response body (#%d): %r", req_id, body)
            return body

    async def close(self) -> None:
        """Close the underlying httpx.AsyncClient."""
        await self._client.aclose()
