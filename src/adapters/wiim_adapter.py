"""
WiiM device adapter — PEQ and RoomFit read/write operations.

Wraps WiiMHttpClient with domain-aware methods that issue the correct LV2 PEQ
commands, parse responses via ``wiim_parser``, and return typed domain objects.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 5.3, 5.4, 17.3
"""

from __future__ import annotations

import asyncio
import logging
import time
from functools import partial
from typing import TYPE_CHECKING, Any

from src.adapters.wiim_commands import (
    PLUGIN_URI,
    encode_wiim_command,
    expect_dict_response,
    expect_list_response,
)
from src.adapters.wiim_http import WiiMHttpClient
from src.models.canonical import CanonicalFilter
from src.models.capabilities import DeviceCapabilities
from src.models.channel_mode import ChannelMode, coerce_channel_mode
from src.models.errors import (
    RoomFitUnsupportedError,
    WiiMResponseError,
)
from src.models.peq import PEQSettings
from src.models.source_slot import SourceSlotInfo
from src.translator.wiim_generator import generate_wiim_band_array
from src.translator.wiim_parser import parse_wiim_band_array

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from src.adapters.command_queue import WiiMCommandQueue

logger = logging.getLogger("wiim_rew_sync.wiim_api")

# Band letters a-l (up to 12 bands on newer firmware; older devices use a-j for 10)
_BAND_LETTERS = "abcdefghijkl"


def _flat_array_to_band_params(
    band_array: list[float], num_bands: int, *, start_band: int = 0
) -> list[dict[str, str | float]]:
    """Convert a flat band array into the WiiM EQBand parameter list format.

    Args:
        band_array: Flat list of [mode, freq, gain, q, mode, freq, ...] values.
        num_bands: Number of bands to extract from the array.
        start_band: Starting band index (0-based) for letter assignment.
            Used when building params for a single band in sequential writes.

    Returns:
        List of {"param_name": "<letter>_<param>", "value": <float>} dicts.
    """
    params: list[dict[str, str | float]] = []
    for i in range(num_bands):
        offset = i * 4
        letter = _BAND_LETTERS[start_band + i]
        params.append({"param_name": f"{letter}_mode", "value": band_array[offset]})
        params.append({"param_name": f"{letter}_freq", "value": band_array[offset + 1]})
        params.append({"param_name": f"{letter}_gain", "value": band_array[offset + 2]})
        params.append({"param_name": f"{letter}_q", "value": band_array[offset + 3]})
    return params


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

    async def raw_command(self, command: str) -> dict[str, Any] | str:
        """Issue an arbitrary httpapi command and return the raw response.

        Escape hatch for the Diagnostics panel's raw-command console. Bypasses
        all PEQ/RoomFit domain parsing — callers get back exactly what
        WiiMHttpClient.command() returns.

        Args:
            command: The WiiM API command string (already URL-encoded if needed).

        Returns:
            Parsed JSON dict, or the raw response text if not valid JSON.

        Raises:
            WiiMTimeoutError: Device did not respond within the timeout window.
            WiiMConnectionError: Device unreachable or connection refused.
            WiiMResponseError: Non-200 HTTP status code.
        """
        return await self._client.command(command)

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
        command = encode_wiim_command("EQGetLV2SourceBandEx", source_name=source_name)

        # WiiMHttpClient.command() raises WiiMConnectionError / WiiMTimeoutError
        # on network failure — let those propagate directly.
        response = await self._client.command(command)
        response = expect_dict_response(response, "EQGetLV2SourceBandEx")

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
            channel_mode=ChannelMode.STEREO,
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
            channel_mode=ChannelMode.LR,
            name=name,
            bands_l=bands_l,
            bands_r=bands_r,
        )

    # ------------------------------------------------------------------
    # PEQ Enable/Disable
    # ------------------------------------------------------------------

    async def _set_fx_state(self, command: str, source_name: str, eq_level: int) -> None:
        """Shared EQChangeSourceFX/EQSourceOff issuer for enable_peq/disable_peq."""
        response = await self._client.command(
            encode_wiim_command(command, source_name=source_name, eq_level=eq_level)
        )
        # WiiM typically returns "OK" or a JSON dict on success.
        # A WiiMResponseError from the HTTP layer (non-200) is raised automatically.
        if self._is_write_rejection(response):
            raise WiiMResponseError(f"{command} failed for source '{source_name}': {response}")

    async def enable_peq(self, source_name: str) -> None:
        """Enable PEQ on a specific source by switching to the LV2 EqNp plugin.

        Issues ``EQChangeSourceFX`` with the source name, plugin URI, and
        ``EQLevel: 1`` (confirmed via real-app traffic).

        Args:
            source_name: The audio input source (e.g. "wifi", "bluetooth").

        Returns:
            None on success.

        Raises:
            WiiMResponseError: Device returned an error response.
            WiiMConnectionError: Device unreachable (propagated from http_client).
        """
        await self._set_fx_state("EQChangeSourceFX", source_name, eq_level=1)

    async def disable_peq(self, source_name: str) -> None:
        """Disable PEQ on a specific source.

        Issues ``EQSourceOff`` with the source name, plugin URI, and
        ``EQLevel: 1`` (confirmed via real-app traffic).

        Args:
            source_name: The audio input source (e.g. "wifi", "bluetooth").

        Returns:
            None on success.

        Raises:
            WiiMResponseError: Device returned an error response.
            WiiMConnectionError: Device unreachable (propagated from http_client).
        """
        await self._set_fx_state("EQSourceOff", source_name, eq_level=1)

    async def set_peq_enabled(self, source_name: str, enabled: bool) -> None:
        """Enable or disable PEQ on a source based on a bool.

        Mirrors ``set_roomfit_enabled()``'s shared branch, for callers
        restoring a captured enable/disable state rather than
        unconditionally turning PEQ on or off.
        """
        if enabled:
            await self.enable_peq(source_name)
        else:
            await self.disable_peq(source_name)

    async def set_peq_enabled_best_effort(
        self, source_name: str, enabled: bool, *, context: str
    ) -> None:
        """Best-effort ``set_peq_enabled()``: logs and swallows a failure
        instead of raising.

        Shared by SafeWrite's success/rollback/undo paths (safe_write.py)
        and read_peq_preset_preview() below, so this try/except/log pattern
        can't independently drift out of sync across call sites the way
        RoomFit's equivalent did before being consolidated into
        restore_roomfit_selection_and_enable_state() (#192).
        """
        try:
            await self.set_peq_enabled(source_name, enabled)
        except Exception:
            logger.warning(
                "Failed to %s PEQ on source '%s' (%s).",
                "enable" if enabled else "disable",
                source_name,
                context,
                exc_info=True,
            )

    # ------------------------------------------------------------------
    # RoomFit Enable/Disable
    # ------------------------------------------------------------------

    async def enable_roomfit(self) -> None:
        """Enable RoomFit's global DSP on/off toggle.

        Issues ``EQChangeSourceFX`` with an explicit empty source name and
        ``EQLevel: 2`` -- the same command pair as ``enable_peq()``, but
        RoomFit's toggle is device-global rather than per-source (see
        docs/wiim_api_notes.md's RoomFit "DSP on/off toggle" section).

        Returns:
            None on success.

        Raises:
            WiiMResponseError: Device returned an error response.
            WiiMConnectionError: Device unreachable (propagated from http_client).
        """
        await self._set_fx_state("EQChangeSourceFX", "", eq_level=2)

    async def disable_roomfit(self) -> None:
        """Disable RoomFit's global DSP on/off toggle.

        Issues ``EQSourceOff`` with an explicit empty source name and
        ``EQLevel: 2`` -- see ``enable_roomfit()``.

        Returns:
            None on success.

        Raises:
            WiiMResponseError: Device returned an error response.
            WiiMConnectionError: Device unreachable (propagated from http_client).
        """
        await self._set_fx_state("EQSourceOff", "", eq_level=2)

    async def set_roomfit_enabled(self, enabled: bool) -> None:
        """Enable or disable RoomFit based on a bool.

        Shared by every RoomFitSafeWrite call site that needs to restore a
        previously-captured on/off state (rather than unconditionally turn
        it on), so that enable/disable branch isn't duplicated at each one.
        """
        if enabled:
            await self.enable_roomfit()
        else:
            await self.disable_roomfit()

    async def _read_fx_status(self, source_name: str, eq_level: int) -> dict[str, Any]:
        """Shared EQGetLV2SourceBandEx issuer for get_peq_enabled/get_roomfit_status/
        read_roomfit."""
        response = await self._client.command(
            encode_wiim_command("EQGetLV2SourceBandEx", source_name=source_name, eq_level=eq_level)
        )
        return expect_dict_response(response, "EQGetLV2SourceBandEx")

    async def get_peq_enabled(self, source_name: str) -> bool:
        """Check whether PEQ is enabled on a specific source.

        Issues ``EQGetLV2SourceBandEx`` with ``EQLevel: 1`` and reads the
        ``EQStat`` field.

        Args:
            source_name: The audio input source (e.g. "wifi", "bluetooth").

        Returns:
            True if PEQ is enabled ("On"), False otherwise ("Off").

        Raises:
            WiiMResponseError: Response missing required fields or non-dict.
            WiiMConnectionError: Device unreachable (propagated from http_client).
        """
        response = await self._read_fx_status(source_name, eq_level=1)
        return bool(response.get("EQStat", "Off") == "On")

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

        Writes bands using the batch path (single ``EQSetLV2SourceBand``) when
        supported, or sequentially via the queue otherwise. ``channelMode`` is
        set inline as part of that same write — confirmed the only reliable
        way to switch it (`docs/wiim_api_notes.md` PEQ "Write" section;
        `EQSetLV2ChannelMode` is confirmed dead on current firmware, see
        `docs/corrections.md`, 2026-07-04).

        Args:
            source_name: Audio input source (e.g. "wifi", "bluetooth").
            settings: PEQ settings containing bands to write.
            queue: Optional command queue for sequential writes.

        Raises:
            WiiMResponseError: Device returned an error response.
            WiiMConnectionError: Device unreachable.
        """

        if settings.channel_mode.is_lr:
            # L/R mode: write both channels independently. No fallback
            # between bands_l/bands_r -- an empty channel is a legitimate
            # device read-state (see _parse_lr()), not a signal to reuse the
            # other channel's bands. A prior version fell back to bands_l
            # when bands_r was empty, which silently copied the left
            # channel's filters into the right channel during rollback
            # (safe_write.py restores an originally-read PEQSettings, which
            # can have a genuinely asymmetric L/R split) -- corrupting the
            # very state recoverability is supposed to restore.
            bands_l = settings.bands_l
            bands_r = settings.bands_r
            band_array_l, _warnings_l = generate_wiim_band_array(
                bands_l, max_bands=self._capabilities.max_filters
            )
            band_array_r, _warnings_r = generate_wiim_band_array(
                bands_r, max_bands=self._capabilities.max_filters
            )
            await self._write_bands(
                partial(
                    self._write_peq_batch,
                    source_name, band_array_l, band_array_r,
                ),
                partial(
                    self._write_peq_sequential,
                    source_name, band_array_l, queue, band_array_r,
                ),
            )
        else:
            # Stereo mode: single band array
            bands = settings.bands
            band_array, _warnings = generate_wiim_band_array(
                bands, max_bands=self._capabilities.max_filters
            )
            await self._write_bands(
                partial(
                    self._write_peq_batch,
                    source_name, band_array,
                ),
                partial(
                    self._write_peq_sequential,
                    source_name, band_array, queue,
                ),
            )

    @staticmethod
    def _is_write_rejection(resp: object) -> bool:
        """True when a write response is an explicit device-side rejection
        ("unknown command" or {"status": "Failed"}) rather than acceptance
        ("OK" string, or a dict on some firmware)."""
        if isinstance(resp, str) and "unknown" in resp.lower():
            return True
        return isinstance(resp, dict) and str(resp.get("status", "")).lower() == "failed"

    async def _write_bands(
        self,
        batch: Callable[[], Awaitable[object]],
        sequential: Callable[[], Awaitable[None]],
    ) -> None:
        """Dispatch a band write to the batch or sequential path.

        ``supports_batch_write`` is tri-state: False skips straight to the
        sequential path. None means "not yet determined" -- there is no
        connect-time write probe anymore (2026-07-10 redesign; the old probe
        performed a real EQSetLV2Band write) -- so the first real push
        attempts the batch form, and on an explicit device-side rejection
        falls back to sequential within the same call, recording the outcome
        on the capabilities object for the rest of the session. True still
        attempts the batch form first, but an explicit rejection is checked
        for regardless of prior state -- a device that previously accepted
        batch writes can start rejecting them (firmware quirk, state change),
        and that's demoted back to False/sequential the same way a first-time
        rejection is, rather than only being caught one round-trip later by
        SafeWrite's read-back verification. Network errors propagate without
        recording anything -- they say nothing about batch support.
        """
        known = self._capabilities.supports_batch_write
        if known is False:
            await sequential()
            return
        resp = await batch()
        if self._is_write_rejection(resp):
            if known is True:
                logger.warning(
                    "Batch PEQ write previously worked but was rejected this "
                    "time (%r); falling back to sequential writes for the "
                    "rest of this session.",
                    resp,
                )
            else:
                logger.info(
                    "Batch PEQ write rejected by device (%r); recording "
                    "supports_batch_write=False and falling back to "
                    "sequential writes.",
                    resp,
                )
            self._capabilities.supports_batch_write = False
            await sequential()
        elif known is None:
            logger.info(
                "Batch PEQ write accepted; recording "
                "supports_batch_write=True."
            )
            self._capabilities.supports_batch_write = True

    async def _write_peq_batch(
        self,
        source_name: str,
        band_array: list[float],
        band_array_r: list[float] | None = None,
    ) -> object:
        """Write all bands in a single EQSetLV2SourceBand payload.

        Stereo when `band_array_r` is None (`band_array` becomes `EQBand`,
        wire `channelMode` "Stereo"); L/R when given (`band_array`/
        `band_array_r` become `EQBandL`/`EQBandR`, wire `channelMode`
        "L/R") -- `band_array_r`'s presence is the sole signal for which
        mode this write is; there is no separate `channel_mode` parameter
        to keep in sync with it.

        Returns the raw device response so _write_bands() can inspect it
        for an explicit rejection when batch capability is still unknown.
        """
        num_bands = self._capabilities.max_filters
        payload: dict[str, object]
        if band_array_r is not None:
            payload = {
                "channelMode": "L/R",
                "EQBandL": _flat_array_to_band_params(band_array, num_bands),
                "EQBandR": _flat_array_to_band_params(band_array_r, num_bands),
            }
        else:
            payload = {
                "channelMode": "Stereo",
                "EQBand": _flat_array_to_band_params(band_array, num_bands),
            }
        command = encode_wiim_command(
            "EQSetLV2SourceBand", payload, source_name=source_name
        )
        return await self._client.command(command)

    async def _write_peq_sequential(
        self,
        source_name: str,
        band_array: list[float],
        queue: WiiMCommandQueue | None,
        band_array_r: list[float] | None = None,
    ) -> None:
        """Write bands one at a time via queue with 100ms inter-command delay.

        Stereo when `band_array_r` is None (one `EQBand` per command, wire
        `channelMode` "Stereo"); L/R when given (one command per band,
        carrying that band's L+R params together as `EQBandL`/`EQBandR`,
        wire `channelMode` "L/R") -- same single-source-of-truth as
        `_write_peq_batch` above, no separate `channel_mode` parameter.

        # TODO (low-priority tech debt): when this write changes the source's
        # channelMode, each call before the last leaves not-yet-sent bands holding
        # whatever was last stored for this (source_name, channelMode) slot --
        # confirmed to be stale/unrelated data, not a default template. Narrow
        # corner case (needs a non-batch device AND a mode switch in the same
        # write); SafeWrite's read-back verification already catches a wrong end
        # state. See docs/corrections.md, 2026-07-04.
        """
        channel_mode = "L/R" if band_array_r is not None else "Stereo"
        num_bands = self._capabilities.max_filters
        for i in range(num_bands):
            payload: dict[str, object]
            if band_array_r is not None:
                payload = {
                    "channelMode": channel_mode,
                    "EQBandL": _flat_array_to_band_params(
                        band_array[i * 4:(i + 1) * 4], 1, start_band=i
                    ),
                    "EQBandR": _flat_array_to_band_params(
                        band_array_r[i * 4:(i + 1) * 4], 1, start_band=i
                    ),
                }
            else:
                payload = {
                    "channelMode": channel_mode,
                    "EQBand": _flat_array_to_band_params(
                        band_array[i * 4:(i + 1) * 4], 1, start_band=i
                    ),
                }
            command = encode_wiim_command(
                "EQSetLV2SourceBand", payload, source_name=source_name
            )

            if queue is not None:
                await queue.enqueue(command)
            else:
                await self._client.command(command)

            # 100ms delay between sequential band writes
            if i < num_bands - 1:
                await asyncio.sleep(0.1)

    # ------------------------------------------------------------------
    # PEQ Profile Management
    # ------------------------------------------------------------------

    async def _fetch_profile_list(self, eq_level: int) -> list[dict[str, str]]:
        """Shared EQv2GetNewList issuer + response parsing for
        list_peq_profiles/list_roomfit_profiles."""
        response = await self._client.command(
            encode_wiim_command("EQv2GetNewList", eq_level=eq_level)
        )
        response = expect_dict_response(response, "EQv2GetNewList")
        return [
            {
                "Name": str(entry.get("Name", "")),
                "channelMode": str(entry.get("channelMode", "")),
                "Type": str(entry.get("Type", "")),
            }
            for entry in response.get("custom", [])
        ]

    async def list_peq_profiles(self, source_name: str) -> list[dict[str, str]]:
        """List PEQ profiles stored on the device.

        Wraps EQv2GetNewList with EQLevel: 1.
        Returns list of dicts with keys: Name, channelMode, Type.
        Requires supports_profile_enumeration capability.

        Args:
            source_name: Audio input source (e.g. "wifi").

        Returns:
            List of profile metadata dicts.

        Raises:
            WiiMResponseError: Device returned unexpected response or
                capability not supported.
        """
        if not self._capabilities.supports_profile_enumeration:
            raise WiiMResponseError(
                "Device does not support profile enumeration "
                "(supports_profile_enumeration is False)"
            )
        return await self._fetch_profile_list(eq_level=1)

    async def save_peq_profile(self, source_name: str, profile_name: str) -> None:
        """Save the currently-active PEQ bands as a named device preset.

        Wraps EQSourceSave. Overwrites if profile_name already exists.

        Args:
            source_name: Audio input source (e.g. "wifi").
            profile_name: Name to save the profile as.

        Raises:
            WiiMResponseError: Device returned an error response.
            WiiMConnectionError: Device unreachable.
        """
        command = encode_wiim_command(
            "EQSourceSave", {"Name": profile_name}, source_name=source_name
        )
        await self._client.command(command)

    async def load_peq_profile(self, source_name: str, profile_name: str) -> None:
        """Load a saved PEQ preset into the live DSP (immediate effect on audio).

        Wraps EQv2SourceLoad.

        Args:
            source_name: Audio input source (e.g. "wifi").
            profile_name: Name of the profile to load.

        Raises:
            WiiMResponseError: Device returned an error response.
            WiiMConnectionError: Device unreachable.
        """
        command = encode_wiim_command(
            "EQv2SourceLoad", {"Name": profile_name}, source_name=source_name
        )
        await self._client.command(command)

    async def read_peq_preset_preview(
        self, source_name: str, preset_name: str
    ) -> PEQSettings:
        """Read a saved PEQ preset's bands, restoring the source's original active
        profile afterward.

        Does NOT make the load invisible -- the device's live audio genuinely
        changes to the previewed preset for the duration of this call; callers
        must get user consent before invoking this (see #166 in the fix plan).

        If the source's original active state has no saved-preset name (e.g.
        raw filters pushed via write_peq without ever being saved as a named
        preset -- the common case for this app's primary push workflow), there
        is no profile name to reload; the original bands are restored directly
        via write_peq() instead so the "then restore what was playing" promise
        in the confirmation dialog holds regardless of how the original state
        got there.

        # ASSUMPTION (#192): load_peq_profile() wraps the same EQv2SourceLoad
        # command RoomFit's equivalent load was hardware-confirmed to
        # sometimes flip EQStat on for (docs/wiim_api_notes.md rule 4). Not
        # independently re-confirmed for PEQ's per-source EQStat -- restoring
        # original.enabled below is a defensive, symmetric precaution, not a
        # hardware-confirmed fix like the RoomFit one.
        """
        original = await self.read_peq(source_name)
        await self.load_peq_profile(source_name, preset_name)
        preview = await self.read_peq(source_name)
        await self.restore_peq_selection_and_enable_state(
            source_name, original, preset_name,
            context=f"after previewing '{preset_name}'",
        )
        return preview

    async def restore_peq_selection_and_enable_state(
        self,
        source_name: str,
        original: PEQSettings,
        current_name: str,
        *,
        context: str,
    ) -> None:
        """Best-effort: re-select the source's original active preset and
        restore its enable-state.

        PEQ twin of ``restore_roomfit_selection_and_enable_state()`` below --
        written once, here, so preview/restore call sites can't drift out of
        sync the way RoomFit's preview and write paths once did (#192). If
        the original state had no saved-preset name (raw filters pushed via
        ``write_peq`` -- the common case for this app's primary push
        workflow), the original bands are written back directly instead.
        Logs and swallows failures rather than raising, since this runs as
        cleanup after the caller's primary operation already completed.
        """
        if original.name != current_name:
            try:
                if original.name:
                    await self.load_peq_profile(source_name, original.name)
                else:
                    await self.write_peq(source_name, original)
            except Exception:
                logger.warning(
                    "Failed to restore original PEQ profile '%s' on source "
                    "'%s' (%s).", original.name or "(unnamed)",
                    source_name, context,
                    exc_info=True,
                )
        await self.set_peq_enabled_best_effort(
            source_name, original.enabled, context=context,
        )

    async def _delete_profile(self, profile_name: str, eq_level: int | None = None) -> None:
        """Shared EQv2Delete issuer for delete_peq_profile/delete_roomfit_profile."""
        await self._client.command(
            encode_wiim_command("EQv2Delete", {"Name": profile_name}, eq_level=eq_level)
        )

    async def delete_peq_profile(self, profile_name: str) -> None:
        """Delete a saved PEQ preset from the device.

        Wraps EQv2Delete.

        Args:
            profile_name: Name of the profile to delete.

        Raises:
            WiiMResponseError: Device returned an error response.
            WiiMConnectionError: Device unreachable.
        """
        await self._delete_profile(profile_name)

    async def delete_roomfit_profile(self, profile_name: str) -> None:
        """Delete a saved RoomFit profile from the device.

        Wraps EQv2Delete with EQLevel: 2, per docs/wiim_api_notes.md — RoomFit
        profile deletion requires this parameter; without it the device
        targets the PEQ-profile namespace instead.

        Args:
            profile_name: Name of the RoomFit profile to delete.

        Raises:
            WiiMResponseError: Device returned an error response.
            WiiMConnectionError: Device unreachable.
        """
        await self._delete_profile(profile_name, eq_level=2)

    # ------------------------------------------------------------------
    # RoomFit
    # ------------------------------------------------------------------

    def _require_roomfit(self, capability: str, operation: str) -> None:
        """Raise RoomFitUnsupportedError if the named RoomFit capability is absent.

        Shared gate for every RoomFit method so the check and error-message
        format live in one place instead of being hand-rolled per method.
        Callers branch on the exception *type*, never the message text
        (docs/corrections.md, 2026-07-10 -- the CLI used to substring-match
        the old ladder-based message, which broke silently when it changed).

        Args:
            capability: "supported" (subsystem present), "read" (band buffer
                readable), or "write" (save confirmed).
            operation: Human-readable operation name for the error message.
        """
        satisfied = {
            "supported": self._capabilities.supports_roomfit,
            "read": self._capabilities.supports_roomfit_read,
            "write": self._capabilities.supports_roomfit_write,
        }[capability]
        if not satisfied:
            raise RoomFitUnsupportedError(
                f"RoomFit {operation} is not supported by this device "
                f"(missing '{capability}' capability)"
            )

    async def get_roomfit_status(self) -> tuple[bool, str]:
        """Read RoomFit's global on/off state and the currently-active profile name.

        Issues ``EQGetLV2SourceBandEx`` with ``EQLevel: 2`` and an explicit
        empty ``source_name`` — this is RoomFit's *global* scope query,
        distinct from ``read_roomfit()``'s per-source buffer read.

        Requires ``supports_roomfit`` in device capabilities.

        Raises:
            RoomFitUnsupportedError: RoomFit not supported by this device.
            WiiMResponseError: Device returned an unexpected response.
        """
        self._require_roomfit("supported", "status")
        response = await self._read_fx_status("", eq_level=2)
        return bool(response.get("EQStat", "Off") == "On"), str(response.get("Name", ""))

    async def load_roomfit_profile(self, profile_name: str) -> None:
        """Load a named RoomFit profile into the API working buffer.

        This is a real, persisted action, not a preview: the buffer adopts
        `profile_name` and any subsequent status read reports it as the
        active/selected profile (docs/wiim_api_notes.md's RoomFit Write
        workflow section). Shared by read_roomfit()'s own load step,
        read_roomfit_preset_preview()'s restore-after step below, and
        RoomFitSafeWrite's restore-previous-active-profile step (#178).
        """
        await self._client.command(
            encode_wiim_command("EQv2SourceLoad", {"Name": profile_name}, eq_level=2)
        )

    async def read_roomfit(
        self, source_name: str, profile_name: str
    ) -> PEQSettings:
        """Read RoomFit bands for a named profile.

        Requires ``supports_roomfit_read`` in device capabilities.

        RoomFit reads return the API working buffer, NOT the DSP-active state.
        We must first load the target profile into the buffer, then read bands.

        Args:
            source_name: Audio input source (e.g. "wifi", "bluetooth"). Not
                included in the RoomFit payloads themselves -- the buffer read
                uses an explicit empty source_name instead (RoomFit is a
                single global buffer, not per-source; see
                docs/wiim_api_notes.md's "source_name & EQLevel Reference") --
                kept here as the source the returned ``PEQSettings`` is
                attributed to.
            profile_name: Name of the RoomFit profile to load and read.

        Returns:
            PEQSettings with parsed bands (stereo or L/R).

        Raises:
            WiiMResponseError: RoomFit read not supported (level < 2) or
                device returned an unexpected response.
        """
        self._require_roomfit("read", "read")

        # Step 1: Load the target profile into the API working buffer
        await self.load_roomfit_profile(profile_name)

        # Step 2: Read bands from the buffer -- the same empty-source_name
        # EQGetLV2SourceBandEx+EQLevel:2 query get_roomfit_status() issues.
        response = await self._read_fx_status("", eq_level=2)

        # Step 3: Parse response using the same logic as PEQ reads
        return self._parse_peq_response(response, source_name)

    async def read_roomfit_preset_preview(
        self, source_name: str, profile_name: str
    ) -> PEQSettings:
        """Read a saved RoomFit profile's bands, restoring the originally-selected
        profile and on/off state afterward.

        # ASSUMPTION (was wrong, now fixed -- #192): this docstring previously
        # claimed reading a profile has no live-audio consequence, since
        # RoomFit's buffer is decoupled from its DSP on/off state. Hardware
        # report confirmed otherwise: EQv2SourceLoad (via load_roomfit_profile,
        # used by read_roomfit() below) can flip EQStat on as an undocumented
        # side effect, same family as #190's EQSourceSave finding. Restoring
        # is not just selection bookkeeping -- it can be a real live-audio
        # safety action, per docs/wiim_api_notes.md rule 4.
        """
        original_enabled, original_name = await self.get_roomfit_status()
        preview = await self.read_roomfit(source_name, profile_name)
        await self.restore_roomfit_selection_and_enable_state(
            original_name,
            original_enabled,
            profile_name,
            context=f"previewing '{profile_name}'",
        )
        return preview

    async def read_preset_preview(
        self, preset_type: str, source_name: str, preset_name: str
    ) -> PEQSettings:
        """Read+preview a preset, dispatching by preset_type.

        Previewing briefly loads the preset onto the device's live DSP and
        restores it after (see #166). Shared by every call site that reads
        a named preset for export/save/copy, which otherwise each
        independently reimplement this dispatch.
        """
        if preset_type == "RoomFit":
            return await self.read_roomfit_preset_preview(source_name, preset_name)
        return await self.read_peq_preset_preview(source_name, preset_name)

    async def restore_roomfit_active_profile(
        self, original_name: str, current_name: str, *, context: str
    ) -> None:
        """Re-select `original_name` as RoomFit's active profile if it
        differs from `current_name`, via `EQv2SourceLoad`.

        Shared by every caller that reads or writes a named RoomFit profile
        and needs to undo the "whichever profile was last loaded/saved
        becomes active" side effect documented in docs/wiim_api_notes.md's
        RoomFit Write workflow section (#175/#178) -- currently
        restore_roomfit_selection_and_enable_state() below and
        RoomFitSafeWrite (src/adapters/safe_write.py), both of which also
        need the on/off-state restore that method adds. Best-effort: logs
        and swallows a failure here rather than raising, since this runs as
        cleanup after the caller's primary operation has already completed.
        """
        if not original_name or original_name == current_name:
            return
        try:
            await self.load_roomfit_profile(original_name)
        except Exception:
            logger.warning(
                "Failed to restore RoomFit active profile '%s' after %s; "
                "device may show '%s' as active instead.",
                original_name,
                context,
                current_name,
                exc_info=True,
            )

    async def restore_roomfit_selection_and_enable_state(
        self,
        active_name: str,
        enabled: bool | None,
        current_name: str,
        *,
        context: str,
    ) -> None:
        """Best-effort: re-select `active_name` (via restore_roomfit_active_profile,
        already a no-op if empty/unchanged) and restore RoomFit's on/off state
        to `enabled` if not None.

        Shared by read_roomfit_preset_preview() above and RoomFitSafeWrite's
        failure/undo paths (safe_write.py) -- written once, here, so the two
        restore sites can't drift out of sync with each other the way
        read_roomfit_preset_preview() and safe_write.py's own copy of this
        logic just did (#192: the preview path restored selection but not
        enable-state).
        """
        await self.restore_roomfit_active_profile(
            active_name, current_name, context=context
        )
        if enabled is not None:
            try:
                await self.set_roomfit_enabled(enabled)
            except Exception:
                logger.warning(
                    "Failed to restore RoomFit enable-state to %s (%s).",
                    "On" if enabled else "Off",
                    context,
                    exc_info=True,
                )

    async def _query_active_output_mode(self) -> str | None:
        """Best-effort read of the device's currently active sound-card output.

        Bare, no-payload GET -- issued fresh before every RoomFit write since the
        active output can change between connect-time capability probing and a
        later push. Externally corroborated (captured traffic from a different
        open-source project, not yet confirmed on this project's own owned
        hardware -- docs/corrections.md, 2026-07-20) that
        ``getActiveSoundCardOutputMode`` returns e.g.
        ``{"mode": "AUDIO_OUTPUT_AUX_MODE", ...}``.

        Never raises: this is advisory input to write_roomfit()'s rc_output
        field, not a required capability check. Any failure -- network error
        or an unsupported command -- is caught and logged; an unusable
        response shape is handled the same way, without raising. Either case
        returns None so the caller omits rc_output entirely rather than
        guessing.

        # ASSUMPTION: the externally-corroborated response shape above
        # (top-level string ``mode`` field) holds on this project's own
        # hardware too -- unconfirmed; see docs/corrections.md, 2026-07-20.
        """
        try:
            resp = expect_dict_response(
                await self._client.command("getActiveSoundCardOutputMode"),
                "getActiveSoundCardOutputMode",
            )
        except Exception:
            logger.info(
                "getActiveSoundCardOutputMode query failed; rc_output will "
                "be omitted from the RoomFit write payload.",
                exc_info=True,
            )
            return None

        mode = resp.get("mode")
        if not isinstance(mode, str) or not mode:
            logger.info(
                "getActiveSoundCardOutputMode returned no usable 'mode' "
                "field (%r); rc_output will be omitted from the RoomFit "
                "write payload.",
                resp,
            )
            return None
        return mode

    async def write_roomfit(
        self,
        source_name: str,
        profile_name: str,
        filters: list[CanonicalFilter],
        channel_mode: str | ChannelMode = ChannelMode.STEREO,
        filters_l: list[CanonicalFilter] | None = None,
        filters_r: list[CanonicalFilter] | None = None,
    ) -> None:
        """Write RoomFit bands to a named profile.

        Requires ``supports_roomfit_read`` in device capabilities --
        deliberately not ``supports_roomfit_write``: there is no write-probe
        at connect time (removed 2026-07-10; the old level-4 probe performed
        a real save with live-audio risk, #190), so a real, SafeWrite-
        protected write attempt here is itself the capability confirmation.
        ``RoomFitSafeWrite.execute()`` sets ``supports_roomfit_write`` on a
        verified-successful write.

        Writes to the API buffer, then saves to the named profile. WARNING:
        the buffer adopts ``profile_name`` as soon as the save succeeds, so a
        bare call to this method always makes ``profile_name`` the
        active/selected profile as reported by a subsequent status read --
        regardless of whether it's new, a different existing profile, or the
        one that was already active. This is no longer something callers
        need to work around: ``RoomFitSafeWrite`` (``src/adapters/
        safe_write.py``) now embraces it as the intended push behavior
        (activate + enable RoomFit on success, restore prior state on
        failure) rather than suppressing it -- see its own docstring.

        Args:
            source_name: Audio input source (e.g. "wifi", "bluetooth"). Not
                included in the RoomFit payloads themselves (see read_roomfit).
            profile_name: Name to save the RoomFit profile as.
            filters: List of CanonicalFilter objects (used for stereo mode).
            channel_mode: ChannelMode enum or string — determines write format.
            filters_l: Left channel filters (required when channel_mode is LR).
            filters_r: Right channel filters (required when channel_mode is LR).

        Raises:
            RoomFitUnsupportedError: RoomFit not readable on this device.
            WiiMResponseError: Device returned an error.
        """
        self._require_roomfit("read", "write")

        num_bands = self._capabilities.max_filters
        mode = coerce_channel_mode(channel_mode)

        band_payload: dict[str, object]
        if mode.is_lr:
            # L/R mode: build EQBandL and EQBandR arrays independently, with
            # no cross-channel fallback and no truthy-emptiness check on
            # filters_l/filters_r -- branch selection depends only on
            # mode.is_lr, matching write_peq()'s design (round-4 review
            # fix). RoomFitSafeWrite.execute()'s rollback path restores an
            # existing_settings.bands_l/bands_r pair read straight off the
            # device, which can legitimately have one empty channel; a
            # truthy check here would silently misroute that restore into
            # the Stereo branch below, writing the wrong channelMode and
            # data instead of restoring the original (asymmetric) state.
            band_array_l, _ = generate_wiim_band_array(
                filters_l or [], max_bands=num_bands
            )
            band_array_r, _ = generate_wiim_band_array(
                filters_r or [], max_bands=num_bands
            )
            eq_band_l = _flat_array_to_band_params(band_array_l, num_bands)
            eq_band_r = _flat_array_to_band_params(band_array_r, num_bands)
            channel_mode_value = "L/R"
            band_payload = {"EQBandL": eq_band_l, "EQBandR": eq_band_r}
        else:
            # Stereo mode: single EQBand array
            band_array, _warnings = generate_wiim_band_array(filters, max_bands=num_bands)
            eq_band_params = _flat_array_to_band_params(band_array, num_bands)
            channel_mode_value = "Stereo"
            band_payload = {"EQBand": eq_band_params}

        # Matches the WiiM app's own write traffic when present; does NOT
        # change the saved profile's Type field (always "Custom" for
        # app-saved profiles regardless -- see the RoomFit "Quirk" note in
        # docs/wiim_api_notes.md and docs/corrections.md 2026-07-04). Queried
        # live via _query_active_output_mode() immediately below rather than
        # hard-coded -- a fixed "AUDIO_OUTPUT_SPEAKER_MODE" is externally
        # corroborated (not project-hardware-confirmed) as wrong on
        # non-Speaker devices (docs/corrections.md, 2026-07-20). Omitted
        # entirely (not defaulted to the old hard-coded value) when the live
        # query fails, is unsupported, or returns an unexpected shape.
        active_output_mode = await self._query_active_output_mode()
        if active_output_mode is None:
            logger.warning(
                "Writing RoomFit profile %r without rc_output -- active "
                "output mode could not be determined (see preceding log "
                "entry for why).",
                profile_name,
            )

        extra_payload: dict[str, object] = {
            "channelMode": channel_mode_value,
            **band_payload,
        }
        if active_output_mode is not None:
            extra_payload["rc_output"] = active_output_mode

        write_command = encode_wiim_command(
            "EQSetLV2SourceBand",
            extra_payload,
            source_name="",
            eq_level=2,
        )

        # Write to buffer -- check for an explicit device-side rejection
        # before proceeding to save, reusing _is_write_rejection() since
        # this is the same EQSetLV2SourceBand command family the PEQ batch
        # write path already checks it against (_write_bands()). Without
        # this, a rejected band write was only caught two round-trips
        # later by RoomFitSafeWrite.execute()'s post-write read-back
        # verification -- not incorrect, just slower to fail. Code-review
        # finding, not a hardware-tested behavior correction -- no
        # corrections.md entry (that ledger is for assumptions that failed
        # against real hardware, not this).
        resp = await self._client.command(write_command)
        if self._is_write_rejection(resp):
            raise WiiMResponseError(f"RoomFit band write rejected by device: {resp!r}")

        # Save buffer to profile
        save_command = encode_wiim_command(
            "EQSourceSave",
            {"Name": profile_name, "UpdateAt": str(int(time.time() * 1000))},
            eq_level=2,
        )
        await self._client.command(save_command)

    async def list_roomfit_profiles(
        self, source_name: str
    ) -> list[dict[str, str]]:
        """List RoomFit profiles on the device.

        Requires ``supports_roomfit`` in device capabilities.

        Args:
            source_name: Audio input source (not used in command, but kept
                for interface consistency with other methods).

        Returns:
            List of dicts with keys: Name, channelMode, Type.

        Raises:
            WiiMResponseError: RoomFit not supported (level < 1) or
                device returned an unexpected response.
        """
        self._require_roomfit("supported", "profile listing")
        return await self._fetch_profile_list(eq_level=2)

    # ------------------------------------------------------------------
    # Source-slot diagnostic (#194 follow-up, docs/wiim_api_notes.md)
    # ------------------------------------------------------------------

    async def get_source_slot_overview(self) -> list[SourceSlotInfo]:
        """Read every live per-source PEQ slot the device currently tracks.

        Issues a bare ``EQGetSourceModes`` -- one call instead of one
        ``EQGetLV2SourceBandEx`` round-trip per source. Read-only: this is a
        diagnostic to surface garbage slots left behind by a comma-joined or
        otherwise invalid ``source_name`` write (docs/smoke_test_issues.md
        #194), not a cleanup tool -- no known command removes a slot once
        written (docs/corrections.md, 2026-07-10), so there is no delete
        path here.

        Rows are filtered to ``pluginURI == EqNp`` (PEQ) -- other plugin
        URIs (e.g. the legacy ``Eq10HP`` graphic-EQ) are not this app's
        domain and are silently skipped. A row whose ``source_name`` isn't
        one of ``capabilities.source_names`` is flagged
        ``is_known_source=False``.

        Returns:
            One SourceSlotInfo per EqNp row, in the order the device
            reported them.

        Raises:
            WiiMResponseError: The response isn't the expected list-of-dicts
                shape (e.g. a generic-LinkPlay device that doesn't support
                this command).
            WiiMConnectionError: Device unreachable (propagated from
                http_client).
        """
        response = expect_list_response(
            await self._client.command("EQGetSourceModes"), "EQGetSourceModes"
        )

        known_sources = set(self._capabilities.source_names)
        slots: list[SourceSlotInfo] = []
        for row in response:
            if not isinstance(row, dict) or row.get("pluginURI") != PLUGIN_URI:
                continue
            source_name = row.get("source_name", "")
            slots.append(
                SourceSlotInfo(
                    source_name=source_name,
                    name=row.get("Name", ""),
                    enabled=row.get("EQStat", "Off") == "On",
                    channel_mode=row.get("channelMode", ""),
                    is_known_source=source_name in known_sources,
                )
            )
        return slots
