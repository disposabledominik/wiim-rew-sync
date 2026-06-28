"""
REW HTTP API client adapter -- thin httpx.AsyncClient wrapper.

All requests target ``http://localhost:4735`` (REW's local REST API).
REW must be launched with the ``-api`` flag or have API access enabled in preferences.

Every request/response pair is logged to ``rew_api.log`` via the
``wiim_rew_sync.rew_api`` logger.

Requirements: 8.1, 8.3, 8.4, 8.5, 8.6
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import TracebackType
from typing import Self

import httpx

from src.models.canonical import CanonicalFilter
from src.models.errors import REWMeasurementNotFoundError, REWNotConnectedError
from src.translator._warnings import FilterRow
from src.translator.rew_parser import REWParser

logger = logging.getLogger("wiim_rew_sync.rew_api")


@dataclass(frozen=True, slots=True)
class MeasurementSummary:
    """Summary of a single REW measurement."""

    uuid: str
    name: str
    index: int


class REWHttpApiClient:
    """Async HTTP client for REW's localhost REST API.

    Wraps :class:`httpx.AsyncClient` targeting the REW API base URL
    (default ``http://localhost:4735``).  Usable as an async context manager.

    Args:
        base_url: REW API base URL (no trailing slash).
    """

    def __init__(self, base_url: str = "http://localhost:4735") -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(5.0))
        self._parser = REWParser()

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

    async def list_measurements(self) -> list[MeasurementSummary]:
        """Fetch all measurements from REW.

        Returns:
            List of MeasurementSummary objects.

        Raises:
            REWNotConnectedError: REW is not running or API is not enabled.
        """
        url = f"{self._base_url}/measurements"
        logger.debug("REQ  -> GET %s", url)

        try:
            response = await self._client.get(url)
        except httpx.ConnectError as exc:
            logger.error("CONNECT_ERR -> %s: %s", url, exc)
            raise REWNotConnectedError(
                "REW is not connected. Please ensure REW is running and "
                "its HTTP API is enabled (localhost:4735)."
            ) from exc

        logger.debug(
            "RESP <- %d %s (len=%d)", response.status_code, url, len(response.text)
        )

        if response.status_code != 200:
            raise REWNotConnectedError(
                f"REW API returned unexpected status {response.status_code} "
                f"for {url}. Please ensure REW is running and its HTTP API "
                f"is enabled (localhost:4735)."
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise REWNotConnectedError(
                f"REW API returned a non-JSON response for {url}. Please "
                f"ensure REW is running and its HTTP API is enabled "
                f"(localhost:4735)."
            ) from exc
        logger.debug("REW measurements response: %s", repr(data)[:500])

        # Handle both bare array and dict-keyed responses
        items: list[dict[str, object]] = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            # Try common wrapper keys first
            for key in ("measurements", "data", "items"):
                if key in data and isinstance(data[key], list):
                    items = data[key]
                    break
            if not items:
                # REW returns measurements as a dict keyed by index ("1", "2", ...)
                # where each value is a measurement object with title, uuid, etc.
                if data and all(isinstance(v, dict) for v in data.values()):
                    items = list(data.values())
                else:
                    logger.warning("Unexpected REW response format: %s", repr(data)[:200])
                    return []

        summaries: list[MeasurementSummary] = []
        for i, item in enumerate(items):
            # Support multiple field name variants
            uuid = str(item.get("uuid") or item.get("id") or item.get("UUID") or f"idx_{i}")
            name = str(
                item.get("title") or item.get("name") or item.get("Title") or f"Measurement {i + 1}"
            )
            summaries.append(
                MeasurementSummary(
                    uuid=uuid,
                    name=name,
                    index=i,
                )
            )
        return summaries

    async def get_filters(self, uuid: str) -> list[CanonicalFilter]:
        """Fetch filters for a specific measurement.

        Args:
            uuid: The measurement UUID.

        Returns:
            List of CanonicalFilter objects parsed from the REW API response.

        Raises:
            REWNotConnectedError: REW is not running or API is not enabled.
            REWMeasurementNotFoundError: The measurement UUID was not found.
        """
        data = await self._fetch_filter_settings(uuid)
        return self._parser.parse_filter_settings(data)

    async def get_filters_with_rows(
        self, uuid: str
    ) -> tuple[list[CanonicalFilter], list[FilterRow], dict[int, list[str]]]:
        """Fetch filters for a measurement, also returning display rows.

        Same as get_filters(), but also returns `rows`: the filters in
        original order with SkippedBand placeholders for any filter type
        REW reports that has no WiiM translation (e.g. Notch); and
        `conversion_notes`: notes about values REW's API omitted and had to
        be substituted (currently: the fixed Q applied to a bare LP/HP).

        Args:
            uuid: The measurement UUID.

        Raises:
            REWNotConnectedError: REW is not running or API is not enabled.
            REWMeasurementNotFoundError: The measurement UUID was not found.
        """
        data = await self._fetch_filter_settings(uuid)
        return self._parser.parse_filter_settings_with_rows(data)

    async def _fetch_filter_settings(self, uuid: str) -> list[dict[str, object]]:
        """GET and JSON-decode the raw FilterSetting list for a measurement."""
        url = f"{self._base_url}/measurements/{uuid}/filters"
        logger.debug("REQ  -> GET %s", url)

        try:
            response = await self._client.get(url)
        except httpx.ConnectError as exc:
            logger.error("CONNECT_ERR -> %s: %s", url, exc)
            raise REWNotConnectedError(
                "REW is not connected. Please ensure REW is running and "
                "its HTTP API is enabled (localhost:4735)."
            ) from exc

        logger.debug(
            "RESP <- %d %s (len=%d)", response.status_code, url, len(response.text)
        )

        if response.status_code == 404:
            raise REWMeasurementNotFoundError(
                f"Measurement '{uuid}' not found in REW"
            )
        if response.status_code != 200:
            raise REWNotConnectedError(
                f"REW API returned unexpected status {response.status_code} "
                f"for {url}. Please ensure REW is running and its HTTP API "
                f"is enabled (localhost:4735)."
            )

        try:
            return response.json()  # type: ignore[no-any-return]
        except ValueError as exc:
            raise REWNotConnectedError(
                f"REW API returned a non-JSON response for {url}. Please "
                f"ensure REW is running and its HTTP API is enabled "
                f"(localhost:4735)."
            ) from exc

    async def close(self) -> None:
        """Close the underlying httpx.AsyncClient."""
        await self._client.aclose()
