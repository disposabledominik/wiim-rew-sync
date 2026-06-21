"""Unit tests for MainWindow push and export handlers.

Tests the push and export handler flows:
- _on_push_requested() -> guards busy, advances wizard, calls _bridge_wrapper
- _do_push() -> creates PEQSettings from state, calls safe_write.execute()
- _on_export_requested() -> guards busy, opens QFileDialog, calls _bridge_wrapper
- _do_export(filters, path) -> calls REWGenerator().generate_file()

Requirements: 6.1-6.7, 7.1-7.6
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.adapters.safe_write import WriteResult
from src.gui.app_settings import AppSettings
from src.gui.main_window import MainWindow
from src.models.canonical import CanonicalFilter
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


def _setup_push_state(window) -> None:
    """Set up wizard state required for a push operation."""
    window._wizard_controller.state.selected_source = "wifi"
    window._wizard_controller.state.current_filters = [
        _make_filter(100.0),
        _make_filter(200.0),
        _make_filter(500.0),
    ]
    window._wizard_controller.state.channel_mode = "Stereo"
    window._wizard_controller.state.dry_run = False

    # Provide a mocked WiiMAdapter (required by _do_push assert)
    mock_adapter = MagicMock()
    mock_adapter.capabilities = MagicMock()
    window._wiim_adapter = mock_adapter

    # Provide a mocked SafeWrite
    mock_safe_write = AsyncMock()
    window._safe_write = mock_safe_write
    return mock_safe_write


# ---------------------------------------------------------------------------
# Push — Happy Path
# ---------------------------------------------------------------------------


class TestPushHappyPath:
    """Test _do_push with successful SafeWrite execution."""

    @pytest.mark.asyncio
    async def test_push_happy_path(self, window) -> None:
        """Verify write_complete emitted with success result after successful push.

        Requirement: 6.1, 6.2, 6.3
        """
        mock_safe_write = _setup_push_state(window)
        result = WriteResult(
            success=True,
            rollback_success=None,
            backup_path=Path("/backups/wifi_backup.json"),
        )
        mock_safe_write.execute = AsyncMock(return_value=result)

        await window._do_push()

        mock_safe_write.execute.assert_called_once()
        # Verify source_name passed correctly
        call_args = mock_safe_write.execute.call_args
        assert call_args[0][0] == "wifi"
        # Verify write_complete emitted with success and encoded backup path
        window._bridge.write_complete.emit.assert_called_once()
        emitted_result = window._bridge.write_complete.emit.call_args[0][0]
        assert emitted_result.success is True
        assert "wifi=" in emitted_result.backup_path
        assert "/backups/wifi_backup.json" in emitted_result.backup_path

    @pytest.mark.asyncio
    async def test_push_rollback_success(self, window) -> None:
        """Verify write_complete emitted with failure result when rollback succeeds.

        Requirement: 6.4
        """
        mock_safe_write = _setup_push_state(window)
        result = WriteResult(
            success=False,
            rollback_success=True,
            backup_path=Path("/backups/wifi_backup.json"),
            error_message="Verification mismatch on band 3",
        )
        mock_safe_write.execute = AsyncMock(return_value=result)

        await window._do_push()

        window._bridge.write_complete.emit.assert_called_once_with(result)

    @pytest.mark.asyncio
    async def test_push_critical_rollback_failure(self, window) -> None:
        """Verify write_complete emitted when rollback itself fails (critical state).

        Requirement: 6.5
        """
        mock_safe_write = _setup_push_state(window)
        result = WriteResult(
            success=False,
            rollback_success=False,
            backup_path=Path("/backups/wifi_backup.json"),
            error_message="Rollback verification failed",
        )
        mock_safe_write.execute = AsyncMock(return_value=result)

        await window._do_push()

        window._bridge.write_complete.emit.assert_called_once_with(result)


# ---------------------------------------------------------------------------
# Push — Progress Updates
# ---------------------------------------------------------------------------


class TestPushProgressUpdates:
    """Test _do_push emits progress_update signals for SafeWrite stages."""

    @pytest.mark.asyncio
    async def test_push_progress_updates(self, window) -> None:
        """Verify progress_update emitted with "Backing up..." stage message.

        Requirement: 6.6
        """
        mock_safe_write = _setup_push_state(window)
        result = WriteResult(
            success=True,
            rollback_success=None,
            backup_path=Path("/backups/wifi_backup.json"),
        )
        mock_safe_write.execute = AsyncMock(return_value=result)

        await window._do_push()

        # Verify progress_update was called with stage messages
        progress_calls = window._bridge.progress_update.emit.call_args_list
        messages = [call[0][0] for call in progress_calls]
        assert "Backing up..." in messages

    @pytest.mark.asyncio
    async def test_push_success_emits_verifying(self, window) -> None:
        """Verify success path emits Verifying progress stage.

        Requirement: 6.6
        """
        mock_safe_write = _setup_push_state(window)
        result = WriteResult(
            success=True,
            rollback_success=None,
            backup_path=Path("/backups/wifi_backup.json"),
        )
        mock_safe_write.execute = AsyncMock(return_value=result)

        await window._do_push()

        progress_calls = window._bridge.progress_update.emit.call_args_list
        messages = [call[0][0] for call in progress_calls]
        assert "Backing up..." in messages
        assert "Verifying..." in messages


# ---------------------------------------------------------------------------
# Push — Exception via bridge_wrapper
# ---------------------------------------------------------------------------


class TestPushException:
    """Test _do_push exception handling through _bridge_wrapper."""

    @pytest.mark.asyncio
    async def test_push_exception_emits_operation_error(self, window) -> None:
        """Verify operation_error emitted when safe_write.execute raises.

        Requirement: 6.1, 12.1
        """
        mock_safe_write = _setup_push_state(window)
        mock_safe_write.execute = AsyncMock(
            side_effect=ConnectionError("Device lost connection")
        )

        await window._bridge_wrapper("push", window._do_push())

        window._bridge.operation_error.emit.assert_called_once()
        error_type, _message = window._bridge.operation_error.emit.call_args[0]
        assert error_type == "ConnectionError"


# ---------------------------------------------------------------------------
# Push — Busy Guard
# ---------------------------------------------------------------------------


class TestPushBusyGuard:
    """Test _on_push_requested when another operation is in progress."""

    def test_push_blocked_when_busy(self, window) -> None:
        """Verify no run_async called when feedback manager is active.

        Requirement: 13.4
        """
        window._feedback_manager._is_active = True

        window._on_push_requested()

        window._bridge.run_async.assert_not_called()


# ---------------------------------------------------------------------------
# Push — Channel Mode
# ---------------------------------------------------------------------------


class TestPushChannelMode:
    """Test _do_push constructs PEQSettings correctly for different channel modes."""

    @pytest.mark.asyncio
    async def test_push_stereo_mode(self, window) -> None:
        """Verify PEQSettings built with bands for stereo mode.

        Requirement: 6.1, 6.2
        """
        mock_safe_write = _setup_push_state(window)
        result = WriteResult(success=True, rollback_success=None)
        mock_safe_write.execute = AsyncMock(return_value=result)

        await window._do_push()

        call_args = mock_safe_write.execute.call_args
        settings = call_args[0][1]
        assert settings.channel_mode == "stereo"
        assert settings.bands == window._wizard_controller.state.current_filters

    @pytest.mark.asyncio
    async def test_push_lr_mode(self, window) -> None:
        """Verify PEQSettings splits bands into L/R for lr channel mode.

        Requirement: 6.1, 6.2
        """
        mock_safe_write = _setup_push_state(window)
        window._wizard_controller.state.channel_mode = "LR"
        # 4 filters: first 2 → bands_l, last 2 → bands_r
        filters = [_make_filter(f) for f in [100.0, 200.0, 500.0, 1000.0]]
        window._wizard_controller.state.current_filters = filters
        result = WriteResult(success=True, rollback_success=None)
        mock_safe_write.execute = AsyncMock(return_value=result)

        await window._do_push()

        call_args = mock_safe_write.execute.call_args
        settings = call_args[0][1]
        assert settings.channel_mode == "lr"
        assert settings.bands_l == filters[:2]
        assert settings.bands_r == filters[2:]


# ---------------------------------------------------------------------------
# Export — Happy Path
# ---------------------------------------------------------------------------


class TestExportHappyPath:
    """Test _do_export with successful file generation."""

    @pytest.mark.asyncio
    async def test_export_happy_path(self, window) -> None:
        """Verify "File exported successfully" emitted when no warnings.

        Requirement: 7.1, 7.2
        """
        filters = [_make_filter(100.0), _make_filter(200.0)]

        with patch(
            "src.translator.rew_generator.REWGenerator.generate_file",
            return_value=[],
        ) as mock_gen:
            await window._do_export(filters, "/export/eq.txt")

            mock_gen.assert_called_once()
            call_args = mock_gen.call_args
            assert call_args[0][0] == filters
            assert call_args[0][1] == Path("/export/eq.txt")

        window._bridge.progress_update.emit.assert_called_once()
        msg = window._bridge.progress_update.emit.call_args[0][0]
        assert msg == "File exported successfully"

    @pytest.mark.asyncio
    async def test_export_with_warnings(self, window) -> None:
        """Verify skip count included in success message when warnings present.

        Requirement: 7.3
        """
        filters = [_make_filter(100.0)]
        warnings = [
            ValidationWarning(
                field="type",
                message="Skipped UNKNOWN filter",
                original_value="None",
            ),
            ValidationWarning(
                field="type",
                message="Skipped UNKNOWN filter",
                original_value="None",
            ),
        ]

        with patch(
            "src.translator.rew_generator.REWGenerator.generate_file",
            return_value=warnings,
        ):
            await window._do_export(filters, "/export/eq.txt")

        window._bridge.progress_update.emit.assert_called_once()
        msg = window._bridge.progress_update.emit.call_args[0][0]
        assert "2" in msg
        assert "skipped" in msg
        assert "File exported successfully" in msg


# ---------------------------------------------------------------------------
# Export — Dialog Cancel
# ---------------------------------------------------------------------------


class TestExportDialogCancel:
    """Test _on_export_requested when user cancels the file dialog."""

    def test_export_dialog_cancel(self, window) -> None:
        """Verify run_async not called when user cancels file dialog.

        Requirement: 7.4
        """
        window._feedback_manager._is_active = False

        with patch(
            "src.gui.main_window.QFileDialog.getSaveFileName",
            return_value=("", ""),
        ):
            window._on_export_requested()

        window._bridge.run_async.assert_not_called()


# ---------------------------------------------------------------------------
# Export — I/O Error via bridge_wrapper
# ---------------------------------------------------------------------------


class TestExportIOError:
    """Test _do_export exception handling through _bridge_wrapper."""

    @pytest.mark.asyncio
    async def test_export_io_error(self, window) -> None:
        """Verify operation_error emitted when generate_file raises OSError.

        Requirement: 7.6
        """
        filters = [_make_filter(100.0)]

        with patch(
            "src.translator.rew_generator.REWGenerator.generate_file",
            side_effect=OSError("Permission denied"),
        ):
            await window._bridge_wrapper(
                "export", window._do_export(filters, "/readonly/eq.txt")
            )

        window._bridge.operation_error.emit.assert_called_once()
        error_type, message = window._bridge.operation_error.emit.call_args[0]
        assert error_type == "OSError"
        assert "could not be written" in message.lower()


# ---------------------------------------------------------------------------
# Export — Busy Guard
# ---------------------------------------------------------------------------


class TestExportBusyGuard:
    """Test _on_export_requested when another operation is in progress."""

    def test_export_blocked_when_busy(self, window) -> None:
        """Verify handler returns early when feedback manager is active.

        Requirement: 13.4
        """
        window._feedback_manager._is_active = True

        window._on_export_requested()

        window._bridge.run_async.assert_not_called()
