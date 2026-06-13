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
                f"Cannot connect to REW API at {self._base_url}: {exc}"
            ) from exc

        logger.debug(
            "RESP <- %d %s (len=%d)", response.status_code, url, len(response.text)
        )

        data = response.json()
        summaries: list[MeasurementSummary] = []
        for i, item in enumerate(data):
            summaries.append(
                MeasurementSummary(
                    uuid=item["uuid"],
                    name=item["title"],
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
        url = f"{self._base_url}/measurements/{uuid}/filters"
        logger.debug("REQ  -> GET %s", url)

        try:
            response = await self._client.get(url)
        except httpx.ConnectError as exc:
            logger.error("CONNECT_ERR -> %s: %s", url, exc)
            raise REWNotConnectedError(
                f"Cannot connect to REW API at {self._base_url}: {exc}"
            ) from exc

        logger.debug(
            "RESP <- %d %s (len=%d)", response.status_code, url, len(response.text)
        )

        if response.status_code == 404:
            raise REWMeasurementNotFoundError(
                f"Measurement '{uuid}' not found in REW"
            )

        data = response.json()
        return self._parser.parse_filter_settings(data)

    async def close(self) -> None:
        """Close the underlying httpx.AsyncClient."""
        await self._client.aclose()
