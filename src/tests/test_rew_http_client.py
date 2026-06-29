"""Unit tests for REWHttpApiClient (src/adapters/rew_http_client.py).

Uses ``respx`` to mock httpx calls without touching the network.
"""

from __future__ import annotations

import logging

import httpx
import pytest
import respx

from src.adapters.rew_http_client import MeasurementSummary, REWHttpApiClient
from src.models.errors import REWMeasurementNotFoundError, REWNotConnectedError

BASE_URL = "http://localhost:4735"


@pytest.fixture
def client() -> REWHttpApiClient:
    """Create a REWHttpApiClient instance for testing."""
    return REWHttpApiClient(base_url=BASE_URL)


# --------------------------------------------------------------------------
# list_measurements
# --------------------------------------------------------------------------


@respx.mock
async def test_list_measurements_returns_parsed_summaries(
    client: REWHttpApiClient,
) -> None:
    """list_measurements returns a list of MeasurementSummary from JSON array."""
    payload = [
        {
            "title": "Listening Position",
            "uuid": "ba2da346-0f31-4d9d-bbeb-2bfcd07e1cb9",
            "date": "2026-06-04 13:00:00",
            "startFreq": 20.0,
            "endFreq": 20000.0,
        },
        {
            "title": "Near Field",
            "uuid": "cc3ea457-1f42-5e0e-ccfc-3c0de18f2eda",
            "date": "2026-06-05 14:00:00",
            "startFreq": 20.0,
            "endFreq": 20000.0,
        },
    ]
    respx.get(f"{BASE_URL}/measurements").mock(
        return_value=httpx.Response(200, json=payload)
    )

    result = await client.list_measurements()

    assert len(result) == 2
    assert result[0] == MeasurementSummary(
        uuid="ba2da346-0f31-4d9d-bbeb-2bfcd07e1cb9",
        name="Listening Position",
        index=0,
    )
    assert result[1] == MeasurementSummary(
        uuid="cc3ea457-1f42-5e0e-ccfc-3c0de18f2eda",
        name="Near Field",
        index=1,
    )


@respx.mock
async def test_list_measurements_connection_refused_raises_rew_not_connected(
    client: REWHttpApiClient,
) -> None:
    """Connection refused on list_measurements raises REWNotConnectedError."""
    respx.get(f"{BASE_URL}/measurements").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )

    with pytest.raises(REWNotConnectedError, match="REW is not connected"):
        await client.list_measurements()


@respx.mock
async def test_list_measurements_500_raises_without_calling_json(
    client: REWHttpApiClient,
) -> None:
    """HTTP 500 on list_measurements must raise before attempting response.json()."""
    respx.get(f"{BASE_URL}/measurements").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )

    with pytest.raises(REWNotConnectedError, match="unexpected status 500"):
        await client.list_measurements()


@respx.mock
async def test_list_measurements_non_json_200_raises_rew_not_connected(
    client: REWHttpApiClient,
) -> None:
    """A 200 response with a non-JSON body raises REWNotConnectedError, not a raw decode error."""
    respx.get(f"{BASE_URL}/measurements").mock(
        return_value=httpx.Response(200, text="<html>not json</html>")
    )

    with pytest.raises(REWNotConnectedError, match="non-JSON response"):
        await client.list_measurements()


# --------------------------------------------------------------------------
# get_filters
# --------------------------------------------------------------------------


@respx.mock
async def test_get_filters_returns_canonical_filters(
    client: REWHttpApiClient,
) -> None:
    """get_filters parses FilterSetting objects into CanonicalFilter list.

    The bare "LS" shelf type carries a shelf-slope parameter S, not a
    Butterworth Q -- it's in _SKIP_TYPES and dropped from the filters list
    (see docs/corrections.md, 2026-06-28), so it's absent here entirely
    rather than passed through.
    """
    uuid = "ba2da346-0f31-4d9d-bbeb-2bfcd07e1cb9"
    payload = [
        {"filterNo": 1, "on": True, "type": "PK", "freq": 80.0, "gain": 5.3, "q": 3.885},
        {"filterNo": 2, "on": True, "type": "LS", "freq": 40.0, "gain": 3.0, "q": 0.707},
        {"filterNo": 3, "on": False, "type": "PK", "freq": 200.0, "gain": 0.0, "q": 1.0},
    ]
    respx.get(f"{BASE_URL}/measurements/{uuid}/filters").mock(
        return_value=httpx.Response(200, json=payload)
    )

    result = await client.get_filters(uuid)

    assert len(result) == 2
    # First filter: PK enabled -> PEAK
    assert result[0].type == "PEAK"
    assert result[0].frequency_hz == 80.0
    assert result[0].gain_db == 5.3
    assert result[0].q == 3.885
    # Second filter (filterNo 2, "LS") is skipped -- not WiiM-translatable.
    # Third filter: PK disabled -> OFF
    assert result[1].type == "OFF"
    assert result[1].frequency_hz == 200.0


@respx.mock
async def test_get_filters_404_raises_measurement_not_found(
    client: REWHttpApiClient,
) -> None:
    """HTTP 404 on get_filters raises REWMeasurementNotFoundError."""
    uuid = "nonexistent-uuid"
    respx.get(f"{BASE_URL}/measurements/{uuid}/filters").mock(
        return_value=httpx.Response(404, text="Not Found")
    )

    with pytest.raises(REWMeasurementNotFoundError, match="not found"):
        await client.get_filters(uuid)


@respx.mock
async def test_get_filters_connection_refused_raises_rew_not_connected(
    client: REWHttpApiClient,
) -> None:
    """Connection refused on get_filters raises REWNotConnectedError."""
    uuid = "ba2da346-0f31-4d9d-bbeb-2bfcd07e1cb9"
    respx.get(f"{BASE_URL}/measurements/{uuid}/filters").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )

    with pytest.raises(REWNotConnectedError, match="REW is not connected"):
        await client.get_filters(uuid)


@respx.mock
async def test_get_filters_500_raises_without_calling_json(
    client: REWHttpApiClient,
) -> None:
    """HTTP 500 on get_filters must raise before attempting response.json()."""
    uuid = "ba2da346-0f31-4d9d-bbeb-2bfcd07e1cb9"
    respx.get(f"{BASE_URL}/measurements/{uuid}/filters").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )

    with pytest.raises(REWNotConnectedError, match="unexpected status 500"):
        await client.get_filters(uuid)


@respx.mock
async def test_get_filters_non_json_200_raises_rew_not_connected(
    client: REWHttpApiClient,
) -> None:
    """A 200 response with a non-JSON body raises REWNotConnectedError, not a raw decode error."""
    uuid = "ba2da346-0f31-4d9d-bbeb-2bfcd07e1cb9"
    respx.get(f"{BASE_URL}/measurements/{uuid}/filters").mock(
        return_value=httpx.Response(200, text="<html>not json</html>")
    )

    with pytest.raises(REWNotConnectedError, match="non-JSON response"):
        await client.get_filters(uuid)


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------


@respx.mock
async def test_request_response_logging(
    client: REWHttpApiClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Every request/response pair is logged to wiim_rew_sync.rew_api."""
    payload = [
        {
            "title": "Test",
            "uuid": "abc-123",
            "date": "2026-01-01 00:00:00",
            "startFreq": 20.0,
            "endFreq": 20000.0,
        },
    ]
    respx.get(f"{BASE_URL}/measurements").mock(
        return_value=httpx.Response(200, json=payload)
    )

    rew_logger = logging.getLogger("wiim_rew_sync.rew_api")
    rew_logger.propagate = True
    try:
        with caplog.at_level(logging.DEBUG, logger="wiim_rew_sync.rew_api"):
            await client.list_measurements()

        messages = caplog.text
        assert "REQ" in messages
        assert "/measurements" in messages
        assert "RESP" in messages
        assert "200" in messages
    finally:
        rew_logger.propagate = False


@respx.mock
async def test_connection_error_logging(
    client: REWHttpApiClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Connection errors are logged."""
    respx.get(f"{BASE_URL}/measurements").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )

    rew_logger = logging.getLogger("wiim_rew_sync.rew_api")
    rew_logger.propagate = True
    try:
        with caplog.at_level(logging.DEBUG, logger="wiim_rew_sync.rew_api"):
            with pytest.raises(REWNotConnectedError):
                await client.list_measurements()

        assert "CONNECT_ERR" in caplog.text
    finally:
        rew_logger.propagate = False
