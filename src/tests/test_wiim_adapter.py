"""Unit tests for WiiMAdapter — PEQ read and multiroom operations.

Tests use AsyncMock to mock WiiMHttpClient.command() and exercise
stereo/LR parsing, error handling, and multiroom master IP resolution.

Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.adapters.wiim_adapter import WiiMAdapter
from src.adapters.wiim_http import WiiMHttpClient
from src.models.capabilities import DeviceCapabilities
from src.models.errors import WiiMConnectionError, WiiMResponseError
from src.models.peq import PEQSettings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def capabilities() -> DeviceCapabilities:
    """Minimal device capabilities for adapter tests."""
    return DeviceCapabilities(
        supports_peq=True,
        supports_channel_peq=True,
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
        assert result.channel_mode == "stereo"
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
        assert result.channel_mode == "lr"
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
# Tests: get_multiroom_master_ip
# ---------------------------------------------------------------------------


class TestGetMultiroomMasterIp:
    """Test multiroom master IP resolution."""

    async def test_returns_master_ip(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Returns master_ip from GetMultiroomInfo response."""
        mock_client.command.return_value = {
            "role": 2,
            "master_ip": "192.168.1.100",
            "slave_list": [],
        }

        result = await adapter.get_multiroom_master_ip()

        assert result == "192.168.1.100"

    async def test_returns_none_for_solo(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Returns None when device is solo (no master_ip field)."""
        mock_client.command.return_value = {
            "role": 0,
        }

        result = await adapter.get_multiroom_master_ip()

        assert result is None

    async def test_returns_none_on_connection_error(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Returns None when device is unreachable."""
        mock_client.command.side_effect = WiiMConnectionError("timeout")

        result = await adapter.get_multiroom_master_ip()

        assert result is None

    async def test_returns_none_on_non_dict_response(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Returns None when response is not a dict (e.g. 'unknown command')."""
        mock_client.command.return_value = "unknown command"

        result = await adapter.get_multiroom_master_ip()

        assert result is None

    async def test_returns_none_for_empty_master_ip(
        self, adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Returns None when master_ip is empty string."""
        mock_client.command.return_value = {
            "role": 0,
            "master_ip": "",
        }

        result = await adapter.get_multiroom_master_ip()

        assert result is None


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
            supports_channel_peq=True,
            max_filters=10,
            model="WiiM_Ultra",
            firmware="6.0.1.20",
            role="solo",
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
        """Batch write issues EQSetLV2ChannelMode + one EQSetLV2SourceBand."""
        mock_client.command.return_value = "OK"
        settings = self._make_settings()

        await batch_adapter.write_peq("wifi", settings)

        # Two calls: channel mode switch + batch write
        assert mock_client.command.call_count == 2
        calls = [c[0][0] for c in mock_client.command.call_args_list]
        assert calls[0].startswith("EQSetLV2ChannelMode:")
        assert calls[1].startswith("EQSetLV2SourceBand:")

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
            supports_channel_peq=True,
            max_filters=10,
            model="WiiM_Pro",
            firmware="5.0.0.10",
            role="solo",
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

        # 1 channel mode switch + 10 band writes = 11 commands
        assert mock_client.command.call_count == 11

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
            role="solo",
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
            role="solo",
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


# ---------------------------------------------------------------------------
# Tests: read_roomfit — Level gating and real API commands
# ---------------------------------------------------------------------------


class TestReadRoomfit:
    """Test read_roomfit level gating and response parsing with real API commands."""

    @pytest.fixture
    def roomfit_read_capabilities(self) -> DeviceCapabilities:
        """Capabilities with roomfit_level >= 2 (read supported)."""
        return DeviceCapabilities(
            supports_peq=True,
            supports_roomfit=True,
            supports_roomfit_read=True,
            roomfit_level=3,
            max_filters=10,
            model="WiiM_Ultra",
            firmware="6.0.1.20",
            role="solo",
        )

    @pytest.fixture
    def low_roomfit_capabilities(self) -> DeviceCapabilities:
        """Capabilities with roomfit_level < 2 (read NOT supported)."""
        return DeviceCapabilities(
            supports_peq=True,
            roomfit_level=1,
            max_filters=10,
            model="WiiM_Mini",
            firmware="5.0.0.10",
            role="solo",
        )

    async def test_read_roomfit_insufficient_level_raises(
        self, mock_client: AsyncMock, low_roomfit_capabilities: DeviceCapabilities
    ) -> None:
        """read_roomfit raises WiiMResponseError when roomfit_level < 2."""
        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=low_roomfit_capabilities
        )

        with pytest.raises(WiiMResponseError, match="roomfit_level >= 2"):
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
        assert result.channel_mode == "stereo"
        assert len(result.bands) == 10
        assert result.bands[0].type == "PEAK"
        assert result.bands[0].frequency_hz == 80.0
        assert result.bands[0].gain_db == -4.0

        # Verify the correct commands were issued
        calls = mock_client.command.call_args_list
        assert len(calls) == 2
        # First: load command
        assert "EQv2SourceLoad:" in calls[0][0][0]
        assert "EQLevel" in calls[0][0][0]
        assert "My%20RoomFit" in calls[0][0][0]
        # Second: read command
        assert "EQGetLV2SourceBandEx:" in calls[1][0][0]
        assert "EQLevel" in calls[1][0][0]


# ---------------------------------------------------------------------------
# Tests: write_roomfit — Level gating and real API commands
# ---------------------------------------------------------------------------


class TestWriteRoomfit:
    """Test write_roomfit level gating and real API commands."""

    @pytest.fixture
    def roomfit_write_capabilities(self) -> DeviceCapabilities:
        """Capabilities with roomfit_level >= 4 (write supported)."""
        return DeviceCapabilities(
            supports_peq=True,
            supports_roomfit=True,
            supports_roomfit_read=True,
            supports_roomfit_write=True,
            roomfit_level=4,
            max_filters=10,
            model="WiiM_Ultra",
            firmware="6.0.1.20",
            role="solo",
        )

    @pytest.fixture
    def insufficient_write_capabilities(self) -> DeviceCapabilities:
        """Capabilities with roomfit_level < 4 (write NOT supported)."""
        return DeviceCapabilities(
            supports_peq=True,
            supports_roomfit=True,
            supports_roomfit_read=True,
            roomfit_level=3,
            max_filters=10,
            model="WiiM_Ultra",
            firmware="6.0.1.20",
            role="solo",
        )

    async def test_write_roomfit_insufficient_level_raises(
        self, mock_client: AsyncMock, insufficient_write_capabilities: DeviceCapabilities
    ) -> None:
        """write_roomfit raises WiiMResponseError when roomfit_level < 4."""
        from src.models.canonical import CanonicalFilter

        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=insufficient_write_capabilities
        )
        filters = [CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-2.0, q=1.0)]

        with pytest.raises(WiiMResponseError, match="roomfit_level >= 4"):
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
            "OK",  # EQSetLV2SourceBand response
            "OK",  # EQSourceSave response
        ]

        await adapter.write_roomfit("wifi", "REW Export", filters)

        calls = mock_client.command.call_args_list
        assert len(calls) == 2
        # First: write to buffer with EQLevel: 2
        assert "EQSetLV2SourceBand:" in calls[0][0][0]
        assert "EQLevel" in calls[0][0][0]
        assert "wifi" in calls[0][0][0]
        # Second: save to profile
        assert "EQSourceSave:" in calls[1][0][0]
        assert "EQLevel" in calls[1][0][0]
        assert "REW%20Export" in calls[1][0][0]


# ---------------------------------------------------------------------------
# Tests: list_roomfit_profiles
# ---------------------------------------------------------------------------


class TestListRoomfitProfiles:
    """Test list_roomfit_profiles method."""

    @pytest.fixture
    def roomfit_capabilities(self) -> DeviceCapabilities:
        """Capabilities with roomfit_level >= 1 (profile listing supported)."""
        return DeviceCapabilities(
            supports_peq=True,
            supports_roomfit=True,
            roomfit_level=1,
            max_filters=10,
            model="WiiM_Ultra",
            firmware="6.0.1.20",
            role="solo",
        )

    @pytest.fixture
    def no_roomfit_capabilities(self) -> DeviceCapabilities:
        """Capabilities with roomfit_level 0 (RoomFit not supported)."""
        return DeviceCapabilities(
            supports_peq=True,
            roomfit_level=0,
            max_filters=10,
            model="WiiM_Mini",
            firmware="5.0.0.10",
            role="solo",
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
        """list_roomfit_profiles raises when roomfit_level < 1."""
        adapter = WiiMAdapter(
            http_client=mock_client, capabilities=no_roomfit_capabilities
        )

        with pytest.raises(WiiMResponseError, match="roomfit_level >= 1"):
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
            supports_channel_peq=True,
            max_filters=10,
            model="WiiM_Ultra",
            firmware="6.0.1.20",
            role="solo",
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

        # Two calls: channel mode switch + batch write
        assert mock_client.command.call_count == 2
        batch_call = mock_client.command.call_args_list[1][0][0]
        assert "EQSetLV2SourceBand:" in batch_call
        assert "EQBandL" in batch_call
        assert "EQBandR" in batch_call

    async def test_write_peq_lr_calls_set_channel_mode_lr(
        self, lr_batch_adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Writing L/R mode calls EQSetLV2ChannelMode with 'L/R' before writing bands."""
        mock_client.command.return_value = "OK"
        settings = self._make_lr_settings()

        await lr_batch_adapter.write_peq("wifi", settings)

        first_call = mock_client.command.call_args_list[0][0][0]
        assert "EQSetLV2ChannelMode:" in first_call
        assert "L%2FR" in first_call or "L/R" in first_call


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
            supports_channel_peq=True,
            max_filters=10,
            model="WiiM_Pro",
            firmware="5.0.0.10",
            role="solo",
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

        # 1 channel mode switch + 10 band writes = 11 commands
        assert mock_client.command.call_count == 11
        # Each band write (calls[1:]) should contain both L and R data
        for call in mock_client.command.call_args_list[1:]:
            cmd = call[0][0]
            assert "EQBandL" in cmd
            assert "EQBandR" in cmd


# ---------------------------------------------------------------------------
# Tests: _set_channel_mode (hardware testing regression)
# ---------------------------------------------------------------------------


class TestSetChannelMode:
    """Test that write_peq always sets the channel mode before writing."""

    @pytest.fixture
    def batch_capabilities(self) -> DeviceCapabilities:
        """Capabilities with batch write support."""
        return DeviceCapabilities(
            supports_peq=True,
            supports_batch_write=True,
            supports_channel_peq=True,
            max_filters=10,
            model="WiiM_Ultra",
            firmware="6.0.1.20",
            role="solo",
        )

    @pytest.fixture
    def batch_adapter(
        self, mock_client: AsyncMock, batch_capabilities: DeviceCapabilities
    ) -> WiiMAdapter:
        """Adapter configured for batch write."""
        return WiiMAdapter(http_client=mock_client, capabilities=batch_capabilities)

    async def test_set_channel_mode_stereo(
        self, batch_adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Writing stereo settings sends EQSetLV2ChannelMode with 'Stereo' first."""
        from src.models.canonical import CanonicalFilter

        mock_client.command.return_value = "OK"
        settings = PEQSettings(
            source_name="wifi",
            enabled=True,
            channel_mode="stereo",
            bands=[CanonicalFilter(type="PEAK", frequency_hz=80.0, gain_db=-4.0, q=1.41)],
        )

        await batch_adapter.write_peq("wifi", settings)

        first_call = mock_client.command.call_args_list[0][0][0]
        assert "EQSetLV2ChannelMode:" in first_call
        assert "Stereo" in first_call

    async def test_set_channel_mode_lr(
        self, batch_adapter: WiiMAdapter, mock_client: AsyncMock
    ) -> None:
        """Writing L/R settings sends EQSetLV2ChannelMode with 'L/R' first."""
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

        first_call = mock_client.command.call_args_list[0][0][0]
        assert "EQSetLV2ChannelMode:" in first_call
        assert "L%2FR" in first_call or "L/R" in first_call


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
