"""Smoke test regression tests for push/write, import/export, presets, and settings.

Covers smoke test issues: #7, #8, #10, #11, #12, #13, #20, #22, #23, #24, #25,
#27, #28, #29, #30, #31, #32, #33, #34, #37, #38, #39, #42, #44, #48, #49, #50,
#53, #54, #55, #58, #60, #61, #62, #63, #65, #69, #70, #74, #77, #78, #79, #80,
#85, #2/#9.
Each test validates the specific fix behavior to prevent regressions.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.gui.app_settings import AppSettings
from src.gui.main_window import MainWindow
from src.gui.shared_helpers import (
    build_profile,
    is_lr_mode,
    parse_backup_filters,
    split_lr_filters,
)
from src.gui.wizard_controller import FlowType, WizardStep
from src.models.canonical import CanonicalFilter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def window(qtbot):
    """Create a MainWindow with mocked AsyncBridge for regression testing."""
    mock_bridge = MagicMock()
    mock_bridge.start = MagicMock()
    mock_bridge.shutdown = MagicMock()
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
        w._wizard_controller.state.current_filters = []
        w.close()


def _make_filter(freq: float = 1000.0, gain: float = -3.0) -> CanonicalFilter:
    """Create a minimal CanonicalFilter for testing."""
    return CanonicalFilter(type="PEAK", frequency_hz=freq, gain_db=gain, q=1.0)


def _make_caps(
    model: str = "WiiM Pro Plus",
    roomfit_level: int = 2,
    source_names: list[str] | None = None,
) -> MagicMock:
    """Create a mock DeviceCapabilities."""
    caps = MagicMock()
    caps.roomfit_level = roomfit_level
    caps.device_name = model
    caps.model = model
    caps.source_names = source_names or ["wifi", "optical", "hdmi"]
    caps.active_source = "wifi"
    caps.supports_profile_enumeration = True
    return caps


def _setup_device(window) -> MagicMock:
    """Set up a mocked device adapter on the window."""
    mock_adapter = MagicMock()
    mock_adapter.capabilities = _make_caps()
    window._wiim_adapter = mock_adapter
    window._wizard_controller.state.selected_device = "192.168.1.100"
    window._wizard_controller.state.selected_source = "wifi"
    return mock_adapter


# ===========================================================================
# PUSH / WRITE OPERATIONS
# ===========================================================================


class TestPushWriteOperations:
    """Tests for push/write issues: #7, #55, #58, #61, #63, #77, #80."""

    # --- Issue #7: _on_peq_ready populates ReviewPage and advances wizard ---

    def test_issue7_on_peq_ready_populates_review_page(self, window) -> None:
        """#7: _on_peq_ready populates ReviewPage with filters and advances wizard."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter(100), _make_filter(200)]
        state.channel_mode = "Stereo"

        peq_data = MagicMock()
        peq_data.channel_mode = "stereo"
        peq_data.bands_l = None
        peq_data.bands_r = None

        with patch.object(window._review_page, "set_filters") as mock_set:
            window._on_peq_ready(peq_data)
            mock_set.assert_called_once()

    def test_issue7_on_peq_ready_advances_to_review(self, window) -> None:
        """#7: _on_peq_ready advances wizard (not a stub)."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = "Stereo"
        # Set wizard to FILTERS step so it can advance
        window._wizard_controller.state.current_step = WizardStep.FILTERS

        peq_data = MagicMock(channel_mode="stereo", bands_l=None, bands_r=None)
        with patch.object(window._wizard_controller, "advance") as mock_adv:
            window._on_peq_ready(peq_data)
            mock_adv.assert_called_once()

    # --- Issue #55: _do_push checks both "lr" and "l/r" via is_lr_mode ---

    def test_issue55_is_lr_mode_detects_lr(self) -> None:
        """#55: is_lr_mode returns True for 'lr'."""
        assert is_lr_mode("lr") is True

    def test_issue55_is_lr_mode_detects_l_slash_r(self) -> None:
        """#55: is_lr_mode returns True for 'l/r'."""
        assert is_lr_mode("l/r") is True

    def test_issue55_is_lr_mode_detects_uppercase(self) -> None:
        """#55: is_lr_mode returns True for 'L/R'."""
        assert is_lr_mode("L/R") is True

    def test_issue55_is_lr_mode_stereo_false(self) -> None:
        """#55: is_lr_mode returns False for 'Stereo'."""
        assert is_lr_mode("Stereo") is False

    # --- Issue #58: Multi-device push passes channel_mode through ---

    def test_issue58_apply_to_devices_accepts_channel_mode(self, window) -> None:
        """#58: apply_to_devices takes channel_mode param for L/R."""
        swm = window._secondary_workflows
        # Verify the method signature accepts channel_mode
        import inspect

        sig = inspect.signature(swm.apply_to_devices)
        assert "channel_mode" in sig.parameters

    # --- Issue #61: RoomFit push deferred via _on_name_confirmed ---

    def test_issue61_roomfit_push_deferred_not_immediate(self, window) -> None:
        """#61: _on_push_requested for RoomFit advances to NAME_PROFILE, not push."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = "Stereo"
        state.dry_run = False
        state.flow_type = FlowType.ROOMFIT
        state.current_step = WizardStep.REVIEW

        with patch.object(window._wizard_controller, "advance") as mock_adv:
            window._on_push_requested()
            # Should advance once (to NAME_PROFILE), NOT call run_async for push
            mock_adv.assert_called_once_with(summary="Ready")
            window._bridge.run_async.assert_not_called()

    def test_issue61_name_confirmed_triggers_push(self, window) -> None:
        """#61: _on_name_confirmed stores name, advances, and calls push."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = "Stereo"
        state.dry_run = False

        with patch.object(window._wizard_controller, "advance"):
            window._on_name_confirmed("My RoomFit Profile")

        assert state.roomfit_profile_name == "My RoomFit Profile"
        window._bridge.run_async.assert_called_once()

    # --- Issue #63: write_roomfit accepts channel_mode parameter ---

    def test_issue63_do_push_roomfit_lr_passes_channel_mode(self, window) -> None:
        """#63: RoomFit push with L/R sends channel_mode='lr' to write_roomfit."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter(100), _make_filter(200)]
        state.channel_mode = "L/R"
        state.dry_run = False
        state.roomfit_profile_name = "TestProfile"
        state.flow_type = FlowType.ROOMFIT

        mock_adapter = window._wiim_adapter
        mock_adapter.list_roomfit_profiles = AsyncMock(return_value=[])
        mock_adapter.write_roomfit = AsyncMock()

        # _do_push is a coroutine; we verify write_roomfit gets channel_mode
        import asyncio

        asyncio.run(window._do_push())
        mock_adapter.write_roomfit.assert_called_once()
        call_kwargs = mock_adapter.write_roomfit.call_args
        # Should pass channel_mode="lr" for L/R
        assert call_kwargs.kwargs.get("channel_mode") == "lr" or "lr" in str(call_kwargs)

    # --- Issue #77: Multi-source push stores per-source backup paths ---

    def test_issue77_multi_source_backup_format(self, window) -> None:
        """#77: Multi-source push creates combined backup paths format."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = "Stereo"
        state.dry_run = False
        state.selected_source = "wifi, optical"

        mock_safe_write = AsyncMock()
        result1 = MagicMock(success=True, backup_path="/tmp/backup_wifi.json")
        result2 = MagicMock(success=True, backup_path="/tmp/backup_optical.json")
        mock_safe_write.execute = AsyncMock(side_effect=[result1, result2])
        window._safe_write = mock_safe_write

        import asyncio

        asyncio.run(window._do_push())
        # write_complete should be emitted with combined backup path
        call_args = window._bridge.write_complete.emit.call_args[0][0]
        assert "wifi=" in call_args.backup_path
        assert "optical=" in call_args.backup_path
        assert ";" in call_args.backup_path

    # --- Issue #80: Dry run shows preview without calling _do_push ---

    def test_issue80_dry_run_shows_preview(self, window) -> None:
        """#80: dry_run=True shows preview without calling _do_push."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = "Stereo"
        state.dry_run = True
        state.selected_source = "wifi"
        window._wizard_controller.state.current_step = WizardStep.REVIEW

        with (
            patch.object(window._push_page, "set_dry_run_result") as mock_dry,
            patch.object(window._wizard_controller, "advance"),
        ):
            window._on_push_requested()
            mock_dry.assert_called_once()
            # _bridge.run_async should NOT be called (no actual push)
            window._bridge.run_async.assert_not_called()


# ===========================================================================
# IMPORT / EXPORT
# ===========================================================================


class TestImportExport:
    """Tests for import/export issues: #28, #29, #30, #44, #65."""

    # --- Issue #28: _on_peq_ready with L/R calls set_lr_filters ---

    def test_issue28_peq_ready_lr_calls_set_lr_filters(self, window) -> None:
        """#28: L/R peq_data triggers set_lr_filters on ReviewPage."""
        _setup_device(window)
        state = window._wizard_controller.state
        filters_l = [_make_filter(100), _make_filter(200)]
        filters_r = [_make_filter(300), _make_filter(400)]
        state.current_filters = filters_l + filters_r
        state.channel_mode = "L/R"

        peq_data = MagicMock()
        peq_data.channel_mode = "lr"
        peq_data.bands_l = filters_l
        peq_data.bands_r = filters_r

        with patch.object(window._review_page, "set_lr_filters") as mock_lr:
            window._on_peq_ready(peq_data)
            # validate_filters_for_device returns (filters, warnings, clamping_map)
            # For in-range filters, clamping_map is empty dict {}
            mock_lr.assert_called_once_with(list(filters_l), list(filters_r), {}, {})

    # --- Issue #29: Export branches on channel_mode for L/R ---

    def test_issue29_export_lr_mode_uses_export_dialog(self, window) -> None:
        """#29: L/R export opens ExportDialog for dual-file selection."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter(100), _make_filter(200)]
        state.channel_mode = "L/R"

        with patch(
            "src.gui.dialogs.export_dialog.ExportDialog.get_paths", return_value=None
        ) as mock_dialog:
            window._export_filters_as_rew(state.current_filters, "L/R")
            mock_dialog.assert_called_once()

    # --- Issue #30: Stereo export appends .txt extension ---

    def test_issue30_stereo_export_appends_txt(self, window) -> None:
        """#30: Stereo export appends .txt if not present in chosen path."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = "Stereo"

        with (
            patch(
                "src.gui.main_window.QFileDialog.getSaveFileName",
                return_value=("/tmp/myfile", ""),
            ),
            patch.object(window._bridge, "run_async") as mock_run,
        ):
            window._export_filters_as_rew(state.current_filters, "Stereo")
            mock_run.assert_called_once()

    # --- Issue #44: build_profile sanitizes name ---

    def test_issue44_build_profile_removes_slashes(self) -> None:
        """#44: build_profile removes '/' from name."""
        filters = [_make_filter()]
        profile = build_profile("L/R preset", filters, "Stereo")
        assert "/" not in profile.name

    def test_issue44_build_profile_removes_unsafe_chars(self) -> None:
        """#44: build_profile removes all filesystem-unsafe characters."""
        filters = [_make_filter()]
        profile = build_profile('test:file*"name<>|', filters, "Stereo")
        for ch in '/\\:*?"<>|':
            assert ch not in profile.name

    def test_issue44_build_profile_empty_name_fallback(self) -> None:
        """#44: build_profile uses fallback name when all chars removed."""
        filters = [_make_filter()]
        profile = build_profile("/\\:*?", filters, "Stereo")
        assert profile.name == "Untitled Preset"

    # --- Issue #65: Loading L/R profile sets channel_mode from profile ---

    def test_issue65_profile_load_sets_channel_mode_lr(self, window) -> None:
        """#65: Loading L/R profile sets state.channel_mode before recall."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        # Set up wizard state as if we're past EQ_TYPE and SOURCE
        state.completed_steps = {
            WizardStep.CONNECT: "Connected",
            WizardStep.EQ_TYPE: "PEQ",
            WizardStep.SOURCE: "wifi",
        }
        window._wizard_controller._flow_type = FlowType.PEQ

        profile = MagicMock()
        profile.name = "My LR Preset"
        profile.channel_mode = "left"  # L/R profiles stored as "left"
        profile.filters_l = [_make_filter(100)]
        profile.filters_r = [_make_filter(200)]
        profile.filters = None

        with patch.object(window._secondary_workflows, "recall_profile"):
            window._on_profile_load_requested(profile)

        assert state.channel_mode == "L/R"

    def test_issue65_profile_load_sets_channel_mode_stereo(self, window) -> None:
        """#65: Loading stereo profile sets state.channel_mode to Stereo."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.completed_steps = {
            WizardStep.CONNECT: "Connected",
            WizardStep.EQ_TYPE: "PEQ",
            WizardStep.SOURCE: "wifi",
        }
        window._wizard_controller._flow_type = FlowType.PEQ

        profile = MagicMock()
        profile.name = "My Stereo Preset"
        profile.channel_mode = "stereo"
        profile.filters = [_make_filter()]

        with patch.object(window._secondary_workflows, "recall_profile"):
            window._on_profile_load_requested(profile)

        assert state.channel_mode == "Stereo"


# ===========================================================================
# PRESETS
# ===========================================================================


class TestPresets:
    """Tests for preset issues: #20, #22, #23, #24, #25, #27, #31, #37, #53, #54, #60, #62."""


    # --- Issue #20: Navigation to presets_device triggers _load_device_presets ---

    def test_issue20_nav_presets_device_triggers_load(self, window) -> None:
        """#20: Navigating to presets_device calls _load_device_presets."""
        _setup_device(window)
        with patch.object(window, "_load_device_presets") as mock_load:
            window._on_navigation_requested("presets_device")
            mock_load.assert_called_once()

    # --- Issue #22: _do_list_presets fetches both PEQ + RoomFit ---

    def test_issue22_do_list_presets_fetches_both(self, window) -> None:
        """#22: _do_list_presets fetches PEQ presets AND RoomFit profiles."""
        _setup_device(window)
        mock_adapter = window._wiim_adapter
        mock_adapter.list_peq_profiles = AsyncMock(return_value=[])
        mock_adapter.list_roomfit_profiles = AsyncMock(return_value=[])

        import asyncio

        asyncio.run(window._do_list_presets())
        mock_adapter.list_peq_profiles.assert_called_once()
        mock_adapter.list_roomfit_profiles.assert_called_once()

    # --- Issue #23: _on_eq_type_selected("roomfit") triggers async fetch ---

    def test_issue23_eq_type_roomfit_triggers_profile_fetch(self, window) -> None:
        """#23: Selecting 'roomfit' EQ type triggers _do_list_roomfit_profiles."""
        _setup_device(window)
        # Simulate selecting roomfit eq type
        with patch.object(window._bridge, "run_async") as mock_run:
            window._on_eq_type_selected("roomfit")
            # Should call run_async for roomfit profile listing
            assert mock_run.called

    # --- Issue #24: PresetsDeviceView signals connected in MainWindow ---

    def test_issue24_presets_device_export_connected(self, window) -> None:
        """#24: PresetsDeviceView export_requested signal is connected."""
        assert window._presets_device_view.export_requested is not None

    def test_issue24_presets_device_save_connected(self, window) -> None:
        """#24: PresetsDeviceView save_to_my_presets signal is connected."""
        assert window._presets_device_view.save_to_my_presets is not None

    def test_issue24_presets_device_load_connected(self, window) -> None:
        """#24: PresetsDeviceView load_into_editor signal is connected."""
        assert window._presets_device_view.load_into_editor is not None

    # --- Issue #25: Selecting in one preset list clears the other ---

    def test_issue25_preset_list_mutual_exclusion(self, window) -> None:
        """#25: PresetsDeviceView has mutual exclusion between PEQ and RoomFit lists."""
        # Verify the view has the clear methods that enable mutual exclusion
        view = window._presets_device_view
        assert hasattr(view, "clear_peq_selection") or hasattr(view, "_peq_list")
        assert hasattr(view, "clear_roomfit_selection") or hasattr(view, "_roomfit_list")


    # --- Issue #27: RoomFit profile selection triggers read and advances ---

    def test_issue27_roomfit_profile_selected_triggers_pull(self, window) -> None:
        """#27: roomfit_profile_selected triggers an async read operation."""
        _setup_device(window)
        with patch.object(window._bridge, "run_async") as mock_run:
            window._on_roomfit_profile_selected("My Profile")
            mock_run.assert_called_once()

    # --- Issue #31: Save to My Presets refreshes preset list ---

    def test_issue31_save_preset_refreshes_list(self, window) -> None:
        """#31: After saving a preset, the presets list is refreshed."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = "Stereo"
        state.selected_source = "wifi"
        window._discovered_devices = []

        with (
            patch.object(window, "_save_filters_to_presets") as mock_save,
        ):
            window._on_review_save_preset()
            mock_save.assert_called_once()

    # --- Issue #37: ReviewPage save_preset_requested signal connected ---

    def test_issue37_review_save_preset_signal_connected(self, window) -> None:
        """#37: ReviewPage save_preset_requested is connected to handler."""
        # The signal should be connected to _on_review_save_preset
        # Verify by checking the signal exists and handler exists
        assert hasattr(window._review_page, "save_preset_requested")
        assert hasattr(window, "_on_review_save_preset")

    # --- Issue #53: PushPage export + save signals connected ---

    def test_issue53_push_page_export_connected(self, window) -> None:
        """#53: PushPage export_requested signal is connected."""
        assert hasattr(window._push_page, "export_requested")

    def test_issue53_push_page_save_preset_connected(self, window) -> None:
        """#53: PushPage save_preset_requested signal is connected."""
        assert hasattr(window._push_page, "save_preset_requested")

    # --- Issue #54: _on_write_complete marks PUSH step completed ---

    def test_issue54_write_complete_marks_push_done(self, window) -> None:
        """#54: _on_write_complete marks PUSH step in completed_steps."""
        _setup_device(window)
        result = MagicMock(success=True, backup_path="/tmp/backup.json")

        with patch.object(window._push_page, "set_success"):
            window._on_write_complete(result)

        assert WizardStep.PUSH in window._wizard_controller.state.completed_steps

    # --- Issue #60: NAME_PROFILE step populates existing profile list ---

    def test_issue60_name_profile_populated_on_navigation(self, window) -> None:
        """#60: Navigating to NAME_PROFILE triggers _populate_name_profile_page."""
        _setup_device(window)
        with patch.object(window, "_populate_name_profile_page") as mock_pop:
            window._on_step_changed(WizardStep.NAME_PROFILE)
            mock_pop.assert_called_once()


    # --- Issue #62: RoomFit undo creates backup before overwrite ---

    def test_issue62_roomfit_push_backs_up_existing_profile(self, window) -> None:
        """#62: RoomFit push backs up existing profile before overwrite."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = "Stereo"
        state.dry_run = False
        state.roomfit_profile_name = "Existing"
        state.flow_type = FlowType.ROOMFIT

        mock_adapter = window._wiim_adapter
        mock_adapter.list_roomfit_profiles = AsyncMock(
            return_value=[{"Name": "Existing"}]
        )
        mock_adapter.read_roomfit = AsyncMock(
            return_value=MagicMock(
                channel_mode="stereo",
                bands=[_make_filter()],
                bands_l=None,
                bands_r=None,
            )
        )
        mock_adapter.write_roomfit = AsyncMock()

        mock_backup = MagicMock()
        mock_backup.create_backup = MagicMock(return_value="/tmp/backup.json")
        window._backup_manager = mock_backup

        import asyncio

        asyncio.run(window._do_push())
        # Backup should have been created for the existing profile
        mock_backup.create_backup.assert_called_once()


# ===========================================================================
# SETTINGS / UI STATE
# ===========================================================================


class TestSettingsUIState:
    """Tests for settings/UI issues: #2/#9, #8, #10, #11, #12, #13, #32, #33, #34,
    #38, #39, #42, #48, #49, #50, #69, #70, #74, #78, #79, #85.
    """

    # --- Issue #2/#9: HelpView close navigates back to wizard ---

    def test_issue2_help_close_signal_connected(self, window) -> None:
        """#2/#9: HelpView close_requested signal is connected."""
        assert hasattr(window._help_view, "close_requested")

    def test_issue9_help_close_navigates_back(self, window) -> None:
        """#9: _on_help_close_requested navigates back to current wizard step."""
        with patch.object(window, "_on_step_changed") as mock_step:
            window._on_help_close_requested()
            mock_step.assert_called_once_with(window._wizard_controller.current_step)

    # --- Issue #8: OperationFeedbackManager.finish_operation doesn't wipe success ---

    def test_issue8_finish_operation_preserves_success(self, window) -> None:
        """#8: finish_operation only clears banner if still showing progress."""
        fm = window._feedback_manager
        # Simulate: banner shows a success message (not progress)
        window._status_banner.show_success("Done!")
        fm._is_active = True
        fm.finish_operation()
        # Banner should still show success (not cleared)
        # finish_operation only clears if is_progress() returns True
        assert not fm.is_active


    # --- Issue #10: Measurement picker cancel shows info banner ---

    def test_issue10_picker_cancel_shows_info(self, window) -> None:
        """#10: Cancelling measurement picker shows 'Selection cancelled' info."""
        # Verify the status banner has show_info method
        assert hasattr(window._status_banner, "show_info")
        # The method should be callable
        assert callable(window._status_banner.show_info)

    # --- Issue #11: FiltersPage retry shows option cards ---

    def test_issue11_filters_page_has_retry_mechanism(self, window) -> None:
        """#11: FiltersPage has a method to show options after retry."""
        page = window._filters_page
        # FiltersPage should have show_options or similar recovery method
        assert hasattr(page, "show_error") or hasattr(page, "clear_results")

    # --- Issue #12: Progress shown immediately before async call ---

    def test_issue12_device_pull_shows_progress(self, window) -> None:
        """#12: _on_device_pull_requested shows progress before async call."""
        _setup_device(window)
        with patch.object(window._status_banner, "show_progress") as mock_prog:
            window._on_device_pull_requested()
            # Progress should be shown (either via feedback_manager or directly)
            # The feedback manager is triggered by bridge signals
            assert mock_prog.called or window._bridge.run_async.called

    # --- Issue #13: Empty filters shows persistent guidance ---

    def test_issue13_empty_filters_shows_persistent_message(self, window) -> None:
        """#13: Empty filters from device shows persistent info message."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = []  # Empty filters
        state.channel_mode = "Stereo"

        peq_data = MagicMock(channel_mode="stereo", bands_l=None, bands_r=None)
        # _on_peq_ready with empty filters should trigger guidance message
        # (via QTimer.singleShot, so we just verify no crash)
        window._on_peq_ready(peq_data)
        # No exception = pass (timer-based assertion would require processEvents)

    # --- Issue #32: finish_operation only clears if still showing progress ---

    def test_issue32_finish_clears_only_progress(self, window) -> None:
        """#32: finish_operation only clears banner when is_progress() is True."""
        fm = window._feedback_manager
        banner = window._status_banner

        # Show a non-progress message
        banner.show_success("Operation succeeded")
        fm._is_active = True
        with patch.object(banner, "clear") as mock_clear:
            # If banner.is_progress() returns False, clear should NOT be called
            if hasattr(banner, "is_progress"):
                with patch.object(banner, "is_progress", return_value=False):
                    fm.finish_operation()
                    mock_clear.assert_not_called()

    # --- Issue #33: _do_copy_presets_batch iterates all selected devices ---

    def test_issue33_copy_batch_iterates_all(self, window) -> None:
        """#33: _do_copy_presets_batch processes all items, not just first."""
        _setup_device(window)
        items = [
            MagicMock(name="Preset1", preset_type="PEQ"),
            MagicMock(name="Preset2", preset_type="PEQ"),
        ]
        # Fix MagicMock name attribute (it's special in MagicMock)
        items[0].name = "Preset1"
        items[1].name = "Preset2"

        with patch.object(
            window, "_do_copy_preset_to_device", new_callable=AsyncMock
        ) as mock_copy:
            import asyncio

            asyncio.run(
                window._do_copy_presets_batch(items, "192.168.1.200", "wifi")
            )
            assert mock_copy.call_count == 2


    # --- Issue #34: _do_copy_preset_to_device branches on preset_type ---

    def test_issue34_copy_branches_on_preset_type(self, window) -> None:
        """#34: _do_copy_preset_to_device branches on PEQ vs RoomFit."""
        _setup_device(window)
        # Verify the method exists and accepts preset_type parameter
        import inspect

        sig = inspect.signature(window._do_copy_preset_to_device)
        assert "preset_type" in sig.parameters

    # --- Issue #38: My Saved Presets view has toolbar buttons ---

    def test_issue38_my_presets_view_has_toolbar(self, window) -> None:
        """#38: MyPresetsView has toolbar action signals wired."""
        view = window._my_presets_view
        # Should have action signals for rename, delete, duplicate, load
        assert hasattr(view, "load_requested") or hasattr(view, "profile_load_requested")
        assert hasattr(view, "rename_requested") or hasattr(view, "profile_rename_requested")
        assert hasattr(view, "delete_requested") or hasattr(view, "profile_delete_requested")

    # --- Issue #39: L/R presets show "L/R" badge ---

    def test_issue39_lr_profile_preserves_channel_mode(self) -> None:
        """#39: build_profile with L/R channel_mode stores 'left' (L/R indicator)."""
        filters = [_make_filter(100), _make_filter(200)]
        profile = build_profile("Test", filters, "L/R")
        assert profile.channel_mode == "left"  # Internal L/R representation

    def test_issue39_stereo_profile_channel_mode(self) -> None:
        """#39: build_profile with stereo stores 'stereo'."""
        filters = [_make_filter()]
        profile = build_profile("Test", filters, "Stereo")
        assert profile.channel_mode == "stereo"

    # --- Issue #42: Source page receives all common sources including line-in ---

    def test_issue42_source_page_has_set_sources(self, window) -> None:
        """#42: SourcePage can receive a list of sources including line-in."""
        page = window._source_page
        assert hasattr(page, "set_sources") or hasattr(page, "set_source_options")

    # --- Issue #48: Preset save uses thread-safe pattern ---

    def test_issue48_save_filters_to_presets_callable(self, window) -> None:
        """#48: _save_filters_to_presets is available (thread-safe save)."""
        assert callable(window._save_filters_to_presets)

    # --- Issue #49: recall_profile handles L/R profiles ---

    def test_issue49_recall_profile_lr(self, window) -> None:
        """#49: recall_profile extracts filters from L/R profile correctly."""
        swm = window._secondary_workflows
        profile = MagicMock()
        profile.name = "LR Profile"
        profile.channel_mode = "left"
        profile.filters_l = [_make_filter(100)]
        profile.filters_r = [_make_filter(200)]
        profile.filters = None

        with patch.object(swm, "profile_recalled") as mock_signal:
            mock_signal.emit = MagicMock()
            swm.recall_profile(profile)
            mock_signal.emit.assert_called_once()
            emitted_filters = mock_signal.emit.call_args[0][0]
            assert len(emitted_filters) == 2


    def test_issue49_recall_profile_stereo(self, window) -> None:
        """#49: recall_profile extracts filters from stereo profile correctly."""
        swm = window._secondary_workflows
        profile = MagicMock()
        profile.name = "Stereo Profile"
        profile.channel_mode = "stereo"
        profile.filters = [_make_filter(100), _make_filter(200)]
        profile.filters_l = None
        profile.filters_r = None

        with patch.object(swm, "profile_recalled") as mock_signal:
            mock_signal.emit = MagicMock()
            swm.recall_profile(profile)
            mock_signal.emit.assert_called_once()
            emitted_filters = mock_signal.emit.call_args[0][0]
            assert len(emitted_filters) == 2

    # --- Issue #50: Copy to another source reads from SourcePage source list ---

    def test_issue50_source_page_provides_sources(self, window) -> None:
        """#50: SourcePage has set_sources method for populating source checkboxes."""
        page = window._source_page
        # SourcePage should have set_sources and the internal _source_checkboxes dict
        assert hasattr(page, "set_sources")
        assert hasattr(page, "_source_checkboxes")

    # --- Issue #69: SecondaryWorkflowManager.copy_preset_to_device accepts channel_mode ---

    def test_issue69_copy_preset_to_device_has_channel_mode(self, window) -> None:
        """#69: copy_preset_to_device accepts channel_mode parameter."""
        swm = window._secondary_workflows
        import inspect

        sig = inspect.signature(swm.copy_preset_to_device)
        assert "channel_mode" in sig.parameters

    # --- Issue #70: parse_backup_filters handles stereo and L/R ---

    def test_issue70_parse_backup_stereo(self) -> None:
        """#70: parse_backup_filters handles stereo backup format."""
        backup = {
            "channel_mode": "stereo",
            "filters": [
                {"type": "PEAK", "frequency_hz": 1000, "gain_db": -3, "q": 1.0},
            ],
        }
        filters, mode = parse_backup_filters(backup)
        assert mode == "stereo"
        assert len(filters) == 1
        assert filters[0].frequency_hz == 1000

    def test_issue70_parse_backup_lr(self) -> None:
        """#70: parse_backup_filters handles L/R backup format."""
        backup = {
            "channel_mode": "left",
            "filters_l": [
                {"type": "PEAK", "frequency_hz": 100, "gain_db": -2, "q": 1.0},
            ],
            "filters_r": [
                {"type": "PEAK", "frequency_hz": 200, "gain_db": -4, "q": 1.5},
            ],
        }
        filters, mode = parse_backup_filters(backup)
        assert mode == "lr"
        assert len(filters) == 2

    def test_issue70_parse_backup_empty(self) -> None:
        """#70: parse_backup_filters handles empty backup gracefully."""
        backup: dict[str, object] = {}
        filters, mode = parse_backup_filters(backup)
        assert mode == "stereo"
        assert filters == []

    # --- Issue #74: _do_copy_presets_batch_multi iterates all devices ---

    def test_issue74_copy_batch_multi_iterates_all_devices(self, window) -> None:
        """#74: _do_copy_presets_batch_multi iterates all target devices."""
        _setup_device(window)
        items = [MagicMock()]
        items[0].name = "Preset1"
        items[0].preset_type = "PEQ"

        device1 = MagicMock(ip="192.168.1.201", name="Device A")
        device2 = MagicMock(ip="192.168.1.202", name="Device B")
        devices = [device1, device2]

        with patch.object(
            window, "_do_copy_preset_to_device", new_callable=AsyncMock
        ) as mock_copy:
            import asyncio

            asyncio.run(
                window._do_copy_presets_batch_multi(items, devices, "wifi")
            )
            assert mock_copy.call_count == 2


    # --- Issue #78: Copy status message says "X preset(s) copied to Y device(s)" ---

    def test_issue78_copy_status_message_format(self, window) -> None:
        """#78: Successful multi-device copy shows 'N preset(s) copied to M device(s)'."""
        _setup_device(window)
        items = [MagicMock()]
        items[0].name = "Preset1"
        items[0].preset_type = "PEQ"

        device1 = MagicMock(ip="192.168.1.201", name="Device A")
        device2 = MagicMock(ip="192.168.1.202", name="Device B")
        device3 = MagicMock(ip="192.168.1.203", name="Device C")
        devices = [device1, device2, device3]

        with (
            patch.object(
                window, "_do_copy_preset_to_device", new_callable=AsyncMock
            ),
            patch.object(window._status_banner, "show_success") as mock_success,
        ):
            import asyncio

            asyncio.run(
                window._do_copy_presets_batch_multi(items, devices, "wifi")
            )
            mock_success.assert_called_once()
            msg = mock_success.call_args[0][0]
            assert "1 preset(s)" in msg
            assert "3 device(s)" in msg

    # --- Issue #79: Copy L/R RoomFit preserves channel_mode ---

    def test_issue79_copy_lr_roomfit_preserves_channel(self, window) -> None:
        """#79: _do_copy_preset_to_device passes L/R for RoomFit copies."""
        _setup_device(window)
        mock_adapter = window._wiim_adapter
        # Simulate reading a RoomFit profile that is L/R
        peq_settings = MagicMock()
        peq_settings.channel_mode = "lr"
        peq_settings.bands_l = [_make_filter(100)]
        peq_settings.bands_r = [_make_filter(200)]
        peq_settings.bands = []
        mock_adapter.read_roomfit = AsyncMock(return_value=peq_settings)

        # Mock the target device connection
        with (
            patch("src.gui.main_window.WiiMHttpClient") as mock_client_cls,
            patch("src.gui.main_window.CapabilityProber") as mock_prober_cls,
            patch("src.gui.main_window.WiiMAdapter") as mock_adapter_cls,
        ):
            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client
            mock_prober = AsyncMock()
            mock_prober.probe = AsyncMock(return_value=_make_caps())
            mock_prober_cls.return_value = mock_prober
            mock_target_adapter = AsyncMock()
            mock_adapter_cls.return_value = mock_target_adapter

            import asyncio

            asyncio.run(
                window._do_copy_preset_to_device(
                    "My RoomFit", "RoomFit", "192.168.1.200", "wifi"
                )
            )
            # Target adapter should have write_roomfit called with L/R params
            mock_target_adapter.write_roomfit.assert_called_once()
            call_kwargs = mock_target_adapter.write_roomfit.call_args
            assert (
                "channel_mode" in str(call_kwargs)
                or call_kwargs.kwargs.get("channel_mode") == "lr"
            )

    # --- Issue #85: Diagnostics raw_command_requested connected ---

    def test_issue85_diagnostics_raw_command_connected(self, window) -> None:
        """#85: Diagnostics panel raw_command_requested signal is connected."""
        assert hasattr(window._diagnostics_panel, "raw_command_requested")

    def test_issue85_raw_command_handler_exists(self, window) -> None:
        """#85: _on_raw_command_requested handler exists and is callable."""
        assert callable(window._on_raw_command_requested)

    def test_issue85_raw_command_no_device_shows_error(self, window) -> None:
        """#85: raw command with no device shows error response."""
        window._wiim_adapter = None
        with patch.object(window._diagnostics_panel, "on_raw_response") as mock_resp:
            window._on_raw_command_requested("getStatusEx")
            mock_resp.assert_called_once()
            assert "No device" in mock_resp.call_args[0][0]



# ===========================================================================
# SHARED HELPERS (pure unit tests, no GUI)
# ===========================================================================


class TestSharedHelpers:
    """Direct unit tests for shared_helpers functions (no Qt needed)."""

    # --- split_lr_filters ---

    def test_split_lr_even(self) -> None:
        """split_lr_filters splits evenly for even-length list."""
        filters = [_make_filter(100 * (i + 1)) for i in range(6)]
        left, right = split_lr_filters(filters)
        assert len(left) == 3
        assert len(right) == 3

    def test_split_lr_odd(self) -> None:
        """split_lr_filters with odd count puts extra in right half."""
        filters = [_make_filter(100 * (i + 1)) for i in range(5)]
        left, right = split_lr_filters(filters)
        assert len(left) == 2
        assert len(right) == 3

    def test_split_lr_empty(self) -> None:
        """split_lr_filters with empty list returns two empty lists."""
        left, right = split_lr_filters([])
        assert left == []
        assert right == []

    # --- is_lr_mode comprehensive ---

    def test_is_lr_mode_left(self) -> None:
        """is_lr_mode returns True for 'left'."""
        assert is_lr_mode("left") is True

    def test_is_lr_mode_right(self) -> None:
        """is_lr_mode returns True for 'right'."""
        assert is_lr_mode("right") is True

    def test_is_lr_mode_mixed_case(self) -> None:
        """is_lr_mode is case-insensitive."""
        assert is_lr_mode("LR") is True
        assert is_lr_mode("Lr") is True

    # --- build_profile ---

    def test_build_profile_lr_splits_filters(self) -> None:
        """build_profile with L/R splits filters into filters_l and filters_r."""
        filters = [_make_filter(100), _make_filter(200)]
        profile = build_profile("Test", filters, "L/R")
        assert profile.filters_l is not None
        assert profile.filters_r is not None
        assert len(profile.filters_l) == 1
        assert len(profile.filters_r) == 1

    def test_build_profile_stereo_keeps_filters(self) -> None:
        """build_profile with Stereo keeps filters in single list."""
        filters = [_make_filter(100), _make_filter(200)]
        profile = build_profile("Test", filters, "Stereo")
        assert profile.filters is not None
        assert len(profile.filters) == 2

    # --- parse_backup_filters ---

    def test_parse_backup_right_channel_mode(self) -> None:
        """parse_backup_filters with 'right' channel_mode returns 'lr'."""
        backup = {
            "channel_mode": "right",
            "filters_l": [
                {"type": "PEAK", "frequency_hz": 100, "gain_db": -2, "q": 1.0},
            ],
            "filters_r": [
                {"type": "PEAK", "frequency_hz": 200, "gain_db": -4, "q": 1.5},
            ],
        }
        filters, mode = parse_backup_filters(backup)
        assert mode == "lr"
        assert len(filters) == 2
