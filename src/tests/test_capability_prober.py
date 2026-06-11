"""
Unit tests for the CapabilityProber.

Uses unittest.mock.AsyncMock to mock WiiMHttpClient.command() with canned
fixture responses.

Requirements tested: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 2.8, 2.9, 2.10
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from urllib.parse import quote

import pytest

from src.adapters.capability_prober import CapabilityProber, PLUGIN_URI
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
            if cmd.startswith("EQGetLV2BandEx:"):
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQGetLV2List:"):
                return EQ_GET_LV2_LIST_RESPONSE
            if cmd == "getRoomFitStatus":
                return {"status": "active"}
            if cmd == "getRoomFitBands":
                return {"bands": []}
            if cmd.startswith("setRoomFitBands:"):
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
        assert caps.source_names == ["wifi", "bluetooth", "line-in", "optical"]
        assert caps.supports_channel_peq is True
        assert caps.supports_batch_write is True
        assert caps.supports_profile_enumeration is True
        assert caps.role == "solo"

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
            if cmd.startswith("EQGetLV2List:"):
                return EQ_GET_LV2_LIST_RESPONSE
            if cmd == "getRoomFitStatus":
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
        assert caps.supports_channel_peq is False
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
        assert caps.supports_channel_peq is False
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
    """Test RoomFit level probing at different capability levels."""

    @pytest.mark.asyncio
    async def test_roomfit_level_4_full_support(self) -> None:
        """Device with full RoomFit support → level 4."""
        client = _make_mock_client()

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd.startswith("EQGetLV2BandEx:"):
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQGetLV2List:"):
                return EQ_GET_LV2_LIST_RESPONSE
            if cmd == "getRoomFitStatus":
                return {"status": "active"}
            if cmd == "getRoomFitBands":
                return {"bands": [{"param_name": "a_mode", "value": 1.0}]}
            if cmd.startswith("setRoomFitBands:"):
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

    @pytest.mark.asyncio
    async def test_roomfit_level_2_read_only(self) -> None:
        """Device where RoomFit read works but write fails → level 2."""
        client = _make_mock_client()

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd.startswith("EQGetLV2BandEx:"):
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQGetLV2List:"):
                return EQ_GET_LV2_LIST_RESPONSE
            if cmd == "getRoomFitStatus":
                return {"status": "active"}
            if cmd == "getRoomFitBands":
                # Returns a string (non-dict) — level 2 but not 3
                return "band_data_string"
            if cmd == "GetMultiroomInfo":
                return MULTIROOM_SOLO
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()

        assert caps.roomfit_level == 2
        assert caps.supports_roomfit is True
        assert caps.supports_roomfit_read is True
        assert caps.supports_roomfit_write is False

    @pytest.mark.asyncio
    async def test_roomfit_level_1_status_only(self) -> None:
        """Device where only RoomFit status works → level 1."""
        client = _make_mock_client()

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd.startswith("EQGetLV2BandEx:"):
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQGetLV2List:"):
                return EQ_GET_LV2_LIST_RESPONSE
            if cmd == "getRoomFitStatus":
                return {"status": "inactive"}
            if cmd == "getRoomFitBands":
                return "unknown command"
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
        """Device where RoomFit status returns 'unknown' → level 0."""
        client = _make_mock_client()

        async def mock_command(cmd: str) -> dict | str:
            if cmd == "getStatusEx":
                return STATUS_EX_WIIM_PRO
            if cmd.startswith("EQGetLV2BandEx:"):
                return EQ_GET_LV2_BAND_RESPONSE
            if cmd.startswith("EQSetLV2Band:"):
                return "OK"
            if cmd.startswith("EQGetLV2List:"):
                return EQ_GET_LV2_LIST_RESPONSE
            if cmd == "getRoomFitStatus":
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
            if cmd.startswith("EQGetLV2List:"):
                return EQ_GET_LV2_LIST_RESPONSE
            if cmd == "getRoomFitStatus":
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
            if cmd.startswith("EQGetLV2List:"):
                return EQ_GET_LV2_LIST_RESPONSE
            if cmd == "getRoomFitStatus":
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
            if cmd.startswith("EQGetLV2List:"):
                return EQ_GET_LV2_LIST_RESPONSE
            if cmd == "getRoomFitStatus":
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
            if cmd.startswith("EQGetLV2List:"):
                return EQ_GET_LV2_LIST_RESPONSE
            if cmd == "getRoomFitStatus":
                return "unknown command"
            if cmd == "GetMultiroomInfo":
                raise ConnectionError("Network error")
            return "unknown command"

        client.command = AsyncMock(side_effect=mock_command)

        prober = CapabilityProber(client)
        caps = await prober.probe()
        assert caps.role == "solo"


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
