"""Unit tests for WiiMAdapter — PEQ read and multiroom operations.

Tests use AsyncMock to mock WiiMHttpClient.command() and exercise
stereo/LR parsing, error handling, and multiroom master IP resolution.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch
from urllib.parse import unquote

import pytest

from src.adapters.wiim_adapter import WiiMAdapter
from src.adapters.wiim_http import WiiMHttpClient
from src.models.capabilities import DeviceCapabilities
from src.models.channel_mode import ChannelMode
from src.models.errors import (
    RoomFitUnsupportedError,
    WiiMConnectionError,
    WiiMResponseError,
)
from src.models.peq import PEQSettings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def capabilities() -> DeviceCapabilities:
    """Minimal device capabilities for adapter tests."""
    return DeviceCapabilities(
        supports_peq=True,
        supports_lr_filters=True,
        max_filters=10,
        model="WiiM_Ultra",
        firmware="6.0.1.20",
    )


@pytest.fixture
def mock_client() -> AsyncMock:
    """Mocked WiiMHttpClient with command as AsyncMock."""
    client = AsyncMock(spec=WiiMHttpClient)
    client.command = AsyncMock()
    return client


@pytest.fixture
def adapter(mock_client: AsyncMock, capabilities: DeviceCapabilities) -> WiiMAdapter:
    """WiiMAdapter with mocked client."""
    return WiiMAdapter(http_client=mock_client, capabilities=capabilities)


# ---------------------------------------------------------------------------
# Fixture responses
# ---------------------------------------------------------------------------


def _make_band_params(
    letter: str, mode: int, freq: float, q: float, gain: float
) -> list[dict[str, str | float]]:
    """Create a 4-element param list for one band."""
    return [
        {"param_name": f"{letter}_mode", "value": float(mode)},
        {"param_name": f"{letter}_freq", "value": freq},
        {"param_name": f"{letter}_q", "value": q},
        {"param_name": f"{letter}_gain", "value": gain},
    ]


def _stereo_response() -> dict:
    """Stereo PEQ response with 10 bands (first 2 active, rest OFF)."""
    bands: list[dict[str, str | float]] = []
    letters = "abcdefghij"

    # Band a: PEAK at 80 Hz, Q=1.41, gain=-4.0
    bands.extend(_make_band_params("a", 1, 80.0, 1.41, -4.0))
    # Band b: Low Shelf at 120 Hz, Q=0.71, gain=+2.0
    bands.extend(_make_band_params("b", 0, 120.0, 0.71, 2.0))
    # Bands c-j: OFF
    for letter in letters[2:]:
        bands.extend(_make_band_params(letter, -1, 1000.0, 1.0, 0.0))

    return {
        "EQStat": "On",
        "channelMode": "Stereo",
        "source_name": "wifi",
        "Name": "My Preset",
        "EQBand": bands,
    }


def _lr_response() -> dict:
    """L/R PEQ response with independent left and right bands."""
    letters = "abcdefghij"

    bands_l: list[dict[str, str | float]] = []
    # Left: band a PEAK at 100 Hz
    bands_l.extend(_make_band_params("a", 1, 100.0, 1.0, -3.0))
    for letter in letters[1:]:
        bands_l.extend(_make_band_params(letter, -1, 1000.0, 1.0, 0.0))

    bands_r: list[dict[str, str | float]] = []
    # Right: band a High Shelf at 8000 Hz
    bands_r.extend(_make_band_params("a", 2, 8000.0, 0.5, +1.5))
    for letter in letters[1:]:
        bands_r.extend(_make_band_params(letter, -1, 1000.0, 1.0, 0.0))

    return {
        "EQStat": "On",
        "channelMode": "L/R",
        "source_name": "wifi",
        "Name": "",
        "EQBandL": bands_l,
        "EQBandR": bands_r,
    }


# ---------------------------------------------------------------------------
# Tests: read_peq — Stereo
# ---------------------------------------------------------------------------


class TestReadPeqStereo:
    """Test stereo PEQ read (EQBand key present)."""

    async def test_stereo_read_returns_peq_settings(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Stereo read returns PEQSettings with correct bands."""
        mock_client.command.return_value = _stereo_response()

        result = await adapter.read_peq("wifi")

        assert result.source_name == "wifi"
        assert result.channel_mode == ChannelMode.STEREO
        assert result.enabled is True
        assert result.name == "My Preset"
        assert len(result.bands) == 10

    async def test_stereo_read_first_band_peak(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """First band is parsed as PEAK with correct parameters."""
        mock_client.command.return_value = _stereo_response()

        result = await adapter.read_peq("wifi")
        band_a = result.bands[0]

        assert band_a.type == "PEAK"
        assert band_a.frequency_hz == 80.0
        assert band_a.q == 1.41
        assert band_a.gain_db == -4.0

    async def test_stereo_read_second_band_low_shelf(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Second band is parsed as LS (Low Shelf)."""
        mock_client.command.return_value = _stereo_response()

        result = await adapter.read_peq("wifi")
        band_b = result.bands[1]

        assert band_b.type == "LS"
        assert band_b.frequency_hz == 120.0
        assert band_b.q == 0.71
        assert band_b.gain_db == 2.0

    async def test_stereo_read_off_bands(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Bands c-j are parsed as OFF."""
        mock_client.command.return_value = _stereo_response()

        result = await adapter.read_peq("wifi")

        for band in result.bands[2:]:
            assert band.type == "OFF"

    async def test_stereo_read_issues_correct_command(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Adapter issues EQGetLV2SourceBandEx with correct payload."""
        mock_client.command.return_value = _stereo_response()

        await adapter.read_peq("wifi")

        call_args = mock_client.command.call_args[0][0]
        assert call_args.startswith("EQGetLV2SourceBandEx:")
        # Verify it contains source_name and pluginURI
        assert "wifi" in call_args
        assert "EqNp" in call_args


# ---------------------------------------------------------------------------
# Tests: read_peq — L/R
# ---------------------------------------------------------------------------


class TestReadPeqLR:
    """Test L/R PEQ read (EQBandL + EQBandR keys)."""

    async def test_lr_read_returns_peq_settings(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """L/R read returns PEQSettings with separate left and right bands."""
        mock_client.command.return_value = _lr_response()

        result = await adapter.read_peq("wifi")

        assert result.source_name == "wifi"
        assert result.channel_mode == ChannelMode.LR
        assert result.enabled is True
        assert len(result.bands_l) == 10
        assert len(result.bands_r) == 10

    async def test_lr_read_left_channel(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Left channel first band is parsed correctly."""
        mock_client.command.return_value = _lr_response()

        result = await adapter.read_peq("wifi")
        left_a = result.bands_l[0]

        assert left_a.type == "PEAK"
        assert left_a.frequency_hz == 100.0
        assert left_a.gain_db == -3.0

    async def test_lr_read_right_channel(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Right channel first band is parsed correctly."""
        mock_client.command.return_value = _lr_response()

        result = await adapter.read_peq("wifi")
        right_a = result.bands_r[0]

        assert right_a.type == "HS"
        assert right_a.frequency_hz == 8000.0
        assert right_a.gain_db == 1.5

    async def test_lr_read_stereo_bands_empty(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """In L/R mode, the shared 'bands' field is empty."""
        mock_client.command.return_value = _lr_response()

        result = await adapter.read_peq("wifi")

        assert result.bands == []


# ---------------------------------------------------------------------------
# Tests: read_peq — Error handling
# ---------------------------------------------------------------------------


class TestReadPeqErrors:
    """Test error handling for missing fields and connection failures."""

    async def test_missing_channel_mode_raises(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Missing channelMode raises WiiMResponseError."""
        mock_client.command.return_value = {
            "EQStat": "On",
            "EQBand": [],
        }

        with pytest.raises(WiiMResponseError, match="channelMode"):
            await adapter.read_peq("wifi")

    async def test_stereo_missing_eq_band_raises(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Stereo mode with missing EQBand raises WiiMResponseError."""
        mock_client.command.return_value = {
            "channelMode": "Stereo",
            "EQStat": "On",
        }

        with pytest.raises(WiiMResponseError, match="EQBand"):
            await adapter.read_peq("wifi")

    async def test_lr_missing_eq_band_l_raises(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """L/R mode with missing EQBandL raises WiiMResponseError."""
        mock_client.command.return_value = {
            "channelMode": "L/R",
            "EQStat": "On",
            "EQBandR": [],
        }

        with pytest.raises(WiiMResponseError, match="EQBandL"):
            await adapter.read_peq("wifi")

    async def test_lr_missing_eq_band_r_raises(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """L/R mode with missing EQBandR raises WiiMResponseError."""
        mock_client.command.return_value = {
            "channelMode": "L/R",
            "EQStat": "On",
            "EQBandL": [],
        }

        with pytest.raises(WiiMResponseError, match="EQBandR"):
            await adapter.read_peq("wifi")

    async def test_non_dict_response_raises(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Non-dict response (e.g. plain string) raises WiiMResponseError."""
        mock_client.command.return_value = "unknown command"

        with pytest.raises(WiiMResponseError, match="Expected JSON dict"):
            await adapter.read_peq("wifi")

    async def test_connection_error_propagates(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """WiiMConnectionError from http client propagates directly."""
        mock_client.command.side_effect = WiiMConnectionError("Device unreachable")

        with pytest.raises(WiiMConnectionError, match="unreachable"):
            await adapter.read_peq("wifi")

    async def test_unknown_channel_mode_raises(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Unknown channelMode value raises WiiMResponseError."""
        mock_client.command.return_value = {
            "channelMode": "Unknown",
            "EQStat": "On",
            "EQBand": [],
        }

        with pytest.raises(WiiMResponseError, match="Unknown channelMode"):
            await adapter.read_peq("wifi")


# ---------------------------------------------------------------------------
# Tests: write_peq — Batch path
# ---------------------------------------------------------------------------


class TestWritePeqBatch:
    """Test PEQ write via batch path (supports_batch_write=True)."""

    @pytest.fixture
    def batch_capabilities(self) -> DeviceCapabilities:
        """Capabilities with batch write support."""
        return DeviceCapabilities(
            supports_peq=True,
            supports_batch_write=True,
            supports_lr_filters=True,
            max_filters=10,
            model="WiiM_Ultra",
            firmware="6.0.1.20",
        )

    @pytest.fixture
    def batch_adapter(
        self, mock_client: AsyncMock, batch_capabilities: DeviceCapabilities
    ) -> WiiMAdapter:
        """Adapter configured for batch write."""
        return WiiMAdapter(http_client=mock_client, capabilities=batch_capabilities)

    def _make_settings(self) -> PEQSettings:
        """Create minimal PEQSettings for testing."""
        from src.models.canonical import CanonicalFilter

        bands = [
            CanonicalFilter(type="PEAK", frequency_hz=80.0, gain_db=-4.0, q=1.41),
            CanonicalFilter(type="LS", frequency_hz=120.0, gain_db=2.0, q=0.71),
        ]
        # Remaining bands will be filled as OFF by generate_wiim_band_array
        return PEQSettings(
            source_name="wifi",
            enabled=True,
            channel_mode="stereo",
            bands=bands,
        )

    async def test_batch_write_issues_single_command(
        self, batch_adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Batch write issues exactly one EQSetLV2SourceBand call."""
        mock_client.command.return_value = "OK"
        settings = self._make_settings()

        await batch_adapter.write_peq("wifi", settings)

        assert mock_client.command.call_count == 1
        calls = [c[0][0] for c in mock_client.command.call_args_list]
        assert calls[0].startswith("EQSetLV2SourceBand:")

    async def test_batch_write_payload_contains_source_and_plugin(
        self, batch_adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Batch payload includes source_name, pluginURI, and channelMode."""
        mock_client.command.return_value = "OK"
        settings = self._make_settings()

        await batch_adapter.write_peq("wifi", settings)

        call_args = mock_client.command.call_args[0][0]
        # URL-decoded the command should contain these keys
        assert "wifi" in call_args
        assert "EqNp" in call_args
        assert "Stereo" in call_args

    async def test_batch_write_payload_contains_all_bands(
        self, batch_adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Batch payload includes EQBand with 40 parameters (10 bands x 4 params)."""
        mock_client.command.return_value = "OK"
        settings = self._make_settings()

        await batch_adapter.write_peq("wifi", settings)

        call_args = mock_client.command.call_args[0][0]
        # Should contain all band letters
        assert "a_mode" in call_args
        assert "j_mode" in call_args

    async def test_batch_rejection_falls_back_to_sequential_even_when_previously_true(
        self, batch_adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """A device that previously accepted batch writes (supports_batch_write
        already True) but rejects this one must still be detected and fall
        back to sequential -- previously the rejection check only ran when
        supports_batch_write was None (first attempt), so a later rejection
        with known=True went unnoticed here and was only ever caught one
        round-trip later by SafeWrite's read-back verification."""
        mock_client.command.side_effect = [{"status": "Failed"}, *(["OK"] * 10)]
        settings = self._make_settings()

        await batch_adapter.write_peq("wifi", settings)

        # 1 rejected batch attempt + 10 sequential band writes
        assert mock_client.command.call_count == 11
        assert batch_adapter.capabilities.supports_batch_write is False


# ---------------------------------------------------------------------------
# Tests: write_peq — Sequential path
# ---------------------------------------------------------------------------


class TestWritePeqSequential:
    """Test PEQ write via sequential path (supports_batch_write=False)."""

    @pytest.fixture
    def seq_capabilities(self) -> DeviceCapabilities:
        """Capabilities without batch write support."""
        return DeviceCapabilities(
            supports_peq=True,
            supports_batch_write=False,
            supports_lr_filters=True,
            max_filters=10,
            model="WiiM_Pro",
            firmware="5.0.0.10",
        )

    @pytest.fixture
    def seq_adapter(
        self, mock_client: AsyncMock, seq_capabilities: DeviceCapabilities
    ) -> WiiMAdapter:
        """Adapter configured for sequential write."""
        return WiiMAdapter(http_client=mock_client, capabilities=seq_capabilities)

    def _make_settings(self) -> PEQSettings:
        """Create minimal PEQSettings for testing."""
        from src.models.canonical import CanonicalFilter

        bands = [
            CanonicalFilter(type="PEAK", frequency_hz=80.0, gain_db=-4.0, q=1.41),
        ]
        return PEQSettings(
            source_name="wifi",
            enabled=True,
            channel_mode="stereo",
            bands=bands,
        )

    async def test_sequential_write_uses_queue(
        self, seq_adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Sequential write delegates to queue.enqueue for each band."""
        mock_queue = AsyncMock()
        mock_queue.enqueue = AsyncMock()
        settings = self._make_settings()

        await seq_adapter.write_peq("wifi", settings, queue=mock_queue)

        # 10 bands should each be enqueued
        assert mock_queue.enqueue.call_count == 10

    async def test_sequential_write_without_queue_uses_client(
        self, seq_adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Sequential write without queue falls back to direct client.command."""
        mock_client.command.return_value = "OK"
        settings = self._make_settings()

        await seq_adapter.write_peq("wifi", settings, queue=None)

        # 10 band writes
        assert mock_client.command.call_count == 10

    async def test_sequential_write_commands_contain_single_band(
        self, seq_adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Each sequential command targets one band (4 params)."""
        mock_queue = AsyncMock()
        mock_queue.enqueue = AsyncMock()
        settings = self._make_settings()

        await seq_adapter.write_peq("wifi", settings, queue=mock_queue)

        # First call should contain band "a" parameters
        first_call = mock_queue.enqueue.call_args_list[0][0][0]
        assert "a_mode" in first_call
        assert "EQSetLV2SourceBand:" in first_call


# ---------------------------------------------------------------------------
# Tests: PEQ Profile Management
# ---------------------------------------------------------------------------


class TestListPeqProfiles:
    """Test list_peq_profiles — profile enumeration."""

    @pytest.fixture
    def profile_capabilities(self) -> DeviceCapabilities:
        """Capabilities with profile enumeration support."""
        return DeviceCapabilities(
            supports_peq=True,
            supports_profile_enumeration=True,
            max_filters=10,
            model="WiiM_Ultra",
            firmware="6.0.1.20",
        )

    @pytest.fixture
    def no_profile_capabilities(self) -> DeviceCapabilities:
        """Capabilities without profile enumeration support."""
        return DeviceCapabilities(
            supports_peq=True,
            supports_profile_enumeration=False,
            max_filters=10,
            model="WiiM_Mini",
            firmware="5.0.0.10",
        )

    async def test_list_peq_profiles_success(
        self, mock_client: AsyncMock, profile_capabilities: DeviceCapabilities
    ) -> None:
        """list_peq_profiles returns parsed profile list from EQv2GetNewList."""
        mock_client.command.return_value = {
            "custom": [
                {"Name": "My Profile", "channelMode": "Stereo", "Type": "Custom"},
                {"Name": "Bass Boost", "channelMode": "L/R", "Type": "Custom"},
            ],
            "preset": [],
        }
        adapter = WiiMAdapter(http_client=mock_client, capabilities=profile_capabilities)

        result = await adapter.list_peq_profiles("wifi")

        assert len(result) == 2
        assert result[0] == {"Name": "My Profile", "channelMode": "Stereo", "Type": "Custom"}
        assert result[1] == {"Name": "Bass Boost", "channelMode": "L/R", "Type": "Custom"}

    async def test_list_peq_profiles_empty(
        self, mock_client: AsyncMock, profile_capabilities: DeviceCapabilities
    ) -> None:
        """Returns empty list when no custom profiles exist."""
        mock_client.command.return_value = {"custom": [], "preset": []}
        adapter = WiiMAdapter(http_client=mock_client, capabilities=profile_capabilities)

        result = await adapter.list_peq_profiles("wifi")

        assert result == []

    async def test_list_peq_profiles_not_supported_raises(
        self, mock_client: AsyncMock, no_profile_capabilities: DeviceCapabilities
    ) -> None:
        """Raises WiiMResponseError when supports_profile_enumeration is False."""
        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=no_profile_capabilities
        )

        with pytest.raises(WiiMResponseError, match="profile enumeration"):
            await adapter.list_peq_profiles("wifi")

    async def test_list_peq_profiles_issues_correct_command(
        self, mock_client: AsyncMock, profile_capabilities: DeviceCapabilities
    ) -> None:
        """Adapter issues EQv2GetNewList with EQLevel: 1."""
        mock_client.command.return_value = {"custom": [], "preset": []}
        adapter = WiiMAdapter(http_client=mock_client, capabilities=profile_capabilities)

        await adapter.list_peq_profiles("wifi")

        call_args = mock_client.command.call_args[0][0]
        assert call_args.startswith("EQv2GetNewList:")
        assert "EQLevel" in call_args
        assert "EqNp" in call_args


class TestSavePeqProfile:
    """Test save_peq_profile — saving active PEQ as device preset."""

    async def test_save_peq_profile_success(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """save_peq_profile issues EQSourceSave with correct payload."""
        mock_client.command.return_value = "OK"

        await adapter.save_peq_profile("wifi", "My New Preset")

        mock_client.command.assert_called_once()
        call_args = mock_client.command.call_args[0][0]
        assert call_args.startswith("EQSourceSave:")
        assert "My New Preset" in call_args or "My%20New%20Preset" in call_args
        assert "wifi" in call_args
        assert "EqNp" in call_args

    async def test_save_peq_profile_connection_error_propagates(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Connection errors propagate from save_peq_profile."""
        mock_client.command.side_effect = WiiMConnectionError("timeout")

        with pytest.raises(WiiMConnectionError, match="timeout"):
            await adapter.save_peq_profile("wifi", "Test")


class TestLoadPeqProfile:
    """Test load_peq_profile — loading a saved preset into live DSP."""

    async def test_load_peq_profile_success(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """load_peq_profile issues EQv2SourceLoad with correct payload."""
        mock_client.command.return_value = "OK"

        await adapter.load_peq_profile("wifi", "Bass Boost")

        mock_client.command.assert_called_once()
        call_args = mock_client.command.call_args[0][0]
        assert call_args.startswith("EQv2SourceLoad:")
        assert "Bass" in call_args
        assert "wifi" in call_args
        assert "EqNp" in call_args

    async def test_load_peq_profile_connection_error_propagates(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Connection errors propagate from load_peq_profile."""
        mock_client.command.side_effect = WiiMConnectionError("timeout")

        with pytest.raises(WiiMConnectionError, match="timeout"):
            await adapter.load_peq_profile("wifi", "Test")


class TestDeletePeqProfile:
    """Test delete_peq_profile — deleting a saved preset."""

    async def test_delete_peq_profile_success(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """delete_peq_profile issues EQv2Delete with correct payload."""
        mock_client.command.return_value = "OK"

        await adapter.delete_peq_profile("Old Preset")

        mock_client.command.assert_called_once()
        call_args = mock_client.command.call_args[0][0]
        assert call_args.startswith("EQv2Delete:")
        assert "Old" in call_args
        assert "EqNp" in call_args

    async def test_delete_peq_profile_connection_error_propagates(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Connection errors propagate from delete_peq_profile."""
        mock_client.command.side_effect = WiiMConnectionError("timeout")

        with pytest.raises(WiiMConnectionError, match="timeout"):
            await adapter.delete_peq_profile("Test")


class TestDeleteRoomfitProfile:
    """Test delete_roomfit_profile — deleting a saved RoomFit profile.

    Per docs/wiim_api_notes.md, RoomFit profile deletion requires EQLevel: 2
    in the payload — without it the device targets the PEQ-profile
    namespace instead (corrections.md row 16).
    """

    async def test_delete_roomfit_profile_success(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """delete_roomfit_profile issues EQv2Delete with EQLevel: 2."""
        mock_client.command.return_value = "OK"

        await adapter.delete_roomfit_profile("Old RoomFit Profile")

        mock_client.command.assert_called_once()
        call_args = mock_client.command.call_args[0][0]
        assert call_args.startswith("EQv2Delete:")
        assert "Old" in call_args
        assert "EqNp" in call_args
        assert "EQLevel" in call_args

    async def test_delete_roomfit_profile_connection_error_propagates(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Connection errors propagate from delete_roomfit_profile."""
        mock_client.command.side_effect = WiiMConnectionError("timeout")

        with pytest.raises(WiiMConnectionError, match="timeout"):
            await adapter.delete_roomfit_profile("Test")


# ---------------------------------------------------------------------------
# Tests: read_roomfit — Level gating and real API commands
# ---------------------------------------------------------------------------


class TestReadRoomfit:
    """Test read_roomfit level gating and response parsing with real API commands."""

    @pytest.fixture
    def roomfit_read_capabilities(self) -> DeviceCapabilities:
        """Capabilities with RoomFit read supported."""
        return DeviceCapabilities(
            supports_peq=True,
            supports_roomfit=True,
            supports_roomfit_read=True,
            max_filters=10,
            model="WiiM_Ultra",
            firmware="6.0.1.20",
        )

    @pytest.fixture
    def low_roomfit_capabilities(self) -> DeviceCapabilities:
        """Capabilities with RoomFit present but read NOT supported."""
        return DeviceCapabilities(
            supports_peq=True,
            supports_roomfit=True,
            max_filters=10,
            model="WiiM_Mini",
            firmware="5.0.0.10",
        )

    async def test_read_roomfit_insufficient_level_raises(
        self, mock_client: AsyncMock, low_roomfit_capabilities: DeviceCapabilities
    ) -> None:
        """read_roomfit raises RoomFitUnsupportedError without read support."""
        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=low_roomfit_capabilities
        )

        with pytest.raises(RoomFitUnsupportedError, match="read"):
            await adapter.read_roomfit("wifi", "My Profile")

    async def test_read_roomfit_insufficient_level_no_commands(
        self, mock_client: AsyncMock, low_roomfit_capabilities: DeviceCapabilities
    ) -> None:
        """No HTTP commands issued when level is insufficient."""
        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=low_roomfit_capabilities
        )

        with pytest.raises(WiiMResponseError):
            await adapter.read_roomfit("wifi", "My Profile")

        mock_client.command.assert_not_called()

    async def test_read_roomfit_success(
        self, mock_client: AsyncMock, roomfit_read_capabilities: DeviceCapabilities
    ) -> None:
        """read_roomfit loads profile then reads bands via real API commands."""
        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=roomfit_read_capabilities
        )

        # First call: EQv2SourceLoad (load profile into buffer)
        # Second call: EQGetLV2SourceBandEx with EQLevel:2 (read bands)
        letters = "abcdefghij"
        bands: list[dict[str, str | float]] = []
        bands.extend(_make_band_params("a", 1, 80.0, 1.41, -4.0))
        for letter in letters[1:]:
            bands.extend(_make_band_params(letter, -1, 1000.0, 1.0, 0.0))

        mock_client.command.side_effect = [
            "OK",  # EQv2SourceLoad response
            {  # EQGetLV2SourceBandEx response
                "EQStat": "On",
                "channelMode": "Stereo",
                "Name": "My RoomFit",
                "EQBand": bands,
            },
        ]

        result = await adapter.read_roomfit("wifi", "My RoomFit")

        # Returns PEQSettings now
        assert result.channel_mode == ChannelMode.STEREO
        assert len(result.bands) == 10
        assert result.bands[0].type == "PEAK"
        assert result.bands[0].frequency_hz == 80.0
        assert result.bands[0].gain_db == -4.0

        # Verify the correct commands were issued
        calls = mock_client.command.call_args_list
        assert len(calls) == 2
        # First: load command (EQv2SourceLoad is profile CRUD -- source_name
        # omitted entirely, per docs/wiim_api_notes.md's source_name & EQLevel
        # Reference).
        assert "EQv2SourceLoad:" in calls[0][0][0]
        assert "EQLevel" in calls[0][0][0]
        assert "My%20RoomFit" in calls[0][0][0]
        assert "wifi" not in calls[0][0][0]
        first_payload = json.loads(unquote(calls[0][0][0].split(":", 1)[1]))
        assert "source_name" not in first_payload
        # Second: read command (band read/write requires source_name="" --
        # present but empty, not omitted; omitting it was the root cause of a
        # RoomFit-detection regression, see docs/corrections.md 2026-07-04).
        assert "EQGetLV2SourceBandEx:" in calls[1][0][0]
        assert "EQLevel" in calls[1][0][0]
        assert "wifi" not in calls[1][0][0]
        second_payload = json.loads(unquote(calls[1][0][0].split(":", 1)[1]))
        assert second_payload["source_name"] == ""


# ---------------------------------------------------------------------------
# Tests: write_roomfit — Level gating and real API commands
# ---------------------------------------------------------------------------


class TestWriteRoomfit:
    """Test write_roomfit level gating and real API commands."""

    @pytest.fixture
    def roomfit_write_capabilities(self) -> DeviceCapabilities:
        """Capabilities with RoomFit write support confirmed."""
        return DeviceCapabilities(
            supports_peq=True,
            supports_roomfit=True,
            supports_roomfit_read=True,
            supports_roomfit_write=True,
            max_filters=10,
            model="WiiM_Ultra",
            firmware="6.0.1.20",
        )

    @pytest.fixture
    def insufficient_write_capabilities(self) -> DeviceCapabilities:
        """Capabilities where the device never confirmed RoomFit read
        support -- write is gated on read (no write-probe exists)."""
        return DeviceCapabilities(
            supports_peq=True,
            supports_roomfit=True,
            max_filters=10,
            model="WiiM_Ultra",
            firmware="6.0.1.20",
        )

    @pytest.fixture
    def unconfirmed_write_capabilities(self) -> DeviceCapabilities:
        """Capabilities with read confirmed but write never confirmed --
        a real write attempt is allowed and serves as its own capability
        confirmation (there is no connect-time write probe)."""
        return DeviceCapabilities(
            supports_peq=True,
            supports_roomfit=True,
            supports_roomfit_read=True,
            max_filters=10,
            model="WiiM_Ultra",
            firmware="6.0.1.20",
        )

    async def test_write_roomfit_insufficient_level_raises(
        self, mock_client: AsyncMock, insufficient_write_capabilities: DeviceCapabilities
    ) -> None:
        """write_roomfit raises RoomFitUnsupportedError without read support."""
        from src.models.canonical import CanonicalFilter

        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=insufficient_write_capabilities
        )
        filters = [CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-2.0, q=1.0)]

        with pytest.raises(RoomFitUnsupportedError, match="write"):
            await adapter.write_roomfit("wifi", "My Profile", filters)

    async def test_write_roomfit_insufficient_level_no_commands(
        self, mock_client: AsyncMock, insufficient_write_capabilities: DeviceCapabilities
    ) -> None:
        """No HTTP commands issued when level is insufficient for write."""
        from src.models.canonical import CanonicalFilter

        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=insufficient_write_capabilities
        )
        filters = [CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-2.0, q=1.0)]

        with pytest.raises(WiiMResponseError):
            await adapter.write_roomfit("wifi", "My Profile", filters)

        mock_client.command.assert_not_called()

    async def test_write_roomfit_unconfirmed_write_allowed(
        self, mock_client: AsyncMock, unconfirmed_write_capabilities: DeviceCapabilities
    ) -> None:
        """#190/#191: a device with read confirmed but write unconfirmed is
        allowed to attempt a real write -- the gate only requires read
        support."""
        from src.models.canonical import CanonicalFilter

        mock_client.command.return_value = "OK"
        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=unconfirmed_write_capabilities
        )
        filters = [CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-2.0, q=1.0)]

        await adapter.write_roomfit("wifi", "My Profile", filters)

        mock_client.command.assert_called()

    async def test_write_roomfit_success(
        self, mock_client: AsyncMock, roomfit_write_capabilities: DeviceCapabilities
    ) -> None:
        """write_roomfit writes bands then saves to profile."""
        from src.models.canonical import CanonicalFilter

        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=roomfit_write_capabilities
        )
        filters = [
            CanonicalFilter(type="PEAK", frequency_hz=80.0, gain_db=-4.0, q=1.41),
            CanonicalFilter(type="LS", frequency_hz=120.0, gain_db=2.0, q=0.71),
        ]

        mock_client.command.side_effect = [
            {"mode": "AUDIO_OUTPUT_SPEAKER_MODE"},  # getActiveSoundCardOutputMode
            "OK",  # EQSetLV2SourceBand response
            "OK",  # EQSourceSave response
        ]

        await adapter.write_roomfit("wifi", "REW Export", filters)

        calls = mock_client.command.call_args_list
        assert len(calls) == 3
        assert calls[0][0][0] == "getActiveSoundCardOutputMode"
        # Second: write to buffer with EQLevel: 2. Band read/write requires
        # source_name="" -- present but empty, not omitted; omitting it was
        # the root cause of a RoomFit-detection regression (docs/corrections.md
        # 2026-07-04).
        assert "EQSetLV2SourceBand:" in calls[1][0][0]
        assert "EQLevel" in calls[1][0][0]
        assert "wifi" not in calls[1][0][0]
        write_payload = json.loads(unquote(calls[1][0][0].split(":", 1)[1]))
        assert write_payload["source_name"] == ""
        # rc_output reflects the live-queried active output mode; it does NOT
        # change the saved profile's Type field (always "Custom" for
        # app-saved profiles -- see the RoomFit "Quirk" note in
        # docs/wiim_api_notes.md and docs/corrections.md 2026-07-04).
        assert write_payload["rc_output"] == "AUDIO_OUTPUT_SPEAKER_MODE"
        # Third: save to profile (EQSourceSave is profile CRUD -- source_name
        # omitted entirely).
        assert "EQSourceSave:" in calls[2][0][0]
        assert "EQLevel" in calls[2][0][0]
        assert "REW%20Export" in calls[2][0][0]
        assert "wifi" not in calls[2][0][0]
        save_payload = json.loads(unquote(calls[2][0][0].split(":", 1)[1]))
        assert "source_name" not in save_payload

    async def test_write_roomfit_lr_success(
        self, mock_client: AsyncMock, roomfit_write_capabilities: DeviceCapabilities
    ) -> None:
        """L/R mode writes EQBandL/EQBandR with channelMode "L/R" -- same
        shape as the stereo path (test_write_roomfit_success) other than
        the band-payload keys, confirming the stereo/L-R branch
        consolidation didn't change either wire payload."""
        from src.models.canonical import CanonicalFilter

        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=roomfit_write_capabilities
        )
        filters_l = [CanonicalFilter(type="PEAK", frequency_hz=80.0, gain_db=-4.0, q=1.41)]
        filters_r = [CanonicalFilter(type="LS", frequency_hz=120.0, gain_db=2.0, q=0.71)]

        mock_client.command.side_effect = [
            {"mode": "AUDIO_OUTPUT_SPEAKER_MODE"},
            "OK",
            "OK",
        ]

        await adapter.write_roomfit(
            "wifi",
            "REW Export",
            filters=[],
            channel_mode="left",
            filters_l=filters_l,
            filters_r=filters_r,
        )

        calls = mock_client.command.call_args_list
        assert len(calls) == 3
        write_payload = json.loads(unquote(calls[1][0][0].split(":", 1)[1]))
        assert write_payload["channelMode"] == "L/R"
        assert "EQBandL" in write_payload
        assert "EQBandR" in write_payload
        assert "EQBand" not in write_payload
        assert write_payload["source_name"] == ""
        assert write_payload["rc_output"] == "AUDIO_OUTPUT_SPEAKER_MODE"

    async def test_write_roomfit_lr_empty_right_channel_stays_lr(
        self, mock_client: AsyncMock, roomfit_write_capabilities: DeviceCapabilities
    ) -> None:
        """A genuinely empty right channel (legitimate device read-state,
        restored as-is by RoomFitSafeWrite's rollback path) must still be
        written as channelMode "L/R" with an empty EQBandR, not silently
        misrouted into the Stereo branch. The prior `filters_l and
        filters_r` truthy check took the Stereo branch whenever either
        channel was empty -- writing the wrong channelMode and, on
        rollback, failing to restore the original asymmetric split
        (round-4 review finding #2, 2026-07-19)."""
        from src.models.canonical import CanonicalFilter

        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=roomfit_write_capabilities
        )
        filters_l = [CanonicalFilter(type="PEAK", frequency_hz=80.0, gain_db=-4.0, q=1.41)]

        mock_client.command.side_effect = [
            {"mode": "AUDIO_OUTPUT_SPEAKER_MODE"},
            "OK",
            "OK",
        ]

        await adapter.write_roomfit(
            "wifi",
            "REW Export",
            filters=[],
            channel_mode="left",
            filters_l=filters_l,
            filters_r=[],
        )

        calls = mock_client.command.call_args_list
        write_payload = json.loads(unquote(calls[1][0][0].split(":", 1)[1]))
        assert write_payload["channelMode"] == "L/R"
        assert "EQBandL" in write_payload
        assert "EQBandR" in write_payload
        assert "EQBand" not in write_payload

    async def test_write_roomfit_rejected_band_write_raises_before_save(
        self, mock_client: AsyncMock, roomfit_write_capabilities: DeviceCapabilities
    ) -> None:
        """An explicit device-side rejection of the band write (the same
        {"status": "Failed"} shape _is_write_rejection() already detects
        for the PEQ batch path) must raise WiiMResponseError immediately,
        before EQSourceSave is ever issued -- previously the response was
        discarded and the write proceeded straight to save regardless."""
        from src.models.canonical import CanonicalFilter

        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=roomfit_write_capabilities
        )
        filters = [CanonicalFilter(type="PEAK", frequency_hz=80.0, gain_db=-4.0, q=1.41)]

        mock_client.command.return_value = {"status": "Failed"}

        with pytest.raises(WiiMResponseError, match="rejected"):
            await adapter.write_roomfit("wifi", "REW Export", filters)

        # The output-mode query (call 0) also receives {"status": "Failed"}
        # -- a dict with no usable "mode" key, so it degrades gracefully to
        # rc_output being omitted rather than raising. Only the query and
        # the rejected band write were attempted -- EQSourceSave must not fire.
        assert mock_client.command.call_count == 2
        assert mock_client.command.call_args_list[0][0][0] == "getActiveSoundCardOutputMode"
        assert "EQSetLV2SourceBand:" in mock_client.command.call_args_list[1][0][0]

    @pytest.mark.parametrize(
        "first_response, expected_rc_output",
        [
            # Real mode reported -- rc_output is no longer a fixed constant,
            # it reflects whatever getActiveSoundCardOutputMode reports as
            # the device's current output, e.g. AUX on a WiiM Ultra
            # (docs/corrections.md, 2026-07-20).
            ({"mode": "AUDIO_OUTPUT_AUX_MODE"}, "AUDIO_OUTPUT_AUX_MODE"),
            # Query raises (network error, unsupported command on older
            # firmware) -- omit rc_output, never fall back to the old
            # hard-coded value, which is confirmed wrong on non-Speaker
            # devices.
            (WiiMConnectionError("device unreachable"), None),
            # Bare non-dict response (generic-LinkPlay "unknown command"
            # shape) -- omit rc_output, don't raise.
            ("unknown command", None),
            # Dict response without a usable 'mode' key -- omit rc_output,
            # don't raise or write a bogus value.
            ({"audioCast": "0", "btSource": "0"}, None),
        ],
    )
    async def test_write_roomfit_rc_output_reflects_queried_mode(
        self,
        mock_client: AsyncMock,
        roomfit_write_capabilities: DeviceCapabilities,
        first_response: object,
        expected_rc_output: str | None,
    ) -> None:
        """rc_output is populated from the live getActiveSoundCardOutputMode
        query on success, and omitted entirely (never defaulted) on any
        failure shape."""
        from src.models.canonical import CanonicalFilter

        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=roomfit_write_capabilities
        )
        filters = [CanonicalFilter(type="PEAK", frequency_hz=80.0, gain_db=-4.0, q=1.41)]

        mock_client.command.side_effect = [first_response, "OK", "OK"]

        await adapter.write_roomfit("wifi", "REW Export", filters)

        calls = mock_client.command.call_args_list
        write_payload = json.loads(unquote(calls[1][0][0].split(":", 1)[1]))
        if expected_rc_output is None:
            assert "rc_output" not in write_payload
        else:
            assert write_payload["rc_output"] == expected_rc_output


class TestQueryActiveOutputMode:
    """Test the private _query_active_output_mode() helper directly (same
    pattern as TestRequireRoomfit calling _require_roomfit() directly)."""

    async def test_returns_mode_string(self, adapter: WiiMAdapter, mock_client: AsyncMock) -> None:
        mock_client.command.return_value = {"mode": "AUDIO_OUTPUT_COAX_MODE"}

        result = await adapter._query_active_output_mode()

        assert result == "AUDIO_OUTPUT_COAX_MODE"
        assert mock_client.command.call_args[0][0] == "getActiveSoundCardOutputMode"

    @pytest.mark.parametrize(
        "response",
        [
            "unknown command",
            {"audioCast": "0"},
            {"mode": ""},
            {"mode": None},
            {"mode": 123},
        ],
    )
    async def test_returns_none_on_unusable_response(
        self, adapter: WiiMAdapter, mock_client: AsyncMock, response: object
    ) -> None:
        mock_client.command.return_value = response

        result = await adapter._query_active_output_mode()

        assert result is None

    async def test_returns_none_on_raise(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        mock_client.command.side_effect = WiiMConnectionError("device unreachable")

        result = await adapter._query_active_output_mode()

        assert result is None


class TestRequireRoomfit:
    """Test the shared _require_roomfit() gate used by every RoomFit method
    (get_roomfit_status/list_roomfit_profiles -> "supported",
    read_roomfit/write_roomfit -> "read") -- extracted to replace four
    hand-rolled duplicates of the same check. Callers branch on the
    RoomFitUnsupportedError *type*, never the message text."""

    def test_passes_when_capability_present(self, adapter: WiiMAdapter) -> None:
        adapter.capabilities.supports_roomfit_read = True
        adapter._require_roomfit("read", "read")  # does not raise

    def test_raises_typed_error_when_capability_absent(
        self, adapter: WiiMAdapter
    ) -> None:
        adapter.capabilities.supports_roomfit_read = False
        with pytest.raises(RoomFitUnsupportedError):
            adapter._require_roomfit("read", "read")

    def test_is_a_wiim_response_error(self, adapter: WiiMAdapter) -> None:
        """Existing except-WiiMResponseError handlers keep working."""
        adapter.capabilities.supports_roomfit = False
        with pytest.raises(WiiMResponseError):
            adapter._require_roomfit("supported", "status")

    def test_error_message_includes_operation(self, adapter: WiiMAdapter) -> None:
        adapter.capabilities.supports_roomfit = False
        with pytest.raises(RoomFitUnsupportedError, match="status"):
            adapter._require_roomfit("supported", "status")


# ---------------------------------------------------------------------------
# Tests: list_roomfit_profiles
# ---------------------------------------------------------------------------


class TestListRoomfitProfiles:
    """Test list_roomfit_profiles method."""

    @pytest.fixture
    def roomfit_capabilities(self) -> DeviceCapabilities:
        """Capabilities with RoomFit present (profile listing supported)."""
        return DeviceCapabilities(
            supports_peq=True,
            supports_roomfit=True,
            max_filters=10,
            model="WiiM_Ultra",
            firmware="6.0.1.20",
        )

    @pytest.fixture
    def no_roomfit_capabilities(self) -> DeviceCapabilities:
        """Capabilities with RoomFit not supported."""
        return DeviceCapabilities(
            supports_peq=True,
            max_filters=10,
            model="WiiM_Mini",
            firmware="5.0.0.10",
        )

    async def test_list_roomfit_profiles_success(
        self, mock_client: AsyncMock, roomfit_capabilities: DeviceCapabilities
    ) -> None:
        """list_roomfit_profiles returns the custom profiles list."""
        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=roomfit_capabilities
        )

        mock_client.command.return_value = {
            "custom": [
                {"Name": "My RoomFit Profile", "channelMode": "L/R", "Type": "RC"},
                {"Name": "User Profile", "channelMode": "Stereo", "Type": "Custom"},
            ],
            "preset": [],
        }

        result = await adapter.list_roomfit_profiles("wifi")

        assert len(result) == 2
        assert result[0]["Name"] == "My RoomFit Profile"
        assert result[0]["channelMode"] == "L/R"
        assert result[0]["Type"] == "RC"
        assert result[1]["Name"] == "User Profile"

        # Verify command contains EQLevel: 2
        call_args = mock_client.command.call_args[0][0]
        assert "EQv2GetNewList:" in call_args
        assert "EQLevel" in call_args

    async def test_list_roomfit_profiles_level_too_low(
        self, mock_client: AsyncMock, no_roomfit_capabilities: DeviceCapabilities
    ) -> None:
        """list_roomfit_profiles raises without RoomFit support."""
        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=no_roomfit_capabilities
        )

        with pytest.raises(RoomFitUnsupportedError):
            await adapter.list_roomfit_profiles("wifi")

        mock_client.command.assert_not_called()

    async def test_list_roomfit_profiles_empty(
        self, mock_client: AsyncMock, roomfit_capabilities: DeviceCapabilities
    ) -> None:
        """list_roomfit_profiles returns empty list when no profiles exist."""
        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=roomfit_capabilities
        )

        mock_client.command.return_value = {"custom": [], "preset": []}

        result = await adapter.list_roomfit_profiles("wifi")

        assert result == []


# ---------------------------------------------------------------------------
# Tests: write_peq — L/R batch path (hardware testing regression)
# ---------------------------------------------------------------------------


class TestWritePeqLRBatch:
    """Test PEQ L/R write via batch path (supports_batch_write=True)."""

    @pytest.fixture
    def lr_batch_capabilities(self) -> DeviceCapabilities:
        """Capabilities with batch write and channel PEQ support."""
        return DeviceCapabilities(
            supports_peq=True,
            supports_batch_write=True,
            supports_lr_filters=True,
            max_filters=10,
            model="WiiM_Ultra",
            firmware="6.0.1.20",
        )

    @pytest.fixture
    def lr_batch_adapter(
        self, mock_client: AsyncMock, lr_batch_capabilities: DeviceCapabilities
    ) -> WiiMAdapter:
        """Adapter configured for batch L/R write."""
        return WiiMAdapter(http_client=mock_client, capabilities=lr_batch_capabilities)

    def _make_lr_settings(self) -> PEQSettings:
        """Create L/R PEQSettings for testing."""
        from src.models.canonical import CanonicalFilter

        bands_l = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-3.0, q=1.0),
            CanonicalFilter(type="LS", frequency_hz=200.0, gain_db=2.0, q=0.71),
        ]
        bands_r = [
            CanonicalFilter(type="PEAK", frequency_hz=150.0, gain_db=-2.0, q=1.2),
            CanonicalFilter(type="HS", frequency_hz=8000.0, gain_db=1.5, q=0.5),
        ]
        return PEQSettings(
            source_name="wifi",
            enabled=True,
            channel_mode="lr",
            bands_l=bands_l,
            bands_r=bands_r,
        )

    async def test_write_peq_lr_batch_sends_both_channels(
        self, lr_batch_adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Batch L/R write payload contains both EQBandL and EQBandR keys."""
        mock_client.command.return_value = "OK"
        settings = self._make_lr_settings()

        await lr_batch_adapter.write_peq("wifi", settings)

        assert mock_client.command.call_count == 1
        batch_call = mock_client.command.call_args_list[0][0][0]
        assert "EQSetLV2SourceBand:" in batch_call
        assert "EQBandL" in batch_call
        assert "EQBandR" in batch_call

    async def test_write_peq_lr_sets_channel_mode_inline(
        self, lr_batch_adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Writing L/R mode sets channelMode:'L/R' inline on the EQSetLV2SourceBand call."""
        mock_client.command.return_value = "OK"
        settings = self._make_lr_settings()

        await lr_batch_adapter.write_peq("wifi", settings)

        call = mock_client.command.call_args_list[0][0][0]
        assert "L%2FR" in call or "L/R" in call

    async def test_write_peq_lr_empty_right_channel_not_flattened_to_left(
        self, lr_batch_adapter: WiiMAdapter
    ) -> None:
        """An L/R PEQSettings with a genuinely empty right channel (valid
        device read-state -- see WiiMAdapter._parse_lr(), which builds
        bands_l/bands_r independently from parsed device data) must write
        an empty right channel, not silently copy the left channel's bands
        into it. safe_write.py's rollback path restores exactly this kind
        of settings object (as read from the device before the write), so
        flattening here would corrupt the state recoverability is meant to
        restore (branch-quality review, flagged-not-changed #2, 2026-07-18).
        """
        from src.models.canonical import CanonicalFilter
        from src.translator.wiim_generator import generate_wiim_band_array

        bands_l = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-3.0, q=1.0),
        ]
        settings = PEQSettings(
            source_name="wifi",
            enabled=True,
            channel_mode="lr",
            bands_l=bands_l,
            bands_r=[],
        )

        with patch.object(
            lr_batch_adapter, "_write_peq_batch", new=AsyncMock(return_value="OK")
        ) as mock_batch:
            await lr_batch_adapter.write_peq("wifi", settings)

        band_array_l = mock_batch.call_args[0][1]
        band_array_r = mock_batch.call_args[0][2]
        expected_empty_r, _ = generate_wiim_band_array([], max_bands=10)

        assert band_array_r == expected_empty_r
        assert band_array_r != band_array_l


# ---------------------------------------------------------------------------
# Tests: write_peq — L/R sequential path (hardware testing regression)
# ---------------------------------------------------------------------------


class TestWritePeqLRSequential:
    """Test PEQ L/R write via sequential path (supports_batch_write=False)."""

    @pytest.fixture
    def lr_seq_capabilities(self) -> DeviceCapabilities:
        """Capabilities without batch write support."""
        return DeviceCapabilities(
            supports_peq=True,
            supports_batch_write=False,
            supports_lr_filters=True,
            max_filters=10,
            model="WiiM_Pro",
            firmware="5.0.0.10",
        )

    @pytest.fixture
    def lr_seq_adapter(
        self, mock_client: AsyncMock, lr_seq_capabilities: DeviceCapabilities
    ) -> WiiMAdapter:
        """Adapter configured for sequential L/R write."""
        return WiiMAdapter(http_client=mock_client, capabilities=lr_seq_capabilities)

    def _make_lr_settings(self) -> PEQSettings:
        """Create L/R PEQSettings for testing."""
        from src.models.canonical import CanonicalFilter

        bands_l = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-3.0, q=1.0),
        ]
        bands_r = [
            CanonicalFilter(type="PEAK", frequency_hz=150.0, gain_db=-2.0, q=1.2),
        ]
        return PEQSettings(
            source_name="wifi",
            enabled=True,
            channel_mode="lr",
            bands_l=bands_l,
            bands_r=bands_r,
        )

    async def test_write_peq_lr_sequential_sends_both_channels(
        self, lr_seq_adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Sequential L/R write: each command contains both EQBandL and EQBandR."""
        mock_client.command.return_value = "OK"
        settings = self._make_lr_settings()

        await lr_seq_adapter.write_peq("wifi", settings, queue=None)

        # 10 band writes
        assert mock_client.command.call_count == 10
        # Each band write should contain both L and R data
        for call in mock_client.command.call_args_list:
            cmd = call[0][0]
            assert "EQBandL" in cmd
            assert "EQBandR" in cmd


# ---------------------------------------------------------------------------
# Tests: EQSetLV2ChannelMode is never issued (confirmed dead command, see
# docs/corrections.md 2026-07-04 — channelMode is set inline on the write)
# ---------------------------------------------------------------------------


class TestNoStandaloneChannelModeCommand:
    """Regression guard: write_peq must never issue EQSetLV2ChannelMode."""

    @pytest.fixture
    def batch_capabilities(self) -> DeviceCapabilities:
        """Capabilities with batch write support."""
        return DeviceCapabilities(
            supports_peq=True,
            supports_batch_write=True,
            supports_lr_filters=True,
            max_filters=10,
            model="WiiM_Ultra",
            firmware="6.0.1.20",
        )

    @pytest.fixture
    def batch_adapter(
        self, mock_client: AsyncMock, batch_capabilities: DeviceCapabilities
    ) -> WiiMAdapter:
        """Adapter configured for batch write."""
        return WiiMAdapter(http_client=mock_client, capabilities=batch_capabilities)

    async def test_stereo_write_does_not_call_channel_mode_command(
        self, batch_adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Writing stereo settings never issues EQSetLV2ChannelMode."""
        from src.models.canonical import CanonicalFilter

        mock_client.command.return_value = "OK"
        settings = PEQSettings(
            source_name="wifi",
            enabled=True,
            channel_mode="stereo",
            bands=[CanonicalFilter(type="PEAK", frequency_hz=80.0, gain_db=-4.0, q=1.41)],
        )

        await batch_adapter.write_peq("wifi", settings)

        calls = [c[0][0] for c in mock_client.command.call_args_list]
        assert not any("EQSetLV2ChannelMode:" in call for call in calls)

    async def test_lr_write_does_not_call_channel_mode_command(
        self, batch_adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Writing L/R settings never issues EQSetLV2ChannelMode."""
        from src.models.canonical import CanonicalFilter

        mock_client.command.return_value = "OK"
        settings = PEQSettings(
            source_name="wifi",
            enabled=True,
            channel_mode="lr",
            bands_l=[CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-3.0, q=1.0)],
            bands_r=[CanonicalFilter(type="PEAK", frequency_hz=150.0, gain_db=-2.0, q=1.2)],
        )

        await batch_adapter.write_peq("wifi", settings)

        calls = [c[0][0] for c in mock_client.command.call_args_list]
        assert not any("EQSetLV2ChannelMode:" in call for call in calls)


# ---------------------------------------------------------------------------
# Tests: PEQ Enable/Disable Toggle
# ---------------------------------------------------------------------------


class TestEnablePeq:
    """Test enable_peq — enabling PEQ on a source via EQChangeSourceFX."""

    async def test_enable_peq_sends_correct_command(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """enable_peq issues EQChangeSourceFX with source_name and pluginURI."""
        mock_client.command.return_value = "OK"

        await adapter.enable_peq("wifi")

        mock_client.command.assert_called_once()
        call_args = mock_client.command.call_args[0][0]
        assert call_args.startswith("EQChangeSourceFX:")
        assert "wifi" in call_args
        assert "EqNp" in call_args

    async def test_enable_peq_returns_none_on_success(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """enable_peq returns None on successful call."""
        mock_client.command.return_value = "OK"

        await adapter.enable_peq("wifi")
        # enable_peq is declared -> None; no return value to check

    async def test_enable_peq_connection_error_propagates(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """WiiMConnectionError propagates from enable_peq."""
        mock_client.command.side_effect = WiiMConnectionError("timeout")

        with pytest.raises(WiiMConnectionError, match="timeout"):
            await adapter.enable_peq("wifi")

    async def test_enable_peq_response_error_on_failure(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """enable_peq raises WiiMResponseError when response contains error."""
        mock_client.command.side_effect = WiiMResponseError("HTTP 500")

        with pytest.raises(WiiMResponseError):
            await adapter.enable_peq("wifi")


class TestDisablePeq:
    """Test disable_peq — disabling PEQ on a source via EQSourceOff."""

    async def test_disable_peq_sends_correct_command(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """disable_peq issues EQSourceOff with source_name and pluginURI."""
        mock_client.command.return_value = "OK"

        await adapter.disable_peq("wifi")

        mock_client.command.assert_called_once()
        call_args = mock_client.command.call_args[0][0]
        assert call_args.startswith("EQSourceOff:")
        assert "wifi" in call_args
        assert "EqNp" in call_args

    async def test_disable_peq_returns_none_on_success(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """disable_peq returns None on successful call."""
        mock_client.command.return_value = "OK"

        await adapter.disable_peq("wifi")
        # disable_peq is declared -> None; no return value to check

    async def test_disable_peq_connection_error_propagates(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """WiiMConnectionError propagates from disable_peq."""
        mock_client.command.side_effect = WiiMConnectionError("timeout")

        with pytest.raises(WiiMConnectionError, match="timeout"):
            await adapter.disable_peq("wifi")

    async def test_disable_peq_response_error_on_failure(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """disable_peq raises WiiMResponseError when device returns error."""
        mock_client.command.side_effect = WiiMResponseError("HTTP 500")

        with pytest.raises(WiiMResponseError):
            await adapter.disable_peq("wifi")


class TestEnableRoomfit:
    """Test enable_roomfit — enabling RoomFit's global toggle via EQChangeSourceFX."""

    async def test_enable_roomfit_sends_correct_command(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """enable_roomfit issues EQChangeSourceFX with empty source_name and EQLevel:2."""
        mock_client.command.return_value = "OK"

        await adapter.enable_roomfit()

        mock_client.command.assert_called_once()
        call_args = mock_client.command.call_args[0][0]
        assert call_args.startswith("EQChangeSourceFX:")
        assert "EqNp" in call_args

    async def test_enable_roomfit_connection_error_propagates(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """WiiMConnectionError propagates from enable_roomfit."""
        mock_client.command.side_effect = WiiMConnectionError("timeout")

        with pytest.raises(WiiMConnectionError, match="timeout"):
            await adapter.enable_roomfit()

    async def test_enable_roomfit_response_error_on_failure(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """enable_roomfit raises WiiMResponseError when device returns error."""
        mock_client.command.side_effect = WiiMResponseError("HTTP 500")

        with pytest.raises(WiiMResponseError):
            await adapter.enable_roomfit()


class TestDisableRoomfit:
    """Test disable_roomfit — disabling RoomFit's global toggle via EQSourceOff."""

    async def test_disable_roomfit_sends_correct_command(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """disable_roomfit issues EQSourceOff with empty source_name and EQLevel:2."""
        mock_client.command.return_value = "OK"

        await adapter.disable_roomfit()

        mock_client.command.assert_called_once()
        call_args = mock_client.command.call_args[0][0]
        assert call_args.startswith("EQSourceOff:")
        assert "EqNp" in call_args

    async def test_disable_roomfit_connection_error_propagates(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """WiiMConnectionError propagates from disable_roomfit."""
        mock_client.command.side_effect = WiiMConnectionError("timeout")

        with pytest.raises(WiiMConnectionError, match="timeout"):
            await adapter.disable_roomfit()


class TestSetRoomfitEnabled:
    """Test set_roomfit_enabled — the bool-driven enable/disable wrapper."""

    async def test_set_roomfit_enabled_true_calls_enable(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        mock_client.command.return_value = "OK"

        await adapter.set_roomfit_enabled(True)

        call_args = mock_client.command.call_args[0][0]
        assert call_args.startswith("EQChangeSourceFX:")

    async def test_set_roomfit_enabled_false_calls_disable(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        mock_client.command.return_value = "OK"

        await adapter.set_roomfit_enabled(False)

        call_args = mock_client.command.call_args[0][0]
        assert call_args.startswith("EQSourceOff:")


class TestSetPeqEnabled:
    """Test set_peq_enabled — the bool-driven per-source PEQ enable/disable
    wrapper (#192), mirroring set_roomfit_enabled()."""

    async def test_set_peq_enabled_true_calls_enable(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        mock_client.command.return_value = "OK"

        await adapter.set_peq_enabled("wifi", True)

        call_args = mock_client.command.call_args[0][0]
        assert call_args.startswith("EQChangeSourceFX:")
        assert "wifi" in call_args

    async def test_set_peq_enabled_false_calls_disable(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        mock_client.command.return_value = "OK"

        await adapter.set_peq_enabled("wifi", False)

        call_args = mock_client.command.call_args[0][0]
        assert call_args.startswith("EQSourceOff:")
        assert "wifi" in call_args


class TestSetPeqEnabledBestEffort:
    """Test set_peq_enabled_best_effort — the try/except/log wrapper shared
    by SafeWrite's success/rollback/undo paths (safe_write.py) and
    read_peq_preset_preview() (this file), consolidated so the pattern can't
    independently drift the way RoomFit's equivalent did before being
    consolidated into restore_roomfit_selection_and_enable_state() (#192)."""

    async def test_delegates_to_set_peq_enabled(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        mock_client.command.return_value = "OK"

        await adapter.set_peq_enabled_best_effort("wifi", True, context="test")

        call_args = mock_client.command.call_args[0][0]
        assert call_args.startswith("EQChangeSourceFX:")

    async def test_swallows_and_logs_failure(
        self,
        adapter: WiiMAdapter,
        mock_client: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        mock_client.command.side_effect = WiiMConnectionError("boom")

        logger = logging.getLogger("wiim_rew_sync.wiim_api")
        logger.propagate = True
        try:
            with caplog.at_level(logging.WARNING, logger="wiim_rew_sync.wiim_api"):
                await adapter.set_peq_enabled_best_effort(
                    "wifi", False, context="after rollback"
                )
        finally:
            logger.propagate = False

        assert any(
            "Failed to disable PEQ" in rec.message and "after rollback" in rec.message
            for rec in caplog.records
        )


class TestGetPeqEnabled:
    """Test get_peq_enabled — reading PEQ enabled state from EQStat field."""

    async def test_get_peq_enabled_returns_true_when_on(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """get_peq_enabled returns True when EQStat is 'On'."""
        mock_client.command.return_value = {
            "EQStat": "On",
            "channelMode": "Stereo",
            "EQBand": [],
        }

        result = await adapter.get_peq_enabled("wifi")

        assert result is True

    async def test_get_peq_enabled_returns_false_when_off(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """get_peq_enabled returns False when EQStat is 'Off'."""
        mock_client.command.return_value = {
            "EQStat": "Off",
            "channelMode": "Stereo",
            "EQBand": [],
        }

        result = await adapter.get_peq_enabled("wifi")

        assert result is False

    async def test_get_peq_enabled_returns_false_when_missing(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """get_peq_enabled returns False when EQStat field is missing."""
        mock_client.command.return_value = {
            "channelMode": "Stereo",
            "EQBand": [],
        }

        result = await adapter.get_peq_enabled("wifi")

        assert result is False

    async def test_get_peq_enabled_non_dict_raises(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """get_peq_enabled raises WiiMResponseError for non-dict response."""
        mock_client.command.return_value = "unknown command"

        with pytest.raises(WiiMResponseError, match="Expected JSON dict"):
            await adapter.get_peq_enabled("wifi")

    async def test_get_peq_enabled_connection_error_propagates(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """WiiMConnectionError propagates from get_peq_enabled."""
        mock_client.command.side_effect = WiiMConnectionError("timeout")

        with pytest.raises(WiiMConnectionError, match="timeout"):
            await adapter.get_peq_enabled("wifi")


# ---------------------------------------------------------------------------
# Tests: get_roomfit_status (#165)
# ---------------------------------------------------------------------------


class TestGetRoomfitStatus:
    """Test get_roomfit_status — global RoomFit on/off + active-profile query."""

    @pytest.fixture
    def roomfit_status_capabilities(self) -> DeviceCapabilities:
        """Capabilities with RoomFit present (status query supported)."""
        return DeviceCapabilities(
            supports_peq=True,
            supports_roomfit=True,
            max_filters=10,
            model="WiiM_Ultra",
            firmware="6.0.1.20",
        )

    async def test_returns_enabled_and_active_name(
        self, mock_client: AsyncMock, roomfit_status_capabilities: DeviceCapabilities
    ) -> None:
        """Returns (True, name) when RoomFit is on with an active profile."""
        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=roomfit_status_capabilities
        )
        mock_client.command.return_value = {"EQStat": "On", "Name": "Living Room"}

        enabled, name = await adapter.get_roomfit_status()

        assert enabled is True
        assert name == "Living Room"

    async def test_returns_disabled_and_empty_name(
        self, mock_client: AsyncMock, roomfit_status_capabilities: DeviceCapabilities
    ) -> None:
        """Returns (False, "") when RoomFit is off with no active profile."""
        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=roomfit_status_capabilities
        )
        mock_client.command.return_value = {"EQStat": "Off", "Name": ""}

        enabled, name = await adapter.get_roomfit_status()

        assert enabled is False
        assert name == ""

    async def test_issues_correct_command(
        self, mock_client: AsyncMock, roomfit_status_capabilities: DeviceCapabilities
    ) -> None:
        """Uses EQLevel:2 with an explicit empty source_name (global scope)."""
        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=roomfit_status_capabilities
        )
        mock_client.command.return_value = {"EQStat": "On", "Name": "Living Room"}

        await adapter.get_roomfit_status()

        command = mock_client.command.call_args[0][0]
        assert "EQGetLV2SourceBandEx:" in command
        assert "EQLevel" in command
        assert "source_name" in command  # explicit "" -- distinct from omitting it

    async def test_insufficient_level_raises(self) -> None:
        """Raises RoomFitUnsupportedError without RoomFit support."""
        mock_client = AsyncMock(spec=WiiMHttpClient)
        caps = DeviceCapabilities(supports_peq=True, max_filters=10)
        adapter = WiiMAdapter(http_client=mock_client, capabilities=caps)

        with pytest.raises(RoomFitUnsupportedError):
            await adapter.get_roomfit_status()

        mock_client.command.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: read_peq_preset_preview / read_roomfit_preset_preview (#166)
# ---------------------------------------------------------------------------


class TestReadPeqPresetPreview:
    """Test read_peq_preset_preview — preview a saved PEQ preset, then restore."""

    async def test_loads_then_restores_original(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Loads the target preset, reads it, then restores the original
        (both name and enable-state, #192)."""
        original_response = {
            "EQStat": "On", "channelMode": "Stereo", "Name": "Original", "EQBand": [],
        }
        preview_response = {
            "EQStat": "On", "channelMode": "Stereo", "Name": "Preview", "EQBand": [],
        }
        mock_client.command.side_effect = [
            original_response,  # read_peq (original)
            "OK",  # load_peq_profile (target)
            preview_response,  # read_peq (preview)
            "OK",  # load_peq_profile (restore original)
            "OK",  # set_peq_enabled(True) (restore original enable-state)
        ]

        result = await adapter.read_peq_preset_preview("wifi", "Preview")

        assert result.name == "Preview"
        calls = mock_client.command.call_args_list
        assert len(calls) == 5
        assert "EQGetLV2SourceBandEx:" in calls[0][0][0]
        assert "EQv2SourceLoad:" in calls[1][0][0]
        assert "Preview" in calls[1][0][0]
        assert "EQGetLV2SourceBandEx:" in calls[2][0][0]
        assert "EQv2SourceLoad:" in calls[3][0][0]
        assert "Original" in calls[3][0][0]
        assert "EQChangeSourceFX" in calls[4][0][0]

    async def test_restores_enable_state_when_it_had_been_disabled(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """#192: previewing on a source where PEQ was OFF must leave it OFF
        afterward -- defensive fix mirroring the hardware-confirmed RoomFit
        finding, since load_peq_profile() wraps the same EQv2SourceLoad
        command family."""
        original_response = {
            "EQStat": "Off", "channelMode": "Stereo", "Name": "Original", "EQBand": [],
        }
        preview_response = {
            "EQStat": "On", "channelMode": "Stereo", "Name": "Preview", "EQBand": [],
        }
        mock_client.command.side_effect = [
            original_response,
            "OK",
            preview_response,
            "OK",
            "OK",  # set_peq_enabled(False)
        ]

        await adapter.read_peq_preset_preview("wifi", "Preview")

        calls = mock_client.command.call_args_list
        assert len(calls) == 5
        assert "EQSourceOff" in calls[4][0][0]

    async def test_skips_restore_when_same_preset(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """No name-restore call when the target preset is already active,
        but enable-state is still unconditionally restored."""
        same_response = {
            "EQStat": "On", "channelMode": "Stereo", "Name": "Preview", "EQBand": [],
        }
        mock_client.command.side_effect = [
            same_response,  # read_peq (original == target)
            "OK",  # load_peq_profile (target)
            same_response,  # read_peq (preview)
            "OK",  # set_peq_enabled(True)
        ]

        await adapter.read_peq_preset_preview("wifi", "Preview")

        assert mock_client.command.call_count == 4

    async def test_restores_via_write_peq_when_original_unnamed(
        self, mock_client: AsyncMock
    ) -> None:
        """Falls back to write_peq() to restore raw bands when the original
        active state has no saved-preset name to reload by (e.g. filters
        pushed directly without ever being saved as a named preset) -- the
        confirmation dialog's "restore what was playing" promise must hold
        even when there's no name to reload."""
        batch_capabilities = DeviceCapabilities(
            supports_peq=True,
            supports_batch_write=True,
            supports_lr_filters=True,
            max_filters=10,
            model="WiiM_Ultra",
            firmware="6.0.1.20",
        )
        adapter = WiiMAdapter(http_client=mock_client, capabilities=batch_capabilities)
        unnamed_response = {
            "EQStat": "On", "channelMode": "Stereo", "Name": "", "EQBand": [],
        }
        preview_response = {
            "EQStat": "On", "channelMode": "Stereo", "Name": "Preview", "EQBand": [],
        }
        mock_client.command.side_effect = [
            unnamed_response,  # read_peq (original, no name)
            "OK",  # load_peq_profile (target)
            preview_response,  # read_peq (preview)
            "OK",  # _write_peq_batch (restore via write_peq)
            "OK",  # set_peq_enabled(True)
        ]

        await adapter.read_peq_preset_preview("wifi", "Preview")

        calls = mock_client.command.call_args_list
        assert len(calls) == 5
        assert "EQSetLV2SourceBand:" in calls[3][0][0]

    async def test_restore_failure_is_logged_not_raised(
        self, adapter: WiiMAdapter, mock_client: AsyncMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A failed restore attempt is logged as a warning, not propagated --
        the caller already has the successfully-read preview to return."""
        import logging

        original_response = {
            "EQStat": "On", "channelMode": "Stereo", "Name": "Original", "EQBand": [],
        }
        preview_response = {
            "EQStat": "On", "channelMode": "Stereo", "Name": "Preview", "EQBand": [],
        }

        async def side_effect(_command: str) -> dict | str:
            calls = mock_client.command.call_count
            if calls == 1:
                return original_response
            if calls == 2:
                return "OK"
            if calls == 3:
                return preview_response
            raise WiiMConnectionError("restore failed")

        mock_client.command.side_effect = side_effect

        logger = logging.getLogger("wiim_rew_sync.wiim_api")
        logger.propagate = True
        try:
            with caplog.at_level(logging.WARNING, logger="wiim_rew_sync.wiim_api"):
                result = await adapter.read_peq_preset_preview("wifi", "Preview")
        finally:
            logger.propagate = False

        assert result.name == "Preview"
        assert any("Failed to restore" in rec.message for rec in caplog.records)


class TestReadRoomfitPresetPreview:
    """Test read_roomfit_preset_preview — preview a RoomFit profile, then restore."""

    @pytest.fixture
    def roomfit_preview_capabilities(self) -> DeviceCapabilities:
        """Capabilities with RoomFit read + status supported."""
        return DeviceCapabilities(
            supports_peq=True,
            supports_roomfit=True,
            supports_roomfit_read=True,
            max_filters=10,
            model="WiiM_Ultra",
            firmware="6.0.1.20",
        )

    async def test_loads_then_restores_original_selection_and_enable_state(
        self, mock_client: AsyncMock, roomfit_preview_capabilities: DeviceCapabilities
    ) -> None:
        """Loads the target profile, reads it, then restores the original
        selection AND on/off state (#192 -- previously only selection was
        restored, leaving RoomFit enabled if it had been off)."""
        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=roomfit_preview_capabilities
        )
        status_response = {"EQStat": "Off", "Name": "Original"}
        load_target_response = "OK"
        band_response = {
            "EQStat": "Off", "channelMode": "Stereo", "Name": "Preview", "EQBand": [],
        }
        restore_response = "OK"
        disable_response = "OK"
        mock_client.command.side_effect = [
            status_response,  # get_roomfit_status
            load_target_response,  # load_roomfit_profile (target, via read_roomfit)
            band_response,  # EQGetLV2SourceBandEx (via read_roomfit)
            restore_response,  # load_roomfit_profile (restore original selection)
            disable_response,  # set_roomfit_enabled(False) (restore original Off state)
        ]

        result = await adapter.read_roomfit_preset_preview("wifi", "Preview")

        assert result.name == "Preview"
        calls = mock_client.command.call_args_list
        assert len(calls) == 5
        assert "Original" in calls[3][0][0]
        assert "EQSourceOff" in calls[4][0][0]

    async def test_skips_selection_restore_but_still_restores_enable_state(
        self, mock_client: AsyncMock, roomfit_preview_capabilities: DeviceCapabilities
    ) -> None:
        """No selection-restore call when the target profile is already
        selected, but enable-state is still unconditionally restored."""
        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=roomfit_preview_capabilities
        )
        status_response = {"EQStat": "Off", "Name": "Preview"}
        band_response = {
            "EQStat": "Off", "channelMode": "Stereo", "Name": "Preview", "EQBand": [],
        }
        mock_client.command.side_effect = [
            status_response,  # get_roomfit_status (already "Preview")
            "OK",  # load_roomfit_profile (target, via read_roomfit)
            band_response,  # EQGetLV2SourceBandEx (via read_roomfit)
            "OK",  # set_roomfit_enabled(False)
        ]

        await adapter.read_roomfit_preset_preview("wifi", "Preview")

        calls = mock_client.command.call_args_list
        assert len(calls) == 4
        assert "EQSourceOff" in calls[3][0][0]

    async def test_restore_failure_is_logged_not_raised(
        self,
        mock_client: AsyncMock,
        roomfit_preview_capabilities: DeviceCapabilities,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A failed restore attempt (selection or enable-state) is logged as
        a warning, not propagated."""
        import logging

        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=roomfit_preview_capabilities
        )
        status_response = {"EQStat": "Off", "Name": "Original"}
        band_response = {
            "EQStat": "Off", "channelMode": "Stereo", "Name": "Preview", "EQBand": [],
        }

        async def side_effect(_command: str) -> dict | str:
            calls = mock_client.command.call_count
            if calls == 1:
                return status_response
            if calls == 2:
                return "OK"
            if calls == 3:
                return band_response
            raise WiiMConnectionError("restore failed")

        mock_client.command.side_effect = side_effect

        logger = logging.getLogger("wiim_rew_sync.wiim_api")
        logger.propagate = True
        try:
            with caplog.at_level(logging.WARNING, logger="wiim_rew_sync.wiim_api"):
                result = await adapter.read_roomfit_preset_preview("wifi", "Preview")
        finally:
            logger.propagate = False

        assert result.name == "Preview"
        assert any("Failed to restore" in rec.message for rec in caplog.records)


class TestReadPresetPreview:
    """Test read_preset_preview() -- dispatches by preset_type to
    read_roomfit_preset_preview()/read_peq_preset_preview(). Moved here
    from src.gui.shared_helpers (no Qt/GUI dependency, and it does device
    I/O, so it belongs on WiiMAdapter itself rather than a free function
    taking an adapter as its first argument)."""

    async def test_roomfit_dispatches_to_roomfit_read(
        self, adapter: WiiMAdapter
    ) -> None:
        """preset_type=='RoomFit' dispatches to read_roomfit_preset_preview."""
        settings = PEQSettings(source_name="wifi", channel_mode=ChannelMode.STEREO, bands=[])
        with (
            patch.object(
                adapter, "read_roomfit_preset_preview", AsyncMock(return_value=settings)
            ) as mock_roomfit,
            patch.object(adapter, "read_peq_preset_preview", AsyncMock()) as mock_peq,
        ):
            result = await adapter.read_preset_preview("RoomFit", "wifi", "Living Room")

        assert result is settings
        mock_roomfit.assert_awaited_once_with("wifi", "Living Room")
        mock_peq.assert_not_awaited()

    async def test_peq_dispatches_to_peq_read(self, adapter: WiiMAdapter) -> None:
        """preset_type=='PEQ' (or anything else) dispatches to read_peq_preset_preview."""
        settings = PEQSettings(source_name="wifi", channel_mode=ChannelMode.STEREO, bands=[])
        with (
            patch.object(adapter, "read_roomfit_preset_preview", AsyncMock()) as mock_roomfit,
            patch.object(
                adapter, "read_peq_preset_preview", AsyncMock(return_value=settings)
            ) as mock_peq,
        ):
            result = await adapter.read_preset_preview("PEQ", "wifi", "Movie Night")

        assert result is settings
        mock_peq.assert_awaited_once_with("wifi", "Movie Night")
        mock_roomfit.assert_not_awaited()


class TestRestoreRoomfitActiveProfile:
    """Direct unit coverage for restore_roomfit_active_profile() (#178) --
    shared by read_roomfit_preset_preview() above and RoomFitSafeWrite.execute()
    (safe_write.py). Its own tests only verify it's called with the right
    arguments; the skip/call decision itself is tested here."""

    @pytest.fixture
    def adapter(
        self, mock_client: AsyncMock, roomfit_preview_capabilities: DeviceCapabilities
    ) -> WiiMAdapter:
        return WiiMAdapter(http_client=mock_client, capabilities=roomfit_preview_capabilities)

    @pytest.fixture
    def roomfit_preview_capabilities(self) -> DeviceCapabilities:
        return DeviceCapabilities(
            supports_peq=True,
            supports_roomfit=True,
            supports_roomfit_read=True,
            max_filters=10,
            model="WiiM_Ultra",
            firmware="6.0.1.20",
        )

    async def test_calls_load_when_names_differ(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        mock_client.command.return_value = "OK"

        await adapter.restore_roomfit_active_profile(
            "Living Room", "Movie Night", context="writing 'Movie Night'"
        )

        mock_client.command.assert_called_once()
        assert "Living%20Room" in mock_client.command.call_args[0][0]

    async def test_skips_when_original_name_empty(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        await adapter.restore_roomfit_active_profile(
            "", "Movie Night", context="writing 'Movie Night'"
        )

        mock_client.command.assert_not_called()

    async def test_skips_when_names_match(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        await adapter.restore_roomfit_active_profile(
            "Movie Night", "Movie Night", context="writing 'Movie Night'"
        )

        mock_client.command.assert_not_called()

    async def test_swallows_and_logs_load_failure(
        self,
        adapter: WiiMAdapter,
        mock_client: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        mock_client.command.side_effect = WiiMConnectionError("boom")

        logger = logging.getLogger("wiim_rew_sync.wiim_api")
        logger.propagate = True
        try:
            with caplog.at_level(logging.WARNING, logger="wiim_rew_sync.wiim_api"):
                await adapter.restore_roomfit_active_profile(
                    "Living Room", "Movie Night", context="writing 'Movie Night'"
                )
        finally:
            logger.propagate = False

        assert any("Failed to restore" in rec.message for rec in caplog.records)


class TestRestoreRoomfitSelectionAndEnableState:
    """Direct unit coverage for restore_roomfit_selection_and_enable_state()
    (#192) -- shared by read_roomfit_preset_preview() and RoomFitSafeWrite's
    failure/undo paths (safe_write.py). Introduced when a hardware report
    showed the preview path was restoring selection but silently dropping
    the captured enable/disable state, leaving RoomFit on after a read-only
    preview if it had been off."""

    @pytest.fixture
    def adapter(
        self, mock_client: AsyncMock, roomfit_preview_capabilities: DeviceCapabilities
    ) -> WiiMAdapter:
        return WiiMAdapter(http_client=mock_client, capabilities=roomfit_preview_capabilities)

    @pytest.fixture
    def roomfit_preview_capabilities(self) -> DeviceCapabilities:
        return DeviceCapabilities(
            supports_peq=True,
            supports_roomfit=True,
            supports_roomfit_read=True,
            max_filters=10,
            model="WiiM_Ultra",
            firmware="6.0.1.20",
        )

    async def test_restores_both_selection_and_enable_state(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        mock_client.command.return_value = "OK"

        await adapter.restore_roomfit_selection_and_enable_state(
            "Living Room", False, "Movie Night", context="previewing 'Movie Night'"
        )

        calls = mock_client.command.call_args_list
        assert len(calls) == 2
        assert "Living%20Room" in calls[0][0][0]
        assert "EQSourceOff" in calls[1][0][0]

    async def test_skips_enable_restore_when_enabled_is_none(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        mock_client.command.return_value = "OK"

        await adapter.restore_roomfit_selection_and_enable_state(
            "Living Room", None, "Movie Night", context="previewing 'Movie Night'"
        )

        calls = mock_client.command.call_args_list
        assert len(calls) == 1
        assert "Living%20Room" in calls[0][0][0]

    async def test_still_restores_enable_state_when_selection_unchanged(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Selection restore is skipped (same name), but enable-state restore
        is unconditional -- the exact gap #192 fixed."""
        mock_client.command.return_value = "OK"

        await adapter.restore_roomfit_selection_and_enable_state(
            "Movie Night", True, "Movie Night", context="previewing 'Movie Night'"
        )

        calls = mock_client.command.call_args_list
        assert len(calls) == 1
        assert "EQChangeSourceFX" in calls[0][0][0]

    async def test_swallows_and_logs_enable_restore_failure(
        self,
        adapter: WiiMAdapter,
        mock_client: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        async def side_effect(_command: str) -> str:
            if mock_client.command.call_count == 1:
                return "OK"
            raise WiiMConnectionError("boom")

        mock_client.command.side_effect = side_effect

        logger = logging.getLogger("wiim_rew_sync.wiim_api")
        logger.propagate = True
        try:
            with caplog.at_level(logging.WARNING, logger="wiim_rew_sync.wiim_api"):
                await adapter.restore_roomfit_selection_and_enable_state(
                    "Living Room", True, "Movie Night", context="previewing 'Movie Night'"
                )
        finally:
            logger.propagate = False

        assert any(
            "Failed to restore RoomFit enable-state" in rec.message
            for rec in caplog.records
        )


# ---------------------------------------------------------------------------
# Tests: get_source_slot_overview (#194 follow-up diagnostic)
# ---------------------------------------------------------------------------


class TestGetSourceSlotOverview:
    """Test the EQGetSourceModes-based source-slot diagnostic."""

    @pytest.fixture
    def caps_with_known_sources(self) -> DeviceCapabilities:
        return DeviceCapabilities(
            supports_peq=True,
            max_filters=10,
            model="WiiM_Ultra",
            source_names=["wifi", "bluetooth", "optical"],
        )

    async def test_classifies_known_and_unknown_slots(
        self, mock_client: AsyncMock, caps_with_known_sources: DeviceCapabilities
    ) -> None:
        """Real hardware dump (2026-07-10): a mix of real sources and
        garbage rows left behind by invalid source_name writes -- the
        unsplit comma-joined value and a stray typo'd name."""
        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=caps_with_known_sources
        )
        mock_client.command.return_value = [
            {
                "source_name": "wifi",
                "Name": "M16",
                "NameL": "M16",
                "NameR": "M16",
                "channelMode": "Stereo",
                "EQStat": "On",
                "pluginURI": "http://moddevices.com/plugins/caps/EqNp",
            },
            {
                "source_name": "wifi,bluetooth,auxIn",
                "Name": "",
                "channelMode": "Stereo",
                "EQStat": "Off",
                "pluginURI": "http://moddevices.com/plugins/caps/EqNp",
            },
            {
                "source_name": "dominik",
                "Name": "Test",
                "channelMode": "L/R",
                "EQStat": "Off",
                "pluginURI": "http://moddevices.com/plugins/caps/EqNp",
            },
        ]

        slots = await adapter.get_source_slot_overview()

        assert len(slots) == 3
        assert slots[0].source_name == "wifi"
        assert slots[0].is_known_source is True
        assert slots[0].enabled is True
        assert slots[1].source_name == "wifi,bluetooth,auxIn"
        assert slots[1].is_known_source is False
        assert slots[2].source_name == "dominik"
        assert slots[2].is_known_source is False
        assert slots[2].channel_mode == "L/R"

        call_args = mock_client.command.call_args[0][0]
        assert call_args == "EQGetSourceModes"

    async def test_non_eqnp_plugin_rows_are_skipped(
        self, mock_client: AsyncMock, caps_with_known_sources: DeviceCapabilities
    ) -> None:
        """Legacy Eq10HP graphic-EQ rows aren't this app's domain -- skip."""
        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=caps_with_known_sources
        )
        mock_client.command.return_value = [
            {
                "source_name": "wifi",
                "Name": "M16",
                "channelMode": "Stereo",
                "EQStat": "On",
                "pluginURI": "http://some.other/plugin/Eq10HP",
            },
        ]

        slots = await adapter.get_source_slot_overview()

        assert slots == []

    async def test_empty_list_response(
        self, mock_client: AsyncMock, caps_with_known_sources: DeviceCapabilities
    ) -> None:
        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=caps_with_known_sources
        )
        mock_client.command.return_value = []

        slots = await adapter.get_source_slot_overview()

        assert slots == []

    async def test_non_list_response_raises(
        self, mock_client: AsyncMock, caps_with_known_sources: DeviceCapabilities
    ) -> None:
        """A device that doesn't support EQGetSourceModes typically returns
        the generic "unknown command" string -- not the expected list."""
        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=caps_with_known_sources
        )
        mock_client.command.return_value = "unknown command"

        with pytest.raises(WiiMResponseError):
            await adapter.get_source_slot_overview()
