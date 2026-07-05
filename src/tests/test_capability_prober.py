"""
Unit tests for the CapabilityProber.

Uses unittest.mock.AsyncMock to mock WiiMHttpClient.command() with canned
fixture responses.

Requirements tested: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock
from urllib.parse import quote, unquote

import pytest

from src.adapters.capability_prober import CapabilityProber
from src.adapters.wiim_commands import PLUGIN_URI
from src.adapters.wiim_http import WiiMHttpClient
from src.models.capabilities import DeviceCapabilities

# ---------------------------------------------------------------------------
# Fixture responses
# ---------------------------------------------------------------------------

STATUS_EX_WIIM_PRO = {
    "DeviceName": "Living Room",
    "uuid": "FF31F09E-1234-5678-ABCD-000000000001",
    "Release": "6.0.1.20",
    "project": "WiiM_Pro",
    "MAC": "AA:BB:CC:DD:EE:FF",
    "InputList": '["wifi","bluetooth","line-in","optical"]',
}

STATUS_EX_WIIM_MINI = {
    "DeviceName": "Bedroom",
    "uuid": "FF31F09E-1234-5678-ABCD-000000000002",
    "Release": "5.5.0.10",
    "project": "WiiM_Mini",
    "MAC": "11:22:33:44:55:66",
    "InputList": '["wifi","bluetooth"]',
}

STATUS_EX_GENERIC_LINKPLAY = {
    "DeviceName": "Kitchen Speaker",
    "uuid": "AABBCCDD-0000-0000-0000-000000000003",
    "Release": "3.2.1.0",
    "project": "UP2STREAM_PRO_V3",
    "MAC": "00:11:22:33:44:55",
    "InputList": '["wifi","line-in"]',
}

EQ_GET_LV2_BAND_RESPONSE = {
    "EQStat": "On",
    "channelMode": "Stereo",
    "EQBand": [
        {"param_name": "a_mode", "value": 1.0},
        {"param_name": "a_freq", "value": 80.0},
        {"param_name": "a_q", "value": 1.41},
        {"param_name": "a_gain", "value": -4.0},
    ] + [
        {"param_name": f"{chr(ord('b') + i)}_mode", "value": -1.0}
        for i in range(9)
    ],
}

EQ_GET_LV2_LIST_RESPONSE = {
    "custom": ["My Preset 1", "My Preset 2"],
    "preset": ["Flat", "Rock"],
}

MULTIROOM_SOLO = {"role": 0}
MULTIROOM_MASTER = {"role": 1}
MULTIROOM_SLAVE = {"role": 2}

# getAudioInputEnable fixture, matching real hardware traffic
# (docs/wiim_api_notes.md, WiiM Amp Ultra-style response) -- "udisk" (a hardware
# capability, not a real PEQ source) never appears in this list at all, and
# "bluetooth"/"optical" are present but disabled (enable: 0).
AUDIO_INPUT_ENABLE_RESPONSE = {
    "ver": "1.0",
    "audioInput": [
        {"mode": "wifi", "enable": 1},
        {"mode": "bluetooth", "enable": 0},
        {"mode": "line-in", "enable": 1},
        {"mode": "optical", "enable": 0},
        {"mode": "HDMI", "enable": 1},
    ],
}

# 12-band fixture response (letters a through l) for dynamic max_filters detection
EQ_GET_LV2_BAND_12_RESPONSE = {
    "EQStat": "On",
    "channelMode": "Stereo",
    "EQBand": [
        {"param_name": f"{chr(ord('a') + i)}_{param}", "value": val}
        for i in range(12)
        for param, val in [("mode", 1.0), ("freq", 100.0 * (i + 1)), ("gain", 0.0), ("q", 1.41)]
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_client() -> WiiMHttpClient:
    """Create a mock WiiMHttpClient with command as AsyncMock."""
    client = AsyncMock(spec=WiiMHttpClient)
    return client


def _encoded_uri() -> str:
    return quote(PLUGIN_URI)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWiiMDeviceDetection:
    """Test that WiiM devices are correctly identified and probed."""

    @pytest.mark.asyncio
    async def test_wiim_pro_detected_correctly(self) -> None:
        """WiiM Pro should be detected as WiiM → supports_peq=True, max_filters=10."""
        client = _make_mock_client()

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd == "getAudioInputEnable":
                return AUDIO_INPUT_ENABLE_RESPONSE
            if cmd.startswith("EQGetLV2BandEx:"):
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQv2GetNewList:"):
                if '"EQLevel": 2' in cmd:
                    # RoomFit profile list (EQLevel:2)
                    return {
                        "custom": [{"Name": "RF1", "channelMode": "Stereo", "Type": "RC"}],
                        "preset": [],
                    }
                # PEQ profile enumeration probe (EQLevel:1)
                return EQ_GET_LV2_LIST_RESPONSE
            if cmd.startswith("EQGetLV2SourceBandEx:"):
                return {"EQStat": "On", "channelMode": "Stereo", "EQBand": [
                    {"param_name": "a_mode", "value": 1.0},
                    {"param_name": "a_freq", "value": 80.0},
                    {"param_name": "a_q", "value": 1.41},
                    {"param_name": "a_gain", "value": -4.0},
                ]}
            if cmd.startswith("EQSetLV2SourceBand:"):
                return "OK"
            if cmd.startswith("EQSourceSave:"):
                return "OK"
            if cmd.startswith("EQv2Delete:"):
                return "OK"
            if cmd == "GetMultiroomInfo":
                return MULTIROOM_SOLO
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_peq is True
        assert caps.max_filters == 10
        assert caps.model == "WiiM_Pro"
        assert caps.firmware == "6.0.1.20"
        assert caps.uuid == "FF31F09E-1234-5678-ABCD-000000000001"
        assert caps.mac_address == "AA:BB:CC:DD:EE:FF"
        # Only enable:1 entries surface as source_names -- "bluetooth"/"optical"
        # are present but disabled in the fixture, matching real hardware traffic.
        assert caps.source_names == ["wifi", "line-in", "HDMI"]
        assert caps.supports_lr_filters is True
        assert caps.supports_batch_write is True
        assert caps.supports_profile_enumeration is True
        assert caps.role == "solo"

    @pytest.mark.asyncio
    async def test_batch_write_probe_restores_active_preset(self) -> None:
        """#177: the batch-write probe reads the live source's bands then
        writes them back unchanged via the bare EQSetLV2Band -- confirmed on
        real hardware that this raw write drops the live source's "this
        equals saved preset X" Name association even with byte-identical
        bands (docs/corrections.md 2026-07-05), the same mechanism as #175's
        RoomFit probe fix. The probe must restore the pre-probe Name via
        EQv2SourceLoad, scoped to the source_name the read itself echoed
        back (PEQ's EQv2SourceLoad requires an explicit source_name)."""
        client = _make_mock_client()
        calls: list[str] = []

        live_band_response = {
            "EQStat": "On",
            "channelMode": "Stereo",
            "Name": "M16",
            "source_name": "HDMI",
            "EQBand": [
                {"param_name": "a_mode", "value": 1.0},
                {"param_name": "a_freq", "value": 80.0},
                {"param_name": "a_q", "value": 1.41},
                {"param_name": "a_gain", "value": -4.0},
            ],
        }

        async def mock_command(cmd: str) -> dict | str:
            calls.append(cmd)
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd == "getAudioInputEnable":
                return AUDIO_INPUT_ENABLE_RESPONSE
            if cmd.startswith("EQGetLV2BandEx:"):
                return live_band_response
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQv2SourceLoad:"):
                return "OK"
            if cmd.startswith("EQv2GetNewList:"):
                return "unknown command"
            if cmd.startswith("EQGetLV2SourceBandEx:"):
                return "unknown command"
            if cmd == "GetMultiroomInfo":
                return MULTIROOM_SOLO
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_batch_write is True

        load_calls = [c for c in calls if c.startswith("EQv2SourceLoad:")]
        assert len(load_calls) == 1, "Probe must restore the pre-probe active preset"
        payload = json.loads(unquote(load_calls[0].split(":", 1)[1]))
        assert payload["Name"] == "M16"
        assert payload["source_name"] == "HDMI"
        # Restore must happen AFTER the write-back, not before.
        write_index = next(i for i, c in enumerate(calls) if c.startswith("EQSetLV2Band:"))
        load_index = next(i for i, c in enumerate(calls) if c.startswith("EQv2SourceLoad:"))
        assert write_index < load_index

    @pytest.mark.asyncio
    async def test_batch_write_probe_skips_restore_when_no_prior_active_name(
        self,
    ) -> None:
        """#177: if the live source's buffer had no name before the probe ran
        (e.g. raw/unsaved filters, never loaded from a preset), there's
        nothing to restore -- the probe must not issue a spurious
        EQv2SourceLoad."""
        client = _make_mock_client()
        calls: list[str] = []

        live_band_response = {
            "EQStat": "On",
            "channelMode": "Stereo",
            "Name": "",
            "source_name": "wifi",
            "EQBand": [
                {"param_name": "a_mode", "value": 1.0},
                {"param_name": "a_freq", "value": 80.0},
                {"param_name": "a_q", "value": 1.41},
                {"param_name": "a_gain", "value": -4.0},
            ],
        }

        async def mock_command(cmd: str) -> dict | str:
            calls.append(cmd)
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd == "getAudioInputEnable":
                return AUDIO_INPUT_ENABLE_RESPONSE
            if cmd.startswith("EQGetLV2BandEx:"):
                return live_band_response
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQv2SourceLoad:"):
                return "OK"
            if cmd.startswith("EQv2GetNewList:"):
                return "unknown command"
            if cmd.startswith("EQGetLV2SourceBandEx:"):
                return "unknown command"
            if cmd == "GetMultiroomInfo":
                return MULTIROOM_SOLO
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_batch_write is True
        load_calls = [c for c in calls if c.startswith("EQv2SourceLoad:")]
        assert load_calls == []

    @pytest.mark.asyncio
    async def test_malformed_dict_response_not_treated_as_enumeration_support(
        self,
    ) -> None:
        """#170: a dict response missing both 'status' AND the real success
        shape's 'custom'/'preset' keys must not be treated as enumeration
        support -- only rejecting a 'status' key (not requiring the real
        shape) would silently re-admit this exact false-positive class."""
        client = _make_mock_client()

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd == "getAudioInputEnable":
                return AUDIO_INPUT_ENABLE_RESPONSE
            if cmd.startswith("EQGetLV2BandEx:"):
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQv2GetNewList:"):
                # Malformed dict: no "status" key, but also no "custom"/"preset"
                return {"unexpected": "shape"}
            if cmd == "GetMultiroomInfo":
                return MULTIROOM_SOLO
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_profile_enumeration is False

    @pytest.mark.asyncio
    async def test_wiim_mini_detected_correctly(self) -> None:
        """WiiM Mini should be detected as WiiM with PEQ but no RoomFit."""
        client = _make_mock_client()

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_MINI
            if cmd.startswith("EQGetLV2BandEx:"):
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQv2GetNewList:"):
                return "unknown command"
            if cmd == "GetMultiroomInfo":
                return MULTIROOM_SOLO
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_peq is True
        assert caps.max_filters == 10
        assert caps.model == "WiiM_Mini"
        assert caps.roomfit_level == 0
        assert caps.supports_roomfit is False
        assert caps.supports_roomfit_read is False
        assert caps.supports_roomfit_write is False
        # Mini has no getAudioInputEnable ("unknown command" via the fallback
        # branch above) -- source_names ends up whatever the bundled
        # device_capabilities.json's WiiM_Mini entry provides via merge_into()
        # (#167), not asserted here since that's this test's model's own data,
        # not this probe step's behavior.

    @pytest.mark.asyncio
    async def test_get_audio_input_enable_malformed_response_degrades_gracefully(
        self,
    ) -> None:
        """A non-dict, non-'unknown command' getAudioInputEnable response is
        ignored, leaving source_names empty out of _probe_source_names itself
        -- merge_into()'s DEFAULT_SOURCE_NAMES fallback (#167b) then fills it
        in with the generic list, same as any other source-enumeration
        failure, rather than raising."""
        from src.models.constants import DEFAULT_SOURCE_NAMES

        client = _make_mock_client()

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd == "getAudioInputEnable":
                return "not a dict or a recognised error string"
            if cmd == "GetMultiroomInfo":
                return MULTIROOM_SOLO
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.source_names == list(DEFAULT_SOURCE_NAMES)


class TestGenericLinkPlayDefaults:
    """Test that generic LinkPlay devices get conservative defaults."""

    @pytest.mark.asyncio
    async def test_generic_linkplay_returns_conservative_defaults(self) -> None:
        """Generic LinkPlay device → max_filters=0, supports_peq=False."""
        client = _make_mock_client()

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return STATUS_EX_GENERIC_LINKPLAY
            if cmd == "GetMultiroomInfo":
                return MULTIROOM_SOLO
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_peq is False
        assert caps.max_filters == 0
        assert caps.model == "UP2STREAM_PRO_V3"
        assert caps.supports_lr_filters is False
        assert caps.supports_batch_write is False
        assert caps.supports_profile_enumeration is False
        assert caps.roomfit_level == 0
        assert caps.role == "solo"


class TestConnectionFailure:
    """Test that connection failures return all-conservative capabilities."""

    @pytest.mark.asyncio
    async def test_connection_failure_returns_all_false(self) -> None:
        """Complete connection failure → all-conservative DeviceCapabilities."""
        client = _make_mock_client()
        client.command = AsyncMock(side_effect=ConnectionError("Device unreachable"))

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_peq is False
        assert caps.max_filters == 0
        assert caps.supports_lr_filters is False
        assert caps.supports_batch_write is False
        assert caps.supports_profile_enumeration is False
        assert caps.roomfit_level == 0
        assert caps.supports_roomfit is False
        assert caps.supports_roomfit_read is False
        assert caps.supports_roomfit_write is False
        assert caps.role == "solo"
        assert caps.model == ""

    @pytest.mark.asyncio
    async def test_timeout_on_status_returns_defaults(self) -> None:
        """Timeout on getStatusEx → defaults with empty model."""
        from src.models.errors import WiiMTimeoutError

        client = _make_mock_client()
        client.command = AsyncMock(side_effect=WiiMTimeoutError("Timed out"))

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.model == ""
        assert caps.supports_peq is False
        assert caps.max_filters == 0


class TestRoomFitLevelDetection:
    """Test RoomFit level probing using real API commands (EQLevel: 2).

    RoomFit uses standard LV2 PEQ commands with EQLevel: 2 in the payload.
    See docs/corrections.md 2026-06-14 for context.
    """

    @pytest.mark.asyncio
    async def test_roomfit_level_4_full_support(self) -> None:
        """Device with full RoomFit support → level 4."""
        client = _make_mock_client()
        calls: list[str] = []

        roomfit_band_response = {
            "EQStat": "On",
            "channelMode": "Stereo",
            "Name": "My RoomFit",
            "EQBand": [
                {"param_name": "a_mode", "value": 1.0},
                {"param_name": "a_freq", "value": 80.0},
                {"param_name": "a_q", "value": 1.41},
                {"param_name": "a_gain", "value": -4.0},
            ],
        }

        async def mock_command(cmd: str) -> dict | str:
            calls.append(cmd)
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd.startswith("EQGetLV2BandEx:"):
                # PEQ probe (no EQLevel) vs RoomFit probe (EQLevel: 2)
                if "EQLevel" in cmd:
                    return roomfit_band_response
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQSetLV2SourceBand:"):
                return "OK"
            if cmd.startswith("EQv2GetNewList:"):
                if '"EQLevel": 2' in cmd:
                    return {
                        "custom": [
                            {"Name": "My RoomFit", "channelMode": "Stereo", "Type": "RC"}
                        ],
                        "preset": [],
                    }
                return EQ_GET_LV2_LIST_RESPONSE
            if cmd.startswith("EQGetLV2SourceBandEx:"):
                if "EQLevel" in cmd:
                    return roomfit_band_response
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSourceSave:"):
                return "OK"
            if cmd.startswith("EQv2Delete:"):
                return "OK"
            if cmd.startswith("EQChangeSourceFX:"):
                return "OK"
            if cmd.startswith("EQSourceOff:"):
                return "OK"
            if cmd == "GetMultiroomInfo":
                return MULTIROOM_SOLO
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.roomfit_level == 4
        assert caps.supports_roomfit is True
        assert caps.supports_roomfit_read is True
        assert caps.supports_roomfit_write is True

        # #190: the pre-probe EQStat ("On") must be explicitly restored via
        # EQChangeSourceFX, not left at whatever the level-4 write test left it.
        fx_calls = [c for c in calls if c.startswith("EQChangeSourceFX:")]
        assert len(fx_calls) == 1
        assert [c for c in calls if c.startswith("EQSourceOff:")] == []

    @pytest.mark.asyncio
    async def test_roomfit_level_4_probe_restores_active_profile(self) -> None:
        """#177: the level-4 write test saves the buffer under a throwaway
        name then deletes it -- the buffer "adopts" whatever name it's saved
        under, so deleting that same name orphans it from whatever profile
        was genuinely active before the probe ran (confirmed on real
        hardware: EQStat stays "On" but Name comes back "" afterward, and the
        WiiM app itself shows RoomFit as deselected). The probe must restore
        the pre-probe active name via EQv2SourceLoad once cleanup is done."""
        client = _make_mock_client()
        calls: list[str] = []

        roomfit_band_response = {
            "EQStat": "On",
            "channelMode": "Stereo",
            "Name": "Lođa zatvorena REW",
            "EQBand": [
                {"param_name": "a_mode", "value": 1.0},
                {"param_name": "a_freq", "value": 80.0},
                {"param_name": "a_q", "value": 1.41},
                {"param_name": "a_gain", "value": -4.0},
            ],
        }

        async def mock_command(cmd: str) -> dict | str:
            calls.append(cmd)
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd.startswith("EQGetLV2BandEx:"):
                if "EQLevel" in cmd:
                    return roomfit_band_response
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQv2GetNewList:"):
                if '"EQLevel": 2' in cmd:
                    return {
                        "custom": [
                            {
                                "Name": "Lođa zatvorena REW",
                                "channelMode": "Stereo",
                                "Type": "RC",
                            }
                        ],
                        "preset": [],
                    }
                return EQ_GET_LV2_LIST_RESPONSE
            if cmd.startswith("EQGetLV2SourceBandEx:"):
                if "EQLevel" in cmd:
                    return roomfit_band_response
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSourceSave:"):
                return "OK"
            if cmd.startswith("EQv2Delete:"):
                return "OK"
            if cmd.startswith("EQv2SourceLoad:"):
                return "OK"
            if cmd.startswith("EQChangeSourceFX:"):
                return "OK"
            if cmd.startswith("EQSourceOff:"):
                return "OK"
            if cmd == "GetMultiroomInfo":
                return MULTIROOM_SOLO
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.roomfit_level == 4

        load_calls = [c for c in calls if c.startswith("EQv2SourceLoad:")]
        assert len(load_calls) == 1, "Probe must restore the pre-probe active profile"
        payload = json.loads(unquote(load_calls[0].split(":", 1)[1]))
        assert payload["Name"] == "Lođa zatvorena REW"
        # Restore must happen AFTER the temp probe profile is deleted, not before.
        save_index = next(i for i, c in enumerate(calls) if c.startswith("EQSourceSave:"))
        delete_index = next(i for i, c in enumerate(calls) if c.startswith("EQv2Delete:"))
        load_index = next(i for i, c in enumerate(calls) if c.startswith("EQv2SourceLoad:"))
        assert delete_index < load_index

        # #190: pre-probe EQStat ("On") must also be explicitly restored --
        # and, since RoomFit applies whatever profile is selected to live
        # audio as soon as it's enabled, this is a live-audio safety
        # ordering, not just cleanup housekeeping: the restore must fire
        # immediately after the save, *before* the delete/name-restore
        # round-trips, to minimize how long an unknown filter could be
        # audible if the save flips EQStat on as a side effect.
        fx_calls = [c for c in calls if c.startswith("EQChangeSourceFX:")]
        assert len(fx_calls) == 1
        assert [c for c in calls if c.startswith("EQSourceOff:")] == []
        fx_index = next(i for i, c in enumerate(calls) if c.startswith("EQChangeSourceFX:"))
        assert save_index < fx_index < delete_index

    @pytest.mark.asyncio
    async def test_roomfit_level_4_probe_skips_restore_when_no_prior_active_name(
        self,
    ) -> None:
        """#177: if the buffer had no name before the probe ran (e.g. a fresh
        device with no saved RoomFit profiles yet), there's nothing to
        restore -- the probe must not issue a spurious EQv2SourceLoad.

        #190: this is also the exact shape of a real regression report --
        a device with RoomFit originally *disabled* (EQStat "Off") came back
        with RoomFit enabled after nothing more than a routine capability
        probe, because the level-4 write test's save-then-delete sequence
        only restored the pre-probe active Name, never the pre-probe on/off
        state. The probe must issue an explicit EQSourceOff to put RoomFit
        back in the "Off" state it found."""
        client = _make_mock_client()
        calls: list[str] = []

        roomfit_band_response = {
            "EQStat": "Off",
            "channelMode": "Stereo",
            "Name": "",
            "EQBand": [
                {"param_name": "a_mode", "value": -1.0},
            ],
        }

        async def mock_command(cmd: str) -> dict | str:
            calls.append(cmd)
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd.startswith("EQGetLV2BandEx:"):
                if "EQLevel" in cmd:
                    return roomfit_band_response
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQv2GetNewList:"):
                if '"EQLevel": 2' in cmd:
                    return {"custom": [], "preset": []}
                return EQ_GET_LV2_LIST_RESPONSE
            if cmd.startswith("EQGetLV2SourceBandEx:"):
                if "EQLevel" in cmd:
                    return roomfit_band_response
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSourceSave:"):
                return "OK"
            if cmd.startswith("EQv2Delete:"):
                return "OK"
            if cmd.startswith("EQv2SourceLoad:"):
                return "OK"
            if cmd.startswith("EQChangeSourceFX:"):
                return "OK"
            if cmd.startswith("EQSourceOff:"):
                return "OK"
            if cmd == "GetMultiroomInfo":
                return MULTIROOM_SOLO
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.roomfit_level == 4
        load_calls = [c for c in calls if c.startswith("EQv2SourceLoad:")]
        assert load_calls == []

        # #190: EQStat must be put back to "Off" via an explicit EQSourceOff,
        # not left however the level-4 write test happened to leave it. And,
        # since RoomFit's DSP toggle gates whether the selected profile's
        # (here unknown/possibly extreme) filters are actually applied to
        # live playback, this restore is a safety-critical ordering: it must
        # fire immediately after the save, before the delete round-trip,
        # rather than being the last thing cleanup gets around to.
        off_calls = [c for c in calls if c.startswith("EQSourceOff:")]
        assert len(off_calls) == 1
        assert [c for c in calls if c.startswith("EQChangeSourceFX:")] == []
        save_index = next(i for i, c in enumerate(calls) if c.startswith("EQSourceSave:"))
        off_index = next(i for i, c in enumerate(calls) if c.startswith("EQSourceOff:"))
        delete_index = next(i for i, c in enumerate(calls) if c.startswith("EQv2Delete:"))
        assert save_index < off_index < delete_index

    @pytest.mark.asyncio
    async def test_roomfit_level_4_probe_skipped_when_disabled_with_selected_profile(
        self,
    ) -> None:
        """#190: the actual reported-regression shape -- RoomFit disabled
        (EQStat "Off") but a named profile ("DangerDanger") is still
        selected underneath, per the WiiM Home app's own behavior (a profile
        stays selected while disabled -- docs/wiim_api_notes.md). What's
        applied to live audio when RoomFit is enabled is that selected,
        persisted profile's real filter values, not the transient working
        buffer -- so if EQSourceSave's undocumented side effect can flip
        EQStat to "On", the only way to guarantee "DangerDanger"'s unknown,
        possibly-extreme filters never become briefly audible is to never
        attempt the live write test in this state at all. The probe must
        skip level 4 entirely (no EQSourceSave, no EQv2Delete, no toggle
        commands) and stay at level 3."""
        client = _make_mock_client()
        calls: list[str] = []

        roomfit_band_response = {
            "EQStat": "Off",
            "channelMode": "Stereo",
            "Name": "DangerDanger",
            "EQBand": [
                {"param_name": "a_mode", "value": 1.0},
                {"param_name": "a_freq", "value": 80.0},
                {"param_name": "a_q", "value": 1.41},
                {"param_name": "a_gain", "value": 12.0},
            ],
        }

        async def mock_command(cmd: str) -> dict | str:
            calls.append(cmd)
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd.startswith("EQGetLV2BandEx:"):
                if "EQLevel" in cmd:
                    return roomfit_band_response
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQv2GetNewList:"):
                if '"EQLevel": 2' in cmd:
                    return {
                        "custom": [
                            {"Name": "DangerDanger", "channelMode": "Stereo", "Type": "RC"}
                        ],
                        "preset": [],
                    }
                return EQ_GET_LV2_LIST_RESPONSE
            if cmd.startswith("EQGetLV2SourceBandEx:"):
                if "EQLevel" in cmd:
                    return roomfit_band_response
                return EQ_GET_LV2_BAND_RESPONSE
            # EQSourceSave/EQv2Delete/EQv2SourceLoad/EQChangeSourceFX/
            # EQSourceOff deliberately have no success case here -- the
            # probe must never call any of them in this scenario, so if it
            # does, the "unknown command" fallback below makes that visible
            # via caps rather than the test accidentally validating a
            # broken guard.
            if cmd == "GetMultiroomInfo":
                return MULTIROOM_SOLO
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.roomfit_level == 3
        assert caps.supports_roomfit_write is False
        assert caps.supports_roomfit_read is True

        for prefix in (
            "EQSourceSave:",
            "EQv2Delete:",
            "EQv2SourceLoad:",
            "EQChangeSourceFX:",
            "EQSourceOff:",
        ):
            assert [c for c in calls if c.startswith(prefix)] == [], (
                f"{prefix} must never be issued when RoomFit is disabled "
                "with a real profile selected"
            )

    @pytest.mark.asyncio
    async def test_roomfit_level_2_read_only(self) -> None:
        """Device where RoomFit read works but save fails → level 3 (parseable)."""
        client = _make_mock_client()

        roomfit_band_response = {
            "EQStat": "On",
            "channelMode": "Stereo",
            "EQBand": [
                {"param_name": "a_mode", "value": 1.0},
                {"param_name": "a_freq", "value": 80.0},
                {"param_name": "a_q", "value": 1.41},
                {"param_name": "a_gain", "value": -4.0},
            ],
        }

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd.startswith("EQGetLV2BandEx:"):
                if "EQLevel" in cmd:
                    return roomfit_band_response
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQv2GetNewList:"):
                if '"EQLevel": 2' in cmd:
                    return {"custom": [], "preset": []}
                return EQ_GET_LV2_LIST_RESPONSE
            if cmd.startswith("EQGetLV2SourceBandEx:"):
                if "EQLevel" in cmd:
                    return roomfit_band_response
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSourceSave:"):
                # Save fails for RoomFit → level 4 not reached
                return "unknown command"
            if cmd == "GetMultiroomInfo":
                return MULTIROOM_SOLO
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        # Level 3 because bands are parseable (dict with EQBand key)
        # but write returned "unknown command"
        assert caps.roomfit_level == 3
        assert caps.supports_roomfit is True
        assert caps.supports_roomfit_read is True
        assert caps.supports_roomfit_write is False

    @pytest.mark.asyncio
    async def test_roomfit_level_1_status_only(self) -> None:
        """Device where EQv2GetNewList succeeds but band read fails → level 1."""
        client = _make_mock_client()

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd.startswith("EQGetLV2BandEx:"):
                if "EQLevel" in cmd:
                    # Band read fails — returns non-dict
                    return "unknown command"
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQv2GetNewList:"):
                if '"EQLevel": 2' in cmd:
                    return {"custom": [], "preset": []}
                return EQ_GET_LV2_LIST_RESPONSE
            if cmd.startswith("EQGetLV2SourceBandEx:"):
                if "EQLevel" in cmd:
                    # Returns non-dict (level 2 fails)
                    return "error"
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd == "GetMultiroomInfo":
                return MULTIROOM_SOLO
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.roomfit_level == 1
        assert caps.supports_roomfit is True
        assert caps.supports_roomfit_read is False
        assert caps.supports_roomfit_write is False

    @pytest.mark.asyncio
    async def test_roomfit_level_0_no_support(self) -> None:
        """Device where EQv2GetNewList returns 'unknown command' → level 0."""
        client = _make_mock_client()

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd.startswith("EQGetLV2BandEx:"):
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQv2GetNewList:"):
                return "unknown command"
            if cmd == "GetMultiroomInfo":
                return MULTIROOM_SOLO
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.roomfit_level == 0
        assert caps.supports_roomfit is False


class TestMultiroomRoleDetection:
    """Test multiroom role detection from GetMultiroomInfo."""

    @pytest.mark.asyncio
    async def test_solo_role(self) -> None:
        """Device in solo mode → role='solo'."""
        client = _make_mock_client()

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd.startswith("EQGetLV2BandEx:"):
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQv2GetNewList:"):
                return "unknown command"
            if cmd == "GetMultiroomInfo":
                return {"role": 0}
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()
        assert caps.role == "solo"

    @pytest.mark.asyncio
    async def test_master_role(self) -> None:
        """Device as master → role='master'."""
        client = _make_mock_client()

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd.startswith("EQGetLV2BandEx:"):
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQv2GetNewList:"):
                return "unknown command"
            if cmd == "GetMultiroomInfo":
                return {"role": 1}
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()
        assert caps.role == "master"

    @pytest.mark.asyncio
    async def test_slave_role(self) -> None:
        """Device as slave → role='slave'."""
        client = _make_mock_client()

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd.startswith("EQGetLV2BandEx:"):
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQv2GetNewList:"):
                return "unknown command"
            if cmd == "GetMultiroomInfo":
                return {"role": 2}
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()
        assert caps.role == "slave"

    @pytest.mark.asyncio
    async def test_multiroom_probe_failure_defaults_to_solo(self) -> None:
        """GetMultiroomInfo failure → role='solo'."""
        client = _make_mock_client()

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd.startswith("EQGetLV2BandEx:"):
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQv2GetNewList:"):
                return "unknown command"
            if cmd == "GetMultiroomInfo":
                raise ConnectionError("Network error")
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()
        assert caps.role == "solo"


class TestDynamicMaxFilters:
    """Test dynamic max_filters detection from EQGetLV2BandEx band count."""

    @pytest.mark.asyncio
    async def test_12_band_response_capped_to_10_by_default(self) -> None:
        """Device reporting 12 bands (a-l) with no capability-file override
        for its model is still capped to the 10-band default (Requirement 7).
        """
        client = _make_mock_client()

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd.startswith("EQGetLV2BandEx:"):
                return EQ_GET_LV2_BAND_12_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQv2GetNewList:"):
                return "unknown command"
            if cmd == "GetMultiroomInfo":
                return MULTIROOM_SOLO
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_peq is True
        assert caps.max_filters == 10

    @pytest.mark.asyncio
    async def test_12_band_response_not_capped_with_file_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A model whose capability-file entry raises max_bands keeps the
        full probed band count instead of the 10-band default (Requirement 7).

        Uses a synthetic capability-file entry (rather than asserting on the
        bundled file's actual shipped values, which may be tuned over time)
        to test the override mechanism itself in isolation.
        """
        from src.models.device_capability_file import CapabilityFileEntry, LoadedCapabilityFile

        monkeypatch.setattr(
            "src.adapters.capability_prober.get_cached_capability_file",
            lambda: LoadedCapabilityFile(
                entries={"WiiM_Amp_Ultra": CapabilityFileEntry(max_bands=12)},
                default_max_bands=10,
            ),
        )

        client = _make_mock_client()
        status_amp_ultra = dict(STATUS_EX_WIIM_PRO, project="WiiM_Amp_Ultra")

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return status_amp_ultra
            if cmd.startswith("EQGetLV2BandEx:"):
                return EQ_GET_LV2_BAND_12_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQv2GetNewList:"):
                return "unknown command"
            if cmd == "GetMultiroomInfo":
                return MULTIROOM_SOLO
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_peq is True
        assert caps.max_filters == 12

    @pytest.mark.asyncio
    async def test_10_band_response_sets_max_filters_10(self) -> None:
        """Device with 10 bands (a-j) in response → max_filters=10."""
        client = _make_mock_client()

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd.startswith("EQGetLV2BandEx:"):
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQv2GetNewList:"):
                return "unknown command"
            if cmd == "GetMultiroomInfo":
                return MULTIROOM_SOLO
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_peq is True
        assert caps.max_filters == 10

    @pytest.mark.asyncio
    async def test_empty_eqband_defaults_to_10(self) -> None:
        """Device with empty EQBand list → max_filters defaults to 10."""
        client = _make_mock_client()

        empty_band_response = {
            "EQStat": "On",
            "channelMode": "Stereo",
            "EQBand": [],
        }

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd.startswith("EQGetLV2BandEx:"):
                return empty_band_response
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQv2GetNewList:"):
                return "unknown command"
            if cmd == "GetMultiroomInfo":
                return MULTIROOM_SOLO
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_peq is True
        assert caps.max_filters == 10


class TestProbeNeverRaises:
    """Verify that probe() never raises, regardless of failure mode."""

    @pytest.mark.asyncio
    async def test_probe_with_all_exceptions_never_raises(self) -> None:
        """Even with exotic exceptions, probe() returns DeviceCapabilities."""
        client = _make_mock_client()
        client.command = AsyncMock(side_effect=RuntimeError("Unexpected error"))

        prober = CapabilityProber(client)
        # Should NOT raise
        caps = await prober.probe()
        assert isinstance(caps, DeviceCapabilities)

    @pytest.mark.asyncio
    async def test_probe_with_non_dict_getstatusex(self) -> None:
        """getStatusEx returning a string → conservative defaults."""
        client = _make_mock_client()

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return "OK"  # Non-dict
            if cmd == "GetMultiroomInfo":
                return MULTIROOM_SOLO
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        # Empty model → not recognised as WiiM → conservative defaults
        assert caps.model == ""
        assert caps.supports_peq is False
        assert caps.max_filters == 0


# ---------------------------------------------------------------------------
# Test: Muzo_Mini recognition (hardware validation findings)
# ---------------------------------------------------------------------------

STATUS_EX_MUZO_MINI = {
    "DeviceName": "Kitchen",
    "uuid": "FF31F09E-1234-5678-ABCD-000000000099",
    "Release": "5.2.0.5",
    "project": "Muzo_Mini",
    "MAC": "AA:BB:CC:DD:EE:01",
    "InputList": '["wifi","bluetooth"]',
}


class TestMuzoMiniRecognition:
    """Hardware validation: Muzo_Mini is recognised as a WiiM device with PEQ."""

    @pytest.mark.asyncio
    async def test_muzo_mini_recognised_as_wiim(self) -> None:
        """getStatusEx returning project='Muzo_Mini' → supports_peq=True, max_filters > 0."""
        client = _make_mock_client()

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return STATUS_EX_MUZO_MINI
            if cmd.startswith("EQGetLV2BandEx:"):
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQv2GetNewList:"):
                return "unknown command"
            if cmd == "GetMultiroomInfo":
                return MULTIROOM_SOLO
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_peq is True
        assert caps.max_filters > 0
        assert caps.model == "Muzo_Mini"


# ---------------------------------------------------------------------------
# Test: RoomFit probe does not send EQSetLV2SourceBand (hardware testing regression)
# ---------------------------------------------------------------------------


class TestRoomFitProbeNoSourceBandWrite:
    """Verify the RoomFit probe doesn't issue EQSetLV2SourceBand.

    The original implementation tried to write bands back as part of the level 4
    probe, which could hit HTTP 431 (request header too large) on 12-band L/R
    devices. The fix uses only EQSourceSave to test write capability.
    """

    @pytest.mark.asyncio
    async def test_roomfit_probe_does_not_send_eqsetlv2sourceband(self) -> None:
        """12-band L/R RoomFit device: _probe_roomfit does NOT issue EQSetLV2SourceBand."""
        client = _make_mock_client()

        # 12-band L/R roomfit response
        letters = "abcdefghijkl"
        bands_l: list[dict[str, str | float]] = []
        bands_r: list[dict[str, str | float]] = []
        for i, letter in enumerate(letters):
            bands_l.extend([
                {"param_name": f"{letter}_mode", "value": 1.0},
                {"param_name": f"{letter}_freq", "value": 100.0 * (i + 1)},
                {"param_name": f"{letter}_q", "value": 1.41},
                {"param_name": f"{letter}_gain", "value": -2.0},
            ])
            bands_r.extend([
                {"param_name": f"{letter}_mode", "value": 1.0},
                {"param_name": f"{letter}_freq", "value": 200.0 * (i + 1)},
                {"param_name": f"{letter}_q", "value": 1.0},
                {"param_name": f"{letter}_gain", "value": -1.5},
            ])

        roomfit_lr_response = {
            "EQStat": "On",
            "channelMode": "L/R",
            "EQBandL": bands_l,
            "EQBandR": bands_r,
        }

        issued_commands: list[str] = []

        async def mock_command(cmd: str) -> dict | str:
            issued_commands.append(cmd)
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd.startswith("EQGetLV2BandEx:"):
                if "EQLevel" in cmd:
                    return roomfit_lr_response
                return EQ_GET_LV2_BAND_12_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQv2GetNewList:"):
                if '"EQLevel": 2' in cmd:
                    return {
                        "custom": [
                            {"Name": "RF1", "channelMode": "L/R", "Type": "RC"},
                        ],
                        "preset": [],
                    }
                return EQ_GET_LV2_LIST_RESPONSE
            if cmd.startswith("EQGetLV2SourceBandEx:"):
                if "EQLevel" in cmd:
                    return roomfit_lr_response
                return EQ_GET_LV2_BAND_12_RESPONSE
            if cmd.startswith("EQSetLV2SourceBand:"):
                return "OK"
            if cmd.startswith("EQSourceSave:"):
                return "OK"
            if cmd.startswith("EQv2Delete:"):
                return "OK"
            if cmd == "GetMultiroomInfo":
                return MULTIROOM_SOLO
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        # Device should reach level 4 (full RoomFit support)
        assert caps.roomfit_level == 4
        assert caps.supports_roomfit_write is True

        # The probe MUST NOT send EQSetLV2SourceBand with EQLevel in the payload
        # (that's the command that would hit HTTP 431 on large L/R data)
        roomfit_source_band_writes = [
            cmd for cmd in issued_commands
            if cmd.startswith("EQSetLV2SourceBand:") and "EQLevel" in cmd
        ]
        assert roomfit_source_band_writes == [], (
            f"Probe sent EQSetLV2SourceBand with EQLevel (would hit HTTP 431): "
            f"{roomfit_source_band_writes}"
        )

        # Verify that EQSourceSave IS used (the safe alternative)
        roomfit_saves = [
            cmd for cmd in issued_commands
            if cmd.startswith("EQSourceSave:") and "EQLevel" in cmd
        ]
        assert len(roomfit_saves) >= 1, "Probe should use EQSourceSave for level 4 test"
