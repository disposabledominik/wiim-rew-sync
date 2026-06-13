"""
WiiM device adapter — PEQ read/write and multiroom operations.

Wraps WiiMHttpClient with domain-aware methods that issue the correct LV2 PEQ
commands, parse responses via ``wiim_parser``, and return typed domain objects.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.3, 5.4, 5.11, 17.1, 17.4
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from src.adapters.wiim_http import WiiMHttpClient
from src.models.canonical import CanonicalFilter
from src.models.capabilities import DeviceCapabilities
from src.models.errors import WiiMConnectionError, WiiMResponseError, WiiMSlaveTargetError
from src.models.peq import PEQSettings
from src.translator.wiim_generator import generate_wiim_band_array
from src.translator.wiim_parser import parse_wiim_band_array

if TYPE_CHECKING:
    from src.adapters.command_queue import WiiMCommandQueue

logger = logging.getLogger("wiim_rew_sync.wiim_api")

# LV2 plugin URI used by all WiiM PEQ commands
_PLUGIN_URI = "http://moddevices.com/plugins/caps/EqNp"

# Band letters a-l (up to 12 bands on newer firmware; older devices use a-j for 10)
_BAND_LETTERS = "abcdefghijkl"


def _params_to_band_dicts(
    param_array: list[dict[str, Any]],
) -> list[dict[str, int | float | str]]:
    """Convert the raw WiiM param_name/value array into per-band dicts.

    The WiiM API returns 40 entries (4 params x 10 bands) in the format:
        [{"param_name": "a_mode", "value": 1.0}, {"param_name": "a_freq", ...}, ...]

    This function groups them into 10 band dicts with keys:
        {"mode": ..., "freq": ..., "q": ..., "gain": ...}

    which is the format expected by ``parse_wiim_band_array()``.
    """
    # Build a lookup: "a_mode" -> 1.0, "a_freq" -> 80.0, etc.
    params: dict[str, float] = {}
    for entry in param_array:
        param_name = str(entry.get("param_name", ""))
        value = entry.get("value", 0.0)
        params[param_name] = float(value)

    bands: list[dict[str, int | float | str]] = []
    for letter in _BAND_LETTERS:
        mode_key = f"{letter}_mode"
        freq_key = f"{letter}_freq"
        q_key = f"{letter}_q"
        gain_key = f"{letter}_gain"

        # If we have at least a mode for this letter, include the band
        if mode_key in params:
            bands.append({
                "mode": int(params.get(mode_key, -1)),
                "freq": params.get(freq_key, 1000.0),
                "q": params.get(q_key, 1.0),
                "gain": params.get(gain_key, 0.0),
            })

    return bands


class WiiMAdapter:
    """High-level adapter for WiiM PEQ operations.

    Args:
        http_client: Injected WiiMHttpClient for network communication.
        capabilities: Pre-probed device capabilities.
    """

    def __init__(
        self,
        http_client: WiiMHttpClient,
        capabilities: DeviceCapabilities,
    ) -> None:
        self._client = http_client
        self._capabilities = capabilities

    @property
    def capabilities(self) -> DeviceCapabilities:
        """Expose the device capabilities for external consumers (e.g. SafeWrite)."""
        return self._capabilities

    # ------------------------------------------------------------------
    # PEQ Read
    # ------------------------------------------------------------------

    async def read_peq(self, source_name: str) -> PEQSettings:
        """Read the current PEQ settings for a given source.

        Issues ``EQGetLV2SourceBandEx`` with the source name and plugin URI,
        then parses the response into a ``PEQSettings`` domain object.

        Args:
            source_name: The audio input source (e.g. "wifi", "bluetooth").

        Returns:
            PEQSettings with parsed bands (stereo or L/R).

        Raises:
            WiiMResponseError: Response missing required fields.
            WiiMConnectionError: Device unreachable (propagated from http_client).
        """
        payload = json.dumps({"source_name": source_name, "pluginURI": _PLUGIN_URI})
        command = f"EQGetLV2SourceBandEx:{quote(payload)}"

        # WiiMHttpClient.command() raises WiiMConnectionError / WiiMTimeoutError
        # on network failure — let those propagate directly.
        response = await self._client.command(command)

        if not isinstance(response, dict):
            raise WiiMResponseError(
                f"Expected JSON dict from EQGetLV2SourceBandEx, got: {type(response).__name__}"
            )

        return self._parse_peq_response(response, source_name)

    def _parse_peq_response(
        self, response: dict[str, Any], source_name: str
    ) -> PEQSettings:
        """Parse the EQGetLV2SourceBandEx JSON response into PEQSettings."""
        # Extract channel mode — required field
        channel_mode_raw: str | None = response.get("channelMode")
        if channel_mode_raw is None:
            raise WiiMResponseError(
                "Missing 'channelMode' field in EQGetLV2SourceBandEx response"
            )

        # Extract optional fields
        enabled = response.get("EQStat", "Off") == "On"
        name = response.get("Name", "")

        if channel_mode_raw == "Stereo":
            return self._parse_stereo(response, source_name, enabled, name)
        elif channel_mode_raw == "L/R":
            return self._parse_lr(response, source_name, enabled, name)
        else:
            raise WiiMResponseError(
                f"Unknown channelMode value: '{channel_mode_raw}'"
            )

    def _parse_stereo(
        self,
        response: dict[str, Any],
        source_name: str,
        enabled: bool,
        name: str,
    ) -> PEQSettings:
        """Parse stereo mode response (EQBand key)."""
        eq_band_raw: list[dict[str, Any]] | None = response.get("EQBand")
        if eq_band_raw is None:
            raise WiiMResponseError(
                "Stereo mode response missing 'EQBand' field"
            )

        band_dicts = _params_to_band_dicts(eq_band_raw)
        bands: list[CanonicalFilter] = parse_wiim_band_array(band_dicts, channel="stereo")

        return PEQSettings(
            source_name=source_name,
            enabled=enabled,
            channel_mode="stereo",
            name=name,
            bands=bands,
        )

    def _parse_lr(
        self,
        response: dict[str, Any],
        source_name: str,
        enabled: bool,
        name: str,
    ) -> PEQSettings:
        """Parse L/R mode response (EQBandL + EQBandR keys)."""
        eq_band_l_raw: list[dict[str, Any]] | None = response.get("EQBandL")
        eq_band_r_raw: list[dict[str, Any]] | None = response.get("EQBandR")

        if eq_band_l_raw is None:
            raise WiiMResponseError(
                "L/R mode response missing 'EQBandL' field"
            )
        if eq_band_r_raw is None:
            raise WiiMResponseError(
                "L/R mode response missing 'EQBandR' field"
            )

        band_dicts_l = _params_to_band_dicts(eq_band_l_raw)
        band_dicts_r = _params_to_band_dicts(eq_band_r_raw)
        bands_l: list[CanonicalFilter] = parse_wiim_band_array(band_dicts_l, channel="left")
        bands_r: list[CanonicalFilter] = parse_wiim_band_array(band_dicts_r, channel="right")

        return PEQSettings(
            source_name=source_name,
            enabled=enabled,
            channel_mode="lr",
            name=name,
            bands_l=bands_l,
            bands_r=bands_r,
        )

    # ------------------------------------------------------------------
    # Multiroom
    # ------------------------------------------------------------------

    async def get_multiroom_master_ip(self) -> str | None:
        """Return master IP from GetMultiroomInfo, or None if solo/unreachable.

        Returns:
            Master device IP string, or None if the device is solo or the
            info cannot be retrieved.
        """
        try:
            response = await self._client.command("GetMultiroomInfo")
        except (WiiMConnectionError, Exception) as exc:
            logger.warning("GetMultiroomInfo failed: %s", exc)
            return None

        if not isinstance(response, dict):
            return None

        # The response contains a 'master_ip' field when the device is part
        # of a multiroom group.
        master_ip: str | None = response.get("master_ip")
        if master_ip:
            return master_ip

        return None

    # ------------------------------------------------------------------
    # PEQ Write
    # ------------------------------------------------------------------

    async def write_peq(
        self,
        source_name: str,
        settings: PEQSettings,
        queue: WiiMCommandQueue | None = None,
    ) -> None:
        """Write PEQ bands to the device for a given source.

        Uses the batch path (single ``EQSetLV2SourceBand`` with full payload) when
        ``supports_batch_write`` is True. Otherwise writes bands sequentially via
        the queue with a 100 ms inter-command delay.

        Args:
            source_name: Audio input source (e.g. "wifi", "bluetooth").
            settings: PEQ settings containing bands to write.
            queue: Optional command queue for sequential writes.

        Raises:
            WiiMSlaveTargetError: Device role is slave (writes not allowed).
            WiiMResponseError: Device returned an error response.
            WiiMConnectionError: Device unreachable.
        """
        if self._capabilities.role == "slave":
            raise WiiMSlaveTargetError(
                "Cannot write PEQ to a slave device; target the master node instead"
            )

        # Determine which bands to write based on channel mode
        if settings.channel_mode == "stereo":
            bands = settings.bands
            channel_mode_wire = "Stereo"
        else:
            # For L/R mode, write left bands (right handled separately if needed)
            bands = settings.bands_l if settings.bands_l else settings.bands
            channel_mode_wire = "L/R"

        # Generate the WiiM 40-entry flat parameter array
        band_array, _warnings = generate_wiim_band_array(bands)

        if self._capabilities.supports_batch_write:
            await self._write_peq_batch(source_name, band_array, channel_mode_wire)
        else:
            await self._write_peq_sequential(source_name, band_array, channel_mode_wire, queue)

    async def _write_peq_batch(
        self,
        source_name: str,
        band_array: list[float],
        channel_mode: str,
    ) -> None:
        """Write all bands in a single EQSetLV2SourceBand payload."""
        # Build the EQBand parameter array from the flat band_array
        eq_band_params: list[dict[str, str | float]] = []
        for i in range(10):
            offset = i * 4
            letter = _BAND_LETTERS[i]
            eq_band_params.append({"param_name": f"{letter}_mode", "value": band_array[offset]})
            eq_band_params.append({"param_name": f"{letter}_freq", "value": band_array[offset + 1]})
            eq_band_params.append({"param_name": f"{letter}_gain", "value": band_array[offset + 2]})
            eq_band_params.append({"param_name": f"{letter}_q", "value": band_array[offset + 3]})

        payload = json.dumps({
            "pluginURI": _PLUGIN_URI,
            "source_name": source_name,
            "channelMode": channel_mode,
            "EQBand": eq_band_params,
        })
        command = f"EQSetLV2SourceBand:{quote(payload)}"
        await self._client.command(command)

    async def _write_peq_sequential(
        self,
        source_name: str,
        band_array: list[float],
        channel_mode: str,
        queue: WiiMCommandQueue | None,
    ) -> None:
        """Write bands one at a time via queue with 100ms inter-command delay."""
        for i in range(10):
            offset = i * 4
            letter = _BAND_LETTERS[i]

            band_params: list[dict[str, str | float]] = [
                {"param_name": f"{letter}_mode", "value": band_array[offset]},
                {"param_name": f"{letter}_freq", "value": band_array[offset + 1]},
                {"param_name": f"{letter}_gain", "value": band_array[offset + 2]},
                {"param_name": f"{letter}_q", "value": band_array[offset + 3]},
            ]

            payload = json.dumps({
                "pluginURI": _PLUGIN_URI,
                "source_name": source_name,
                "channelMode": channel_mode,
                "EQBand": band_params,
            })
            command = f"EQSetLV2SourceBand:{quote(payload)}"

            if queue is not None:
                await queue.enqueue(command)
            else:
                await self._client.command(command)

            # 100ms delay between sequential band writes
            if i < 9:
                await asyncio.sleep(0.1)

    # ------------------------------------------------------------------
    # RoomFit
    # ------------------------------------------------------------------

    async def read_roomfit(self) -> list[CanonicalFilter]:
        """Read RoomFit filter bands from the device.

        Requires ``roomfit_level >= 2`` in device capabilities.

        Returns:
            List of CanonicalFilter objects representing the RoomFit filters.

        Raises:
            WiiMResponseError: RoomFit read not supported (level < 2) or
                device returned an unexpected response.
        """
        if self._capabilities.roomfit_level < 2:
            raise WiiMResponseError(
                f"RoomFit read requires roomfit_level >= 2, "
                f"device has level {self._capabilities.roomfit_level}"
            )

        response = await self._client.command("getRoomFitBands")

        if not isinstance(response, dict):
            raise WiiMResponseError(
                f"Expected JSON dict from EQGetRoomFitBandEx, got: {type(response).__name__}"
            )

        eq_band_raw: list[dict[str, Any]] | None = response.get("EQBand")
        if eq_band_raw is None:
            raise WiiMResponseError("RoomFit response missing 'EQBand' field")

        band_dicts = _params_to_band_dicts(eq_band_raw)
        return parse_wiim_band_array(band_dicts, channel="stereo")

    async def write_roomfit(self, filters: list[CanonicalFilter]) -> None:
        """Write RoomFit filter bands to the device.

        Requires ``roomfit_level >= 4`` in device capabilities.

        Args:
            filters: List of CanonicalFilter objects to write as RoomFit bands.

        Raises:
            WiiMResponseError: RoomFit write not supported (level < 4) or
                device returned an error.
        """
        if self._capabilities.roomfit_level < 4:
            raise WiiMResponseError(
                f"RoomFit write requires roomfit_level >= 4, "
                f"device has level {self._capabilities.roomfit_level}"
            )

        band_array, _warnings = generate_wiim_band_array(filters)

        # Build EQBand parameter array
        eq_band_params: list[dict[str, str | float]] = []
        for i in range(10):
            offset = i * 4
            letter = _BAND_LETTERS[i]
            eq_band_params.append({"param_name": f"{letter}_mode", "value": band_array[offset]})
            eq_band_params.append({"param_name": f"{letter}_freq", "value": band_array[offset + 1]})
            eq_band_params.append({"param_name": f"{letter}_gain", "value": band_array[offset + 2]})
            eq_band_params.append({"param_name": f"{letter}_q", "value": band_array[offset + 3]})

        payload = json.dumps({
            "pluginURI": _PLUGIN_URI,
            "EQBand": eq_band_params,
        })
        command = f"setRoomFitBands:{quote(payload)}"
        await self._client.command(command)
