"""Unit tests for MainWindow filter-loading handlers (file import, device pull, REW pull).

Tests the three filter-loading handlers:
- _on_file_import_requested(path)
- _on_device_pull_requested()
- _on_rew_api_pull_requested()

Covers happy paths, error paths, and precondition failures.

Requirements: 3.1-3.6, 4.1-4.5, 5.1-5.7
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.adapters.rew_http_client import MeasurementSummary
from src.gui.app_settings import AppSettings
from src.gui.main_window import MainWindow
from src.models.canonical import CanonicalFilter
from src.models.errors import ParseError, REWNotConnectedError
from src.models.peq import PEQSettings
from src.translator._warnings import ValidationWarning

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def window(qtbot):
    """Create a MainWindow with mocked AsyncBridge for handler testing."""
    mock_bridge = MagicMock()
    mock_bridge.start = MagicMock()
    mock_bridge.shutdown = MagicMock()
    # Signal mocks — allow .emit() to be called and tracked
    mock_bridge.peq_ready = MagicMock()
    mock_bridge.operation_error = MagicMock()
    mock_bridge.progress_update = MagicMock()
    mock_bridge.rew_measurements_ready = MagicMock()
    mock_bridge.rew_filters_ready = MagicMock()
    mock_bridge.operation_started = MagicMock()
    mock_bridge.operation_finished = MagicMock()
    mock_bridge.discovery_complete = MagicMock()
    mock_bridge.capabilities_ready = MagicMock()
    mock_bridge.write_complete = MagicMock()
    mock_bridge.run_async = MagicMock()

    app_settings = AppSettings(first_run_complete=True)
    with (
        patch("src.gui.app_settings.AppSettings.load", return_value=app_settings),
        patch("src.gui.app_settings.AppSettings.save"),
    ):
        w = MainWindow(async_bridge=mock_bridge)
        qtbot.addWidget(w)
        yield w
        # Clear filters to prevent UnsavedChangesDialog from blocking on close
        w._wizard_controller.state.current_filters = []
        w.close()


def _make_filter(freq: float = 1000.0, gain: float = -3.0) -> CanonicalFilter:
    """Create a minimal CanonicalFilter for testing."""
    return CanonicalFilter(
        type="PEAK",
        frequency_hz=freq,
        gain_db=gain,
        q=1.0,
    )


# ---------------------------------------------------------------------------
# File Import — Happy Path
# ---------------------------------------------------------------------------


class TestFileImportHappyPath:
    """Test _on_file_import_requested with successful parse."""

    @pytest.mark.asyncio
    async def test_file_import_happy_path(self, window) -> None:
        """Verify peq_ready signal emitted after successful file import.

        Requirement: 3.1, 3.2
        """
        filters = [_make_filter(100.0), _make_filter(200.0)]

        with patch(
            "src.translator.rew_parser.REWParser.parse_file_with_warnings",
            return_value=(filters, []),
        ):
            await window._do_file_import("/fake/path/eq.txt")

        window._bridge.peq_ready.emit.assert_called_once_with(filters)

    @pytest.mark.asyncio
    async def test_file_import_with_warnings(self, window) -> None:
        """Verify progress_update emitted with skip count when warnings present.

        Requirement: 3.3, 3.5
        """
        filters = [_make_filter(100.0)]
        warnings = [
            ValidationWarning(
                field="filter_type",
                message="Unsupported type",
                original_value="Notch",
            ),
            ValidationWarning(
                field="filter_type",
                message="Unsupported type",
                original_value="Bandpass",
            ),
        ]

        with patch(
            "src.translator.rew_parser.REWParser.parse_file_with_warnings",
            return_value=(filters, warnings),
        ):
            await window._do_file_import("/fake/path/eq.txt")

        window._bridge.peq_ready.emit.assert_called_once_with(filters)
        window._bridge.progress_update.emit.assert_called_once()
        msg = window._bridge.progress_update.emit.call_args[0][0]
        assert "2" in msg  # skip count
        assert "skipped" in msg


# ---------------------------------------------------------------------------
# File Import — Error Paths
# ---------------------------------------------------------------------------


class TestFileImportErrors:
    """Test _on_file_import_requested error handling via _bridge_wrapper."""

    @pytest.mark.asyncio
    async def test_file_import_file_not_found(self, window) -> None:
        """Verify operation_error emitted when file doesn't exist.

        Requirement: 3.4
        """
        with patch(
            "src.translator.rew_parser.REWParser.parse_file_with_warnings",
            side_effect=FileNotFoundError("No such file"),
        ):
            # Call the wrapper which catches exceptions
            await window._bridge_wrapper(
                "file_import", window._do_file_import("/nonexistent/file.txt")
            )

        window._bridge.operation_error.emit.assert_called_once()
        error_type, message = window._bridge.operation_error.emit.call_args[0]
        assert error_type == "FileNotFoundError"
        assert "not found" in message.lower() or "File not found" in message

    @pytest.mark.asyncio
    async def test_file_import_parse_error(self, window) -> None:
        """Verify operation_error emitted when file is malformed.

        Requirement: 3.6
        """
        with patch(
            "src.translator.rew_parser.REWParser.parse_file_with_warnings",
            side_effect=ParseError(
                "Expected 'Equaliser:' header", line_number=1
            ),
        ):
            await window._bridge_wrapper(
                "file_import", window._do_file_import("/bad/file.txt")
            )

        window._bridge.operation_error.emit.assert_called_once()
        error_type, message = window._bridge.operation_error.emit.call_args[0]
        assert error_type == "ParseError"
        assert "Could not read file" in message


# ---------------------------------------------------------------------------
# File Import — Busy Guard
# ---------------------------------------------------------------------------


class TestFileImportBusyGuard:
    """Test _on_file_import_requested when another operation is in progress."""

    def test_file_import_blocked_when_busy(self, window) -> None:
        """Verify no run_async called when feedback manager is active.

        Requirement: 13.4
        """
        window._feedback_manager._is_active = True

        window._on_file_import_requested("/some/path.txt")

        window._bridge.run_async.assert_not_called()


# ---------------------------------------------------------------------------
# Device Pull — Happy Path
# ---------------------------------------------------------------------------


class TestDevicePullHappyPath:
    """Test _on_device_pull_requested with successful adapter read."""

    @pytest.mark.asyncio
    async def test_device_pull_happy_path(self, window) -> None:
        """Verify peq_ready emitted after successful device pull.

        Requirement: 4.1, 4.2
        """
        bands = [_make_filter(500.0), _make_filter(1000.0)]
        peq_settings = PEQSettings(
            source_name="wifi",
            enabled=True,
            channel_mode="stereo",
            bands=bands,
        )

        # Set up adapter and source
        mock_adapter = AsyncMock()
        mock_adapter.read_peq = AsyncMock(return_value=peq_settings)
        window._wiim_adapter = mock_adapter
        window._wizard_controller.state.selected_source = "wifi"

        await window._do_device_pull()

        window._bridge.peq_ready.emit.assert_called_once_with(peq_settings)

    @pytest.mark.asyncio
    async def test_device_pull_lr_mode(self, window) -> None:
        """Verify L/R mode combines both channel band lists in state.

        Requirement: 4.3
        """
        bands_l = [_make_filter(100.0)]
        bands_r = [_make_filter(200.0)]
        peq_settings = PEQSettings(
            source_name="wifi",
            enabled=True,
            channel_mode="lr",
            bands=[],
            bands_l=bands_l,
            bands_r=bands_r,
        )

        mock_adapter = AsyncMock()
        mock_adapter.read_peq = AsyncMock(return_value=peq_settings)
        window._wiim_adapter = mock_adapter
        window._wizard_controller.state.selected_source = "wifi"

        await window._do_device_pull()

        # State should have combined L+R filters
        state_filters = window._wizard_controller.state.current_filters
        assert len(state_filters) == 2
        assert state_filters[0].frequency_hz == 100.0
        assert state_filters[1].frequency_hz == 200.0


# ---------------------------------------------------------------------------
# Device Pull — Precondition Failures
# ---------------------------------------------------------------------------


class TestDevicePullPreconditions:
    """Test _on_device_pull_requested precondition checks."""

    def test_device_pull_no_adapter(self, window) -> None:
        """Verify error shown when no device is connected (adapter is None).

        Requirement: 4.4
        """
        window._wiim_adapter = None
        window._feedback_manager._is_active = False

        window._on_device_pull_requested()

        # Should NOT call run_async — precondition failed
        window._bridge.run_async.assert_not_called()

    def test_device_pull_no_source_selected(self, window) -> None:
        """Verify error shown when no source has been selected.

        Requirement: 4.5
        """
        # Adapter is set but source is empty
        window._wiim_adapter = MagicMock()
        window._wizard_controller.state.selected_source = ""
        window._feedback_manager._is_active = False

        window._on_device_pull_requested()

        # Should NOT call run_async — precondition failed
        window._bridge.run_async.assert_not_called()


# ---------------------------------------------------------------------------
# REW Pull — Happy Path
# ---------------------------------------------------------------------------


class TestREWPullHappyPath:
    """Test _on_rew_api_pull_requested with successful measurement listing."""

    @pytest.mark.asyncio
    async def test_rew_list_happy_path(self, window) -> None:
        """Verify rew_measurements_ready emitted with measurement list.

        Requirement: 5.1, 5.2
        """
        measurements = [
            MeasurementSummary(uuid="abc-123", name="Room 1", index=0),
            MeasurementSummary(uuid="def-456", name="Room 2", index=1),
        ]

        mock_client = AsyncMock()
        mock_client.list_measurements = AsyncMock(return_value=measurements)
        window._rew_client = mock_client

        await window._do_rew_list_measurements()

        window._bridge.rew_measurements_ready.emit.assert_called_once_with(measurements)

    @pytest.mark.asyncio
    async def test_rew_list_empty(self, window) -> None:
        """Verify progress_update "No measurements found" when list is empty.

        Requirement: 5.5
        """
        mock_client = AsyncMock()
        mock_client.list_measurements = AsyncMock(return_value=[])
        window._rew_client = mock_client

        await window._do_rew_list_measurements()

        window._bridge.rew_measurements_ready.emit.assert_not_called()
        window._bridge.progress_update.emit.assert_called_once()
        msg = window._bridge.progress_update.emit.call_args[0][0]
        assert "No measurements found" in msg

    @pytest.mark.asyncio
    async def test_rew_not_connected_error(self, window) -> None:
        """Verify operation_error emitted when REW is not running.

        Requirement: 5.6
        """
        mock_client = AsyncMock()
        mock_client.list_measurements = AsyncMock(
            side_effect=REWNotConnectedError("Cannot connect to REW")
        )
        window._rew_client = mock_client

        await window._bridge_wrapper(
            "rew_list", window._do_rew_list_measurements()
        )

        window._bridge.operation_error.emit.assert_called_once()
        error_type, message = window._bridge.operation_error.emit.call_args[0]
        assert error_type == "REWNotConnectedError"
        assert "not connected" in message.lower()


# ---------------------------------------------------------------------------
# REW Pull — Busy Guard
# ---------------------------------------------------------------------------


class TestREWPullBusyGuard:
    """Test _on_rew_api_pull_requested when another operation is in progress."""

    def test_rew_list_blocked_when_busy(self, window) -> None:
        """Verify no run_async called when feedback manager is active.

        Requirement: 13.4
        """
        window._feedback_manager._is_active = True

        window._on_rew_api_pull_requested()

        window._bridge.run_async.assert_not_called()
