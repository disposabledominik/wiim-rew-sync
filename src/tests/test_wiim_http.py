"""Unit tests for WiiMHttpClient (src/adapters/wiim_http.py).

Uses ``respx`` to mock httpx calls without touching the network.
"""

from __future__ import annotations

import logging

import httpx
import pytest
import respx

from src.adapters.wiim_http import WiiMHttpClient
from src.models.errors import WiiMConnectionError, WiiMResponseError, WiiMTimeoutError

DEVICE_IP = "192.168.1.100"
BASE_URL = f"https://{DEVICE_IP}/httpapi.asp"


@pytest.fixture
def client() -> WiiMHttpClient:
    """Create a WiiMHttpClient instance for testing."""
    return WiiMHttpClient(ip=DEVICE_IP, timeout=5.0)


# --------------------------------------------------------------------------
# Successful responses
# --------------------------------------------------------------------------


@respx.mock
async def test_command_json_response(client: WiiMHttpClient) -> None:
    """JSON responses are returned as parsed dicts."""
    payload = {"DeviceName": "Living Room", "uuid": "ABC123"}
    respx.get(f"{BASE_URL}?command=getStatusEx").mock(
        return_value=httpx.Response(200, json=payload)
    )

    result = await client.command("getStatusEx")

    assert result == payload
    assert isinstance(result, dict)


@respx.mock
async def test_command_raw_text_response(client: WiiMHttpClient) -> None:
    """Non-JSON responses are returned as raw strings."""
    respx.get(f"{BASE_URL}?command=EQOff").mock(
        return_value=httpx.Response(200, text="OK")
    )

    result = await client.command("EQOff")

    assert result == "OK"
    assert isinstance(result, str)


# --------------------------------------------------------------------------
# Error handling
# --------------------------------------------------------------------------


@respx.mock
async def test_timeout_raises_wiim_timeout_error(client: WiiMHttpClient) -> None:
    """httpx.TimeoutException maps to WiiMTimeoutError."""
    respx.get(f"{BASE_URL}?command=getStatusEx").mock(
        side_effect=httpx.ReadTimeout("timed out")
    )

    with pytest.raises(WiiMTimeoutError, match="did not respond"):
        await client.command("getStatusEx")


@respx.mock
async def test_connection_refused_raises_wiim_connection_error(client: WiiMHttpClient) -> None:
    """httpx.ConnectError maps to WiiMConnectionError."""
    respx.get(f"{BASE_URL}?command=getStatusEx").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )

    with pytest.raises(WiiMConnectionError, match="Cannot connect"):
        await client.command("getStatusEx")


@respx.mock
async def test_http_500_raises_wiim_response_error(client: WiiMHttpClient) -> None:
    """Non-200 HTTP status raises WiiMResponseError."""
    respx.get(f"{BASE_URL}?command=badCommand").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )

    with pytest.raises(WiiMResponseError, match="HTTP 500"):
        await client.command("badCommand")


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------


@respx.mock
async def test_request_response_logging(
    client: WiiMHttpClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Every request/response pair is logged to wiim_rew_sync.wiim_api."""
    respx.get(f"{BASE_URL}?command=getDeviceName").mock(
        return_value=httpx.Response(200, json={"DeviceName": "Test"})
    )

    wiim_logger = logging.getLogger("wiim_rew_sync.wiim_api")
    wiim_logger.propagate = True
    try:
        with caplog.at_level(logging.DEBUG, logger="wiim_rew_sync.wiim_api"):
            await client.command("getDeviceName")

        # Verify request and response are both logged
        messages = caplog.text
        assert "REQ" in messages
        assert "getDeviceName" in messages
        assert "RESP" in messages
        assert "200" in messages
    finally:
        wiim_logger.propagate = False


@respx.mock
async def test_timeout_error_logging(
    client: WiiMHttpClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Timeout errors are logged."""
    respx.get(f"{BASE_URL}?command=getStatusEx").mock(
        side_effect=httpx.ReadTimeout("timed out")
    )

    wiim_logger = logging.getLogger("wiim_rew_sync.wiim_api")
    wiim_logger.propagate = True
    try:
        with caplog.at_level(logging.DEBUG, logger="wiim_rew_sync.wiim_api"):
            with pytest.raises(WiiMTimeoutError):
                await client.command("getStatusEx")

        assert "TIMEOUT" in caplog.text
    finally:
        wiim_logger.propagate = False


# --------------------------------------------------------------------------
# Async context manager
# --------------------------------------------------------------------------


@respx.mock
async def test_async_context_manager() -> None:
    """Client works as async context manager and closes cleanly."""
    respx.get(f"{BASE_URL}?command=getStatusEx").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    async with WiiMHttpClient(ip=DEVICE_IP) as client:
        result = await client.command("getStatusEx")
        assert result == {"ok": True}

    # After exiting context, the internal client should be closed
    assert client._client.is_closed
