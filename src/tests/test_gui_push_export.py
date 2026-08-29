"""Unit tests for MainWindow push and export handlers.

Tests the push and export handler flows:
- _on_push_requested() -> guards busy, advances wizard, dispatches to
  PrimaryWorkflowManager.push()
- PrimaryWorkflowManager._do_push() -> creates PEQSettings from state,
  calls safe_write.execute() (moved out of MainWindow, docs/backlog.md
  item 2 Phase D)
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
from src.models.channel_mode import ChannelMode
from src.models.errors import BackupError, WiiMConnectionError, WiiMTimeoutError
from src.tests.conftest import close_coroutine_tree
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
    mock_bridge.run_async = MagicMock(side_effect=close_coroutine_tree)

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


def _setup_push_state(window) -> AsyncMock:
    """Set up wizard state required for a push operation."""
    window._wizard_controller.state.selected_source = "wifi"
    window._wizard_controller.state.current_filters = [
        _make_filter(100.0),
        _make_filter(200.0),
        _make_filter(500.0),
    ]
    window._wizard_controller.state.channel_mode = ChannelMode.STEREO
    window._wizard_controller.state.dry_run = False

    # Provide a mocked WiiMAdapter as PrimaryWorkflowManager's current
    # adapter (required by _do_push's _require_adapter() call) -- _do_push
    # now lives on the manager, not MainWindow, so window._wiim_adapter
    # itself is no longer what it reads.
    mock_adapter = MagicMock()
    mock_adapter.capabilities = MagicMock()
    window._wiim_adapter = mock_adapter
    window._primary_workflows.set_current_adapter(mock_adapter)

    # Provide a mocked SafeWrite via the factory _do_push now builds it
    # from, rather than a cached window._safe_write attribute.
    mock_safe_write = AsyncMock()
    window._primary_workflows._safe_write_factory = lambda adapter: mock_safe_write
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

        await window._primary_workflows._do_push()

        mock_safe_write.execute.assert_called_once()
        # Verify source_name passed correctly
        call_args = mock_safe_write.execute.call_args
        assert call_args[0][0] == "wifi"
        # Verify write_complete emitted with success and encoded backup path
        window._bridge.write_complete.emit.assert_called_once()
        emitted_result = window._bridge.write_complete.emit.call_args[0][0]
        assert emitted_result.success is True
        assert "wifi=" in str(emitted_result.backup_path)
        assert "/backups/wifi_backup.json" in str(emitted_result.backup_path).replace("\\", "/")

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

        await window._primary_workflows._do_push()

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

        await window._primary_workflows._do_push()

        window._bridge.write_complete.emit.assert_called_once_with(result)


# ---------------------------------------------------------------------------
# Push -- Multi-source round indicator
# ---------------------------------------------------------------------------


class TestPushMultiSourceRound:
    """Test push_round_changed emission for multi-source pushes."""

    @pytest.mark.asyncio
    async def test_single_source_does_not_emit_push_round_changed(self, window) -> None:
        """A single-source push (the common case) never emits push_round_changed."""
        mock_safe_write = _setup_push_state(window)
        result = WriteResult(success=True, rollback_success=None, backup_path=None)
        mock_safe_write.execute = AsyncMock(return_value=result)

        await window._primary_workflows._do_push()

        window._bridge.push_round_changed.emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_multi_source_emits_push_round_changed_per_source(self, window) -> None:
        """Each selected source emits push_round_changed with its 1-based
        index and the total count, in order."""
        mock_safe_write = _setup_push_state(window)
        window._wizard_controller.state.selected_sources = ["wifi", "optical"]
        result = WriteResult(success=True, rollback_success=None, backup_path=None)
        mock_safe_write.execute = AsyncMock(return_value=result)

        await window._primary_workflows._do_push()

        calls = [c.args for c in window._bridge.push_round_changed.emit.call_args_list]
        assert calls == [("wifi", 1, 2), ("optical", 2, 2)]


# ---------------------------------------------------------------------------
# Push — Multi-source partial failure (smoke #242)
# ---------------------------------------------------------------------------


class TestPushMultiSourcePartialFailure:
    """A multi-source push that fails partway through must surface the
    prior-succeeded sources' backups for Undo, and must NOT lose the
    failing source's own backup_path/rollback_success/error_message --
    see WriteResult.partial_sources/partial_backup_paths docstrings.
    """

    @pytest.mark.asyncio
    async def test_second_of_three_sources_failing_reports_one_partial_source(
        self, window
    ) -> None:
        """wifi succeeds, optical fails, hdmi is never attempted. The emitted
        result must carry partial_sources=1 and an encoded backup string for
        wifi alone -- not for a source that never ran.
        """
        mock_safe_write = _setup_push_state(window)
        window._wizard_controller.state.selected_sources = ["wifi", "optical", "hdmi"]
        wifi_result = WriteResult(
            success=True, rollback_success=None, backup_path=Path("/backups/wifi.json")
        )
        optical_result = WriteResult(
            success=False,
            rollback_success=True,
            backup_path=Path("/backups/optical.json"),
            error_message="Verification mismatch on band 2",
        )
        mock_safe_write.execute = AsyncMock(side_effect=[wifi_result, optical_result])

        await window._primary_workflows._do_push()

        # Only wifi and optical were attempted -- hdmi is never reached.
        assert mock_safe_write.execute.call_count == 2

        window._bridge.write_complete.emit.assert_called_once()
        emitted = window._bridge.write_complete.emit.call_args[0][0]
        assert emitted is optical_result  # mutated in place, not replaced
        assert emitted.success is False
        assert emitted.partial_sources == 1
        assert emitted.partial_backup_paths == "wifi=/backups/wifi.json"
        # The failing source's OWN backup/rollback/error info must survive
        # unchanged -- that's what critical-recovery display depends on.
        assert emitted.backup_path == Path("/backups/optical.json")
        assert emitted.rollback_success is True
        assert emitted.error_message == "Verification mismatch on band 2"

    @pytest.mark.asyncio
    async def test_first_source_failing_reports_zero_partial_sources(self, window) -> None:
        """No prior source succeeded, so there's nothing to offer Undo for --
        partial_sources must stay 0 and partial_backup_paths must stay None,
        exactly like a single-source failure (the common case).
        """
        mock_safe_write = _setup_push_state(window)
        window._wizard_controller.state.selected_sources = ["wifi", "optical"]
        failure = WriteResult(
            success=False,
            rollback_success=True,
            backup_path=Path("/backups/wifi.json"),
            error_message="Verification mismatch",
        )
        mock_safe_write.execute = AsyncMock(return_value=failure)

        await window._primary_workflows._do_push()

        assert mock_safe_write.execute.call_count == 1
        emitted = window._bridge.write_complete.emit.call_args[0][0]
        assert emitted.partial_sources == 0
        assert emitted.partial_backup_paths is None
        assert emitted.backup_path == Path("/backups/wifi.json")

    @pytest.mark.asyncio
    async def test_two_of_four_sources_succeed_third_fails_auto_rollback_restores_both(
        self, window, tmp_path
    ) -> None:
        """wifi and optical succeed, hdmi fails, ethernet is never attempted.
        wifi/optical are automatically rolled back (docs/backlog.md item 3)
        -- auto_rollback_attempted=2, partial_sources=0 (nothing left to
        manually undo), no Undo button offered.
        """
        mock_safe_write = _setup_push_state(window)
        window._wizard_controller.state.selected_sources = [
            "wifi", "optical", "hdmi", "ethernet",
        ]
        wifi_backup = tmp_path / "wifi.json"
        wifi_backup.write_text("{}", encoding="utf-8")
        optical_backup = tmp_path / "optical.json"
        optical_backup.write_text("{}", encoding="utf-8")

        wifi_result = WriteResult(success=True, backup_path=wifi_backup)
        optical_result = WriteResult(success=True, backup_path=optical_backup)
        hdmi_result = WriteResult(
            success=False, rollback_success=True, backup_path=Path("/backups/hdmi.json"),
            error_message="Verification mismatch",
        )
        mock_safe_write.execute = AsyncMock(
            side_effect=[wifi_result, optical_result, hdmi_result]
        )
        mock_safe_write.undo = AsyncMock(return_value=WriteResult(success=True))

        await window._primary_workflows._do_push()

        assert mock_safe_write.execute.call_count == 3
        assert mock_safe_write.undo.await_count == 2
        undo_paths = {c.args[0] for c in mock_safe_write.undo.await_args_list}
        assert undo_paths == {wifi_backup, optical_backup}

        window._bridge.write_complete.emit.assert_called_once()
        emitted = window._bridge.write_complete.emit.call_args[0][0]
        assert emitted.success is False
        assert emitted.auto_rollback_attempted == 2
        assert emitted.partial_sources == 0
        assert emitted.partial_backup_paths is None
        # hdmi's own recovery info survives unchanged.
        assert emitted.backup_path == Path("/backups/hdmi.json")
        assert emitted.error_message == "Verification mismatch"

    @pytest.mark.asyncio
    async def test_auto_rollback_partial_failure_reports_only_failed_subset(
        self, window, tmp_path
    ) -> None:
        """wifi and optical succeed, hdmi fails. Auto-rollback of wifi
        succeeds but optical's own restore fails -- partial_sources must
        report only optical (1), not both, and auto_rollback_attempted
        stays 2 so the UI can say "1 of 2" rather than implying nothing was
        attempted.
        """
        mock_safe_write = _setup_push_state(window)
        window._wizard_controller.state.selected_sources = ["wifi", "optical", "hdmi"]
        wifi_backup = tmp_path / "wifi.json"
        wifi_backup.write_text("{}", encoding="utf-8")
        optical_backup = tmp_path / "optical.json"
        optical_backup.write_text("{}", encoding="utf-8")

        wifi_result = WriteResult(success=True, backup_path=wifi_backup)
        optical_result = WriteResult(success=True, backup_path=optical_backup)
        hdmi_result = WriteResult(
            success=False, rollback_success=True, backup_path=Path("/backups/hdmi.json"),
            error_message="Verification mismatch",
        )
        mock_safe_write.execute = AsyncMock(
            side_effect=[wifi_result, optical_result, hdmi_result]
        )

        async def _undo(path: Path, source_name: str, **_kwargs: object) -> WriteResult:
            if path == optical_backup:
                return WriteResult(success=False, error_message="Device unreachable")
            return WriteResult(success=True)

        mock_safe_write.undo = _undo

        await window._primary_workflows._do_push()

        emitted = window._bridge.write_complete.emit.call_args[0][0]
        assert emitted.auto_rollback_attempted == 2
        assert emitted.partial_sources == 1
        assert emitted.partial_backup_paths == f"optical={optical_backup}"

    @pytest.mark.asyncio
    async def test_main_window_offers_undo_for_partial_multi_source_failure(
        self, window
    ) -> None:
        """MainWindow._on_write_complete must pass partial_sources through to
        PushPage.set_failure() and store the encoded prior-sources backup
        string (not the failing source's own backup_path) as
        last_backup_path, so a subsequent Undo click restores the right
        sources via the existing multi-source undo path.
        """
        result = WriteResult(
            success=False,
            rollback_success=True,
            backup_path=Path("/backups/optical.json"),
            error_message="Verification mismatch",
            partial_sources=1,
            partial_backup_paths="wifi=/backups/wifi.json",
        )

        with patch.object(window._push_page, "set_failure") as mock_set_failure:
            window._on_write_complete(result)

        mock_set_failure.assert_called_once_with(
            "Verification mismatch", str(Path("/backups/optical.json")), False, 1,
            True, 0,
        )
        assert window._wizard_controller.state.last_backup_path == "wifi=/backups/wifi.json"


# ---------------------------------------------------------------------------
# Push — Exception via bridge_wrapper
# ---------------------------------------------------------------------------


class TestPushException:
    """Test _do_push exception handling through _bridge_wrapper."""

    @pytest.mark.asyncio
    async def test_push_exception_emits_operation_error(self, window) -> None:
        """A genuinely unexpected exception (not one of the domain
        connection/response/backup types _do_push()'s PEQ loop now catches
        -- see TestPushConnectionFailure below, docs/backlog.md item 9)
        still safety-nets through operation_error via _bridge_wrapper's
        catch-all, rather than being silently swallowed.

        Requirement: 6.1, 12.1
        """
        mock_safe_write = _setup_push_state(window)
        mock_safe_write.execute = AsyncMock(
            side_effect=ConnectionError("Device lost connection")
        )

        await window._bridge_wrapper("push", window._primary_workflows._do_push())

        window._bridge.operation_error.emit.assert_called_once()
        error_type, _message = window._bridge.operation_error.emit.call_args[0]
        assert error_type == "ConnectionError"


# ---------------------------------------------------------------------------
# Push — Connection/response/backup errors during write (docs/backlog.md
# item 9: main card must reflect this, not just a status banner)
# ---------------------------------------------------------------------------


class TestPushConnectionFailure:
    """A WiiMConnectionError/WiiMTimeoutError/BackupError raised by
    safe_write.execute() mid-push must be caught inside _do_push() and
    turned into a failed WriteResult (verified=False) emitted via
    write_complete -- not left to propagate to _bridge_wrapper's generic
    operation_error handler, which never reaches PushPage.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "exc",
        [
            WiiMConnectionError("Could not reach device"),
            WiiMTimeoutError("Device not responding"),
            BackupError("Disk full"),
        ],
        ids=["connection", "timeout", "backup"],
    )
    async def test_single_source_emits_unverified_failure(self, window, exc) -> None:
        mock_safe_write = _setup_push_state(window)
        mock_safe_write.execute = AsyncMock(side_effect=exc)

        await window._bridge_wrapper("push", window._primary_workflows._do_push())

        window._bridge.operation_error.emit.assert_not_called()
        window._bridge.write_complete.emit.assert_called_once()
        emitted = window._bridge.write_complete.emit.call_args[0][0]
        assert emitted.success is False
        assert emitted.verified is False
        assert emitted.backup_path is None
        assert emitted.error_message == str(exc)
        assert emitted.partial_sources == 0
        assert emitted.auto_rollback_attempted == 0

    @pytest.mark.asyncio
    async def test_second_of_three_sources_raising_reports_one_partial_source(
        self, window
    ) -> None:
        """wifi succeeds, optical's execute() raises (not returns a failed
        result), hdmi is never attempted -- mirrors
        TestPushMultiSourcePartialFailure's returned-failure case, proving
        the two failure origins (raised vs. returned) can't drift apart
        (both go through PrimaryWorkflowManager._finalize_push_failure()).
        """
        mock_safe_write = _setup_push_state(window)
        window._wizard_controller.state.selected_sources = ["wifi", "optical", "hdmi"]
        wifi_result = WriteResult(
            success=True, rollback_success=None, backup_path=Path("/backups/wifi.json")
        )
        mock_safe_write.execute = AsyncMock(
            side_effect=[wifi_result, WiiMConnectionError("Could not reach device")]
        )

        await window._primary_workflows._do_push()

        assert mock_safe_write.execute.call_count == 2
        window._bridge.write_complete.emit.assert_called_once()
        emitted = window._bridge.write_complete.emit.call_args[0][0]
        assert emitted.success is False
        assert emitted.verified is False
        assert emitted.backup_path is None
        assert emitted.partial_sources == 1
        assert emitted.partial_backup_paths == "wifi=/backups/wifi.json"

    @pytest.mark.asyncio
    async def test_roomfit_connection_error_emits_write_complete_not_operation_error(
        self, window
    ) -> None:
        """RoomFit's except block (primary_workflows.py, already existing
        before docs/backlog.md item 9) has zero test coverage today --
        close that gap, not just add PEQ coverage."""
        from src.gui.wizard_controller import FlowType

        state = window._wizard_controller.state
        state.flow_type = FlowType.ROOMFIT
        state.roomfit_profile_name = "Living Room"
        state.selected_sources = ["wifi"]
        state.dry_run = False

        mock_adapter = MagicMock()
        mock_adapter.capabilities = MagicMock()
        window._wiim_adapter = mock_adapter
        window._primary_workflows.set_current_adapter(mock_adapter)

        mock_roomfit_safe_write = AsyncMock()
        mock_roomfit_safe_write.execute = AsyncMock(
            side_effect=WiiMConnectionError("Could not reach device")
        )
        window._primary_workflows._roomfit_safe_write_factory = (
            lambda adapter: mock_roomfit_safe_write
        )

        await window._bridge_wrapper("push", window._primary_workflows._do_push())

        window._bridge.operation_error.emit.assert_not_called()
        window._bridge.write_complete.emit.assert_called_once()
        emitted = window._bridge.write_complete.emit.call_args[0][0]
        assert emitted.success is False
        assert emitted.error_message == "Could not reach device"
        assert emitted.verified is False

    @pytest.mark.asyncio
    async def test_finalize_push_failure_treats_both_failure_origins_identically(
        self, window, tmp_path
    ) -> None:
        """_finalize_push_failure() is the one place partial_sources/
        partial_backup_paths get populated, called from both the returned-
        failure branch and the raised-exception branch in _do_push()'s PEQ
        loop -- proving directly that the same backup_paths input produces
        the same partial-source outcome regardless of which of the two
        failure origins the failing source's own WriteResult came from.
        """
        mock_safe_write = _setup_push_state(window)
        wifi_backup = tmp_path / "wifi.json"
        wifi_backup.write_text("{}", encoding="utf-8")
        backup_paths = [("wifi", str(wifi_backup))]
        mock_safe_write.undo = AsyncMock(
            return_value=WriteResult(success=False, error_message="Device unreachable")
        )

        returned_failure = WriteResult(
            success=False, rollback_success=True, backup_path=Path("/backups/optical.json"),
            error_message="Verification mismatch",
        )
        raised_failure = WriteResult(
            success=False, error_message="Could not reach device", backup_path=None,
            verified=False,
        )

        await window._primary_workflows._finalize_push_failure(
            returned_failure, list(backup_paths), mock_safe_write
        )
        await window._primary_workflows._finalize_push_failure(
            raised_failure, list(backup_paths), mock_safe_write
        )

        assert returned_failure.auto_rollback_attempted == raised_failure.auto_rollback_attempted
        assert returned_failure.partial_sources == raised_failure.partial_sources
        assert returned_failure.partial_backup_paths == raised_failure.partial_backup_paths
        # Every other field stays exactly what the caller set -- proving
        # _finalize_push_failure() only ever mutates the three
        # auto-rollback outcome fields, never backup_path/error_message/
        # verified/rollback_success.
        assert returned_failure.backup_path == Path("/backups/optical.json")
        assert raised_failure.backup_path is None
        assert raised_failure.verified is False


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

        await window._primary_workflows._do_push()

        call_args = mock_safe_write.execute.call_args
        settings = call_args[0][1]
        assert settings.channel_mode == ChannelMode.STEREO
        assert settings.bands == window._wizard_controller.state.current_filters

    @pytest.mark.asyncio
    async def test_push_lr_mode(self, window) -> None:
        """Verify PEQSettings uses explicit per-channel state for lr channel mode.

        _do_push always passes state.filters_l/filters_r explicitly (never
        re-derives a split positionally) — see code review fix 2026-06-28.

        Requirement: 6.1, 6.2
        """
        mock_safe_write = _setup_push_state(window)
        window._wizard_controller.state.channel_mode = ChannelMode.LR
        filters_l = [_make_filter(f) for f in [100.0, 200.0]]
        filters_r = [_make_filter(f) for f in [500.0, 1000.0]]
        window._wizard_controller.state.filters_l = filters_l
        window._wizard_controller.state.filters_r = filters_r
        window._wizard_controller.state.current_filters = filters_l + filters_r
        result = WriteResult(success=True, rollback_success=None)
        mock_safe_write.execute = AsyncMock(return_value=result)

        await window._primary_workflows._do_push()

        call_args = mock_safe_write.execute.call_args
        settings = call_args[0][1]
        assert settings.channel_mode == ChannelMode.LR
        assert settings.bands_l == filters_l
        assert settings.bands_r == filters_r

    @pytest.mark.asyncio
    async def test_push_lr_mode_empty_channel_emits_write_complete_failure(
        self, window
    ) -> None:
        """An L/R push with one empty channel raises ValueError from
        build_peq_settings() (resolve_channel_split -> require_lr_filters).
        Unlike the RoomFit branch, the PEQ branch had no local try/except,
        so this used to propagate to _bridge_wrapper's generic
        operation_error handler instead of driving PushPage.set_failure()
        via write_complete like every other push failure does (round-4
        review finding #4, 2026-07-19)."""
        mock_safe_write = _setup_push_state(window)
        window._wizard_controller.state.channel_mode = ChannelMode.LR
        window._wizard_controller.state.filters_l = [_make_filter(100.0)]
        window._wizard_controller.state.filters_r = []
        window._wizard_controller.state.current_filters = [_make_filter(100.0)]
        mock_safe_write.execute = AsyncMock()

        await window._primary_workflows._do_push()

        mock_safe_write.execute.assert_not_called()
        window._bridge.write_complete.emit.assert_called_once()
        emitted_result = window._bridge.write_complete.emit.call_args[0][0]
        assert emitted_result.success is False
        window._bridge.operation_error.emit.assert_not_called()


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
            await window._primary_workflows._do_export(filters, "/export/eq.txt")

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
            await window._primary_workflows._do_export(filters, "/export/eq.txt")

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
                "export", window._primary_workflows._do_export(filters, "/readonly/eq.txt")
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
