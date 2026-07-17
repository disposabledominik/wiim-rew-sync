"""
Unit tests for the CapabilityProber.

Uses unittest.mock.AsyncMock to mock WiiMHttpClient.command() with canned
fixture responses.

Requirements tested: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10
"""

from __future__ import annotations

from typing import ClassVar
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
        # No write-probe exists anymore: batch capability is unknown until
        # the first real push attempts it (WiiMAdapter._write_bands).
        assert caps.supports_batch_write is None
        assert caps.supports_profile_enumeration is True

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
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_profile_enumeration is False

    @pytest.mark.asyncio
    async def test_wiim_mini_detected_correctly(self) -> None:
        """WiiM Mini should be detected as WiiM with PEQ but no RoomFit."""
        client = _make_mock_client()

        write_commands: list[str] = []

        async def mock_command(cmd: str) -> dict | str:
            if cmd.startswith(("EQSourceSave:", "EQv2Delete:", "EQSetLV2SourceBand:")):
                write_commands.append(cmd)
                return "OK"
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_MINI
            if cmd.startswith("EQGetLV2BandEx:"):
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQv2GetNewList:"):
                # Real Mini hardware never returns "unknown command" here: the
                # RoomFit-namespace list (EQLevel:2) is a valid-looking dict
                # with an EMPTY custom list -- the sole no-RoomFit signal
                # (docs/wiim_api_notes.md Capability detection; docs/
                # corrections.md 2026-07-10) -- while the PEQ-namespace list
                # (EQLevel:1) genuinely works and can even hold calibration
                # profiles.
                if '"EQLevel": 2' in unquote(cmd):
                    return {"custom": [], "preset": []}
                return EQ_GET_LV2_LIST_RESPONSE
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_peq is True
        assert caps.max_filters == 10
        assert caps.model == "WiiM_Mini"
        assert caps.supports_roomfit is False
        assert caps.supports_roomfit_read is False
        assert caps.supports_roomfit_write is False
        # The empty-custom signal must stop the probe BEFORE any RoomFit
        # write: without it, the probe proceeded to a real EQSourceSave on
        # hardware with nothing to write to (docs/corrections.md, 2026-07-10).
        assert write_commands == []
        # Mini has no getAudioInputEnable ("unknown command" via the fallback
        # branch above) -- source_names ends up whatever the bundled
        # device_capabilities.json's WiiM_Mini entry provides via merge_into()
        # (#167), not asserted here since that's this test's model's own data,
        # not this probe step's behavior.

    @pytest.mark.asyncio
    async def test_tone_control_dict_response_is_not_peq(self) -> None:
        """Generic-LinkPlay-style firmware answers every EQGetLV2* command
        with a stock tone-control dict -- captured from real hardware
        (AudioCast, docs/device_capability_examples/, docs/corrections.md
        2026-07-10). It's a dict, so the old isinstance() check reported
        supports_peq=True with an invented max_filters=10. Must probe as
        no-PEQ. Uses a WiiM-recognized model string so the probe actually
        reaches _probe_peq (non-WiiM models short-circuit earlier and never
        exercise the shape check)."""
        client = _make_mock_client()

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd.startswith(("EQGetLV2BandEx:", "EQGetLV2SourceBandEx:")):
                # Real generic-LinkPlay response shape, regardless of plugin URI
                return {"Bass": 0, "EQEnable": 0, "Treble": 0}
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_peq is False
        assert caps.supports_lr_filters is False
        assert caps.max_filters == 0

    @pytest.mark.asyncio
    async def test_probe_peq_counts_bands_when_device_is_in_lr_mode(self) -> None:
        """A device probed while in L/R mode returns EQBandL/EQBandR and no
        EQBand. The band count must come from the per-channel array (8
        letters here -> max_filters=8, unambiguous against both the
        default-10 cap and the old always-10 fallback) -- counting only
        EQBand was why the old 10-band fallback existed."""
        client = _make_mock_client()

        lr_band_response = {
            "EQStat": "On",
            "channelMode": "L/R",
            "EQBandL": [
                {"param_name": f"{chr(ord('a') + i)}_{param}", "value": 1.0}
                for i in range(8)
                for param in ("mode", "freq", "gain", "q")
            ],
            "EQBandR": [
                {"param_name": f"{chr(ord('a') + i)}_{param}", "value": 1.0}
                for i in range(8)
                for param in ("mode", "freq", "gain", "q")
            ],
        }

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd.startswith("EQGetLV2BandEx:"):
                return lr_band_response
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_peq is True
        assert caps.supports_lr_filters is True
        assert caps.max_filters == 8

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
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_peq is False
        assert caps.max_filters == 0
        assert caps.model == "UP2STREAM_PRO_V3"
        assert caps.supports_lr_filters is False
        assert caps.supports_batch_write is None
        assert caps.supports_profile_enumeration is False
        assert caps.supports_roomfit is False


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
        assert caps.supports_batch_write is None
        assert caps.supports_profile_enumeration is False
        assert caps.supports_roomfit is False
        assert caps.supports_roomfit_read is False
        assert caps.supports_roomfit_write is False
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


class TestAcousticCapabilityProbe:
    """GetAcousticCapability -- the declarative, read-only capability report
    that replaces per-command RoomFit probing on devices that support it
    (docs/wiim_api_notes.md; fixtures mirror the real hardware dumps in
    docs/device_capability_examples/, 2026-07-10)."""

    ACOUSTIC_FULL: ClassVar[dict] = {
        "Version": "1.0",
        "GEQ": {"Version": "1.0"},
        "PEQ": {"Version": "1.0", "Filters": ["OFF", "LS", "PK", "HS", "LP", "HP"]},
        "RC": {"Version": "1.1"},
        "SubLPF": {"Version": "1.0"},
        "EQBlock": {
            "Version": "1.0",
            "Blocks": [{"id": 1, "type": "EQ"}, {"id": 2, "type": "RC"}],
        },
    }

    @staticmethod
    def _client_with(acoustic_response: dict | str) -> tuple:
        client = _make_mock_client()
        issued: list[str] = []

        async def mock_command(cmd: str) -> dict | str:
            issued.append(cmd)
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd == "GetAcousticCapability":
                return acoustic_response
            if cmd.startswith("EQGetLV2BandEx:"):
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQv2GetNewList:"):
                if '"EQLevel": 2' in unquote(cmd):
                    return {
                        "custom": [
                            {"Name": "RF1", "channelMode": "Stereo", "Type": "RC"}
                        ],
                        "preset": [],
                    }
                return EQ_GET_LV2_LIST_RESPONSE
            if cmd.startswith("EQGetLV2SourceBandEx:"):
                return EQ_GET_LV2_BAND_RESPONSE
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)
        return client, issued

    @pytest.mark.asyncio
    async def test_rc_block_means_full_roomfit_support(self) -> None:
        """RC present in the schema -> all three RoomFit booleans set, plus
        rc_version captured; the fallback probe is skipped entirely."""
        client, issued = self._client_with(self.ACOUSTIC_FULL)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_roomfit is True
        assert caps.supports_roomfit_read is True
        assert caps.supports_roomfit_write is True
        assert caps.rc_version == "1.1"
        # Declarative answer obtained -- no EQLevel:2 fallback probing
        roomfit_probes = [
            c for c in issued
            if c.startswith(("EQv2GetNewList:", "EQGetLV2SourceBandEx:"))
            and '"EQLevel": 2' in unquote(c)
        ]
        assert roomfit_probes == []

    @pytest.mark.asyncio
    async def test_schema_without_rc_means_no_roomfit(self) -> None:
        """A real schema lacking the RC block -> no RoomFit, fallback skipped."""
        no_rc = {k: v for k, v in self.ACOUSTIC_FULL.items() if k != "RC"}
        client, issued = self._client_with(no_rc)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_roomfit is False
        assert caps.supports_roomfit_read is False
        assert caps.supports_roomfit_write is False
        assert caps.rc_version == ""
        roomfit_probes = [
            c for c in issued
            if c.startswith(("EQv2GetNewList:", "EQGetLV2SourceBandEx:"))
            and '"EQLevel": 2' in unquote(c)
        ]
        assert roomfit_probes == []

    @pytest.mark.asyncio
    async def test_failed_status_falls_back_to_per_command_probe(self) -> None:
        """{"status":"Failed"} (WiiM Mini shape) -> declarative data absent;
        the read-only fallback probe runs and determines support."""
        client, issued = self._client_with({"status": "Failed"})

        prober = CapabilityProber(client)
        caps = await prober.probe()

        # Fallback found a non-empty custom list + readable buffer
        assert caps.supports_roomfit is True
        assert caps.supports_roomfit_read is True
        assert caps.supports_roomfit_write is True
        fallback_lists = [
            c for c in issued
            if c.startswith("EQv2GetNewList:") and '"EQLevel": 2' in unquote(c)
        ]
        assert len(fallback_lists) == 1

    @pytest.mark.asyncio
    async def test_unknown_command_falls_back_to_per_command_probe(self) -> None:
        """Generic-LinkPlay "unknown command" -> fallback probe runs."""
        client, issued = self._client_with("unknown command")

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_roomfit is True  # via fallback fixtures
        fallback_lists = [
            c for c in issued
            if c.startswith("EQv2GetNewList:") and '"EQLevel": 2' in unquote(c)
        ]
        assert len(fallback_lists) == 1

    @pytest.mark.asyncio
    async def test_unrecognised_dict_shape_falls_back(self) -> None:
        """A dict that isn't the capability schema (no PEQ/RC keys) must not
        be interpreted as "no RoomFit" -- fall back instead."""
        client, issued = self._client_with({"Bass": 0, "EQEnable": 0, "Treble": 0})

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_roomfit is True  # via fallback fixtures
        fallback_lists = [
            c for c in issued
            if c.startswith("EQv2GetNewList:") and '"EQLevel": 2' in unquote(c)
        ]
        assert len(fallback_lists) == 1


class TestRoomfitModelFallback:
    """_apply_roomfit_model_fallback() -- a defensive fallback for RoomFit
    support on model strings not yet listed in the capability file (smoke
    #36), consolidated here from what used to be a duplicate, GUI-layer-only
    check in MainWindow._on_capabilities_ready()."""

    @staticmethod
    def _client_with(project: str, acoustic_response: dict) -> WiiMHttpClient:
        client = _make_mock_client()
        status = {**STATUS_EX_WIIM_PRO, "project": project}

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return status
            if cmd == "GetAcousticCapability":
                return acoustic_response
            if cmd.startswith("EQGetLV2BandEx:"):
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQv2GetNewList:"):
                if '"EQLevel": 2' in unquote(cmd):
                    return {
                        "custom": [
                            {"Name": "RF1", "channelMode": "Stereo", "Type": "RC"}
                        ],
                        "preset": [],
                    }
                return EQ_GET_LV2_LIST_RESPONSE
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)
        return client

    @pytest.mark.asyncio
    async def test_exact_capability_file_match_takes_precedence(self) -> None:
        """"WiiM_Mini" is an exact capability-file match -- confirms the
        fallback doesn't need to run (and doesn't override) when the
        precise, file-driven path already applies."""
        client = self._client_with(
            "WiiM_Mini", TestAcousticCapabilityProbe.ACOUSTIC_FULL
        )

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.capability_file_override is True
        assert caps.supports_roomfit_read is False

    @pytest.mark.asyncio
    async def test_unlisted_mini_variant_forces_roomfit_off(self) -> None:
        """A model string containing "mini" that does NOT match the
        capability file's exact key/alias (confirmed: "WiiM Mini 2" does not
        equal "WiiM_Mini"/"Muzo_Mini" under case/space/underscore-insensitive
        matching) still gets supports_roomfit* forced off, even though
        GetAcousticCapability's RC block would otherwise report full
        support -- the substring fallback this test exercises, which the
        exact-match test above confirms is not needed for already-listed
        models."""
        client = self._client_with(
            "WiiM Mini 2", TestAcousticCapabilityProbe.ACOUSTIC_FULL
        )

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.capability_file_override is False
        assert caps.supports_roomfit is False
        assert caps.supports_roomfit_read is False
        assert caps.supports_roomfit_write is False

    @pytest.mark.asyncio
    async def test_non_mini_model_unaffected(self) -> None:
        """A model with no capability-file entry and no "mini" in its name
        keeps its genuinely-probed RoomFit support untouched."""
        client = self._client_with(
            "WiiM Amp Ultra", TestAcousticCapabilityProbe.ACOUSTIC_FULL
        )

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.capability_file_override is False
        assert caps.supports_roomfit is True
        assert caps.supports_roomfit_read is True
        assert caps.supports_roomfit_write is True

    @pytest.mark.asyncio
    async def test_partial_capability_file_match_does_not_bypass_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression test (branch-quality review, 2026-07-17): a
        capability-file entry that matches a "mini"-substring model but only
        sets an unrelated field (max_bands here, not any supports_roomfit*/
        roomfit_level field) must NOT bypass the smoke #36 fallback.

        Before the fix, the fallback gated on caps.capability_file_override
        (set to True by merge_into() whenever ANY entry field matched,
        regardless of which fields), so this exact scenario would silently
        skip the correction and leave supports_roomfit_read at its
        (incorrectly) probed True value.
        """
        from src.models.device_capability_file import CapabilityFileEntry, LoadedCapabilityFile

        monkeypatch.setattr(
            "src.adapters.capability_prober.get_cached_capability_file",
            lambda: LoadedCapabilityFile(
                entries={"WiiM_Mini_2": CapabilityFileEntry(max_bands=12)},
                default_max_bands=10,
            ),
        )

        client = self._client_with(
            "WiiM Mini 2", TestAcousticCapabilityProbe.ACOUSTIC_FULL
        )

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.capability_file_override is True  # the max_bands entry did match
        assert caps.supports_roomfit is False  # but the fallback still fired
        assert caps.supports_roomfit_read is False
        assert caps.supports_roomfit_write is False


class TestRoomFitFallbackProbe:
    """The read-only per-command RoomFit fallback (devices without
    GetAcousticCapability). Detection is: non-empty custom list, then a
    readable band buffer. Write support := read support -- there is no
    write test (2026-07-10 redesign)."""

    ROOMFIT_BAND_RESPONSE: ClassVar[dict] = {
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

    def _client(self, *, list_resp: dict | str, band_resp: dict | str) -> tuple:
        client = _make_mock_client()
        issued: list[str] = []

        async def mock_command(cmd: str) -> dict | str:
            issued.append(cmd)
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd.startswith("EQGetLV2BandEx:"):
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQv2GetNewList:"):
                if '"EQLevel": 2' in unquote(cmd):
                    return list_resp
                return EQ_GET_LV2_LIST_RESPONSE
            if cmd.startswith("EQGetLV2SourceBandEx:"):
                if '"EQLevel": 2' in unquote(cmd):
                    return band_resp
                return EQ_GET_LV2_BAND_RESPONSE
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)
        return client, issued

    @pytest.mark.asyncio
    async def test_full_support_is_read_only_probing(self) -> None:
        """Profiles exist + buffer readable -> all three booleans True, and
        the probe never issues a single write command (the old level-4
        probe's EQSourceSave/EQv2Delete are gone)."""
        client, issued = self._client(
            list_resp={
                "custom": [{"Name": "RF1", "channelMode": "Stereo", "Type": "RC"}],
                "preset": [],
            },
            band_resp=self.ROOMFIT_BAND_RESPONSE,
        )

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_roomfit is True
        assert caps.supports_roomfit_read is True
        assert caps.supports_roomfit_write is True
        writes = [
            c for c in issued
            if c.startswith((
                "EQSourceSave:", "EQv2Delete:", "EQSetLV2SourceBand:",
                "EQSetLV2Band:", "EQv2SourceLoad:", "EQChangeSourceFX:",
                "EQSourceOff:",
            ))
        ]
        assert writes == [], f"probe issued write/side-effect commands: {writes}"

    @pytest.mark.asyncio
    async def test_empty_custom_list_means_no_roomfit(self) -> None:
        """Empty custom list is THE no-RoomFit signal -- probing stops
        before the band read."""
        client, issued = self._client(
            list_resp={"custom": [], "preset": []},
            band_resp=self.ROOMFIT_BAND_RESPONSE,
        )

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_roomfit is False
        assert caps.supports_roomfit_read is False
        assert caps.supports_roomfit_write is False
        band_reads = [
            c for c in issued
            if c.startswith("EQGetLV2SourceBandEx:") and '"EQLevel": 2' in unquote(c)
        ]
        assert band_reads == []

    @pytest.mark.asyncio
    async def test_unknown_command_means_no_roomfit(self) -> None:
        client, _ = self._client(
            list_resp="unknown command",
            band_resp=self.ROOMFIT_BAND_RESPONSE,
        )

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_roomfit is False
        assert caps.supports_roomfit_read is False
        assert caps.supports_roomfit_write is False

    @pytest.mark.asyncio
    async def test_unreadable_buffer_means_list_only_support(self) -> None:
        """Profiles exist but the band buffer isn't readable -> subsystem
        present, read (and therefore write) unconfirmed."""
        client, _ = self._client(
            list_resp={
                "custom": [{"Name": "RF1", "channelMode": "Stereo", "Type": "RC"}],
                "preset": [],
            },
            band_resp={"status": "Failed"},
        )

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_roomfit is True
        assert caps.supports_roomfit_read is False
        assert caps.supports_roomfit_write is False


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
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_peq is True
        assert caps.max_filters == 10

    @pytest.mark.asyncio
    async def test_empty_eqband_means_no_peq(self) -> None:
        """Device with an EQBand key but no parseable band entries is not a
        real EqNp PEQ engine -- supports_peq=False, max_filters=0. This
        replaces the old behavior of inventing a 10-band default, which
        turned generic-LinkPlay tone-control responses into phantom PEQ
        devices (docs/corrections.md, 2026-07-10)."""
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
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.supports_peq is False
        assert caps.max_filters == 0


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
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        # Full RoomFit support detected via the read-only fallback
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

        # There is no write test at all anymore: EQSourceSave must not
        # appear either (2026-07-10 redesign).
        roomfit_saves = [
            cmd for cmd in issued_commands
            if cmd.startswith("EQSourceSave:")
        ]
        assert roomfit_saves == []
