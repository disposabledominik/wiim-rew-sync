"""
WiiM device adapter — PEQ read and multiroom operations.

Wraps WiiMHttpClient with domain-aware methods that issue the correct LV2 PEQ
commands, parse responses via ``wiim_parser``, and return typed domain objects.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import quote

from src.adapters.wiim_http import WiiMHttpClient
from src.models.canonical import CanonicalFilter
from src.models.capabilities import DeviceCapabilities
from src.models.errors import WiiMConnectionError, WiiMResponseError
from src.models.peq import PEQSettings
from src.translator.wiim_parser import parse_wiim_band_array

logger = logging.getLogger("wiim_rew_sync.wiim_api")

# LV2 plugin URI used by all WiiM PEQ commands
_PLUGIN_URI = "http://moddevices.com/plugins/caps/EqNp"

# Band letters a-j (1-10)
_BAND_LETTERS = "abcdefghij"


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
