"""Smoke test regression tests for push/write, import/export, presets, and settings.

Covers smoke test issues: #7, #8, #10, #11, #12, #13, #20, #22, #23, #24, #25,
#27, #28, #29, #30, #31, #32, #33, #34, #37, #38, #39, #42, #44, #48, #49, #50,
#53, #54, #55, #58, #60, #61, #62, #63, #65, #69, #70, #74, #77, #78, #79, #80,
#85, #2/#9, #156, #158, #176, #183, #189.
Each test validates the specific fix behavior to prevent regressions.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.adapters.rew_http_client import MeasurementSummary
from src.adapters.safe_write import RoomFitSafeWrite, WriteResult
from src.gui.app_settings import AppSettings
from src.gui.main_window import MainWindow
from src.gui.shared_helpers import (
    build_profile,
    is_lr_mode,
    parse_backup_filters,
    read_preset_preview,
)
from src.gui.views.presets_device_view import PresetItem
from src.gui.wizard_controller import FlowType, WizardStep
from src.models.canonical import CanonicalFilter
from src.models.channel_mode import ChannelMode
from src.models.peq import PEQSettings
from src.tests.conftest import close_coroutine_tree

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
    mock_bridge.run_async = MagicMock(side_effect=close_coroutine_tree)

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
    caps.supports_roomfit = roomfit_level >= 1
    caps.supports_roomfit_read = roomfit_level >= 2
    caps.supports_roomfit_write = roomfit_level >= 4
    caps.device_name = model
    caps.model = model
    caps.source_names = source_names or ["wifi", "optical", "hdmi"]
    caps.active_source = "wifi"
    caps.supports_profile_enumeration = True
    caps.capability_file_override = False
    caps.used_generic_capabilities = False
    return caps


def _setup_device(window) -> MagicMock:
    """Set up a mocked device adapter on the window."""
    mock_adapter = MagicMock()
    mock_adapter.capabilities = _make_caps()
    window._wiim_adapter = mock_adapter
    window._primary_workflows.set_current_adapter(mock_adapter)
    window._roomfit_safe_write = RoomFitSafeWrite(mock_adapter, window._backup_manager)
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
        """#7: _on_peq_ready populates ReviewPage with the real filter rows
        (not just "called once" -- must be the actual imported filters, not
        an empty list or an unrelated placeholder)."""
        _setup_device(window)
        state = window._wizard_controller.state
        filters = [_make_filter(100), _make_filter(200)]
        state.current_filters = filters
        state.channel_mode = ChannelMode.STEREO

        peq_data = MagicMock()
        peq_data.channel_mode = "stereo"
        peq_data.bands_l = None
        peq_data.bands_r = None

        with patch.object(window._review_page, "set_filters") as mock_set:
            window._on_peq_ready(peq_data)
            mock_set.assert_called_once()
            passed_filters = mock_set.call_args[0][0]
            assert [f.frequency_hz for f in passed_filters] == [100, 200]

    def test_issue7_on_peq_ready_advances_to_review(self, window) -> None:
        """#7: _on_peq_ready actually advances the wizard controller's real
        state to REVIEW (not a mocked advance() -- verifies the real step
        transition happens, not merely that *some* method got called)."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = ChannelMode.STEREO
        # Set wizard to FILTERS step so it can advance
        window._wizard_controller.state.current_step = WizardStep.FILTERS

        peq_data = MagicMock(channel_mode="stereo", bands_l=None, bands_r=None)
        window._on_peq_ready(peq_data)

        assert window._wizard_controller.state.current_step == WizardStep.REVIEW

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

    # --- Issue #58: Multi-device push respects channel_mode (live equivalent) ---

    def test_issue58_copy_presets_batch_multi_peq_lr_uses_lr_channel_mode(
        self, window
    ) -> None:
        """#58: Multi-device PEQ push/copy must build L/R PEQSettings (not
        always stereo) when the source preset is L/R.

        NOTE: the function the doc originally cited, apply_to_devices(), no
        longer exists anywhere in the codebase (confirmed via repo-wide
        grep) -- it was superseded by
        MainWindow._do_copy_presets_batch_multi() ->
        _do_copy_preset_to_device(), which is the current live multi-device
        write path (see docstrings in src/gui/secondary_workflows.py noting
        "Apply to multiple devices" was removed as dead code in the
        2026-06-28 quality audit). This test exercises that current path
        with 2 devices and an L/R PEQ preset, asserting the PEQSettings
        built for the SafeWrite call has channel_mode=ChannelMode.LR with
        the correct per-channel bands -- not a stereo fallback.
        """
        _setup_device(window)
        source_adapter = window._wiim_adapter
        filters_l = [_make_filter(100)]
        filters_r = [_make_filter(200)]
        source_adapter.load_peq_profile = AsyncMock()
        source_adapter.read_peq = AsyncMock(
            return_value=MagicMock(
                channel_mode="lr", bands_l=filters_l, bands_r=filters_r, bands=[]
            )
        )
        # _do_copy_preset_to_device now reads via read_peq_preset_preview (#166)
        source_adapter.read_peq_preset_preview = AsyncMock(
            return_value=MagicMock(
                channel_mode="lr", bands_l=filters_l, bands_r=filters_r, bands=[]
            )
        )

        items = [MagicMock()]
        items[0].name = "LR Preset"
        items[0].preset_type = "PEQ"
        device1 = MagicMock(ip="192.168.1.201", name="Device A")
        device2 = MagicMock(ip="192.168.1.202", name="Device B")

        with (
            patch("src.gui.main_window.WiiMHttpClient"),
            patch("src.gui.main_window.CapabilityProber") as mock_prober_cls,
            patch("src.gui.main_window.WiiMAdapter") as mock_adapter_cls,
            patch("src.gui.main_window.SafeWrite") as mock_safe_write_cls,
        ):
            mock_prober = MagicMock()
            mock_prober.probe = AsyncMock(return_value=_make_caps())
            mock_prober_cls.return_value = mock_prober

            target_adapter = MagicMock()
            target_adapter.save_peq_profile = AsyncMock()
            mock_adapter_cls.return_value = target_adapter

            mock_target_client = MagicMock()
            mock_target_client.close = AsyncMock()

            safe_write = MagicMock()
            safe_write.execute = AsyncMock(return_value=WriteResult(success=True))
            mock_safe_write_cls.return_value = safe_write

            import asyncio

            with patch("src.gui.main_window.WiiMHttpClient", return_value=mock_target_client):
                asyncio.run(
                    window._do_copy_presets_batch_multi(items, [device1, device2], "wifi")
                )

            assert safe_write.execute.call_count == 2
            for call in safe_write.execute.call_args_list:
                settings = call.args[1]
                assert settings.channel_mode == ChannelMode.LR
                assert settings.bands_l == filters_l
                assert settings.bands_r == filters_r

    # --- Issue #61: RoomFit push deferred via _on_name_confirmed ---

    def test_issue61_roomfit_push_deferred_not_immediate(self, window) -> None:
        """#61: _on_push_requested for RoomFit advances to NAME_PROFILE, not push."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = ChannelMode.STEREO
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
        state.channel_mode = ChannelMode.STEREO
        state.dry_run = False

        with patch.object(window._wizard_controller, "advance"):
            window._on_name_confirmed("My RoomFit Profile")

        assert state.roomfit_profile_name == "My RoomFit Profile"
        window._bridge.run_async.assert_called_once()

    # --- Issue #165: overwrite-active-profile confirmation ---

    def test_191_name_confirmed_dialog_shown_even_when_roomfit_disabled(self, window) -> None:
        """#191 redesign: a push now always activates the profile and turns
        RoomFit on, regardless of its current state -- so the overwrite-
        active-profile confirm dialog must fire even when RoomFit is
        currently off (previously skipped in this case, since overwriting
        an inactive selection had no live-audio consequence under the old
        restore-previous-state design)."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = ChannelMode.STEREO
        state.dry_run = False
        window._roomfit_enabled = False
        window._name_profile_page.set_existing_profiles(["Living Room"], "Living Room")

        with (
            patch.object(window._wizard_controller, "advance") as mock_adv,
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
                return_value=True,
            ) as mock_question,
        ):
            window._on_name_confirmed("Living Room")

        mock_question.assert_called_once()
        assert state.roomfit_profile_name == "Living Room"
        mock_adv.assert_called_once()
        window._bridge.run_async.assert_called_once()

    def test_165_name_confirmed_no_dialog_when_name_not_active(self, window) -> None:
        """No confirm dialog when RoomFit is on but the chosen name isn't the
        currently-active profile."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = ChannelMode.STEREO
        state.dry_run = False
        window._roomfit_enabled = True
        window._name_profile_page.set_existing_profiles(["Living Room"], "Living Room")

        with (
            patch.object(window._wizard_controller, "advance"),
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm"
            ) as mock_question,
        ):
            window._on_name_confirmed("New Profile")

        mock_question.assert_not_called()
        window._bridge.run_async.assert_called_once()

    def test_165_name_confirmed_dialog_shown_when_overwriting_active(self, window) -> None:
        """Confirm dialog appears when RoomFit is on and the name matches the
        active profile; declining aborts the push."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = ChannelMode.STEREO
        state.dry_run = False
        window._roomfit_enabled = True
        window._name_profile_page.set_existing_profiles(["Living Room"], "Living Room")

        with (
            patch.object(window._wizard_controller, "advance") as mock_adv,
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
                return_value=False,
            ) as mock_question,
        ):
            window._on_name_confirmed("Living Room")

        mock_question.assert_called_once()
        mock_adv.assert_not_called()
        window._bridge.run_async.assert_not_called()

    def test_165_name_confirmed_proceeds_on_yes(self, window) -> None:
        """Accepting the overwrite-active-profile confirmation proceeds with push."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = ChannelMode.STEREO
        state.dry_run = False
        window._roomfit_enabled = True
        window._name_profile_page.set_existing_profiles(["Living Room"], "Living Room")

        with (
            patch.object(window._wizard_controller, "advance"),
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
                return_value=True,
            ),
        ):
            window._on_name_confirmed("Living Room")

        assert state.roomfit_profile_name == "Living Room"
        window._bridge.run_async.assert_called_once()

    # --- Issue #183: overwrite-existing-non-active-profile confirmation ---

    def test_183_name_confirmed_dialog_shown_when_overwriting_non_active(
        self, window
    ) -> None:
        """A distinct confirm dialog appears when the name matches a
        different, non-active existing profile (data-loss risk only, no
        RoomFit deactivation) -- previously this case had no warning at all."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = ChannelMode.STEREO
        state.dry_run = False
        window._roomfit_enabled = True
        window._name_profile_page.set_existing_profiles(
            ["Living Room", "Office"], "Living Room"
        )

        with (
            patch.object(window._wizard_controller, "advance") as mock_adv,
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
                return_value=False,
            ) as mock_question,
        ):
            window._on_name_confirmed("Office")

        mock_question.assert_called_once()
        assert "already exists" in mock_question.call_args.args[2]
        assert "deactivate" not in mock_question.call_args.args[2]
        mock_adv.assert_not_called()
        window._bridge.run_async.assert_not_called()

    def test_183_name_confirmed_proceeds_on_yes_for_non_active(self, window) -> None:
        """Accepting the overwrite-existing-profile confirmation proceeds."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = ChannelMode.STEREO
        state.dry_run = False
        window._roomfit_enabled = True
        window._name_profile_page.set_existing_profiles(
            ["Living Room", "Office"], "Living Room"
        )

        with (
            patch.object(window._wizard_controller, "advance"),
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
                return_value=True,
            ),
        ):
            window._on_name_confirmed("Office")

        assert state.roomfit_profile_name == "Office"
        window._bridge.run_async.assert_called_once()

    def test_183_name_confirmed_no_dialog_for_brand_new_name(self, window) -> None:
        """No confirm dialog when the name matches neither an existing nor
        the active profile."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = ChannelMode.STEREO
        state.dry_run = False
        window._roomfit_enabled = True
        window._name_profile_page.set_existing_profiles(
            ["Living Room", "Office"], "Living Room"
        )

        with (
            patch.object(window._wizard_controller, "advance"),
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm"
            ) as mock_question,
        ):
            window._on_name_confirmed("Brand New Room")

        mock_question.assert_not_called()
        window._bridge.run_async.assert_called_once()

    def test_165_populate_name_profiles_sets_active_and_enabled(self, window) -> None:
        """_do_populate_name_profiles fetches roomfit status and applies it.

        Drives the real name_profiles_ready signal end-to-end (it's a
        PrimaryWorkflowManager-owned QObject signal, always real regardless
        of the mocked AsyncBridge, and is connected to
        MainWindow._on_name_profiles_ready for real via
        _setup_primary_workflows() during __init__) rather than asserting
        on the coroutine's return value.
        """
        import asyncio

        mock_adapter = _setup_device(window)
        mock_adapter.capabilities.roomfit_level = 3
        mock_adapter.list_roomfit_profiles = AsyncMock(
            return_value=[{"Name": "Living Room"}, {"Name": "Office"}]
        )
        mock_adapter.get_roomfit_status = AsyncMock(return_value=(True, "Living Room"))

        asyncio.run(window._primary_workflows._do_populate_name_profiles())

        assert window._roomfit_enabled is True
        assert window._name_profile_page.active_profile == "Living Room"

    def test_165_populate_name_profiles_degrades_gracefully_on_status_failure(
        self, window
    ) -> None:
        """A failed get_roomfit_status() call degrades to disabled/no-active-name
        rather than failing the whole profile list population."""
        import asyncio

        mock_adapter = _setup_device(window)
        mock_adapter.capabilities.roomfit_level = 3
        mock_adapter.list_roomfit_profiles = AsyncMock(
            return_value=[{"Name": "Living Room"}]
        )
        mock_adapter.get_roomfit_status = AsyncMock(side_effect=RuntimeError("boom"))

        asyncio.run(window._primary_workflows._do_populate_name_profiles())

        assert window._roomfit_enabled is False
        assert window._name_profile_page.active_profile == ""
        # The profile list itself is still populated despite the status failure.
        assert window._name_profile_page._profiles_list.count() == 1

    # --- Issue #63: write_roomfit accepts channel_mode parameter ---

    def test_issue63_do_push_roomfit_lr_passes_channel_mode(self, window) -> None:
        """#63: RoomFit push with L/R sends channel_mode=ChannelMode.LR to
        write_roomfit. The real value on the wire is the ChannelMode enum,
        not the string "lr" -- a previous version of this assertion checked
        `== "lr" or "lr" in str(call_kwargs)`, where the primary comparison
        was always False and the test only passed via the loose string
        fallback (which would also spuriously match unrelated kwargs
        containing "lr" as a substring, e.g. a source name).
        """
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter(100), _make_filter(200)]
        state.channel_mode = ChannelMode.LR
        state.dry_run = False
        state.roomfit_profile_name = "TestProfile"
        state.flow_type = FlowType.ROOMFIT

        mock_adapter = window._wiim_adapter
        mock_adapter.list_roomfit_profiles = AsyncMock(return_value=[])
        mock_adapter.write_roomfit = AsyncMock()
        mock_adapter.read_roomfit = AsyncMock(
            return_value=MagicMock(channel_mode=ChannelMode.LR, bands=[], bands_l=[], bands_r=[])
        )
        # RoomFitSafeWrite.execute() also calls get_roomfit_status() and, on
        # success (#191), load_roomfit_profile()/enable_roomfit() to
        # activate the pushed profile -- _setup_device()'s bare MagicMock()
        # would otherwise raise TypeError on await, silently swallowed by
        # execute()'s own best-effort error handling rather than exercised.
        mock_adapter.get_roomfit_status = AsyncMock(return_value=(True, ""))
        mock_adapter.restore_roomfit_active_profile = AsyncMock()
        mock_adapter.load_roomfit_profile = AsyncMock()
        mock_adapter.enable_roomfit = AsyncMock()
        # RoomFitSafeWrite.execute() now always creates a backup, even for
        # a new profile (#191, metadata-only carrier for Undo) -- the real
        # BackupManager would otherwise try to build a filesystem path from
        # _make_caps()'s MagicMock `.uuid`, which isn't a real string.
        mock_backup = MagicMock()
        mock_backup.create_backup = MagicMock(return_value="/tmp/backup.json")
        window._backup_manager = mock_backup
        window._roomfit_safe_write = RoomFitSafeWrite(mock_adapter, mock_backup)

        # _do_push is a coroutine; we verify write_roomfit gets channel_mode
        import asyncio

        asyncio.run(window._do_push())
        mock_adapter.write_roomfit.assert_called_once()
        call_kwargs = mock_adapter.write_roomfit.call_args
        assert call_kwargs.kwargs.get("channel_mode") == ChannelMode.LR

    # --- Issue #77: Multi-source push stores per-source backup paths ---

    def test_issue77_multi_source_backup_format(self, window) -> None:
        """#77: Multi-source push creates combined backup paths format."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = ChannelMode.STEREO
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

    # --- Issue #189: Push stepper reflects real per-stage progress ---

    def test_issue189_do_push_peq_passes_on_stage_to_safe_write(self, window) -> None:
        """#189: _do_push() wires SafeWrite.execute()'s on_stage callback to
        the bridge's stage_changed signal, so the Push page's stepper can
        show live progress (and pinpoint the failing stage) instead of only
        an all-pending/all-complete state.
        """
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = ChannelMode.STEREO
        state.dry_run = False

        mock_safe_write = AsyncMock()
        mock_safe_write.execute = AsyncMock(
            return_value=MagicMock(success=True, backup_path="/tmp/backup.json")
        )
        window._safe_write = mock_safe_write

        import asyncio

        asyncio.run(window._do_push())

        mock_safe_write.execute.assert_called_once()
        call_kwargs = mock_safe_write.execute.call_args.kwargs
        assert call_kwargs["on_stage"] == window._bridge.stage_changed.emit

    def test_issue189_do_push_roomfit_passes_on_stage(self, window) -> None:
        """#189: the RoomFit push flow also wires the on_stage callback."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = ChannelMode.STEREO
        state.dry_run = False
        state.roomfit_profile_name = "TestProfile"
        state.flow_type = FlowType.ROOMFIT

        mock_roomfit_safe_write = AsyncMock()
        mock_roomfit_safe_write.execute = AsyncMock(
            return_value=MagicMock(success=True, backup_path=None)
        )
        window._roomfit_safe_write = mock_roomfit_safe_write

        import asyncio

        asyncio.run(window._do_push())

        mock_roomfit_safe_write.execute.assert_called_once()
        call_kwargs = mock_roomfit_safe_write.execute.call_args.kwargs
        assert call_kwargs["on_stage"] == window._bridge.stage_changed.emit

    def test_issue189_stage_changed_advances_push_page_stepper(self, window) -> None:
        """#189: the stage_changed handler advances PushPage's stepper, marking
        earlier stages complete and the reported stage active.
        """
        window._on_stage_changed("writing")

        assert window.push_page._stage_rows["backing_up"].status == "complete"
        assert window.push_page._stage_rows["writing"].status == "active"
        assert window.push_page._stage_rows["verifying"].status == "pending"

    # --- Issue #80: Dry run shows preview without calling _do_push ---

    def test_issue80_dry_run_shows_preview(self, window) -> None:
        """#80: dry_run=True shows preview without calling _do_push."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = ChannelMode.STEREO
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
        state.channel_mode = ChannelMode.LR

        peq_data = MagicMock()
        peq_data.channel_mode = "lr"
        peq_data.bands_l = filters_l
        peq_data.bands_r = filters_r

        with patch.object(window._review_page, "set_lr_filters") as mock_lr:
            window._on_peq_ready(peq_data)
            # validate_filters_for_device returns (filters, warnings, clamping_map, rows)
            # For in-range filters, clamping_map is empty dict {} and rows == filters
            mock_lr.assert_called_once_with(
                list(filters_l),
                list(filters_r),
                {},
                {},
                list(filters_l),
                list(filters_r),
                {},
                {},
            )

    def test_lr_truncation_warnings_are_labeled_by_channel(self, window) -> None:
        """L/R warnings merged for the Review status banner must say which
        channel each one belongs to, not present an unlabeled combined list.
        """
        _setup_device(window)
        # supported_filter_types must be an explicit empty list -- a bare
        # MagicMock() auto-attribute is truthy (enters the type-restriction
        # branch in validate_filters_for_device()) but iterates as empty,
        # which would mark every band "unsupported" and mask this test's
        # actual truncation-warning assertion entirely.
        window._device_caps = MagicMock(max_filters=2, supported_filter_types=[])
        state = window._wizard_controller.state
        filters_l = [_make_filter(100), _make_filter(200), _make_filter(300)]
        filters_r = [_make_filter(400), _make_filter(500), _make_filter(600)]
        state.current_filters = filters_l + filters_r
        state.channel_mode = ChannelMode.LR

        peq_data = MagicMock()
        peq_data.channel_mode = "lr"
        peq_data.bands_l = filters_l
        peq_data.bands_r = filters_r

        with (
            patch("src.gui.main_window.QTimer.singleShot", side_effect=lambda _ms, fn: fn()),
            patch.object(window._status_banner, "show_info") as mock_info,
        ):
            window._on_peq_ready(peq_data)

        mock_info.assert_called_once()
        warning_text = mock_info.call_args[0][0]
        assert warning_text.count("Left: Imported 3 filters") == 1
        assert warning_text.count("Right: Imported 3 filters") == 1

    # --- Issue #29: Export branches on channel_mode for L/R ---

    def test_issue29_export_lr_mode_uses_export_dialog(self, window, tmp_path) -> None:
        """#29: L/R export opens ExportDialog and, given two real paths (not
        a cancel), actually writes two files with correct per-channel
        content -- not a single 10-band file (the original smoke bug).
        """
        _setup_device(window)
        state = window._wizard_controller.state
        filters_l = [_make_filter(100, gain=-2.0)]
        filters_r = [_make_filter(200, gain=-4.0)]
        state.current_filters = filters_l + filters_r
        state.filters_l = filters_l
        state.filters_r = filters_r
        state.channel_mode = ChannelMode.LR

        path_l = tmp_path / "export_L.txt"
        path_r = tmp_path / "export_R.txt"

        with (
            patch(
                "src.gui.dialogs.export_dialog.ExportDialog.get_paths",
                return_value=(path_l, path_r),
            ) as mock_dialog,
            patch.object(
                window._bridge, "run_async", side_effect=close_coroutine_tree
            ) as mock_run,
        ):
            window._export_filters_as_rew(state.current_filters, "L/R")
            mock_dialog.assert_called_once()
            mock_run.assert_called_once()

        # Run the captured export coroutine for real to verify file content,
        # since run_async was mocked above (close_coroutine_tree only closes it).
        import asyncio

        asyncio.run(window._primary_workflows._do_export_lr(filters_l, filters_r, path_l, path_r))
        assert path_l.exists()
        assert path_r.exists()
        left_content = path_l.read_text()
        right_content = path_r.read_text()
        assert "Fc   100.00 Hz" in left_content
        assert "Gain  -2.00 dB" in left_content
        assert "Fc   200.00 Hz" in right_content
        assert "Gain  -4.00 dB" in right_content
        # Each file must contain only its own channel's band, not both.
        assert "200.00 Hz" not in left_content
        assert "100.00 Hz" not in right_content

    # --- Issue #176: L/R export ignored the configured default REW folder ---

    def test_issue176_lr_export_uses_settings_default_folder(
        self, window, tmp_path
    ) -> None:
        """#176: L/R export (ReviewPage) must pass the Settings "Default REW
        import/export folder" through to ExportDialog as `default_dir`, not
        silently fall back to the home directory -- unlike stereo export,
        which already respected the setting.
        """
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter(100, gain=-2.0)]
        state.filters_l = [_make_filter(100, gain=-2.0)]
        state.filters_r = [_make_filter(200, gain=-4.0)]
        state.channel_mode = ChannelMode.LR
        window._settings.rew_folder = str(tmp_path)

        with (
            patch(
                "src.gui.dialogs.export_dialog.ExportDialog.get_paths",
                return_value=None,
            ) as mock_dialog,
            patch.object(window._bridge, "run_async"),
        ):
            window._export_filters_as_rew(state.current_filters, "L/R")

        mock_dialog.assert_called_once()
        assert mock_dialog.call_args.kwargs["default_dir"] == str(tmp_path)

    def test_issue176_preset_lr_export_uses_settings_default_folder(
        self, window, tmp_path
    ) -> None:
        """#176: L/R export from "Presets on Device" must also thread the
        configured default REW folder through to ExportDialog.
        """
        item = PresetItem(name="Movie Night", channel_mode="L/R", preset_type="PEQ")
        window._settings.rew_folder = str(tmp_path)

        with (
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
                return_value=True,
            ),
            patch(
                "src.gui.dialogs.export_dialog.ExportDialog.get_paths",
                return_value=None,
            ) as mock_dialog,
        ):
            window._presets_device_view.export_requested.emit([item])

        mock_dialog.assert_called_once()
        assert mock_dialog.call_args.kwargs["default_dir"] == str(tmp_path)

    # --- Issue #30: Stereo export appends .txt extension ---

    def test_issue30_stereo_export_appends_txt(self, window) -> None:
        """#30: Stereo export appends .txt if not present in chosen path.

        Patches the underlying _do_export() coroutine function directly so
        the actual `path` argument it receives can be asserted, instead of
        only checking that run_async was called once (which would pass even
        if the ".txt" append were removed).
        """
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = ChannelMode.STEREO

        async def _fake_do_export(filters: object, path: str) -> None:
            del filters

        with (
            patch(
                "src.gui.main_window.QFileDialog.getSaveFileName",
                return_value=("/tmp/myfile", ""),
            ),
            patch.object(
                window._primary_workflows, "_do_export", side_effect=_fake_do_export
            ) as mock_do_export,
            patch.object(
                window._bridge, "run_async", side_effect=close_coroutine_tree
            ) as mock_run,
        ):
            window._export_filters_as_rew(state.current_filters, "Stereo")
            mock_run.assert_called_once()

        mock_do_export.assert_called_once()
        path_arg = mock_do_export.call_args[0][1]
        assert path_arg == "/tmp/myfile.txt"

    def test_stereo_export_seeds_device_prefixed_filename(self, window) -> None:
        """Stereo REW export seeds the save dialog with a device-name-prefixed
        default filename, unlike before when it had no default filename at all."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = ChannelMode.STEREO
        state.selected_source = "wifi"

        with (
            patch(
                "src.gui.main_window.QFileDialog.getSaveFileName",
                return_value=("", ""),
            ) as mock_dialog,
            patch.object(window._bridge, "run_async"),
        ):
            window._export_filters_as_rew(state.current_filters, "Stereo")

        mock_dialog.assert_called_once()
        seeded_path = mock_dialog.call_args[0][2]
        assert seeded_path.endswith("WiiM - wifi.txt")

    # --- Issue #40: L/R export from Presets on Device generates dual files ---

    def test_issue40_lr_export_generates_dual_files(self, window, tmp_path) -> None:
        """#40: Exporting an L/R preset from Presets-on-Device/Review must
        generate two files (_L.txt/_R.txt) with correct per-channel content
        -- unlike #29's test (ReviewPage export), this exercises the
        Presets-on-Device export path (_on_preset_export_requested ->
        _do_preset_export), giving the export dialog two real save paths
        instead of a cancel.
        """
        mock_adapter = _setup_device(window)
        filters_l = [_make_filter(100, gain=-1.0)]
        filters_r = [_make_filter(200, gain=-2.0)]
        mock_adapter.load_peq_profile = AsyncMock()
        mock_adapter.read_peq = AsyncMock(
            return_value=MagicMock(
                channel_mode="lr", bands_l=filters_l, bands_r=filters_r, bands=[]
            )
        )
        # _do_preset_export now reads via read_peq_preset_preview (#166)
        mock_adapter.read_peq_preset_preview = AsyncMock(
            return_value=MagicMock(
                channel_mode="lr", bands_l=filters_l, bands_r=filters_r, bands=[]
            )
        )

        item = PresetItem(name="Movie Night", channel_mode="L/R", preset_type="PEQ")
        path_l = tmp_path / "Movie Night_L.txt"
        path_r = tmp_path / "Movie Night_R.txt"

        def _run_now(coro: object) -> None:
            import asyncio

            asyncio.run(coro)

        with (
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
                return_value=True,
            ),
            patch(
                "src.gui.dialogs.export_dialog.ExportDialog.get_paths",
                return_value=(path_l, path_r),
            ),
            patch.object(window._bridge, "run_async", side_effect=_run_now),
        ):
            window._presets_device_view.export_requested.emit([item])

        exported_l = (tmp_path / "Movie Night_L.txt")
        exported_r = (tmp_path / "Movie Night_R.txt")
        assert exported_l.exists()
        assert exported_r.exists()
        left_content = exported_l.read_text()
        right_content = exported_r.read_text()
        assert "Fc   100.00 Hz" in left_content
        assert "Fc   200.00 Hz" in right_content
        assert "200.00 Hz" not in left_content
        assert "100.00 Hz" not in right_content

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

    # --- Issue #51: REW file import supports L/R (two files) ---

    def test_issue51_lr_import_dual_file_picker(self, window, qtbot) -> None:
        """#51: Choosing L/R mode on FiltersPage's Stereo/L/R toggle reveals
        the dual (left/right) file browse controls, and browsing both files
        then confirming emits file_import_lr_requested with two distinct
        paths -- not the single-file stereo path.

        The "Stereo/L/R choice" is FiltersPage's inline radio toggle (not a
        separate modal dialog), and the "dual file picker" is two
        independent browse buttons (left channel, right channel), each
        driving its own QFileDialog.getOpenFileName call.
        """
        page = window._filters_page
        window._stacked_widget.setCurrentWidget(page)
        window.show()
        qtbot.wait(10)

        # Select L/R mode -- reveals the dual-file section.
        page._lr_radio.setChecked(True)
        assert page._lr_section.isVisible() is True
        assert page._stereo_section.isVisible() is False

        left_path = "C:/rew/left_channel.txt"
        right_path = "C:/rew/right_channel.txt"

        with patch(
            "src.gui.pages.filters_page.QFileDialog.getOpenFileName",
            side_effect=[(left_path, ""), (right_path, "")],
        ):
            page._on_left_browse()
            page._on_right_browse()

        assert page._left_path == left_path
        assert page._right_path == right_path
        assert page._left_path != page._right_path
        assert page._import_lr_btn.isEnabled() is True

        emitted: list[tuple[str, str]] = []
        page.file_import_lr_requested.connect(
            lambda pl, pr: emitted.append((pl, pr))
        )
        page._on_import_lr_confirmed()

        assert emitted == [(left_path, right_path)]

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

        assert state.channel_mode == ChannelMode.LR

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

        assert state.channel_mode == ChannelMode.STEREO


# ===========================================================================
# PRESETS
# ===========================================================================


class TestPresets:
    """Tests for preset issues: #20, #22, #23, #24, #25, #27, #31, #37, #53, #54, #60, #62,
    #156, #158."""


    # --- Issue #20: Navigation to presets_device triggers _load_device_presets ---

    def test_issue20_nav_presets_device_triggers_load(self, window) -> None:
        """#20: Navigating to presets_device actually populates the view.

        Does not mock _load_device_presets itself (that would only prove the
        method gets called, not that the view ends up with real data) --
        lets it run for real with a mocked adapter, matching the pattern
        used by test_issue22_do_list_presets_fetches_both.
        """
        import asyncio

        mock_adapter = _setup_device(window)
        mock_adapter.list_peq_profiles = AsyncMock(
            return_value=[{"Name": "Movie Night", "channelMode": "Stereo"}]
        )
        mock_adapter.list_roomfit_profiles = AsyncMock(
            return_value=[{"Name": "Living Room", "channelMode": "Stereo"}]
        )

        def _run_now(coro: object) -> None:
            asyncio.run(coro)

        with patch.object(window._bridge, "run_async", side_effect=_run_now):
            window._on_navigation_requested("presets_device")

        assert window._presets_device_view._peq_list.count() == 1
        assert window._presets_device_view._roomfit_list.count() == 1

    # --- Issue #22: _do_list_presets fetches both PEQ + RoomFit ---

    def test_issue22_do_list_presets_fetches_both(self, window) -> None:
        """#22: _do_list_presets fetches PEQ presets AND RoomFit profiles."""
        _setup_device(window)
        mock_adapter = window._wiim_adapter
        mock_adapter.list_peq_profiles = AsyncMock(return_value=[])
        mock_adapter.list_roomfit_profiles = AsyncMock(return_value=[])

        import asyncio

        asyncio.run(window._primary_workflows.refresh_presets())
        mock_adapter.list_peq_profiles.assert_called_once()
        mock_adapter.list_roomfit_profiles.assert_called_once()

    # --- Issue #165c: active preset/profile highlight in Presets on Device ---

    def test_165c_do_list_presets_passes_active_names(self, window) -> None:
        """_do_list_presets fetches the active PEQ name via read_peq and the
        active RoomFit name via get_roomfit_status, passing both through."""
        import asyncio

        from src.models.channel_mode import ChannelMode
        from src.models.peq import PEQSettings

        mock_adapter = _setup_device(window)
        mock_adapter.list_peq_profiles = AsyncMock(
            return_value=[{"Name": "Movie Night", "channelMode": "Stereo"}]
        )
        mock_adapter.read_peq = AsyncMock(
            return_value=PEQSettings(
                source_name="wifi", channel_mode=ChannelMode.STEREO, name="Movie Night"
            )
        )
        mock_adapter.list_roomfit_profiles = AsyncMock(
            return_value=[{"Name": "Living Room", "channelMode": "Stereo"}]
        )
        mock_adapter.get_roomfit_status = AsyncMock(return_value=(True, "Living Room"))

        with patch.object(
            window._presets_device_view, "set_peq_presets"
        ) as mock_set_peq, patch.object(
            window._presets_device_view, "set_roomfit_profiles"
        ) as mock_set_roomfit:
            asyncio.run(window._primary_workflows.refresh_presets())

        mock_set_peq.assert_called_once()
        assert mock_set_peq.call_args[0][1] == "Movie Night"
        mock_set_roomfit.assert_called_once()
        assert mock_set_roomfit.call_args[0][1] == "Living Room"

    def test_165c_do_list_presets_degrades_gracefully_on_active_name_failure(
        self, window
    ) -> None:
        """A failed active-name read doesn't fail the whole preset list --
        it just means no highlight for that section."""
        import asyncio

        mock_adapter = _setup_device(window)
        mock_adapter.list_peq_profiles = AsyncMock(
            return_value=[{"Name": "Movie Night", "channelMode": "Stereo"}]
        )
        mock_adapter.read_peq = AsyncMock(side_effect=RuntimeError("boom"))
        mock_adapter.list_roomfit_profiles = AsyncMock(
            return_value=[{"Name": "Living Room", "channelMode": "Stereo"}]
        )
        mock_adapter.get_roomfit_status = AsyncMock(side_effect=RuntimeError("boom"))

        with patch.object(
            window._presets_device_view, "set_peq_presets"
        ) as mock_set_peq, patch.object(
            window._presets_device_view, "set_roomfit_profiles"
        ) as mock_set_roomfit:
            asyncio.run(window._primary_workflows.refresh_presets())

        # Still populated with the real items, just no active-name highlight.
        assert len(mock_set_peq.call_args[0][0]) == 1
        assert mock_set_peq.call_args[0][1] == ""
        assert len(mock_set_roomfit.call_args[0][0]) == 1
        assert mock_set_roomfit.call_args[0][1] == ""

    # --- Issue #23: _on_eq_type_selected("roomfit") triggers async fetch ---

    def test_issue23_eq_type_roomfit_triggers_profile_fetch(self, window) -> None:
        """#23: Selecting 'roomfit' enables RoomFit mode and fetches profiles."""
        import asyncio

        mock_adapter = _setup_device(window)
        mock_adapter.capabilities.roomfit_level = 2
        mock_adapter.list_roomfit_profiles = AsyncMock(
            return_value=[{"Name": "Living Room"}, {"Name": "Office"}]
        )

        def _run_now(coro: object) -> None:
            asyncio.run(coro)

        with (
            patch.object(window._bridge, "run_async", side_effect=_run_now) as mock_run,
            patch.object(window._filters_page, "set_roomfit_profiles") as mock_set_profiles,
        ):
            window._on_eq_type_selected("roomfit")

        assert window._wizard_controller.flow_type == FlowType.ROOMFIT
        assert window._filters_page._roomfit_mode is True
        mock_run.assert_called_once()
        mock_set_profiles.assert_called_once_with(["Living Room", "Office"])

    # --- Issue #24: PresetsDeviceView signals connected in MainWindow ---

    def test_issue24_presets_device_export_connected(self, window) -> None:
        """#24: Export signal triggers preset export workflow."""
        item = PresetItem(name="Movie Night", channel_mode="Stereo", preset_type="PEQ")

        with (
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
                return_value=True,
            ),
            patch(
                "src.gui.main_window.QFileDialog.getSaveFileName",
                return_value=("/tmp/movie-night.txt", ""),
            ),
            patch.object(
                window._primary_workflows, "_do_preset_export", return_value=object()
            ) as mock_export_workflow,
            patch.object(window._status_banner, "show_progress") as mock_progress,
            patch.object(
                window._bridge, "run_async", side_effect=close_coroutine_tree
            ) as mock_run,
        ):
            window._presets_device_view.export_requested.emit([item])

        mock_progress.assert_called_once_with("Exporting 'Movie Night'...")
        mock_export_workflow.assert_called_once_with("Movie Night", "PEQ", "/tmp/movie-night.txt")
        mock_run.assert_called_once()

    def test_preset_export_seeds_device_prefixed_filename(self, window) -> None:
        """Presets-on-Device stereo export seeds the save dialog with a
        device-name-prefixed filename, while the on-device lookup key
        (preset_name) passed to _do_preset_export stays unprefixed."""
        item = PresetItem(name="Movie Night", channel_mode="Stereo", preset_type="PEQ")

        with (
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
                return_value=True,
            ),
            patch(
                "src.gui.main_window.QFileDialog.getSaveFileName",
                return_value=("", ""),
            ) as mock_dialog,
            patch.object(window._primary_workflows, "_do_preset_export", return_value=object()),
            patch.object(window._bridge, "run_async", side_effect=close_coroutine_tree),
        ):
            window._presets_device_view.export_requested.emit([item])

        mock_dialog.assert_called_once()
        seeded_path = mock_dialog.call_args[0][2]
        assert seeded_path.endswith("WiiM - Movie Night.txt")

    def test_issue24_presets_device_save_connected(self, window) -> None:
        """#24: Save signal triggers preset-save workflow."""
        item = PresetItem(name="Movie Night", channel_mode="Stereo", preset_type="PEQ")

        with (
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
                return_value=True,
            ),
            patch.object(
                window._primary_workflows, "_do_preset_save", return_value=object()
            ) as mock_save_workflow,
            patch.object(window._status_banner, "show_progress") as mock_progress,
            patch.object(
                window._bridge, "run_async", side_effect=close_coroutine_tree
            ) as mock_run,
        ):
            window._presets_device_view.save_to_my_presets.emit([item])

        mock_progress.assert_called_once_with("Saving 'Movie Night' to My Presets...")
        mock_save_workflow.assert_called_once_with("Movie Night", "PEQ", "WiiM - Movie Night")
        mock_run.assert_called_once()

    def test_do_preset_save_reads_device_with_unprefixed_name(self, window) -> None:
        """_do_preset_save must read the on-device preset using the raw
        preset_name (the actual on-device identifier), while the locally
        saved Profile gets the separately-passed, device-prefixed
        saved_name -- prefixing the device-side lookup key would break the
        read outright (the device has no preset literally named
        "WiiM - Movie Night")."""
        mock_adapter = _setup_device(window)
        mock_adapter.read_peq_preset_preview = AsyncMock(
            return_value=PEQSettings(
                source_name="wifi",
                channel_mode=ChannelMode.STEREO,
                bands=[_make_filter()],
            )
        )

        with patch.object(window._profile_repository, "save") as mock_save:
            import asyncio

            asyncio.run(
                window._primary_workflows._do_preset_save(
                    "Movie Night", "PEQ", "WiiM - Movie Night"
                )
            )

        mock_adapter.read_peq_preset_preview.assert_called_once()
        call_args = mock_adapter.read_peq_preset_preview.call_args[0]
        assert call_args[1] == "Movie Night"

        mock_save.assert_called_once()
        saved_profile = mock_save.call_args[0][0]
        assert saved_profile.name == "WiiM - Movie Night"

    def test_issue24_presets_device_load_connected(self, window) -> None:
        """#24: Load signal triggers preset-load workflow."""
        _setup_device(window)
        item = PresetItem(name="Movie Night", channel_mode="Stereo", preset_type="PEQ")

        with (
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
                return_value=True,
            ),
            patch.object(window, "_ensure_wizard_state_for_load", return_value=True),
            patch.object(
                window._primary_workflows, "_do_load_peq_preset", return_value=object()
            ) as mock_load_workflow,
            patch.object(window._status_banner, "show_progress") as mock_progress,
            patch.object(
                window._bridge, "run_async", side_effect=close_coroutine_tree
            ) as mock_run,
        ):
            window._presets_device_view.load_into_editor.emit(item)

        mock_progress.assert_called_once_with("Loading preset 'Movie Night'...")
        mock_load_workflow.assert_called_once_with("Movie Night")
        mock_run.assert_called_once()

    # --- Issue #25: Selecting in one preset list clears the other ---

    def test_issue25_preset_list_mutual_exclusion(self, window) -> None:
        """#25: Selecting one preset list clears the other list selection."""
        view = window._presets_device_view
        peq_item = PresetItem(name="Movie", channel_mode="Stereo", preset_type="PEQ")
        roomfit_item = PresetItem(name="RoomFit A", channel_mode="L/R", preset_type="RoomFit")

        view.set_peq_presets([peq_item])
        view.set_roomfit_profiles([roomfit_item])

        view._roomfit_list.setCurrentRow(0)
        assert len(view._roomfit_list.selectedItems()) == 1

        view._peq_list.setCurrentRow(0)
        assert len(view._peq_list.selectedItems()) == 1
        assert view._roomfit_list.selectedItems() == []

        view._roomfit_list.setCurrentRow(0)
        assert len(view._roomfit_list.selectedItems()) == 1
        assert view._peq_list.selectedItems() == []

    # --- Issue #166: preset preview actions briefly activate live audio ---

    def test_166_confirm_preview_no_dialog_for_roomfit_only(self, window) -> None:
        """A RoomFit-only selection shows no confirmation -- reading a RoomFit
        profile's buffer has no live-audio consequence to consent to."""
        items = [PresetItem(name="Living Room", channel_mode="Stereo", preset_type="RoomFit")]

        with patch(
            "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm"
        ) as mock_question:
            result = window._confirm_preset_preview(items)

        mock_question.assert_not_called()
        assert result is True

    def test_166_confirm_preview_dialog_for_peq_only(self, window) -> None:
        """A PEQ-only selection shows the confirmation, naming the item."""
        items = [PresetItem(name="Movie Night", channel_mode="Stereo", preset_type="PEQ")]

        with patch(
            "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
            return_value=True,
        ) as mock_question:
            result = window._confirm_preset_preview(items)

        mock_question.assert_called_once()
        message = mock_question.call_args[0][2]
        assert "Movie Night" in message
        assert result is True

    def test_166_confirm_preview_mixed_selection_names_only_peq_items(self, window) -> None:
        """A mixed PEQ+RoomFit selection shows the dialog, naming only the
        PEQ items (RoomFit items have nothing to consent to)."""
        items = [
            PresetItem(name="Movie Night", channel_mode="Stereo", preset_type="PEQ"),
            PresetItem(name="Living Room", channel_mode="Stereo", preset_type="RoomFit"),
        ]

        with patch(
            "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
            return_value=True,
        ) as mock_question:
            window._confirm_preset_preview(items)

        message = mock_question.call_args[0][2]
        assert "Movie Night" in message
        assert "Living Room" not in message

    def test_166_confirm_preview_declined_returns_false(self, window) -> None:
        """Declining the confirmation returns False."""
        items = [PresetItem(name="Movie Night", channel_mode="Stereo", preset_type="PEQ")]

        with patch(
            "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
            return_value=False,
        ):
            result = window._confirm_preset_preview(items)

        assert result is False

    def test_166_confirm_preview_escapes_device_supplied_preset_name(self, window) -> None:
        """A preset name containing HTML-significant characters must not be
        interpreted as markup by Qt's rich-text auto-detection -- this
        message already contains <br>/<b> tags, so the device-supplied name
        must be escaped before being embedded in it."""
        items = [PresetItem(name="A <b>Bold</b> & Loud", channel_mode="Stereo", preset_type="PEQ")]

        with patch(
            "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
            return_value=True,
        ) as mock_question:
            window._confirm_preset_preview(items)

        message = mock_question.call_args[0][2]
        assert "<b>Bold</b>" not in message
        assert "&lt;b&gt;Bold&lt;/b&gt;" in message
        assert "&amp; Loud" in message

    def test_166_copy_to_device_cancelled_at_picker_skips_run_async(self, window) -> None:
        """Cancelling the combined warning+picker dialog aborts before any
        run_async call for _on_copy_to_device_requested. The preview and
        activation warnings are now embedded in the device picker itself
        (folded into one dialog) rather than shown as separate confirmations
        beforehand, so "declining" is now expressed as the user cancelling
        that single dialog -- DevicePickerDialog.get_devices returning None."""
        _setup_device(window)
        window._primary_workflows._discovered_devices = [
            MagicMock(ip="192.168.1.200", name="Other Device")
        ]
        items = [PresetItem(name="Movie Night", channel_mode="Stereo", preset_type="PEQ")]

        with (
            patch(
                "src.gui.main_window.DevicePickerDialog.get_devices",
                return_value=None,
            ) as mock_picker,
            patch.object(window._bridge, "run_async") as mock_run,
        ):
            window._on_copy_to_device_requested(items)

        mock_picker.assert_called_once()
        # The combined warning text is passed as the picker's 4th arg.
        warning = mock_picker.call_args[0][3]
        assert warning is not None
        assert "Movie Night" in warning[1]
        mock_run.assert_not_called()

    # --- #191: Copy-to-Device RoomFit target-activation warning ---

    def test_191_copy_activation_warning_html_for_peq_item(self, window) -> None:
        """Copying a PEQ preset warns that it will become active and enable
        PEQ on the target device(s), naming the preset -- PEQ redesign
        mirrors RoomFit's #191 warning (docs/corrections.md).

        `_copy_activation_warning_html` is the pure text builder folded into
        `DevicePickerDialog`'s embedded warning in the actual copy-to-device
        flow (there's no longer a standalone `_confirm_copy_activation`
        dialog to test directly)."""
        items = [PresetItem(name="Movie Night", channel_mode="Stereo", preset_type="PEQ")]

        body = window._copy_activation_warning_html(items)

        assert body is not None
        assert "Movie Night" in body

    def test_191_copy_activation_warning_html_for_roomfit_item(self, window) -> None:
        """Copying a RoomFit profile warns that it will become active and
        enable RoomFit on the target device(s), naming the profile."""
        items = [PresetItem(name="Living Room", channel_mode="Stereo", preset_type="RoomFit")]

        body = window._copy_activation_warning_html(items)

        assert body is not None
        assert "Living Room" in body

    def test_191_copy_activation_warning_html_mixed_selection_combines_both(
        self, window
    ) -> None:
        """A selection containing both types (not reachable via the current
        UI's mutual-exclusion behavior, but the builder must not assume it)
        combines both into one body, not two sequential popups' worth of
        text."""
        items = [
            PresetItem(name="Movie Night", channel_mode="Stereo", preset_type="PEQ"),
            PresetItem(name="Living Room", channel_mode="Stereo", preset_type="RoomFit"),
        ]

        body = window._copy_activation_warning_html(items)

        assert body is not None
        assert "Movie Night" in body
        assert "Living Room" in body

    def test_191_copy_activation_warning_html_empty_selection_returns_none(
        self, window
    ) -> None:
        assert window._copy_activation_warning_html([]) is None

    def test_191_copy_to_device_roomfit_cancelled_at_picker_skips_run_async(
        self, window
    ) -> None:
        """The RoomFit activation warning is embedded in the same combined
        device-picker dialog as the PEQ case -- cancelling that dialog must
        abort before any run_async call, and the warning text passed to the
        picker must name the RoomFit item and mention RoomFit specifically."""
        _setup_device(window)
        window._primary_workflows._discovered_devices = [
            MagicMock(ip="192.168.1.200", name="Other Device")
        ]
        items = [PresetItem(name="Living Room", channel_mode="Stereo", preset_type="RoomFit")]

        with (
            patch(
                "src.gui.main_window.DevicePickerDialog.get_devices",
                return_value=None,
            ) as mock_picker,
            patch.object(window._bridge, "run_async") as mock_run,
        ):
            window._on_copy_to_device_requested(items)

        mock_picker.assert_called_once()
        warning = mock_picker.call_args[0][3]
        assert warning is not None
        assert "Living Room" in warning[1]
        assert "RoomFit" in warning[1]
        mock_run.assert_not_called()

    # --- Issue #156: Delete from Presets on Device ---

    def test_delete_confirmed_after_dialog_triggers_run_async(self, window) -> None:
        """Confirming the delete dialog (Yes) calls run_async exactly once.

        Renamed from test_delete_confirmed_dispatches_by_preset_type: this
        test mocks run_async with close_coroutine_tree, so the real
        per-preset-type dispatch inside _do_delete_presets never actually
        runs here -- it only verifies the confirmation-dialog gating before
        run_async is invoked. Real per-type dispatch coverage (which adapter
        method gets called for PEQ vs RoomFit) lives in
        test_do_delete_presets_dispatches_and_refreshes below, which awaits
        the coroutine for real.
        """
        mock_adapter = _setup_device(window)
        mock_adapter.delete_peq_profile = AsyncMock()
        mock_adapter.delete_roomfit_profile = AsyncMock()
        mock_adapter.list_peq_profiles = AsyncMock(return_value=[])
        mock_adapter.list_roomfit_profiles = AsyncMock(return_value=[])
        items = [
            PresetItem(name="Movie", channel_mode="Stereo", preset_type="PEQ"),
            PresetItem(name="Living Room", channel_mode="Stereo", preset_type="RoomFit"),
        ]

        with (
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
                return_value=True,
            ),
            patch.object(
                window._bridge, "run_async", side_effect=close_coroutine_tree
            ) as mock_run,
        ):
            window._presets_device_view.delete_requested.emit(items)

        mock_run.assert_called_once()

    def test_delete_declined_does_not_call_adapter(self, window) -> None:
        """Declining the confirmation dialog leaves the adapter untouched."""
        mock_adapter = _setup_device(window)
        mock_adapter.delete_peq_profile = AsyncMock()
        item = PresetItem(name="Movie", channel_mode="Stereo", preset_type="PEQ")

        with (
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
                return_value=False,
            ),
            patch.object(window._bridge, "run_async") as mock_run,
        ):
            window._presets_device_view.delete_requested.emit([item])

        mock_run.assert_not_called()
        mock_adapter.delete_peq_profile.assert_not_called()

    def test_do_delete_presets_dispatches_and_refreshes(self, window) -> None:
        """_do_delete_presets calls the right adapter method per item and refreshes."""
        import asyncio

        mock_adapter = _setup_device(window)
        mock_adapter.delete_peq_profile = AsyncMock()
        mock_adapter.delete_roomfit_profile = AsyncMock()
        mock_adapter.list_peq_profiles = AsyncMock(return_value=[])
        mock_adapter.list_roomfit_profiles = AsyncMock(return_value=[])
        items = [
            PresetItem(name="Movie", channel_mode="Stereo", preset_type="PEQ"),
            PresetItem(name="Living Room", channel_mode="Stereo", preset_type="RoomFit"),
        ]

        with patch.object(window._status_banner, "show_success") as mock_success:
            asyncio.run(window._primary_workflows._do_delete_presets(items))

        mock_adapter.delete_peq_profile.assert_called_once_with("Movie")
        mock_adapter.delete_roomfit_profile.assert_called_once_with("Living Room")
        mock_adapter.list_peq_profiles.assert_called_once()
        mock_success.assert_called_once_with("2 preset(s) deleted")

    def test_do_delete_presets_partial_failure_reports_error(self, window) -> None:
        """One failing delete doesn't abort the batch; banner reports partial failure."""
        import asyncio

        mock_adapter = _setup_device(window)
        mock_adapter.delete_peq_profile = AsyncMock(side_effect=Exception("boom"))
        mock_adapter.delete_roomfit_profile = AsyncMock()
        mock_adapter.list_peq_profiles = AsyncMock(return_value=[])
        mock_adapter.list_roomfit_profiles = AsyncMock(return_value=[])
        items = [
            PresetItem(name="Movie", channel_mode="Stereo", preset_type="PEQ"),
            PresetItem(name="Living Room", channel_mode="Stereo", preset_type="RoomFit"),
        ]

        with patch.object(window._status_banner, "show_error") as mock_error:
            asyncio.run(window._primary_workflows._do_delete_presets(items))

        mock_adapter.delete_roomfit_profile.assert_called_once_with("Living Room")
        mock_error.assert_called_once_with("Deleted 1, 1 failed")

    def test_local_preset_delete_confirmed_deletes_and_refreshes(self, window) -> None:
        """Confirming the local-delete dialog deletes the profile and refreshes
        My Saved Presets, mirroring the device-side delete's safety check
        (this one was previously missing any confirmation at all)."""
        with (
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
                return_value=True,
            ),
            patch.object(window._profile_repository, "delete") as mock_delete,
            patch.object(window, "_refresh_presets_view") as mock_refresh,
            patch.object(window._status_banner, "show_success") as mock_success,
        ):
            window._on_profile_delete_requested("Movie Night")

        mock_delete.assert_called_once_with("Movie Night")
        mock_refresh.assert_called_once()
        mock_success.assert_called_once_with("Deleted 'Movie Night'")

    def test_local_preset_delete_declined_does_not_delete(self, window) -> None:
        """Declining the local-delete confirmation leaves the repository untouched."""
        with (
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
                return_value=False,
            ),
            patch.object(window._profile_repository, "delete") as mock_delete,
        ):
            window._on_profile_delete_requested("Movie Night")

        mock_delete.assert_not_called()

    # --- Issue #27: RoomFit profile selection triggers read and advances ---

    def test_issue27_roomfit_profile_selected_triggers_pull(self, window) -> None:
        """#27: Selecting a RoomFit profile stores state and schedules pull."""
        _setup_device(window)
        scheduled: list[object] = []

        def _capture(coro: object) -> None:
            scheduled.append(coro)

        with (
            patch.object(window._bridge, "run_async", side_effect=_capture) as mock_run,
            patch.object(window._status_banner, "show_progress") as mock_progress,
        ):
            window._on_roomfit_profile_selected("My Profile")

        assert window._wizard_controller.state.roomfit_profile_name == "My Profile"
        mock_progress.assert_called_once_with("Loading RoomFit profile 'My Profile'...")
        mock_run.assert_called_once()
        assert len(scheduled) == 1
        close_coroutine_tree(scheduled[0])

    # --- Issue #31: Save to My Presets refreshes preset list ---

    def test_issue31_save_preset_refreshes_list(self, window) -> None:
        """#31: After saving a preset from Review, it is actually persisted
        and the My Presets view is refreshed with it.

        Real behavior-level coverage of the refresh mechanics (repository
        .list_all() -> view.set_presets()) already lives in
        test_issue48_save_filters_to_presets_callable; this test instead
        exercises the real _on_review_save_preset() -> _save_filters_to_presets()
        call chain end-to-end (name generation included) rather than mocking
        away the shared helper, so a regression in that wiring is caught.
        """
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = ChannelMode.STEREO
        state.selected_source = "wifi"
        window._primary_workflows._discovered_devices = []

        with (
            patch.object(window._profile_repository, "save") as mock_save,
            patch.object(
                window._profile_repository, "list_all", return_value=[]
            ) as mock_list,
            patch.object(window._my_presets_view, "set_presets") as mock_set_presets,
        ):
            window._on_review_save_preset()

        mock_save.assert_called_once()
        mock_list.assert_called_once()
        mock_set_presets.assert_called_once_with([])

    # --- Issue #37: ReviewPage save_preset_requested signal connected ---

    def test_issue37_review_save_preset_signal_connected(self, window) -> None:
        """#37: ReviewPage save signal invokes preset-save handler path."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = ChannelMode.STEREO
        state.selected_source = "wifi"

        with patch.object(window, "_save_filters_to_presets") as mock_save:
            window._review_page.save_preset_requested.emit()

        mock_save.assert_called_once()

    # --- Issue #45: Export from Review vs Presets on Device consolidated ---

    def test_issue45_export_consolidated_helper(self, window) -> None:
        """#45: ReviewPage and PushPage export both funnel through the same
        _export_filters_as_rew helper (both wired to _on_export_requested).
        Patches the shared helper once, fires both signals, and asserts it
        was invoked twice with matching filter/channel_mode args -- proving
        there's a single implementation, not two independently-drifting
        copies (the original bug: Review and Presets on Device showed
        different dialogs because each had its own export code path).
        """
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter(100), _make_filter(200)]
        state.channel_mode = ChannelMode.STEREO

        with patch.object(window, "_export_filters_as_rew") as mock_export:
            window._review_page.export_rew_requested.emit()
            window._push_page.export_requested.emit()

        assert mock_export.call_count == 2
        for call in mock_export.call_args_list:
            assert call.args[0] == state.current_filters
            assert call.args[1] == state.channel_mode

    # --- Issue #47: Duplicate save/export logic consolidated into shared helpers ---

    def test_issue47_shared_helpers_consolidated(self, window) -> None:
        """#47: Every known save/export trigger call-site converges on the
        same shared primitives rather than reimplementing name-sanitizing,
        channel-split, or Profile-construction logic inline.

        - Review save and Push save both call MainWindow._save_filters_to_presets.
        - Review export and Push export both call MainWindow._export_filters_as_rew.
        - Presets-on-Device save (_do_preset_save) builds its Profile via the
          same shared_helpers.build_profile() used by _save_filters_to_presets,
          rather than constructing a Profile inline with duplicated
          name-sanitization/channel-split logic.
        """
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = ChannelMode.STEREO
        state.selected_source = "wifi"

        # Review save + Push save -> _save_filters_to_presets
        with patch.object(window, "_save_filters_to_presets") as mock_save:
            window._review_page.save_preset_requested.emit()
            window._push_page.save_preset_requested.emit()
        assert mock_save.call_count == 2

        # Review export + Push export -> _export_filters_as_rew
        with patch.object(window, "_export_filters_as_rew") as mock_export:
            window._review_page.export_rew_requested.emit()
            window._push_page.export_requested.emit()
        assert mock_export.call_count == 2

        # Presets-on-Device save path uses the same build_profile() helper
        # (not a locally-duplicated Profile construction).
        import inspect

        from src.gui.shared_helpers import build_profile as shared_build_profile

        source = inspect.getsource(window._primary_workflows._do_preset_save)
        assert "build_profile(" in source
        assert shared_build_profile.__module__ == "src.gui.shared_helpers"

    # --- Issue #53: PushPage export + save signals connected ---

    def test_issue53_push_page_export_connected(self, window) -> None:
        """#53: PushPage export signal invokes shared export helper."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = ChannelMode.STEREO

        with patch.object(window, "_export_filters_as_rew") as mock_export:
            window._push_page.export_requested.emit()

        mock_export.assert_called_once_with(state.current_filters, state.channel_mode)

    def test_issue53_push_page_save_preset_connected(self, window) -> None:
        """#53: PushPage save signal invokes shared preset-save helper."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = ChannelMode.STEREO
        state.selected_source = "wifi"

        with patch.object(window, "_save_filters_to_presets") as mock_save:
            window._push_page.save_preset_requested.emit()

        mock_save.assert_called_once()

    # --- Issue #54: _on_write_complete marks PUSH step completed ---

    def test_issue54_write_complete_marks_push_done(self, window) -> None:
        """#54: _on_write_complete marks PUSH step in completed_steps."""
        _setup_device(window)
        result = MagicMock(success=True, backup_path="/tmp/backup.json")

        with patch.object(window._push_page, "set_success"):
            window._on_write_complete(result)

        assert WizardStep.PUSH in window._wizard_controller.state.completed_steps

    # --- Issue #121: Push failure shows the actual error, not "Unknown error" ---

    def test_issue121_write_complete_shows_actual_error(self, window) -> None:
        """#121: _on_write_complete surfaces WriteResult.error_message
        verbatim on failure. The original bug read `result.error` (an
        attribute that doesn't exist on WriteResult), so getattr() always
        fell through to the "Unknown error" default regardless of what the
        real failure was."""
        _setup_device(window)
        result = WriteResult(
            success=False,
            rollback_success=True,
            backup_path="/tmp/backup.json",
            error_message="Clamped values rejected",
        )

        with (
            patch.object(window._push_page, "set_failure") as mock_set_failure,
            patch.object(window._status_banner, "show_error") as mock_show_error,
        ):
            window._on_write_complete(result)

        mock_set_failure.assert_called_once_with(
            "Clamped values rejected", "/tmp/backup.json", False
        )
        mock_show_error.assert_called_once_with("Push failed: Clamped values rejected")

    # --- Issue #123: L/R clamping uses separate maps per channel ---

    def test_issue123_lr_clamping_separate_maps(self, window) -> None:
        """#123: When only the left channel has out-of-range values, the
        clamping map passed to set_lr_filters for the left channel must be
        non-empty and the right channel's must stay empty -- previously a
        single combined clamping_map was applied to both channels, marking
        clean right-channel bands as "clamped" too."""
        _setup_device(window)
        state = window._wizard_controller.state
        # Left: gain of 20 dB is outside GAIN_MAX (12.0) -- must be clamped.
        filters_l = [_make_filter(100, gain=20.0)]
        # Right: fully in-range -- must NOT be clamped.
        filters_r = [_make_filter(200, gain=-3.0)]
        state.current_filters = filters_l + filters_r
        state.channel_mode = ChannelMode.LR

        peq_data = MagicMock(channel_mode="lr", bands_l=filters_l, bands_r=filters_r)

        with patch.object(window._review_page, "set_lr_filters") as mock_lr:
            window._on_peq_ready(peq_data)

        mock_lr.assert_called_once()
        call_args = mock_lr.call_args[0]
        # set_lr_filters(validated_l, validated_r, clamping_l, clamping_r, ...)
        clamping_l = call_args[2]
        clamping_r = call_args[3]
        assert clamping_l != {}
        assert 0 in clamping_l
        assert clamping_r == {}

    # --- Issue #158: unsaved-changes dialog false positive after push ---

    def test_unsaved_changes_true_before_push(self, window, monkeypatch) -> None:
        """Filters loaded but never pushed are reported as unsaved."""
        # conftest's autouse _suppress_unsaved_changes_dialog stubs this
        # method out to avoid blocking-dialog hangs on window teardown --
        # undo it here since this test exercises the real logic. Set the
        # window's own escape hatch too, so the real method being restored
        # for the rest of this test can't pop a real modal dialog when the
        # fixture's teardown calls window.close().
        monkeypatch.undo()
        window._skip_unsaved_prompt = True
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]

        assert window._has_unsaved_changes() is True

    def test_push_success_clears_unsaved_flag(self, window, monkeypatch) -> None:
        """A successful push snapshots current_filters, clearing the dirty flag."""
        monkeypatch.undo()
        window._skip_unsaved_prompt = True
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        result = MagicMock(success=True, backup_path="/tmp/backup.json")

        with patch.object(window._push_page, "set_success"):
            window._on_write_complete(result)

        assert window._has_unsaved_changes() is False

    def test_device_switch_resets_pushed_snapshot(self, window, monkeypatch) -> None:
        """Selecting a new device clears both current and last-pushed filters."""
        monkeypatch.undo()
        window._skip_unsaved_prompt = True
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        result = MagicMock(success=True, backup_path="/tmp/backup.json")
        with patch.object(window._push_page, "set_success"):
            window._on_write_complete(result)
        assert state.last_pushed_filters

        window._on_device_selected("192.168.1.200")

        assert window._wizard_controller.state.current_filters == []
        assert window._wizard_controller.state.last_pushed_filters == []

    def test_undo_marks_dirty_again(self, window, monkeypatch) -> None:
        """After undoing a successful push, the wizard is dirty again."""
        monkeypatch.undo()
        window._skip_unsaved_prompt = True
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        result = MagicMock(success=True, backup_path="/tmp/backup.json")
        with patch.object(window._push_page, "set_success"):
            window._on_write_complete(result)
        assert window._has_unsaved_changes() is False

        window._on_undo_complete(True, "Previous filters restored")

        assert window._has_unsaved_changes() is True

    # --- Issue #60: NAME_PROFILE step populates existing profile list ---

    def test_issue60_name_profile_populated_on_navigation(self, window) -> None:
        """#60: Navigating to NAME_PROFILE populates existing profiles."""
        import asyncio

        mock_adapter = _setup_device(window)
        mock_adapter.capabilities.roomfit_level = 2
        mock_adapter.list_roomfit_profiles = AsyncMock(
            return_value=[{"Name": "Living Room"}, {"Name": "Office"}]
        )

        def _run_now(coro: object) -> None:
            asyncio.run(coro)

        with patch.object(window._bridge, "run_async", side_effect=_run_now) as mock_run:
            window._on_step_changed(WizardStep.NAME_PROFILE)

        mock_run.assert_called_once()
        assert window._name_profile_page._profiles_list.count() == 2
        assert window._name_profile_page._profiles_list.item(0).text() == "Living Room"
        assert window._name_profile_page._profiles_list.item(1).text() == "Office"


    # --- Issue #62: RoomFit undo creates backup before overwrite ---

    def test_issue62_roomfit_push_backs_up_existing_profile(self, window) -> None:
        """#62: RoomFit push backs up existing profile before overwrite."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        state.channel_mode = ChannelMode.STEREO
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
        # RoomFitSafeWrite.execute() also calls get_roomfit_status() and, on
        # success (#191), load_roomfit_profile()/enable_roomfit() to
        # activate the pushed profile -- _setup_device()'s bare MagicMock()
        # would otherwise raise TypeError on await, silently swallowed by
        # execute()'s own best-effort error handling rather than exercised.
        mock_adapter.get_roomfit_status = AsyncMock(return_value=(True, ""))
        mock_adapter.restore_roomfit_active_profile = AsyncMock()
        mock_adapter.load_roomfit_profile = AsyncMock()
        mock_adapter.enable_roomfit = AsyncMock()

        mock_backup = MagicMock()
        mock_backup.create_backup = MagicMock(return_value="/tmp/backup.json")
        window._backup_manager = mock_backup
        window._roomfit_safe_write = RoomFitSafeWrite(mock_adapter, mock_backup)

        import asyncio

        asyncio.run(window._do_push())
        # Backup should have been created for the existing profile
        mock_backup.create_backup.assert_called_once()

    def test_issue62_do_undo_roomfit_completes_without_exception(
        self, window, tmp_path
    ) -> None:
        """#62: The method that actually crashed ("Is a directory" error) --
        _do_undo_roomfit -- must complete cleanly given a valid backup file
        path, going through RoomFitSafeWrite like every other RoomFit write.
        """
        _setup_device(window)
        backup_path = tmp_path / "roomfit_backup.json"
        backup_path.write_text(
            '{"channel_mode": "stereo", "filters": '
            '[{"type": "PEAK", "frequency_hz": 100.0, "gain_db": -3.0, "q": 1.0}]}',
            encoding="utf-8",
        )

        from src.models.peq import PEQSettings

        mock_adapter = window._wiim_adapter
        # _make_caps() doesn't set max_filters, leaving it an
        # auto-MagicMock -- RoomFitSafeWrite.execute() slices bands with
        # `filters[:max_filters]`, which requires a real int.
        mock_adapter.capabilities.max_filters = 10
        mock_adapter.list_roomfit_profiles = AsyncMock(
            return_value=[{"Name": "My Profile"}]
        )
        # RoomFitSafeWrite.execute() reconstructs a PEQSettings from
        # read_roomfit()'s return value for both the pre-write backup and
        # the post-write verification read-back -- it must be a real
        # PEQSettings (source_name must be a str for pydantic, and
        # channel_mode must be the real ChannelMode.STEREO enum, not a
        # MagicMock/string that would fail validation or mismatch the
        # `== ChannelMode.STEREO` branch check). Frequency matches the
        # backup file's content so write-then-verify actually agrees.
        mock_adapter.read_roomfit = AsyncMock(
            return_value=PEQSettings(
                source_name="wifi",
                channel_mode=ChannelMode.STEREO,
                bands=[_make_filter(100.0)],
            )
        )
        mock_adapter.write_roomfit = AsyncMock()
        # RoomFitSafeWrite.execute() also calls get_roomfit_status() and, on
        # success (#191), load_roomfit_profile()/enable_roomfit() to
        # activate the pushed profile -- _setup_device()'s bare MagicMock()
        # would otherwise raise TypeError on await, silently swallowed by
        # execute()'s own best-effort error handling rather than exercised.
        mock_adapter.get_roomfit_status = AsyncMock(return_value=(True, ""))
        mock_adapter.restore_roomfit_active_profile = AsyncMock()
        mock_adapter.load_roomfit_profile = AsyncMock()
        mock_adapter.enable_roomfit = AsyncMock()
        # Stub out the real BackupManager -- it constructs a pydantic
        # BackupRecord from capabilities.uuid/firmware_version, which the
        # MagicMock capabilities from _make_caps() can't satisfy, and that
        # validation is orthogonal to what this test verifies (that the
        # undo path routes through RoomFitSafeWrite and reaches write_roomfit).
        mock_backup = MagicMock()
        mock_backup.create_backup = MagicMock(return_value="/tmp/pre_undo_backup.json")
        window._backup_manager = mock_backup
        window._roomfit_safe_write = RoomFitSafeWrite(mock_adapter, mock_backup)

        import asyncio

        with patch.object(window._status_banner, "show_success") as mock_success:
            asyncio.run(
                window._do_undo_roomfit(str(backup_path), "wifi", "My Profile")
            )

        mock_adapter.write_roomfit.assert_called_once()
        mock_success.assert_called_once()

    def test_191_undo_button_always_shown_for_roomfit_push(self, window) -> None:
        """#191 redesign: RoomFitSafeWrite.execute() now always creates a
        backup, even for a brand-new profile (purely to carry pre-push
        selection/enable-state restore metadata for Undo) -- backup_path is
        never empty on a successful RoomFit push, so Undo is always shown.
        Previously this was hidden when backup_path was empty (new-profile
        push, nothing to restore under the old design)."""
        _setup_device(window)
        window._wizard_controller.state.flow_type = FlowType.ROOMFIT
        result = MagicMock(success=True, backup_path="/tmp/new_profile_backup.json")

        window._on_write_complete(result)

        # isHidden() (not isVisible()) is the correct check here: the test
        # window is never actually shown on screen, so isVisible() would be
        # False regardless of setVisible(True/False) -- isHidden() tracks
        # the widget's own explicit show/hide state independent of whether
        # its ancestor chain is on-screen.
        assert not window._push_page._undo_button.isHidden()


# ===========================================================================
# SETTINGS / UI STATE
# ===========================================================================


class TestSettingsUIState:
    """Tests for settings/UI issues: #2/#9, #8, #10, #11, #12, #13, #32, #33, #34,
    #38, #39, #42, #48, #49, #50, #69, #70, #74, #78, #79, #85.
    """

    # --- Issue #2/#9: HelpView close navigates back to wizard ---

    def test_issue2_help_close_signal_connected(self, window) -> None:
        """#2/#9: HelpView close_requested signal is actually wired to the
        handler that hides the help dialog -- not just present as an
        attribute (a bare hasattr() would pass even if the .connect() call
        were deleted). Emits the real signal and asserts the dialog closes.

        This subsumes test_issue9_help_close_navigates_back below, which
        exercises the same behavior by calling the handler directly; kept
        as a separate test because it verifies the signal *wiring* itself.
        """
        assert hasattr(window._help_view, "close_requested")
        window._help_dialog.show()
        assert window._help_dialog.isVisible()
        window._help_view.close_requested.emit()
        assert window._help_dialog.isVisible() is False

    def test_issue9_help_close_navigates_back(self, window) -> None:
        """#9: _on_help_close_requested hides the help dialog window."""
        window._help_dialog.show()
        assert window._help_dialog.isVisible()
        window._on_help_close_requested()
        assert not window._help_dialog.isVisible()

    # --- Issue #8: OperationFeedbackManager.finish_operation doesn't wipe success ---

    def test_issue8_finish_operation_preserves_success(self, window) -> None:
        """#8: finish_operation only clears banner if still showing progress.

        Asserts the banner *text* survives finish_operation() -- not just
        that fm.is_active flips False. A regression that made
        finish_operation() call banner.clear() unconditionally would still
        pass an is_active-only check but would wipe the success message the
        user needs to see (the original smoke bug)."""
        fm = window._feedback_manager
        # Simulate: banner shows a success message (not progress)
        window._status_banner.show_success("Done!")
        fm._is_active = True
        fm.finish_operation()
        # Banner should still show success (not cleared)
        # finish_operation only clears if is_progress() returns True
        assert not fm.is_active
        assert window._status_banner._message_label.text() == "Done!"
        # setVisible(True) was called and the widget was never explicitly
        # hidden by finish_operation() -- isVisible() itself would report
        # False here regardless because the top-level window is never
        # shown in this fixture, which isn't what this test is about.
        assert window._status_banner._message_label.isHidden() is False


    # --- Issue #10: Measurement picker cancel shows info banner ---

    def test_issue10_picker_cancel_shows_info(self, window) -> None:
        """#10: Cancelling the REW picker shows 'Selection cancelled' info.

        The picker is now the embedded RewPullView rather than a modal
        dialog — cancellation happens via its back_requested signal once a
        selection screen (not just the connecting placeholder) was shown.
        """
        measurements = [MeasurementSummary(uuid="uuid-1", name="M1", index=0)]
        window._active_rew_pull_view = window._rew_pull_view
        window._rew_pull_view.set_measurements(measurements)

        with (
            patch.object(window._status_banner, "show_info") as mock_info,
            patch.object(window._bridge, "run_async") as mock_run_async,
        ):
            window._rew_pull_view.back_requested.emit()

        mock_info.assert_called_once_with("Selection cancelled", auto_dismiss=3000)
        mock_run_async.assert_not_called()

    # --- Issue #11: FiltersPage retry shows option cards ---

    def test_issue11_filters_page_has_retry_mechanism(self, window) -> None:
        """#11: Clearing error state fully resets FiltersPage for retry."""
        page = window._filters_page
        page.show_error("Parse failed")
        page._stereo_path = "/tmp/rew.txt"
        page._left_path = "/tmp/left.txt"
        page._right_path = "/tmp/right.txt"
        page._stereo_file_label.setText("rew.txt")
        page._left_file_label.setText("left.txt")
        page._right_file_label.setText("right.txt")
        page._next_btn.setEnabled(True)
        page._import_lr_btn.setEnabled(True)

        page.clear_results()

        assert page._error_section.isVisible() is False
        assert page._warnings_section.isVisible() is False
        assert page._stereo_path == ""
        assert page._left_path == ""
        assert page._right_path == ""
        assert page._stereo_file_label.text() == "No file selected"
        assert page._left_file_label.text() == "No file selected"
        assert page._right_file_label.text() == "No file selected"
        assert page._next_btn.isEnabled() is False
        assert page._import_lr_btn.isEnabled() is False

    # --- Issue #12: Progress shown immediately before async call ---

    def test_issue12_device_pull_shows_progress(self, window) -> None:
        """#12: _on_device_pull_requested shows progress before async call."""
        _setup_device(window)
        call_order: list[str] = []

        def _record_progress(message: str) -> None:
            call_order.append(f"progress:{message}")

        def _record_async(coro: object) -> None:
            call_order.append("run_async")
            close_coroutine_tree(coro)

        with (
            patch.object(window._status_banner, "show_progress", side_effect=_record_progress),
            patch.object(window._bridge, "run_async", side_effect=_record_async),
        ):
            window._on_device_pull_requested()

        assert call_order == [
            "progress:Pulling filters from device...",
            "run_async",
        ]

    # --- Issue #13: Empty filters shows persistent guidance ---

    def test_issue13_empty_filters_shows_persistent_message(self, window) -> None:
        """#13: Empty filters from device shows persistent info message."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = []  # Empty filters
        state.channel_mode = ChannelMode.STEREO

        peq_data = MagicMock(channel_mode="stereo", bands_l=None, bands_r=None)
        with (
            patch("src.gui.main_window.QTimer.singleShot", side_effect=lambda _ms, fn: fn()),
            patch.object(window._status_banner, "show_info") as mock_info,
            patch.object(window._bridge, "run_async") as mock_run_async,
        ):
            window._on_peq_ready(peq_data)

        mock_info.assert_called_once_with(
            "Device has no active filters. Try importing from a REW file instead.",
            auto_dismiss=0,
        )
        mock_run_async.assert_not_called()

    # --- Issue #32: finish_operation only clears if still showing progress ---

    def test_issue32_finish_clears_only_progress(self, window) -> None:
        """#32: finish_operation preserves results but clears active progress."""
        fm = window._feedback_manager
        banner = window._status_banner

        with patch.object(banner, "clear") as mock_clear:
            fm._is_active = True
            with patch.object(banner, "is_progress", return_value=False):
                fm.finish_operation()
            mock_clear.assert_not_called()

            fm._is_active = True
            with patch.object(banner, "is_progress", return_value=True):
                fm.finish_operation()
            mock_clear.assert_called_once()

    def test_issue153_copy_batch_counts_verification_failure(self, window) -> None:
        """#153: a verification failure during copy must count as a real
        failure in the batch summary, not be silently treated as success.
        Previously _do_copy_preset_to_device never checked SafeWrite's
        result at all, so save_peq_profile() ran and "saved" was reported
        unconditionally even after a failed/rolled-back write."""
        _setup_device(window)
        filters = [_make_filter(100)]
        peq_settings = MagicMock(channel_mode="stereo", bands=filters)

        with (
            patch("src.gui.main_window.WiiMHttpClient"),
            patch("src.gui.main_window.CapabilityProber") as mock_prober_cls,
            patch("src.gui.main_window.WiiMAdapter") as mock_adapter_cls,
            patch("src.gui.main_window.SafeWrite") as mock_safe_write_cls,
        ):
            mock_prober = MagicMock()
            mock_prober.probe = AsyncMock(return_value=_make_caps())
            mock_prober_cls.return_value = mock_prober

            mock_target_client = MagicMock()
            mock_target_client.close = AsyncMock()
            target_adapter = MagicMock()
            target_adapter.save_peq_profile = AsyncMock()
            mock_adapter_cls.return_value = target_adapter

            safe_write = MagicMock()
            safe_write.execute = AsyncMock(
                return_value=WriteResult(
                    success=False,
                    rollback_success=True,
                    error_message="Write verification failed; original state restored.",
                )
            )
            mock_safe_write_cls.return_value = safe_write

            import asyncio

            mock_wiim_http = MagicMock(return_value=mock_target_client)
            with patch("src.gui.main_window.WiiMHttpClient", mock_wiim_http):
                with pytest.raises(RuntimeError):
                    asyncio.run(
                        window._do_copy_preset_to_device(
                            "Movie Night", "PEQ", "192.168.1.200", "wifi",
                            filters, ChannelMode.STEREO, peq_settings,
                        )
                    )
            # The failed write must not be saved as if it succeeded.
            target_adapter.save_peq_profile.assert_not_called()

    def test_issue154_undo_roomfit_uses_safe_write(self, window, tmp_path) -> None:
        """#154: _do_undo_roomfit must go through RoomFitSafeWrite (verified,
        rolled back on mismatch) like every other RoomFit write path, not
        call adapter.write_roomfit() directly with no verification at all.

        #191: _do_undo_roomfit is now a thin pass-through to
        RoomFitSafeWrite.undo() (not .execute() directly -- undo() owns the
        backup-parsing/new-vs-overwrite orchestration internally)."""
        _setup_device(window)
        backup_path = tmp_path / "roomfit_backup.json"
        backup_path.write_text(
            '{"channel_mode": "stereo", "filters": '
            '[{"type": "PEAK", "frequency_hz": 100.0, "gain_db": -3.0, "q": 1.0}]}',
            encoding="utf-8",
        )

        with patch("src.gui.main_window.RoomFitSafeWrite") as mock_roomfit_safe_write_cls:
            roomfit_safe_write = MagicMock()
            roomfit_safe_write.undo = AsyncMock(return_value=WriteResult(success=True))
            mock_roomfit_safe_write_cls.return_value = roomfit_safe_write

            import asyncio

            asyncio.run(
                window._do_undo_roomfit(str(backup_path), "wifi", "My Profile")
            )

            roomfit_safe_write.undo.assert_called_once()
            window._wiim_adapter.write_roomfit.assert_not_called()

    def test_issue154_undo_roomfit_surfaces_verification_failure(
        self, window, tmp_path
    ) -> None:
        """#154: a verification failure during RoomFit undo must be reported
        as an error, not silently shown as "restored from backup"."""
        _setup_device(window)
        backup_path = tmp_path / "roomfit_backup.json"
        backup_path.write_text(
            '{"channel_mode": "stereo", "filters": '
            '[{"type": "PEAK", "frequency_hz": 100.0, "gain_db": -3.0, "q": 1.0}]}',
            encoding="utf-8",
        )

        with patch("src.gui.main_window.RoomFitSafeWrite") as mock_roomfit_safe_write_cls:
            roomfit_safe_write = MagicMock()
            roomfit_safe_write.undo = AsyncMock(
                return_value=WriteResult(
                    success=False,
                    rollback_success=True,
                    error_message="RoomFit verification failed; original profile restored.",
                )
            )
            mock_roomfit_safe_write_cls.return_value = roomfit_safe_write

            with patch.object(window._status_banner, "show_error") as mock_show_error, \
                 patch.object(window._status_banner, "show_success") as mock_show_success:
                import asyncio

                asyncio.run(
                    window._do_undo_roomfit(str(backup_path), "wifi", "My Profile")
                )

                mock_show_success.assert_not_called()
                mock_show_error.assert_called_once()

    def test_undo_roomfit_new_profile_shows_reactivation_message(
        self, window, tmp_path
    ) -> None:
        """Undoing a push that created a brand-new profile must not claim
        the profile was "restored from backup" -- nothing existed to
        restore, undo() only re-activates the previously-active profile and
        leaves the new one on the device (see RoomFitSafeWrite.undo())."""
        _setup_device(window)
        backup_path = tmp_path / "roomfit_backup.json"
        backup_path.write_text(
            '{"channel_mode": "stereo", "filters": '
            '[{"type": "PEAK", "frequency_hz": 100.0, "gain_db": -3.0, "q": 1.0}], '
            '"was_new_profile": true}',
            encoding="utf-8",
        )

        with patch("src.gui.main_window.RoomFitSafeWrite") as mock_roomfit_safe_write_cls:
            roomfit_safe_write = MagicMock()
            roomfit_safe_write.undo = AsyncMock(return_value=WriteResult(success=True))
            mock_roomfit_safe_write_cls.return_value = roomfit_safe_write

            import asyncio

            with patch.object(window._status_banner, "show_success") as mock_success:
                asyncio.run(
                    window._do_undo_roomfit(str(backup_path), "wifi", "My Profile")
                )

        message = mock_success.call_args[0][0]
        assert "restored from backup" not in message
        assert "re-activated" in message
        assert "My Profile" in message

    def test_undo_roomfit_overwrite_shows_restored_message(
        self, window, tmp_path
    ) -> None:
        """Undoing a push that overwrote an existing profile keeps the
        "restored from backup" message -- bands actually were restored in
        this case."""
        _setup_device(window)
        backup_path = tmp_path / "roomfit_backup.json"
        backup_path.write_text(
            '{"channel_mode": "stereo", "filters": '
            '[{"type": "PEAK", "frequency_hz": 100.0, "gain_db": -3.0, "q": 1.0}], '
            '"was_new_profile": false}',
            encoding="utf-8",
        )

        with patch("src.gui.main_window.RoomFitSafeWrite") as mock_roomfit_safe_write_cls:
            roomfit_safe_write = MagicMock()
            roomfit_safe_write.undo = AsyncMock(return_value=WriteResult(success=True))
            mock_roomfit_safe_write_cls.return_value = roomfit_safe_write

            import asyncio

            with patch.object(window._status_banner, "show_success") as mock_success:
                asyncio.run(
                    window._do_undo_roomfit(str(backup_path), "wifi", "My Profile")
                )

        message = mock_success.call_args[0][0]
        assert message == "Profile 'My Profile' restored from backup"

    # --- Issue #26: Copy to Another Device actually writes to target ---

    def test_issue26_copy_preset_to_device_writes_to_target(self, window) -> None:
        """#26: A full successful "Copy to Another Device" for a PEQ preset
        must actually write the target device's data (via SafeWrite.execute,
        then save_peq_profile) and show a success status -- not just pick
        the right branch (that narrower claim is already covered by #34's
        test). This is the end-to-end happy path: read from source, connect
        to target, write+verify, persist as a named preset, report success.
        """
        _setup_device(window)
        filters = [_make_filter(100), _make_filter(200)]
        peq_settings = MagicMock(channel_mode="stereo", bands=filters)

        with (
            patch("src.gui.main_window.WiiMHttpClient") as mock_client_cls,
            patch("src.gui.main_window.CapabilityProber") as mock_prober_cls,
            patch("src.gui.main_window.WiiMAdapter") as mock_adapter_cls,
            patch("src.gui.main_window.SafeWrite") as mock_safe_write_cls,
            patch.object(window._status_banner, "show_success") as mock_show_success,
        ):
            mock_target_client = MagicMock()
            mock_target_client.close = AsyncMock()
            mock_client_cls.return_value = mock_target_client

            mock_prober = MagicMock()
            mock_prober.probe = AsyncMock(return_value=_make_caps())
            mock_prober_cls.return_value = mock_prober

            target_adapter = MagicMock()
            target_adapter.save_peq_profile = AsyncMock()
            mock_adapter_cls.return_value = target_adapter

            safe_write = MagicMock()
            safe_write.execute = AsyncMock(return_value=WriteResult(success=True))
            mock_safe_write_cls.return_value = safe_write

            import asyncio

            asyncio.run(
                window._do_copy_preset_to_device(
                    "Movie Night", "PEQ", "192.168.1.200", "wifi",
                    filters, ChannelMode.STEREO, peq_settings,
                )
            )

        # Write must have actually happened, targeting the real data read
        # from the source device.
        safe_write.execute.assert_called_once()
        written_settings = safe_write.execute.call_args[0][1]
        assert written_settings.bands == peq_settings.bands
        # And the write must be saved as a named preset on the target.
        target_adapter.save_peq_profile.assert_called_once_with("wifi", "Movie Night")
        mock_show_success.assert_called_once()
        assert "Movie Night" in mock_show_success.call_args[0][0]

    # --- Issue #69: Copy preset to device carries channel_mode through (PEQ) ---

    def test_issue69_copy_preset_to_device_has_channel_mode(self, window) -> None:
        """#69: Copying an L/R PEQ preset (not RoomFit -- #79 already covers
        the RoomFit case) must carry channel_mode=ChannelMode.LR through to
        the PEQ write path, not silently default to stereo.

        NOTE: the doc's originally-cited SecondaryWorkflowManager
        .copy_preset_to_device() no longer exists -- "Copy to another
        source" / "Apply to multiple devices" were removed as dead code
        (see src/gui/secondary_workflows.py module docstring, 2026-06-28
        audit). The live copy-to-device implementation is
        MainWindow._do_copy_preset_to_device(), which already takes
        channel_mode from the source read rather than a hardcoded default --
        this test targets that current path.
        """
        _setup_device(window)
        filters_l = [_make_filter(100)]
        filters_r = [_make_filter(200)]
        peq_settings = MagicMock(
            channel_mode="lr", bands_l=filters_l, bands_r=filters_r, bands=[]
        )

        with (
            patch("src.gui.main_window.WiiMHttpClient"),
            patch("src.gui.main_window.CapabilityProber") as mock_prober_cls,
            patch("src.gui.main_window.WiiMAdapter") as mock_adapter_cls,
            patch("src.gui.main_window.SafeWrite") as mock_safe_write_cls,
        ):
            mock_prober = MagicMock()
            mock_prober.probe = AsyncMock(return_value=_make_caps())
            mock_prober_cls.return_value = mock_prober

            target_adapter = MagicMock()
            target_adapter.save_peq_profile = AsyncMock()
            mock_adapter_cls.return_value = target_adapter

            mock_target_client = MagicMock()
            mock_target_client.close = AsyncMock()

            safe_write = MagicMock()
            safe_write.execute = AsyncMock(return_value=WriteResult(success=True))
            mock_safe_write_cls.return_value = safe_write

            import asyncio

            with patch("src.gui.main_window.WiiMHttpClient", return_value=mock_target_client):
                asyncio.run(
                    window._do_copy_preset_to_device(
                        "LR Preset", "PEQ", "192.168.1.200", "wifi",
                        filters_l + filters_r, ChannelMode.LR, peq_settings,
                    )
                )

            safe_write.execute.assert_called_once()
            written_settings = safe_write.execute.call_args[0][1]
            assert written_settings.channel_mode == ChannelMode.LR
            assert written_settings.bands_l == filters_l
            assert written_settings.bands_r == filters_r

    # --- Issue #34: _do_copy_preset_to_device branches on preset_type ---

    def test_issue34_copy_branches_on_preset_type(self, window) -> None:
        """#34: _do_copy_preset_to_device uses PEQ and RoomFit write paths correctly."""
        _setup_device(window)

        peq_settings = MagicMock(channel_mode="stereo", bands=[_make_filter(100)])

        roomfit_settings = MagicMock(
            channel_mode="lr",
            bands=[_make_filter(100), _make_filter(200)],
            bands_l=[_make_filter(100)],
            bands_r=[_make_filter(200)],
        )

        with (
            patch("src.gui.main_window.WiiMHttpClient"),
            patch("src.gui.main_window.CapabilityProber") as mock_prober_cls,
            patch("src.gui.main_window.WiiMAdapter") as mock_adapter_cls,
            patch("src.gui.main_window.SafeWrite") as mock_safe_write_cls,
            patch("src.gui.main_window.RoomFitSafeWrite") as mock_roomfit_safe_write_cls,
        ):
            mock_prober = MagicMock()
            mock_prober.probe = AsyncMock(return_value=_make_caps())
            mock_prober_cls.return_value = mock_prober

            mock_target_client = MagicMock()
            mock_target_client.close = AsyncMock()

            target_adapter = MagicMock()
            target_adapter.write_roomfit = AsyncMock()
            target_adapter.save_peq_profile = AsyncMock()
            mock_adapter_cls.return_value = target_adapter
            mock_wiim_http = MagicMock(return_value=mock_target_client)

            safe_write = MagicMock()
            safe_write.execute = AsyncMock(return_value=WriteResult(success=True))
            mock_safe_write_cls.return_value = safe_write

            roomfit_safe_write = MagicMock()
            roomfit_safe_write.execute = AsyncMock(return_value=WriteResult(success=True))
            mock_roomfit_safe_write_cls.return_value = roomfit_safe_write

            import asyncio

            with patch("src.gui.main_window.WiiMHttpClient", mock_wiim_http):
                asyncio.run(
                    window._do_copy_preset_to_device(
                        "Movie Night", "PEQ", "192.168.1.200", "wifi",
                        peq_settings.bands, ChannelMode.STEREO, peq_settings,
                    )
                )
                safe_write.execute.assert_called_once()
                target_adapter.save_peq_profile.assert_called_once_with(
                    "wifi", "Movie Night"
                )
                roomfit_safe_write.execute.assert_not_called()

                safe_write.execute.reset_mock()
                target_adapter.save_peq_profile.reset_mock()
                roomfit_safe_write.execute.reset_mock()

                asyncio.run(
                    window._do_copy_preset_to_device(
                        "RoomFit A", "RoomFit", "192.168.1.200", "wifi",
                        roomfit_settings.bands, ChannelMode.LR, roomfit_settings,
                    )
                )
                # RoomFit copies now go through RoomFitSafeWrite (verified +
                # rolled back on mismatch, smoke #153), not a bare
                # write_roomfit() call with no verification.
                roomfit_safe_write.execute.assert_called_once()
                target_adapter.write_roomfit.assert_not_called()
                safe_write.execute.assert_not_called()
                target_adapter.save_peq_profile.assert_not_called()

    # --- Issue #38: My Saved Presets view has toolbar buttons ---

    def test_issue38_my_presets_view_has_toolbar(self, window, qtbot) -> None:
        """#38: Toolbar actions emit for the selected preset.

        `window` fixture wires `view.delete_requested` to the real
        `MainWindow._on_profile_delete_requested`, which shows a real
        `WarningConfirmDialog` confirmation -- clicking `_delete_btn` below
        fires that handler too, not just this test's own lambda, so
        `WarningConfirmDialog.confirm` must be patched or its `exec()`
        blocks the test run on a real, unclosable popup (this was the
        source of a previously-reported hanging-test bug, #203).
        """
        view = window._my_presets_view
        profile = build_profile("Jazz Night", [_make_filter()], "Stereo")

        window._stacked_widget.setCurrentWidget(view)
        window.show()
        qtbot.wait(10)
        view.set_presets([profile])

        assert view._toolbar.isVisible() is True
        assert view._load_btn.isEnabled() is False
        assert view._rename_btn.isEnabled() is False
        assert view._duplicate_btn.isEnabled() is False
        assert view._delete_btn.isEnabled() is False

        view._list_widget.setCurrentRow(0)
        qtbot.wait(10)

        assert view._load_btn.isEnabled() is True
        assert view._rename_btn.isEnabled() is True
        assert view._duplicate_btn.isEnabled() is True
        assert view._delete_btn.isEnabled() is True

        load_calls: list[object] = []
        duplicate_calls: list[str] = []
        delete_calls: list[str] = []

        view.load_requested.connect(lambda selected: load_calls.append(selected))
        view.duplicate_requested.connect(lambda name: duplicate_calls.append(name))
        view.delete_requested.connect(lambda name: delete_calls.append(name))

        view._load_btn.click()
        view._duplicate_btn.click()
        with patch(
            "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
            return_value=True,
        ):
            view._delete_btn.click()

        assert load_calls == [profile]
        assert duplicate_calls == ["Jazz Night"]
        assert delete_calls == ["Jazz Night"]

    # --- Issue #39: L/R presets show "L/R" badge ---

    def test_issue39_lr_profile_preserves_channel_mode(self) -> None:
        """#39: build_profile with L/R channel_mode stores 'left' (L/R indicator)."""
        filters = [_make_filter(100), _make_filter(200)]
        profile = build_profile(
            "Test", filters, "L/R", filters_l=filters[:1], filters_r=filters[1:]
        )
        assert profile.channel_mode == ChannelMode.LR  # Internal L/R representation

    def test_issue39_stereo_profile_channel_mode(self) -> None:
        """#39: build_profile with stereo stores 'stereo'."""
        filters = [_make_filter()]
        profile = build_profile("Test", filters, "Stereo")
        assert profile.channel_mode == ChannelMode.STEREO

    def test_issue39_lr_profile_renders_lr_badge_not_stereo(self, window) -> None:
        """#39: An L/R profile rendered in MyPresetsView shows the "L/R"
        badge (not "Stereo") and a per-channel band count -- not a flat
        combined count. This is the actual UI-visible manifestation of the
        original bug; the build_profile-level tests above only prove the
        enum is stored correctly, not that the view renders it right.
        """
        filters_l = [_make_filter(100), _make_filter(200)]
        filters_r = [_make_filter(300)]
        profile = build_profile(
            "LR Test", filters_l + filters_r, "L/R",
            filters_l=filters_l, filters_r=filters_r,
        )

        view = window._my_presets_view
        view.set_presets([profile])

        item = view._list_widget.item(0)
        item_widget = view._list_widget.itemWidget(item)
        assert item_widget._mode_badge.text() == "L/R"
        # _count_bands() uses the left channel as the representative count
        # for L/R profiles (2 bands), not a flat/combined 3.
        assert item_widget._band_label.text() == "2/2 bands"

    def test_issue39_stereo_profile_renders_stereo_badge(self, window) -> None:
        """#39 sibling: a stereo profile still shows "Stereo" (not "L/R")."""
        filters = [_make_filter(100), _make_filter(200), _make_filter(300)]
        profile = build_profile("Stereo Test", filters, "Stereo")

        view = window._my_presets_view
        view.set_presets([profile])

        item = view._list_widget.item(0)
        item_widget = view._list_widget.itemWidget(item)
        assert item_widget._mode_badge.text() == "Stereo"
        assert item_widget._band_label.text() == "3/3 bands"

    # --- Issue #42: Source page receives all common sources including line-in ---

    def test_issue42_source_page_has_set_sources(self, window) -> None:
        """#42: SourcePage populates all provided sources, including line-in."""
        page = window._source_page
        page.set_sources(["wifi", "line-in", "optical"])

        assert list(page._source_checkboxes.keys()) == ["wifi", "line-in", "optical"]
        assert page._source_checkboxes["wifi"].isChecked() is True
        assert "recommended default" in page._source_checkboxes["wifi"].text()
        assert page._source_checkboxes["line-in"].text() == "line-in"
        assert page._continue_btn.isEnabled() is True

    # --- Issue #48: Preset save uses thread-safe pattern ---

    def test_issue48_save_filters_to_presets_callable(self, window) -> None:
        """#48: _save_filters_to_presets refreshes the visible presets view."""
        filters = [_make_filter(100), _make_filter(200)]
        state = window._wizard_controller.state
        state.filters_l = []
        state.filters_r = []

        with (
            patch.object(window._profile_repository, "save") as mock_save,
            patch.object(window._profile_repository, "list_all", return_value=[]) as mock_list,
            patch.object(window._my_presets_view, "set_presets") as mock_set_presets,
            patch.object(window._status_banner, "show_success") as mock_success,
        ):
            window._save_filters_to_presets("Thread Safe Preset", filters, ChannelMode.STEREO)

        mock_save.assert_called_once()
        saved_profile = mock_save.call_args[0][0]
        assert saved_profile.name == "Thread Safe Preset"
        assert saved_profile.channel_mode == ChannelMode.STEREO
        assert saved_profile.filters == filters
        mock_list.assert_called_once()
        mock_set_presets.assert_called_once_with([])
        mock_success.assert_called_once_with("Saved 'Thread Safe Preset' to My Presets")

    def test_save_filters_to_presets_shows_error_banner_on_failure(self, window) -> None:
        """A failing ProfileRepository.save() must show an error banner, not
        propagate uncaught -- this path previously had no try/except at all
        (Phase 5 consolidation via _run_profile_action)."""
        filters = [_make_filter(100)]
        state = window._wizard_controller.state
        state.filters_l = []
        state.filters_r = []

        with (
            patch.object(
                window._profile_repository, "save", side_effect=OSError("disk full")
            ) as mock_save,
            patch.object(window, "_refresh_presets_view") as mock_refresh,
            patch.object(window._status_banner, "show_error") as mock_error,
        ):
            window._save_filters_to_presets("Broken Preset", filters, ChannelMode.STEREO)

        mock_save.assert_called_once()
        mock_refresh.assert_not_called()
        mock_error.assert_called_once_with("Save failed: disk full")

    # --- Issue #49: recall_profile handles L/R profiles ---

    def test_issue49_recall_profile_lr(self, window) -> None:
        """#49: recall_profile extracts filters from L/R profile correctly,
        in the right order/content -- not just the right count. Uses
        distinguishable per-channel frequencies (100 Hz left, 200 Hz right)
        so a bug that swapped or merged channels incorrectly would be
        caught, unlike a bare len()==2 check.
        """
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
            assert emitted_filters[0].frequency_hz == 100
            assert emitted_filters[1].frequency_hz == 200


    def test_issue49_recall_profile_stereo(self, window) -> None:
        """#49: recall_profile extracts filters from stereo profile correctly,
        preserving original order/content."""
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
            assert emitted_filters[0].frequency_hz == 100
            assert emitted_filters[1].frequency_hz == 200

    # --- Issue #50: Copy to another source reads from SourcePage source list ---

    def test_issue50_source_page_provides_sources(self, window) -> None:
        """#50: Dry-run summary uses SourcePage selections, not empty caps."""
        page = window._source_page
        page.set_sources(["wifi", "optical", "hdmi"], active_source="wifi")
        page._source_checkboxes["wifi"].setChecked(False)
        page._source_checkboxes["optical"].setChecked(True)
        page._source_checkboxes["hdmi"].setChecked(True)

        _setup_device(window).capabilities.source_names = []
        state = window._wizard_controller.state
        state.selected_source = ",".join(
            source
            for source, checkbox in page._source_checkboxes.items()
            if checkbox.isChecked()
        )
        state.current_filters = [_make_filter()]
        state.channel_mode = ChannelMode.STEREO
        state.dry_run = True

        with patch.object(window._push_page, "set_dry_run_result") as mock_dry:
            window._on_push_requested()

        summary = mock_dry.call_args[0][0]
        assert "optical, hdmi" in summary

    # --- Issue #70: parse_backup_filters handles stereo and L/R ---

    def test_issue70_parse_backup_stereo(self) -> None:
        """#70: parse_backup_filters handles stereo backup format."""
        backup = {
            "channel_mode": "stereo",
            "filters": [
                {"type": "PEAK", "frequency_hz": 1000, "gain_db": -3, "q": 1.0},
            ],
        }
        filters, mode, filters_l, filters_r = parse_backup_filters(backup)
        assert mode == ChannelMode.STEREO
        assert len(filters) == 1
        assert filters[0].frequency_hz == 1000
        assert filters_l is None
        assert filters_r is None

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
        filters, mode, filters_l, filters_r = parse_backup_filters(backup)
        assert mode == ChannelMode.LR
        assert len(filters) == 2
        assert filters_l is not None and len(filters_l) == 1
        assert filters_r is not None and len(filters_r) == 1
        assert filters_l[0].frequency_hz == 100
        assert filters_r[0].frequency_hz == 200

    def test_issue70_parse_backup_empty(self) -> None:
        """#70: parse_backup_filters handles empty backup gracefully."""
        backup: dict[str, object] = {}
        filters, mode, filters_l, filters_r = parse_backup_filters(backup)
        assert mode == ChannelMode.STEREO
        assert filters == []
        assert filters_l is None
        assert filters_r is None

    def test_issue70_parse_backup_lr_unequal_lengths_not_naively_split(self) -> None:
        """Regression: undo must not reconstruct L/R via positional 50/50 split.

        Uses deliberately unequal L/R band counts so a naive split on the
        combined list (which would produce 4/4) is distinguishable from the
        correct per-channel split (3/5) returned by parse_backup_filters.
        """
        backup = {
            "channel_mode": "left",
            "filters_l": [
                {"type": "PEAK", "frequency_hz": 100, "gain_db": -2, "q": 1.0},
                {"type": "PEAK", "frequency_hz": 110, "gain_db": -2, "q": 1.0},
                {"type": "PEAK", "frequency_hz": 120, "gain_db": -2, "q": 1.0},
            ],
            "filters_r": [
                {"type": "PEAK", "frequency_hz": 200, "gain_db": -4, "q": 1.5},
                {"type": "PEAK", "frequency_hz": 210, "gain_db": -4, "q": 1.5},
                {"type": "PEAK", "frequency_hz": 220, "gain_db": -4, "q": 1.5},
                {"type": "PEAK", "frequency_hz": 230, "gain_db": -4, "q": 1.5},
                {"type": "PEAK", "frequency_hz": 240, "gain_db": -4, "q": 1.5},
            ],
        }
        filters, mode, filters_l, filters_r = parse_backup_filters(backup)
        assert mode == ChannelMode.LR
        assert len(filters) == 8
        assert filters_l is not None and len(filters_l) == 3
        assert filters_r is not None and len(filters_r) == 5
        assert [f.frequency_hz for f in filters_l] == [100, 110, 120]
        assert [f.frequency_hz for f in filters_r] == [200, 210, 220, 230, 240]

    # --- Issue #74: _do_copy_presets_batch_multi iterates all devices ---

    def test_issue74_copy_batch_multi_iterates_all_devices(self, window) -> None:
        """#74: _do_copy_presets_batch_multi iterates all (preset, device)
        pairs -- and, critically, actually *targets* each distinct device
        (the original regression called selected_devices[0] repeatedly,
        which a bare call_count check wouldn't catch if all calls silently
        hit the same IP). Also covers multiple *items*, not just multiple
        devices -- folded in from the removed #33 test after #33's
        single-device `_do_copy_presets_batch` was superseded by this
        multi-device version (docs/smoke_test_issues.md row 74) and left
        behind as dead code with its own regression test."""
        _setup_device(window)
        items = [MagicMock(), MagicMock()]
        items[0].name = "Preset1"
        items[0].preset_type = "PEQ"
        items[1].name = "Preset2"
        items[1].preset_type = "PEQ"

        device1 = MagicMock(ip="192.168.1.201", name="Device A")
        device2 = MagicMock(ip="192.168.1.202", name="Device B")
        devices = [device1, device2]

        filters = [_make_filter(100)]
        peq_settings = MagicMock(channel_mode="stereo", bands=filters)
        read_result = (filters, ChannelMode.STEREO, peq_settings)

        with (
            patch.object(
                window, "_read_preset_to_copy", new_callable=AsyncMock,
                return_value=read_result,
            ) as mock_read,
            patch.object(
                window, "_do_copy_preset_to_device", new_callable=AsyncMock
            ) as mock_copy,
        ):
            import asyncio

            asyncio.run(
                window._do_copy_presets_batch_multi(items, devices, "wifi")
            )
            assert mock_read.call_count == 2
            assert mock_copy.call_count == 4
            # _do_copy_preset_to_device(preset_name, preset_type, target_ip, target_source, ...)
            calls = [(c.args[0], c.args[2]) for c in mock_copy.call_args_list]
            assert calls == [
                ("Preset1", "192.168.1.201"),
                ("Preset1", "192.168.1.202"),
                ("Preset2", "192.168.1.201"),
                ("Preset2", "192.168.1.202"),
            ]


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

        filters = [_make_filter(100)]
        peq_settings = MagicMock(channel_mode="stereo", bands=filters)
        read_result = (filters, ChannelMode.STEREO, peq_settings)

        with (
            patch.object(
                window, "_read_preset_to_copy", new_callable=AsyncMock,
                return_value=read_result,
            ),
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
        # Simulate a RoomFit profile that is L/R
        peq_settings = MagicMock()
        peq_settings.channel_mode = "lr"
        peq_settings.bands_l = [_make_filter(100)]
        peq_settings.bands_r = [_make_filter(200)]
        peq_settings.bands = []

        # Mock the target device connection
        with (
            patch("src.gui.main_window.WiiMHttpClient") as mock_client_cls,
            patch("src.gui.main_window.CapabilityProber") as mock_prober_cls,
            patch("src.gui.main_window.WiiMAdapter") as mock_adapter_cls,
            patch("src.gui.main_window.RoomFitSafeWrite") as mock_roomfit_safe_write_cls,
        ):
            mock_client = AsyncMock()
            mock_client_cls.return_value = mock_client
            mock_prober = AsyncMock()
            mock_prober.probe = AsyncMock(return_value=_make_caps())
            mock_prober_cls.return_value = mock_prober
            mock_target_adapter = AsyncMock()
            mock_adapter_cls.return_value = mock_target_adapter

            roomfit_safe_write = MagicMock()
            roomfit_safe_write.execute = AsyncMock(return_value=WriteResult(success=True))
            mock_roomfit_safe_write_cls.return_value = roomfit_safe_write

            import asyncio

            asyncio.run(
                window._do_copy_preset_to_device(
                    "My RoomFit", "RoomFit", "192.168.1.200", "wifi",
                    peq_settings.bands_l + peq_settings.bands_r,
                    ChannelMode.LR, peq_settings,
                )
            )
            # RoomFit copy is verified via RoomFitSafeWrite (smoke #153),
            # not a bare write_roomfit() call -- assert the L/R channel mode
            # is passed through to its execute() call.
            roomfit_safe_write.execute.assert_called_once()
            call_kwargs = roomfit_safe_write.execute.call_args
            assert call_kwargs.kwargs.get("channel_mode") == ChannelMode.LR

    # --- Issue #85: Diagnostics raw_command_requested connected ---

    def test_issue85_diagnostics_raw_command_connected(self, window) -> None:
        """#85: Diagnostics raw command signal triggers async command
        execution and actually reaches the adapter with the exact command
        string requested -- not just "some coroutine got run"."""
        mock_adapter = _setup_device(window)
        mock_adapter.raw_command = AsyncMock(return_value={"foo": "bar"})

        def _run_now(coro: object) -> None:
            import asyncio

            asyncio.run(coro)

        with patch.object(window._bridge, "run_async", side_effect=_run_now) as mock_run:
            window._diagnostics_panel.raw_command_requested.emit("getStatusEx")

        assert mock_run.call_count == 1
        mock_adapter.raw_command.assert_called_once_with("getStatusEx")

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

    # --- Issue #64: shared_helpers.py is the single source of truth ---

    def test_issue64_shared_helpers_created(self) -> None:
        """#64: src/gui/shared_helpers.py exports the documented shared
        functions, and main_window.py (which still needs channel-mode/
        profile logic directly) imports from it rather than reimplementing
        it locally.

        Behavior-level coverage of each individual function already exists
        elsewhere in this file (is_lr_mode, build_profile, build_peq_settings,
        parse_backup_filters, get_lr_filters tests above); this test is
        specifically about the "single source of truth" claim: that the
        module exists with the right surface and that call-sites import
        from it instead of duplicating the logic inline.
        """
        import inspect

        from src.gui import main_window, secondary_workflows, shared_helpers

        # The documented shared surface (get_lr_filters, is_lr_mode,
        # build_peq_settings, build_profile, parse_backup_filters) plus the
        # closely related helpers that grew out of the same consolidation
        # (extract_filters, load_backup_json, validate_filters_for_device).
        for name in (
            "get_lr_filters",
            "is_lr_mode",
            "build_peq_settings",
            "build_profile",
            "parse_backup_filters",
            "extract_filters",
            "load_backup_json",
            "validate_filters_for_device",
        ):
            assert hasattr(shared_helpers, name), f"shared_helpers missing {name}"
            assert callable(getattr(shared_helpers, name))

        # main_window.py imports from shared_helpers rather than defining its
        # own local copies of the same logic.
        main_window_source = inspect.getsource(main_window)
        assert "from src.gui.shared_helpers import" in main_window_source

        # secondary_workflows.py legitimately has no shared_helpers import
        # now (PEQ redesign, mirrors #191): _do_undo() delegates backup
        # parsing and PEQSettings reconstruction entirely to
        # SafeWrite.undo() rather than calling build_peq_settings()/
        # parse_backup_filters() locally -- zero shared_helpers usage here
        # is the correct outcome of that delegation, not reimplementation.
        # Assert the delegation instead: no local re-parsing logic
        # duplicating what SafeWrite.undo() now owns.
        secondary_workflows_source = inspect.getsource(secondary_workflows)
        for reimplemented_name in (
            "build_peq_settings", "parse_backup_filters", "load_backup_json",
        ):
            assert f"def {reimplemented_name}(" not in secondary_workflows_source
        assert "safe_write.undo(" in secondary_workflows_source

        # Spot-check: no duplicate local reimplementation of is_lr_mode's
        # channel-string matching (the specific bug pattern smoke #55/#69
        # were about) anywhere outside shared_helpers.py itself.
        assert "def is_lr_mode" not in main_window_source
        assert "def is_lr_mode" not in secondary_workflows_source
        assert inspect.getsourcefile(shared_helpers.is_lr_mode) == inspect.getsourcefile(
            shared_helpers
        )

    # --- Issue #93: Ensure filter values are rounded to expected precision ---

    def test_issue93_rew_generator_rounding(self, tmp_path: Path) -> None:
        """#93: REWGenerator rounds values for WiiM compatibility."""
        from src.translator.rew_generator import REWGenerator
        generator = REWGenerator()
        out = tmp_path / "test_rounding.txt"

        filters = [
            CanonicalFilter(type="PEAK", frequency_hz=123.4567, gain_db=-3.5555, q=1.41421356)
        ]

        generator.generate_file(filters, out)
        content = out.read_text()

        # Freq: 8.2f (123.46), Gain: 6.2f (-3.56), Q: .3f (1.414)
        assert "Fc   123.46 Hz" in content
        assert "Gain  -3.56 dB" in content
        assert "Q  1.414" in content

    # --- Issue #92: L/R filtering logic ---

    def test_issue92_lr_filter_splitting(self, window) -> None:
        """#92: Explicit L/R bands are stored in wizard state without naive re-splitting."""
        _setup_device(window)
        state = window._wizard_controller.state
        filters_l = [_make_filter(100)]
        filters_r = [_make_filter(200), _make_filter(300)]
        state.current_filters = filters_l + filters_r
        state.channel_mode = ChannelMode.LR

        peq_data = MagicMock(
            channel_mode="lr",
            bands_l=filters_l,
            bands_r=filters_r,
        )

        with patch.object(window._review_page, "set_lr_filters") as mock_lr:
            window._on_peq_ready(peq_data)

        assert state.filters_l == filters_l
        assert state.filters_r == filters_r
        assert state.current_filters == filters_l + filters_r
        mock_lr.assert_called_once_with(
            filters_l, filters_r, {}, {}, filters_l, filters_r, {}, {}
        )

    def test_on_peq_ready_lr_without_explicit_bands_shows_error_and_returns(
        self, window
    ) -> None:
        """_on_peq_ready's L/R-without-bands guard shows an error banner and
        returns without advancing the wizard, rather than guessing a
        channel split (Phase 5 _validate_and_populate_review decomposition
        -- this is the guard's `return None` path)."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter(100)]
        state.channel_mode = ChannelMode.LR

        with (
            patch.object(window._status_banner, "show_error") as mock_error,
            patch.object(window._wizard_controller, "advance") as mock_advance,
        ):
            window._on_peq_ready(object())

        mock_error.assert_called_once_with(
            "Could not determine L/R channel data for this source"
        )
        mock_advance.assert_not_called()

    def test_build_peq_settings_lr_without_explicit_filters_raises(self) -> None:
        """L/R mode without filters_l/filters_r must raise, never guess a split."""
        from src.gui.shared_helpers import build_peq_settings

        filters = [_make_filter(100 * (i + 1)) for i in range(5)]
        with pytest.raises(ValueError, match="refusing to guess channel split"):
            build_peq_settings("wifi", filters, "L/R")

    def test_get_lr_filters_without_state_data_raises(self) -> None:
        """get_lr_filters must raise when wizard state has no filters_l/filters_r."""
        from src.gui.shared_helpers import get_lr_filters

        state = MagicMock()
        state.filters_l = None
        state.filters_r = None
        with pytest.raises(ValueError, match="refusing to guess channel split"):
            get_lr_filters(state, [])

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

    def test_build_profile_lr_without_explicit_filters_raises(self) -> None:
        """build_profile with L/R but no filters_l/filters_r must raise."""
        filters = [_make_filter(100), _make_filter(200)]
        with pytest.raises(ValueError, match="refusing to guess channel split"):
            build_profile("Test", filters, "L/R")

    def test_build_profile_lr_with_explicit_filters_preserves_split(self) -> None:
        """build_profile with explicit filters_l/filters_r uses them as-is."""
        filters = [_make_filter(100), _make_filter(200), _make_filter(300)]
        filters_l = filters[:1]
        filters_r = filters[1:]
        profile = build_profile(
            "Test", filters, "L/R", filters_l=filters_l, filters_r=filters_r
        )
        assert profile.filters_l == filters_l
        assert profile.filters_r == filters_r

    def test_build_profile_stereo_keeps_filters(self) -> None:
        """build_profile with Stereo keeps filters in single list."""
        filters = [_make_filter(100), _make_filter(200)]
        profile = build_profile("Test", filters, "Stereo")
        assert profile.filters is not None
        assert len(profile.filters) == 2

    # --- read_preset_preview ---

    @pytest.mark.asyncio
    async def test_read_preset_preview_roomfit_dispatches_to_roomfit_read(self) -> None:
        """preset_type=='RoomFit' dispatches to read_roomfit_preset_preview."""
        settings = PEQSettings(source_name="wifi", channel_mode=ChannelMode.STEREO, bands=[])
        adapter = MagicMock(
            read_roomfit_preset_preview=AsyncMock(return_value=settings),
            read_peq_preset_preview=AsyncMock(),
        )

        result = await read_preset_preview(adapter, "RoomFit", "wifi", "Living Room")

        assert result is settings
        adapter.read_roomfit_preset_preview.assert_awaited_once_with("wifi", "Living Room")
        adapter.read_peq_preset_preview.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_read_preset_preview_peq_dispatches_to_peq_read(self) -> None:
        """preset_type=='PEQ' (or anything else) dispatches to read_peq_preset_preview."""
        settings = PEQSettings(source_name="wifi", channel_mode=ChannelMode.STEREO, bands=[])
        adapter = MagicMock(
            read_roomfit_preset_preview=AsyncMock(),
            read_peq_preset_preview=AsyncMock(return_value=settings),
        )

        result = await read_preset_preview(adapter, "PEQ", "wifi", "Movie Night")

        assert result is settings
        adapter.read_peq_preset_preview.assert_awaited_once_with("wifi", "Movie Night")
        adapter.read_roomfit_preset_preview.assert_not_awaited()

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
        filters, mode, filters_l, filters_r = parse_backup_filters(backup)
        assert mode == ChannelMode.LR
        assert len(filters) == 2
        assert filters_l is not None and filters_r is not None


class TestIssue194SingleSourceOperations:
    """#194: single-source device operations must never receive the raw
    comma-joined multi-select string as source_name.

    The WiiM API silently stores a permanent junk slot for ANY source_name
    string it receives -- comma-joined selections like "wifi,bluetooth,auxIn"
    were found as real slots on hardware (docs/wiim_api_notes.md "Key rules";
    factory reset is the only removal). Every single-source flow must go
    through WizardState.primary_source, never state.selected_source raw.
    """

    @staticmethod
    def _preview_settings() -> PEQSettings:
        return PEQSettings(
            source_name="wifi",
            channel_mode=ChannelMode.STEREO,
            bands=[_make_filter()],
        )

    def test_issue194_load_peq_preset_uses_single_source(self, window) -> None:
        """Preset load with a multi-source selection targets the first source."""
        adapter = _setup_device(window)
        window._wizard_controller.state.selected_source = "wifi,bluetooth,auxIn"
        adapter.read_peq_preset_preview = AsyncMock(
            return_value=self._preview_settings()
        )

        import asyncio

        asyncio.run(window._primary_workflows._do_load_peq_preset("My Preset"))

        adapter.read_peq_preset_preview.assert_awaited_once_with("wifi", "My Preset")

    def test_issue194_device_pull_uses_single_source(self, window) -> None:
        """Device pull strips whitespace and uses only the first source."""
        adapter = _setup_device(window)
        window._wizard_controller.state.selected_source = "wifi, optical"
        adapter.read_peq = AsyncMock(return_value=self._preview_settings())

        import asyncio

        asyncio.run(window._primary_workflows._do_device_pull())

        adapter.read_peq.assert_awaited_once_with("wifi")

    def test_issue194_read_preset_to_copy_uses_single_source(self, window) -> None:
        """The shared copy-flow read uses the first selected source -- not a
        hardcoded 'wifi', and never the raw comma string."""
        adapter = _setup_device(window)
        window._wizard_controller.state.selected_source = "bluetooth,wifi"
        adapter.read_peq_preset_preview = AsyncMock(
            return_value=self._preview_settings()
        )

        import asyncio

        result = asyncio.run(window._read_preset_to_copy("My Preset", "PEQ"))

        assert result is not None
        adapter.read_peq_preset_preview.assert_awaited_once_with(
            "bluetooth", "My Preset"
        )
