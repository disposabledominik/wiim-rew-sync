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

from src.adapters.safe_write import RoomFitSafeWrite, SafeWrite, WriteResult
from src.gui.app_settings import AppSettings
from src.gui.main_window import MainWindow
from src.gui.views.presets_device_view import PresetItem
from src.gui.wizard_controller import FlowType, WizardStep
from src.models.canonical import CanonicalFilter
from src.models.channel_mode import ChannelMode
from src.models.errors import RoomFitUnsupportedError
from src.models.peq import PEQSettings
from src.models.profile import build_profile
from src.repository.backup_manager import parse_backup_filters
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

    async def _dispatch_preview(preset_type: str, source_name: str, preset_name: str):
        # Mirrors WiiMAdapter.read_preset_preview()'s real dispatch, against
        # whichever of read_roomfit_preset_preview/read_peq_preset_preview a
        # test configures below -- so tests only need to mock the one they
        # actually exercise, same as before this became a real adapter
        # method rather than a free function taking the adapter as its
        # first argument.
        if preset_type == "RoomFit":
            return await mock_adapter.read_roomfit_preset_preview(source_name, preset_name)
        return await mock_adapter.read_peq_preset_preview(source_name, preset_name)

    mock_adapter.read_preset_preview = AsyncMock(side_effect=_dispatch_preview)

    async def _dispatch_preview_or_live(
        preset_type: str, source_name: str, preset_name: str, *, is_custom: bool = False
    ):
        # Mirrors WiiMAdapter.read_preset_preview_or_live()'s real dispatch
        # (#165c) -- a plain read_peq() for the synthetic "Custom" item,
        # otherwise the same read_preset_preview() dispatch above.
        if is_custom:
            return await mock_adapter.read_peq(source_name)
        return await _dispatch_preview(preset_type, source_name, preset_name)

    mock_adapter.read_preset_preview_or_live = AsyncMock(side_effect=_dispatch_preview_or_live)
    window._wiim_adapter = mock_adapter
    window._primary_workflows.set_current_adapter(mock_adapter)
    # _do_undo_roomfit/_do_undo_multi_source now live on SecondaryWorkflowManager
    # (docs/backlog.md item 2, Phase D) and read self._current_adapter/
    # self._bridge there -- normally wired by the real (not exercised here)
    # _on_capabilities_ready -> SecondaryWorkflowManager.configure() call,
    # which this helper bypasses like it already does for PrimaryWorkflowManager.
    window._secondary_workflows._bridge = window._bridge
    window._secondary_workflows.set_current_adapter(mock_adapter)
    window._secondary_workflows._roomfit_safe_write_factory = (
        lambda adapter: RoomFitSafeWrite(adapter, window._backup_manager)
    )
    # _write_preset_copies_to_devices/_read_preset_to_copy (also Phase D)
    # need the same PEQ safe_write factory plus the 3 target-device
    # connection factories -- reuse MainWindow's real ones (default to
    # adapter_factories.make_*) so the existing
    # patch("src.gui.adapter_factories.<Class>") tests below keep working
    # unchanged; only the SafeWrite/RoomFitSafeWrite factories need
    # per-test overrides since those wrap window._backup_manager directly.
    window._secondary_workflows._safe_write_factory = (
        lambda adapter: SafeWrite(adapter, window._backup_manager)
    )
    window._secondary_workflows._wiim_http_client_factory = (
        window._wiim_http_client_factory
    )
    window._secondary_workflows._capability_prober_factory = (
        window._capability_prober_factory
    )
    window._secondary_workflows._target_adapter_factory = window._wiim_adapter_factory
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

    def test_on_peq_ready_invalidates_stale_review_on_filter_change(
        self, window
    ) -> None:
        """Regression: the FILTERS change-detection originally added for
        _on_filters_accepted (browsing back and re-confirming a different
        filter set clears stale Review/Push checkmarks; that method was
        later removed entirely, see docs/smoke_test_issues.md #274) must
        also apply to the device-pull/file-import path, which is the common
        case and previously bypassed it entirely -- _on_peq_ready called
        advance() directly with no invalidation, so this is the only test
        exercising that path's checkmark behavior end to end."""
        _setup_device(window)
        wc = window._wizard_controller
        state = wc.state
        wc.state.current_step = WizardStep.FILTERS

        state.current_filters = [_make_filter(100)]
        state.channel_mode = ChannelMode.STEREO
        peq_data_a = MagicMock(channel_mode="stereo", bands_l=None, bands_r=None)
        window._on_peq_ready(peq_data_a)  # FILTERS done, at REVIEW
        wc.advance(summary="Reviewed")  # REVIEW done, at PUSH

        # Browse back, pull a DIFFERENT filter set -- Review must clear.
        wc.go_to_step(WizardStep.FILTERS)
        state.current_filters = [_make_filter(200)]
        peq_data_b = MagicMock(channel_mode="stereo", bands_l=None, bands_r=None)
        window._on_peq_ready(peq_data_b)

        assert WizardStep.REVIEW not in wc.completed_steps
        assert WizardStep.FILTERS in wc.completed_steps

    def test_on_profile_recalled_invalidates_stale_review_on_filter_change(
        self, window
    ) -> None:
        """Same regression as above, for the Local Library recall path
        (_on_profile_recalled), which also called advance() directly with
        no invalidation."""
        _setup_device(window)
        wc = window._wizard_controller
        wc.state.current_step = WizardStep.FILTERS

        window._on_profile_recalled([_make_filter(100)], "Preset A")
        wc.advance(summary="Reviewed")  # REVIEW done, at PUSH

        wc.go_to_step(WizardStep.FILTERS)
        window._on_profile_recalled([_make_filter(200)], "Preset B")

        assert WizardStep.REVIEW not in wc.completed_steps
        assert WizardStep.FILTERS in wc.completed_steps

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
        _write_preset_to_adapter(), which is the current live multi-device
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
        # _read_preset_to_copy now reads via read_peq_preset_preview (#166)
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
            patch("src.gui.adapter_factories.WiiMHttpClient"),
            patch("src.gui.adapter_factories.CapabilityProber") as mock_prober_cls,
            patch("src.gui.adapter_factories.WiiMAdapter") as mock_adapter_cls,
        ):
            mock_prober = MagicMock()
            mock_prober.probe = AsyncMock(return_value=_make_caps())
            mock_prober_cls.return_value = mock_prober

            target_adapter = MagicMock()
            target_adapter.save_peq_profile = AsyncMock()
            # Unset (not a real DeviceCapabilities) -- explicitly None so the
            # find_unsupported_filter_types() gate treats it as "no
            # restriction" rather than a MagicMock's default empty __iter__,
            # which would make every real filter type look unsupported.
            target_adapter.capabilities.supported_filter_types = None
            mock_adapter_cls.return_value = target_adapter

            mock_target_client = MagicMock()
            mock_target_client.close = AsyncMock()

            safe_write = MagicMock()
            safe_write.execute = AsyncMock(return_value=WriteResult(success=True))
            window._secondary_workflows._safe_write_factory = lambda adapter: safe_write

            import asyncio

            with patch("src.gui.adapter_factories.WiiMHttpClient", return_value=mock_target_client):
                asyncio.run(
                    window._secondary_workflows._do_copy_presets_batch_multi(
                        items, [device1, device2], "wifi", "wifi"
                    )
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
        # get_lr_filters() requires explicit, non-empty filters_l/filters_r
        # for L/R mode (never guesses a split) -- see
        # src.models.channel_mode.require_lr_filters.
        state.filters_l = [_make_filter(100)]
        state.filters_r = [_make_filter(200)]
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
        window._primary_workflows._roomfit_safe_write_factory = (
            lambda adapter: RoomFitSafeWrite(adapter, mock_backup)
        )

        # _do_push is a coroutine; we verify write_roomfit gets channel_mode
        import asyncio

        asyncio.run(window._primary_workflows._do_push())
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
        window._primary_workflows._safe_write_factory = lambda adapter: mock_safe_write

        import asyncio

        asyncio.run(window._primary_workflows._do_push())
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
        window._primary_workflows._safe_write_factory = lambda adapter: mock_safe_write

        import asyncio

        asyncio.run(window._primary_workflows._do_push())

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
        window._primary_workflows._roomfit_safe_write_factory = (
            lambda adapter: mock_roomfit_safe_write
        )

        import asyncio

        asyncio.run(window._primary_workflows._do_push())

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

    def test_roomfit_dry_run_summary_omits_stale_source(self, window) -> None:
        """RoomFit dry-run summary must not name a source: RoomFit applies
        globally, not per-source (CLAUDE.md), and selected_sources can still
        hold values left over from an earlier PEQ run on the same session.
        """
        _setup_device(window)
        state = window._wizard_controller.state
        state.flow_type = FlowType.ROOMFIT
        state.current_filters = [_make_filter()]
        state.channel_mode = ChannelMode.STEREO
        state.dry_run = True
        # Stale sources left behind by a previous PEQ run in this session.
        state.selected_sources = ["wifi", "bluetooth", "auxIn"]
        window._wizard_controller.state.current_step = WizardStep.REVIEW

        with (
            patch.object(window._push_page, "set_dry_run_result") as mock_dry,
            patch.object(window._wizard_controller, "advance"),
        ):
            window._on_push_requested()

        summary = mock_dry.call_args[0][0]
        assert "wifi" not in summary
        assert "bluetooth" not in summary
        assert "auxIn" not in summary
        assert "bands validated" in summary


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

    def test_export_lr_with_empty_channel_shows_error_not_crash(
        self, window, tmp_path
    ) -> None:
        """require_lr_filters() rejects an empty (not just missing) channel
        (ca14e26); _export_filters_as_rew must show an error banner for
        that ValueError, not let it escape uncaught out of the Qt slot
        (branch-quality review, 2026-07-18)."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.filters_l = []
        state.filters_r = [_make_filter(200, gain=-4.0)]
        state.channel_mode = ChannelMode.LR

        path_l = tmp_path / "export_L.txt"
        path_r = tmp_path / "export_R.txt"

        with (
            patch(
                "src.gui.dialogs.export_dialog.ExportDialog.get_paths",
                return_value=(path_l, path_r),
            ),
            patch.object(window._status_banner, "show_error") as mock_error,
            patch.object(window._primary_workflows, "export_file_lr") as mock_export,
        ):
            window._export_filters_as_rew(state.current_filters, "L/R")

        mock_export.assert_not_called()
        mock_error.assert_called_once()
        assert "Export failed" in mock_error.call_args[0][0]
        assert not path_l.exists()
        assert not path_r.exists()

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

        def _run_now(coro: object, **_kwargs: object) -> None:
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
        window._wizard_controller._flow_type = FlowType.PEQ

        profile = MagicMock()
        profile.name = "My LR Preset"
        profile.channel_mode = "left"  # L/R profiles stored as "left"
        profile.filters_l = [_make_filter(100)]
        profile.filters_r = [_make_filter(200)]
        profile.filters = None

        with patch.object(window._secondary_workflows, "recall_profile"):
            window._on_local_profile_selected(profile)

        assert state.channel_mode == ChannelMode.LR

    def test_issue65_profile_load_sets_channel_mode_stereo(self, window) -> None:
        """#65: Loading stereo profile sets state.channel_mode to Stereo."""
        _setup_device(window)
        state = window._wizard_controller.state
        state.current_filters = [_make_filter()]
        window._wizard_controller._flow_type = FlowType.PEQ

        profile = MagicMock()
        profile.name = "My Stereo Preset"
        profile.channel_mode = "stereo"
        profile.filters = [_make_filter()]

        with patch.object(window._secondary_workflows, "recall_profile"):
            window._on_local_profile_selected(profile)

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

        from src.models.channel_mode import ChannelMode
        from src.models.peq import PEQSettings

        mock_adapter = _setup_device(window)
        mock_adapter.list_peq_profiles = AsyncMock(
            return_value=[{"Name": "Movie Night", "channelMode": "Stereo"}]
        )
        mock_adapter.list_roomfit_profiles = AsyncMock(
            return_value=[{"Name": "Living Room", "channelMode": "Stereo"}]
        )
        # Also mock the active-name reads -- without these, they raise on
        # the plain (non-AsyncMock) adapter attribute, degrading to "",
        # which would add a synthetic "Custom" row (#165c) and throw off
        # this test's count assertions, which aren't about that behavior.
        mock_adapter.read_peq = AsyncMock(
            return_value=PEQSettings(
                source_name="wifi", channel_mode=ChannelMode.STEREO, name="Movie Night"
            )
        )
        mock_adapter.get_roomfit_status = AsyncMock(return_value=(True, "Living Room"))

        def _run_now(coro: object, **_kwargs: object) -> None:
            asyncio.run(coro)

        with patch.object(window._bridge, "run_async", side_effect=_run_now):
            window._on_navigation_requested("presets_device")

        assert window._presets_device_view._peq_list.count() == 1
        assert window._presets_device_view._roomfit_list.count() == 1

    # --- Code-review round (2026-08-06): unavailable/hidden forwarding ---

    def test_peq_presets_unavailable_forwards_to_both_views(self, window) -> None:
        """_on_peq_presets_unavailable must clear FiltersPage's Device panel
        too, not just PresetsDeviceView -- both are consumers of
        PrimaryWorkflowManager.peq_presets_unavailable, and before this fix
        only PresetsDeviceView was kept in sync."""
        window._filters_page.set_peq_presets(
            [PresetItem(name="Preset A", channel_mode="Stereo", preset_type="PEQ")],
            active_name="Preset A",
        )
        assert window._filters_page._device_peq.items != []

        window._on_peq_presets_unavailable()

        assert window._filters_page._device_peq.items == []
        assert window._presets_device_view._peq_items == []

    def test_roomfit_profiles_hidden_forwards_to_both_views(self, window) -> None:
        """_on_roomfit_profiles_hidden must clear FiltersPage's Device panel
        too, not just PresetsDeviceView -- same gap as
        test_peq_presets_unavailable_forwards_to_both_views, for RoomFit."""
        window._filters_page.set_roomfit_profiles(
            [PresetItem(name="Profile A", channel_mode="Stereo", preset_type="RoomFit")],
            active_name="Profile A",
        )
        assert window._filters_page._device_roomfit.items != []

        window._on_roomfit_profiles_hidden()

        assert window._filters_page._device_roomfit.items == []
        assert window._presets_device_view._roomfit_items == []

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
        it just means no highlight for that section.

        The PEQ side degrades to None (unknown), not "" (confirmed no
        active preset) -- "" would incorrectly show a synthetic "Custom"
        row for a read that never actually confirmed anything. RoomFit has
        no such row concept, so it keeps degrading to "" (no highlight)."""
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
        assert mock_set_peq.call_args[0][1] is None
        assert len(mock_set_roomfit.call_args[0][0]) == 1
        assert mock_set_roomfit.call_args[0][1] == ""

    # --- "Current configuration on device" button removal: the synthetic
    # "Custom" row now covers devices without profile-enumeration support
    # too, gated on supports_peq instead ---

    def test_no_peq_support_emits_unavailable_without_listing(self, window) -> None:
        """supports_peq=False skips both list_peq_profiles() and the
        active-config read entirely -- there's nothing to show."""
        import asyncio

        mock_adapter = _setup_device(window)
        mock_adapter.capabilities.supports_peq = False
        mock_adapter.list_peq_profiles = AsyncMock(return_value=[])
        mock_adapter.read_peq = AsyncMock()
        mock_adapter.list_roomfit_profiles = AsyncMock(return_value=[])
        mock_adapter.get_roomfit_status = AsyncMock(return_value=(False, ""))

        with patch.object(window._presets_device_view, "set_peq_unavailable") as mock_unavail:
            asyncio.run(window._primary_workflows.refresh_presets())

        mock_unavail.assert_called_once()
        mock_adapter.list_peq_profiles.assert_not_called()
        mock_adapter.read_peq.assert_not_called()

    def test_no_enumeration_but_peq_supported_shows_custom_row(self, window) -> None:
        """supports_peq=True + supports_profile_enumeration=False: no named
        list, but the live config still surfaces as a synthetic "Custom"
        row via a plain read_peq() -- this is what replaces the old
        dedicated "Current configuration on device" button for such
        devices."""
        import asyncio

        from src.models.channel_mode import ChannelMode
        from src.models.peq import PEQSettings

        mock_adapter = _setup_device(window)
        mock_adapter.capabilities.supports_peq = True
        mock_adapter.capabilities.supports_profile_enumeration = False
        mock_adapter.list_peq_profiles = AsyncMock(return_value=[])
        mock_adapter.read_peq = AsyncMock(
            return_value=PEQSettings(source_name="wifi", channel_mode=ChannelMode.LR, name="")
        )

        with patch.object(window._presets_device_view, "set_peq_presets") as mock_set_peq:
            asyncio.run(window._primary_workflows.refresh_presets())

        mock_adapter.list_peq_profiles.assert_not_called()
        mock_set_peq.assert_called_once()
        assert mock_set_peq.call_args[0][0] == []
        assert mock_set_peq.call_args[0][1] == ""
        assert mock_set_peq.call_args[0][2] == "L/R"

    def test_no_enumeration_and_read_fails_emits_unavailable(self, window) -> None:
        """supports_peq=True + supports_profile_enumeration=False, but the
        live-config read itself fails: nothing confirmed to show, same
        outcome as no PEQ support at all -- not a "Custom" row with no
        actual data behind it."""
        import asyncio

        mock_adapter = _setup_device(window)
        mock_adapter.capabilities.supports_peq = True
        mock_adapter.capabilities.supports_profile_enumeration = False
        mock_adapter.list_peq_profiles = AsyncMock(return_value=[])
        mock_adapter.read_peq = AsyncMock(side_effect=RuntimeError("boom"))

        with (
            patch.object(window._presets_device_view, "set_peq_unavailable") as mock_unavail,
            patch.object(window._presets_device_view, "set_peq_presets") as mock_set_peq,
        ):
            asyncio.run(window._primary_workflows.refresh_presets())

        mock_adapter.list_peq_profiles.assert_not_called()
        mock_unavail.assert_called_once()
        mock_set_peq.assert_not_called()

    def test_no_enumeration_with_named_live_config_still_shows_a_row(self, window) -> None:
        """QA-reported bug: a device without profile enumeration (e.g. WiiM
        Mini with `supports_profile_enumeration: false`) whose live PEQ
        config already has a real device-assigned Name (not "") produced an
        empty preset list in both "Presets on Device" and the Filters
        step's Device panel -- only active_name == "" ever produced a row,
        so a *named* live config on such a device was invisible everywhere,
        contradicting qa_signoff.md Test 12a ("Custom is the only PEQ row
        shown" on an enumeration-unsupported device). The live config must
        always surface as a row on such a device, real name included, since
        there's no enumerated list to compare it against in the first
        place."""
        import asyncio

        from src.models.channel_mode import ChannelMode
        from src.models.peq import PEQSettings

        mock_adapter = _setup_device(window)
        mock_adapter.capabilities.supports_peq = True
        mock_adapter.capabilities.supports_profile_enumeration = False
        mock_adapter.list_peq_profiles = AsyncMock(return_value=[])
        mock_adapter.read_peq = AsyncMock(
            return_value=PEQSettings(
                source_name="wifi", channel_mode=ChannelMode.STEREO, name="Movie Night"
            )
        )

        asyncio.run(window._primary_workflows.refresh_presets())

        assert window._presets_device_view._peq_list.count() == 1
        assert window._presets_device_view._peq_list.item(0).text().startswith("Movie Night")
        assert window._filters_page._device_list.count() == 1
        assert window._filters_page._device_list.item(0).text().startswith("Movie Night")

    def test_load_device_presets_fetches_roomfit_without_enumeration(self, window) -> None:
        """_load_device_presets() must not skip the RoomFit fetch just
        because PEQ profile enumeration is unsupported -- the two are
        independent capabilities (a stale early-return used to bail out of
        the whole method, silently dropping RoomFit too)."""
        mock_adapter = _setup_device(window)
        mock_adapter.capabilities.supports_profile_enumeration = False

        with patch.object(window._primary_workflows, "list_presets") as mock_list:
            window._load_device_presets()

        mock_list.assert_called_once()

    # --- EQ-off qualifier: "(active)" alone claims a config is actually
    # being applied, but the device reports a Name/selected-profile
    # independent of the PEQ/RoomFit on-off toggle for that scope ---

    def test_peq_off_forwards_enabled_false_to_both_views(self, window) -> None:
        """A source with PEQ toggled off (EQStat: Off) still has a Name, but
        peq_presets_ready's enabled flag must reflect the real off state so
        both views can qualify the active row as "(active, PEQ off)"."""
        import asyncio

        from src.models.channel_mode import ChannelMode
        from src.models.peq import PEQSettings

        mock_adapter = _setup_device(window)
        mock_adapter.list_peq_profiles = AsyncMock(
            return_value=[{"Name": "Movie Night", "channelMode": "Stereo"}]
        )
        mock_adapter.read_peq = AsyncMock(
            return_value=PEQSettings(
                source_name="wifi",
                channel_mode=ChannelMode.STEREO,
                name="Movie Night",
                enabled=False,
            )
        )
        mock_adapter.list_roomfit_profiles = AsyncMock(return_value=[])
        mock_adapter.get_roomfit_status = AsyncMock(return_value=(True, ""))

        with patch.object(window._presets_device_view, "set_peq_presets") as mock_set_peq:
            asyncio.run(window._primary_workflows.refresh_presets())

        mock_set_peq.assert_called_once()
        assert mock_set_peq.call_args[0][1] == "Movie Night"
        assert mock_set_peq.call_args[0][3] is False

    def test_roomfit_off_forwards_enabled_false_to_both_views(self, window) -> None:
        """RoomFit toggled off globally (EQStat: Off) still reports a
        selected profile name -- roomfit_profiles_ready's enabled flag must
        carry the real off state through to the "(active, RoomFit off)"
        qualifier."""
        import asyncio

        mock_adapter = _setup_device(window)
        mock_adapter.list_peq_profiles = AsyncMock(return_value=[])
        mock_adapter.read_peq = AsyncMock(side_effect=RuntimeError("no peq"))
        mock_adapter.list_roomfit_profiles = AsyncMock(
            return_value=[{"Name": "Living Room", "channelMode": "Stereo"}]
        )
        mock_adapter.get_roomfit_status = AsyncMock(return_value=(False, "Living Room"))

        with patch.object(window._presets_device_view, "set_roomfit_profiles") as mock_set_rf:
            asyncio.run(window._primary_workflows.refresh_presets())

        mock_set_rf.assert_called_once()
        assert mock_set_rf.call_args[0][1] == "Living Room"
        assert mock_set_rf.call_args[0][2] is False

    def test_peq_and_roomfit_enabled_default_true(self, window) -> None:
        """The common case (EQStat: On) forwards enabled=True through both
        signals -- no qualifier shown, matching pre-existing behavior."""
        import asyncio

        from src.models.channel_mode import ChannelMode
        from src.models.peq import PEQSettings

        mock_adapter = _setup_device(window)
        mock_adapter.list_peq_profiles = AsyncMock(
            return_value=[{"Name": "Movie Night", "channelMode": "Stereo"}]
        )
        mock_adapter.read_peq = AsyncMock(
            return_value=PEQSettings(
                source_name="wifi",
                channel_mode=ChannelMode.STEREO,
                name="Movie Night",
                enabled=True,
            )
        )
        mock_adapter.list_roomfit_profiles = AsyncMock(
            return_value=[{"Name": "Living Room", "channelMode": "Stereo"}]
        )
        mock_adapter.get_roomfit_status = AsyncMock(return_value=(True, "Living Room"))

        with (
            patch.object(window._presets_device_view, "set_peq_presets") as mock_set_peq,
            patch.object(window._presets_device_view, "set_roomfit_profiles") as mock_set_rf,
        ):
            asyncio.run(window._primary_workflows.refresh_presets())

        assert mock_set_peq.call_args[0][3] is True
        assert mock_set_rf.call_args[0][2] is True

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
                window._primary_workflows, "export_presets"
            ) as mock_export_workflow,
            patch.object(window._status_banner, "show_progress") as mock_progress,
        ):
            window._presets_device_view.export_requested.emit([item])

        mock_progress.assert_called_once_with("Exporting 'Movie Night'...")
        mock_export_workflow.assert_called_once_with(
            [("Movie Night", "PEQ", "/tmp/movie-night.txt", False)]
        )

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
                window._primary_workflows, "save_presets"
            ) as mock_save_workflow,
            patch.object(window._status_banner, "show_progress") as mock_progress,
        ):
            window._presets_device_view.save_to_my_presets.emit([item])

        mock_progress.assert_called_once_with("Saving 'Movie Night' to My Presets...")
        mock_save_workflow.assert_called_once_with(
            [("Movie Night", "PEQ", "WiiM - Movie Night", False)]
        )

    # --- #165c: Export/Save/Copy on the synthetic "Custom" row ---

    def test_export_custom_item_reads_live_not_preview(self, window) -> None:
        """Exporting the synthetic "Custom" row passes is_custom=True through
        to export_presets -- and, since it's already live, skips the
        "this will briefly change what's playing" preview-warning dialog
        entirely (no WarningConfirmDialog call)."""
        item = PresetItem(
            name="Custom", channel_mode="Stereo", preset_type="PEQ", is_custom=True
        )

        with (
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm"
            ) as mock_warning,
            patch(
                "src.gui.main_window.QFileDialog.getSaveFileName",
                return_value=("/tmp/custom.txt", ""),
            ),
            patch.object(
                window._primary_workflows, "export_presets"
            ) as mock_export_workflow,
        ):
            window._presets_device_view.export_requested.emit([item])

        mock_warning.assert_not_called()
        mock_export_workflow.assert_called_once_with(
            [("Custom", "PEQ", "/tmp/custom.txt", True)]
        )

    def test_save_custom_item_reads_live_not_preview(self, window) -> None:
        """Saving the synthetic "Custom" row passes is_custom=True through to
        save_presets, and skips the preview-warning dialog the same way
        export does."""
        item = PresetItem(
            name="Custom", channel_mode="Stereo", preset_type="PEQ", is_custom=True
        )

        with (
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm"
            ) as mock_warning,
            patch.object(
                window._primary_workflows, "save_presets"
            ) as mock_save_workflow,
        ):
            window._presets_device_view.save_to_my_presets.emit([item])

        mock_warning.assert_not_called()
        mock_save_workflow.assert_called_once_with(
            [("Custom", "PEQ", "WiiM - Custom", True)]
        )

    # --- Multi-select Export/Save must process every item, not just the
    # first (pre-#165c-follow-up gap: the button enabled for a multi-select
    # but silently exported/saved only items[0]) ---

    def test_export_multiple_presets_uses_folder_picker_and_processes_all(
        self, window
    ) -> None:
        """Selecting 2+ presets and clicking Export picks one destination
        folder (not a per-item filename dialog), then exports every
        selected preset into it under its own device-prefixed filename."""
        items = [
            PresetItem(name="Preset A", channel_mode="Stereo", preset_type="PEQ"),
            PresetItem(name="Preset B", channel_mode="L/R", preset_type="PEQ"),
        ]

        with (
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
                return_value=True,
            ),
            patch(
                "src.gui.main_window.QFileDialog.getExistingDirectory",
                return_value="/tmp/exports",
            ) as mock_folder_dialog,
            patch.object(window._primary_workflows, "export_presets") as mock_export,
            patch.object(window._status_banner, "show_progress") as mock_progress,
        ):
            window._presets_device_view.export_requested.emit(items)

        mock_folder_dialog.assert_called_once()
        mock_progress.assert_called_once_with("Exporting 2 preset(s)...")
        mock_export.assert_called_once()
        requests = mock_export.call_args[0][0]
        assert requests == [
            ("Preset A", "PEQ", "/tmp/exports/WiiM - Preset A.txt", False),
            ("Preset B", "PEQ", "/tmp/exports/WiiM - Preset B.txt", False),
        ]

    def test_export_multiple_presets_cancelled_folder_picker_aborts(self, window) -> None:
        """Cancelling the destination-folder dialog aborts the whole batch
        export -- no dispatch at all, not a partial export."""
        items = [
            PresetItem(name="Preset A", channel_mode="Stereo", preset_type="PEQ"),
            PresetItem(name="Preset B", channel_mode="Stereo", preset_type="PEQ"),
        ]

        with (
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
                return_value=True,
            ),
            patch(
                "src.gui.main_window.QFileDialog.getExistingDirectory",
                return_value="",
            ),
            patch.object(window._primary_workflows, "export_presets") as mock_export,
        ):
            window._presets_device_view.export_requested.emit(items)

        mock_export.assert_not_called()

    def test_save_multiple_presets_processes_all(self, window) -> None:
        """Selecting 2+ presets and clicking Save to My Presets saves every
        one of them, not just the first -- no dialog needed, same as the
        single-item case."""
        items = [
            PresetItem(name="Preset A", channel_mode="Stereo", preset_type="PEQ"),
            PresetItem(name="Preset B", channel_mode="Stereo", preset_type="RoomFit"),
        ]

        with (
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
                return_value=True,
            ),
            patch.object(window._primary_workflows, "save_presets") as mock_save,
            patch.object(window._status_banner, "show_progress") as mock_progress,
        ):
            window._presets_device_view.save_to_my_presets.emit(items)

        mock_progress.assert_called_once_with("Saving 2 preset(s) to My Presets...")
        mock_save.assert_called_once_with(
            [
                ("Preset A", "PEQ", "WiiM - Preset A", False),
                ("Preset B", "RoomFit", "WiiM - Preset B", False),
            ]
        )

    def test_presets_export_complete_shows_success_and_partial_failure(
        self, window
    ) -> None:
        """_on_presets_export_complete forwards the batch result to the
        status banner, success or partial-failure."""
        with patch.object(window._status_banner, "show_success") as mock_success:
            window._on_presets_export_complete(2, 0)
        mock_success.assert_called_once_with("2 preset(s) exported")

        with patch.object(window._status_banner, "show_error") as mock_error:
            window._on_presets_export_complete(1, 1)
        mock_error.assert_called_once_with("Exported 1, 1 failed")

    def test_presets_save_complete_shows_success_and_partial_failure(self, window) -> None:
        """_on_presets_save_complete forwards the batch result to the
        status banner, success or partial-failure."""
        with patch.object(window._status_banner, "show_success") as mock_success:
            window._on_presets_save_complete(2, 0)
        mock_success.assert_called_once_with("2 preset(s) saved to My Presets")

        with patch.object(window._status_banner, "show_error") as mock_error:
            window._on_presets_save_complete(1, 1)
        mock_error.assert_called_once_with("Saved 1, 1 failed")

    def test_copy_custom_item_prompts_for_name_and_renames(self, window) -> None:
        """Copying the synthetic "Custom" row prompts for a real name (it
        isn't a device-assigned one, unlike every other copyable item) and
        passes the renamed item -- is_custom still True, so the source-side
        read stays a plain live read -- through to copy_presets_to_devices."""
        _setup_device(window)
        window._primary_workflows._discovered_devices = [
            MagicMock(ip="192.168.1.200", name="Other Device")
        ]
        item = PresetItem(
            name="Custom", channel_mode="Stereo", preset_type="PEQ", is_custom=True
        )

        with (
            patch(
                "src.gui.main_window.QInputDialog.getText",
                return_value=("Living Room Snapshot", True),
            ) as mock_prompt,
            patch(
                "src.gui.main_window.DevicePickerDialog.get_devices",
                return_value=[MagicMock(ip="192.168.1.200")],
            ),
            patch.object(
                window._secondary_workflows, "copy_presets_to_devices"
            ) as mock_copy,
        ):
            window._on_copy_to_device_requested([item])

        mock_prompt.assert_called_once()
        mock_copy.assert_called_once()
        copied_items = mock_copy.call_args[0][0]
        assert len(copied_items) == 1
        assert copied_items[0].name == "Living Room Snapshot"
        assert copied_items[0].is_custom is True

    def test_copy_custom_item_cancelled_prompt_aborts(self, window) -> None:
        """Cancelling the name prompt aborts the whole copy -- no device
        picker, no dispatch -- same "declined" contract as cancelling the
        device picker itself (#166)."""
        _setup_device(window)
        window._primary_workflows._discovered_devices = [
            MagicMock(ip="192.168.1.200", name="Other Device")
        ]
        item = PresetItem(
            name="Custom", channel_mode="Stereo", preset_type="PEQ", is_custom=True
        )

        with (
            patch(
                "src.gui.main_window.QInputDialog.getText", return_value=("", False)
            ),
            patch(
                "src.gui.main_window.DevicePickerDialog.get_devices"
            ) as mock_picker,
            patch.object(window._secondary_workflows, "copy_presets_to_devices") as mock_copy,
        ):
            window._on_copy_to_device_requested([item])

        mock_picker.assert_not_called()
        mock_copy.assert_not_called()

    def test_copy_named_presets_skip_name_prompt(self, window) -> None:
        """Copying ordinary named presets (no "Custom" row involved) never
        touches the name prompt -- regression guard for the #165c addition."""
        _setup_device(window)
        window._primary_workflows._discovered_devices = [
            MagicMock(ip="192.168.1.200", name="Other Device")
        ]
        item = PresetItem(name="Movie Night", channel_mode="Stereo", preset_type="PEQ")

        with (
            patch("src.gui.main_window.QInputDialog.getText") as mock_prompt,
            patch(
                "src.gui.main_window.DevicePickerDialog.get_devices",
                return_value=[MagicMock(ip="192.168.1.200")],
            ),
            patch.object(window._secondary_workflows, "copy_presets_to_devices") as mock_copy,
        ):
            window._on_copy_to_device_requested([item])

        mock_prompt.assert_not_called()
        mock_copy.assert_called_once()
        assert mock_copy.call_args[0][0] == [item]

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

    def test_issue24_filters_device_panel_load_connected(self, window) -> None:
        """#24 (superseded): device_item_selected triggers preset-load workflow.

        The old PresetsDeviceView "Load into Editor" signal this test used
        to target is gone -- loading a device preset now happens via the
        Filters step's merged Device panel, which emits device_item_selected
        instead."""
        _setup_device(window)
        item = PresetItem(name="Movie Night", channel_mode="Stereo", preset_type="PEQ")

        with (
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
                return_value=True,
            ),
            patch.object(
                window._primary_workflows, "_do_load_peq_preset", return_value=object()
            ) as mock_load_workflow,
            patch.object(window._status_banner, "show_progress") as mock_progress,
            patch.object(
                window._bridge, "run_async", side_effect=close_coroutine_tree
            ) as mock_run,
        ):
            window._filters_page.device_item_selected.emit(item)

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

    def test_local_preset_copy_dispatches_raw_profile_fields_to_manager(
        self, window
    ) -> None:
        """_on_local_preset_copy_to_device_requested passes each Profile's raw
        channel_mode/filters/filters_l/filters_r straight through to
        SecondaryWorkflowManager.copy_local_profiles_to_devices rather than
        building/validating a PEQSettings itself. Validating an incomplete
        L/R split (build_peq_settings()'s ValueError, require_lr_filters,
        ca14e26) is the manager's job now -- covered directly against
        _do_copy_local_profiles_to_devices in
        test_gui_integration_secondary.py, not here -- so MainWindow always
        dispatches regardless of whether the split is valid (branch-quality
        review, 2026-08-02: this used to validate synchronously in the Qt
        slot, which put business logic in main_window.py)."""
        _setup_device(window)
        window._primary_workflows._discovered_devices = [
            MagicMock(ip="192.168.1.200", name="Other Device")
        ]
        profile = MagicMock(
            name="Broken LR Profile",
            channel_mode=ChannelMode.LR,
            filters=None,
            filters_l=[],
            filters_r=[_make_filter(100)],
        )
        profile.name = "Broken LR Profile"

        with (
            patch(
                "src.gui.main_window.PresetTypeDialog.get_type", return_value="PEQ"
            ),
            patch(
                "src.gui.main_window.DevicePickerDialog.get_devices",
                return_value=[MagicMock(ip="192.168.1.200", name="Other Device")],
            ),
            patch.object(
                window._secondary_workflows, "copy_local_profiles_to_devices"
            ) as mock_copy,
            patch.object(window._status_banner, "show_error") as mock_error,
        ):
            window._on_local_preset_copy_to_device_requested([profile])

        mock_copy.assert_called_once()
        args = mock_copy.call_args[0]
        profiles_data = args[0]
        assert profiles_data == [
            ("Broken LR Profile", ChannelMode.LR, None, [], [_make_filter(100)])
        ]
        mock_error.assert_not_called()

    def test_local_preset_copy_batches_multiple_selected_profiles(
        self, window
    ) -> None:
        """Multi-select Copy to Another Device in My Saved Presets must send
        every selected profile through in a single batch call, not just the
        first -- regression coverage for the "Copy to Another Device greyed
        out under multi-select" report (the toolbar/context-menu now enable
        Copy for any selection of one or more presets, matching Presets on
        Device)."""
        _setup_device(window)
        window._primary_workflows._discovered_devices = [
            MagicMock(ip="192.168.1.200", name="Other Device")
        ]
        profile_a = MagicMock(
            name="Profile A",
            channel_mode=ChannelMode.STEREO,
            filters=[_make_filter(100)],
            filters_l=None,
            filters_r=None,
        )
        profile_a.name = "Profile A"
        profile_b = MagicMock(
            name="Profile B",
            channel_mode=ChannelMode.STEREO,
            filters=[_make_filter(200)],
            filters_l=None,
            filters_r=None,
        )
        profile_b.name = "Profile B"

        with (
            patch(
                "src.gui.main_window.PresetTypeDialog.get_type", return_value="PEQ"
            ),
            patch(
                "src.gui.main_window.DevicePickerDialog.get_devices",
                return_value=[MagicMock(ip="192.168.1.200", name="Other Device")],
            ),
            patch.object(
                window._secondary_workflows, "copy_local_profiles_to_devices"
            ) as mock_copy,
        ):
            window._on_local_preset_copy_to_device_requested([profile_a, profile_b])

        mock_copy.assert_called_once()
        profiles_data = mock_copy.call_args[0][0]
        assert profiles_data == [
            ("Profile A", ChannelMode.STEREO, [_make_filter(100)], None, None),
            ("Profile B", ChannelMode.STEREO, [_make_filter(200)], None, None),
        ]

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
            window._on_profile_delete_requested(["Movie Night"])

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
            window._on_profile_delete_requested(["Movie Night"])

        mock_delete.assert_not_called()

    def test_local_preset_batch_delete_deletes_all_and_refreshes_once(self, window) -> None:
        """Multi-select local delete runs every item through the shared
        _run_batch_profile_action helper and refreshes only once, not once
        per item."""
        with (
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
                return_value=True,
            ),
            patch.object(window._profile_repository, "delete") as mock_delete,
            patch.object(window, "_refresh_presets_view") as mock_refresh,
            patch.object(window._status_banner, "show_success") as mock_success,
        ):
            window._on_profile_delete_requested(["Movie Night", "Late Night"])

        assert mock_delete.call_count == 2
        mock_delete.assert_any_call("Movie Night")
        mock_delete.assert_any_call("Late Night")
        mock_refresh.assert_called_once()
        mock_success.assert_called_once_with("Deleted 2 presets")

    def test_local_preset_batch_delete_partial_failure_reports_counts(self, window) -> None:
        """One item failing (e.g. already removed by a concurrent change)
        doesn't abort the rest -- the batch still deletes what it can and
        reports succeeded/failed counts, refreshing regardless."""
        with (
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
                return_value=True,
            ),
            patch.object(
                window._profile_repository,
                "delete",
                side_effect=[None, KeyError("not found")],
            ) as mock_delete,
            patch.object(window, "_refresh_presets_view") as mock_refresh,
            patch.object(window._status_banner, "show_error") as mock_error,
        ):
            window._on_profile_delete_requested(["Movie Night", "Late Night"])

        assert mock_delete.call_count == 2
        mock_refresh.assert_called_once()
        mock_error.assert_called_once_with("Deleted 1 preset(s), 1 failed.")

    # --- Issue #27: RoomFit profile selection triggers read and advances ---

    def test_issue27_roomfit_profile_selected_triggers_pull(self, window) -> None:
        """#27: Selecting a RoomFit profile from the Device panel's merged
        list stores state and schedules a pull. Reached via
        device_item_selected now (the old dedicated roomfit-dropdown signal
        this test used to target was removed with the merged Device panel)."""
        _setup_device(window)
        scheduled: list[object] = []

        def _capture(coro: object, **_kwargs: object) -> None:
            scheduled.append(coro)

        item = PresetItem(name="My Profile", channel_mode="Stereo", preset_type="RoomFit")

        with (
            patch.object(window._bridge, "run_async", side_effect=_capture) as mock_run,
            patch.object(window._status_banner, "show_progress") as mock_progress,
        ):
            window._on_device_item_selected(item)

        assert window._wizard_controller.state.roomfit_profile_name == "My Profile"
        mock_progress.assert_called_once_with("Loading preset 'My Profile'...")
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
          same models.profile.build_profile() used by _save_filters_to_presets,
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

        from src.models.profile import build_profile as canonical_build_profile

        source = inspect.getsource(window._primary_workflows._do_preset_save)
        assert "build_profile(" in source
        assert canonical_build_profile.__module__ == "src.models.profile"

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
            "Clamped values rejected", "/tmp/backup.json", False, 0, True, 0
        )
        mock_show_error.assert_called_once_with("Push failed: Clamped values rejected")

    def test_write_complete_rollback_failure_shows_critical_ui(self, window) -> None:
        """_on_write_complete's `critical` flag (derived from
        result.rollback_success is False) must actually reach
        PushPage.set_failure(critical=True) -- the sibling case to
        test_issue121 above, which only ever exercised rollback_success=True.
        This closes the gap between PushPage.set_failure(critical=True)'s own
        unit test (test_gui_pages.py) and the MainWindow wiring that's
        supposed to trigger it for the "write AND rollback both failed"
        case design principle #1 (safety before convenience) depends on
        actually surfacing loudly."""
        _setup_device(window)
        result = WriteResult(
            success=False,
            rollback_success=False,
            backup_path="/tmp/backup.json",
            error_message="Write verification AND rollback failed. Manual recovery required.",
        )

        with (
            patch.object(window._push_page, "set_failure") as mock_set_failure,
            patch.object(window._status_banner, "show_error"),
        ):
            window._on_write_complete(result)

        mock_set_failure.assert_called_once_with(
            "Write verification AND rollback failed. Manual recovery required.",
            "/tmp/backup.json",
            True,
            0,
            True,
            0,
        )

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

        def _run_now(coro: object, **_kwargs: object) -> None:
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
        window._primary_workflows._roomfit_safe_write_factory = (
            lambda adapter: RoomFitSafeWrite(adapter, mock_backup)
        )

        import asyncio

        asyncio.run(window._primary_workflows._do_push())
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
        window._secondary_workflows._roomfit_safe_write_factory = (
            lambda adapter: RoomFitSafeWrite(adapter, mock_backup)
        )

        import asyncio

        with patch.object(window._status_banner, "show_success") as mock_success:
            asyncio.run(
                window._secondary_workflows._do_undo_roomfit(
                    str(backup_path), "wifi", "My Profile"
                )
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

    # --- _do_undo_multi_source characterization (pre-Phase-D extraction) ---
    #
    # No prior coverage existed for this method at all (confirmed via repo
    # grep). These tests originally pinned a latent race as a golden master:
    # self._secondary_workflows.undo_last_push() is synchronous and only
    # *schedules* the real restore via AsyncBridge.run_async(), returning
    # immediately -- the loop's own succeeded/failed tally and "All N
    # source(s) restored" summary banner reflected scheduling success, not
    # the actual per-source restore outcome.
    #
    # Update (branch-quality review, 2026-07-17): this method started
    # emitting its own dedicated undo_multi_source_complete(int, int, str)
    # signal instead of sharing undo_complete(bool, str) with the
    # single-source paths -- fixed a regression where a partial multi-source
    # undo (succeeded > 0, failed > 0) never cleared the pushed-filters
    # snapshot, since the shared signal's binary success flag couldn't
    # distinguish "should the banner say success" from "did anything
    # actually change." The scheduling-vs-outcome race itself remained,
    # visible on the new signal instead of the old one.
    #
    # Update (branch-quality review, 2026-07-18): the race itself is fixed.
    # _do_undo_multi_source now awaits each source's real restore via
    # restore_entries() (src/adapters/safe_write.py) instead of the
    # fire-and-forget undo_last_push(), so succeeded/failed reflects actual
    # per-source outcomes. Tests below mock restore_entries() (the real
    # awaited call, and the same shared restore-loop primitive
    # PrimaryWorkflowManager._do_push()'s auto-rollback uses, docs/
    # backlog.md item 3) rather than undo_last_push() (no longer called by
    # this method at all) or _restore_backup() (no longer called by this
    # method either now that restore_entries() calls restore_one() itself).

    def test_undo_multi_source_single_entry_restores_and_reports_success(
        self, window
    ) -> None:
        """A single "source=path" entry awaits one real restore and reports
        success only once that restore actually succeeds."""
        _setup_device(window)

        async def _fake_restore_entries(safe_write, entries, **_kwargs):
            return len(entries), 0, []

        with (
            patch(
                "src.gui.secondary_workflows.restore_entries",
                side_effect=_fake_restore_entries,
            ) as mock_restore,
            patch.object(window._push_page, "set_undo_success") as mock_undo_success,
            patch.object(window._status_banner, "show_success") as mock_success,
        ):
            import asyncio

            asyncio.run(
                window._secondary_workflows._do_undo_multi_source(
                    "wifi=/tmp/backup_wifi.json"
                )
            )

        mock_restore.assert_called_once()
        assert mock_restore.call_args.args[1] == [("wifi", "/tmp/backup_wifi.json")]
        mock_undo_success.assert_called_once_with("All 1 source(s) restored from backup")
        mock_success.assert_called_once_with("All 1 source(s) restored from backup")

    def test_undo_multi_source_multi_entry_all_restored_reports_success(
        self, window
    ) -> None:
        """Multiple "source=path" entries are all passed to restore_entries()
        in one call; the summary banner counts actual per-source successes
        as restore_entries() reports them."""
        _setup_device(window)
        backup_str = "wifi=/tmp/backup_wifi.json;bluetooth=/tmp/backup_bt.json"

        async def _fake_restore_entries(safe_write, entries, **_kwargs):
            return len(entries), 0, []

        with (
            patch(
                "src.gui.secondary_workflows.restore_entries",
                side_effect=_fake_restore_entries,
            ) as mock_restore,
            patch.object(window._status_banner, "show_success") as mock_success,
        ):
            import asyncio

            asyncio.run(window._secondary_workflows._do_undo_multi_source(backup_str))

        mock_restore.assert_called_once()
        assert mock_restore.call_args.args[1] == [
            ("wifi", "/tmp/backup_wifi.json"),
            ("bluetooth", "/tmp/backup_bt.json"),
        ]
        mock_success.assert_called_once_with("All 2 source(s) restored from backup")

    def test_undo_multi_source_malformed_entries_skipped(self, window) -> None:
        """Entries without "=" (malformed) are silently skipped -- not
        passed to restore_entries() and not counted toward succeeded or
        failed."""
        _setup_device(window)
        backup_str = "wifi=/tmp/backup_wifi.json;garbage-no-equals;;"

        async def _fake_restore_entries(safe_write, entries, **_kwargs):
            return len(entries), 0, []

        with (
            patch(
                "src.gui.secondary_workflows.restore_entries",
                side_effect=_fake_restore_entries,
            ) as mock_restore,
            patch.object(window._status_banner, "show_success") as mock_success,
        ):
            import asyncio

            asyncio.run(window._secondary_workflows._do_undo_multi_source(backup_str))

        mock_restore.assert_called_once()
        assert mock_restore.call_args.args[1] == [("wifi", "/tmp/backup_wifi.json")]
        mock_success.assert_called_once_with("All 1 source(s) restored from backup")

    def test_undo_multi_source_waits_for_real_undo_outcome(self, window) -> None:
        """Regression test for the scheduling-vs-outcome fix (branch-quality
        review, 2026-07-18): the summary reflects restore_entries()'s real,
        awaited return value -- a source that actually fails to restore
        (device unreachable, verification failure, etc.) is counted as
        failed, not as succeeded-because-scheduling-didn't-raise (the prior
        bug this test used to golden-master).
        """
        _setup_device(window)

        captured: list[tuple[int, int, str]] = []
        window._secondary_workflows.undo_multi_source_complete.connect(
            lambda succeeded, failed, msg: captured.append((succeeded, failed, msg))
        )

        async def _fake_restore_entries(safe_write, entries, **_kwargs):
            return 0, len(entries), list(entries)

        with (
            patch(
                "src.gui.secondary_workflows.restore_entries",
                side_effect=_fake_restore_entries,
            ),
            patch.object(window._status_banner, "show_error") as mock_error,
        ):
            import asyncio

            asyncio.run(
                window._secondary_workflows._do_undo_multi_source(
                    "wifi=/tmp/backup_wifi.json"
                )
            )

        mock_error.assert_called_once()
        # The real (failed) outcome is reflected -- not a scheduling-based
        # success, since restore_entries() is awaited before the tally.
        assert captured == [(0, 1, "0 restored, 1 failed")]

    def test_undo_multi_source_partial_failure_clears_snapshot(self, window) -> None:
        """Regression test (branch-quality review, 2026-07-17): a partial
        multi-source undo (2 succeeded, 1 failed) must still clear
        wizard_controller.state.last_pushed_filters, since device state for
        the 2 restored sources actually changed. Pre-fix, the snapshot was
        only cleared when the whole batch succeeded (failed == 0), leaving
        stale dirty-tracking after a real partial device change.
        """
        _setup_device(window)
        window._wizard_controller.state.last_pushed_filters = ["sentinel"]

        async def _fake_restore_entries(safe_write, entries, **_kwargs):
            failed_entries = [e for e in entries if e[0] == "bluetooth"]
            return len(entries) - len(failed_entries), len(failed_entries), failed_entries

        with (
            patch(
                "src.gui.secondary_workflows.restore_entries",
                side_effect=_fake_restore_entries,
            ),
            patch.object(window._status_banner, "show_error"),
        ):
            import asyncio

            asyncio.run(
                window._secondary_workflows._do_undo_multi_source(
                    "wifi=/tmp/backup_wifi.json;bluetooth=/tmp/backup_bt.json"
                )
            )

        assert window._wizard_controller.state.last_pushed_filters == []


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


    # --- Issue #11: FiltersPage retry shows option cards ---

    def test_issue11_filters_page_has_retry_mechanism(self, window) -> None:
        """#11: Clearing state fully resets FiltersPage for retry."""
        page = window._filters_page
        page._stereo_path = "/tmp/rew.txt"
        page._left_path = "/tmp/left.txt"
        page._right_path = "/tmp/right.txt"
        page._stereo_file_label.setText("rew.txt")
        page._left_file_label.setText("left.txt")
        page._right_file_label.setText("right.txt")
        page._next_btn.setEnabled(True)
        page._import_lr_btn.setEnabled(True)

        page.clear_results()

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

        def _record_async(coro: object, **_kwargs: object) -> None:
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
        Previously _write_preset_to_adapter never checked SafeWrite's
        result at all, so save_peq_profile() ran and "saved" was reported
        unconditionally even after a failed/rolled-back write."""
        filters = [_make_filter(100)]
        peq_settings = MagicMock(channel_mode="stereo", bands=filters)

        target_adapter = MagicMock()
        target_adapter.save_peq_profile = AsyncMock()
        target_adapter.capabilities.supported_filter_types = None

        safe_write = MagicMock()
        safe_write.execute = AsyncMock(
            return_value=WriteResult(
                success=False,
                rollback_success=True,
                error_message="Write verification failed; original state restored.",
            )
        )
        window._secondary_workflows._safe_write_factory = lambda adapter: safe_write
        # _write_preset_to_adapter asserts both write factories are set
        # unconditionally, even for a PEQ-only call -- irrelevant here, just
        # needs to be non-None.
        window._secondary_workflows._roomfit_safe_write_factory = lambda adapter: MagicMock()

        import asyncio

        with pytest.raises(RuntimeError):
            asyncio.run(
                window._secondary_workflows._write_preset_to_adapter(
                    target_adapter, "Movie Night", "PEQ", "wifi",
                    filters, ChannelMode.STEREO, peq_settings,
                )
            )
        # The failed write must not be saved as if it succeeded.
        target_adapter.save_peq_profile.assert_not_called()

    def test_copy_rejects_filter_type_unsupported_by_target_device(
        self, window
    ) -> None:
        """Copying a preset containing a filter type the target device
        doesn't support (e.g. LP/HP on a WiiM Mini) must fail cleanly --
        nothing written -- rather than sending the unsupported mode value
        and trusting write+read-back verification to catch a device that
        might silently echo it back unchanged."""
        filters = [CanonicalFilter(type="LP", frequency_hz=100.0, gain_db=-3.0, q=1.0)]
        peq_settings = MagicMock(channel_mode="stereo", bands=filters)

        target_adapter = MagicMock()
        target_adapter.save_peq_profile = AsyncMock()
        # WiiM Mini-like: PEAK/LS/HS only, no LP/HP.
        target_adapter.capabilities.supported_filter_types = ["PEAK", "LS", "HS"]

        safe_write = MagicMock()
        safe_write.execute = AsyncMock(return_value=WriteResult(success=True))
        window._secondary_workflows._safe_write_factory = lambda adapter: safe_write
        window._secondary_workflows._roomfit_safe_write_factory = lambda adapter: MagicMock()

        import asyncio

        with pytest.raises(RuntimeError, match="LP"):
            asyncio.run(
                window._secondary_workflows._write_preset_to_adapter(
                    target_adapter, "Movie Night", "PEQ", "wifi",
                    filters, ChannelMode.STEREO, peq_settings,
                )
            )
        safe_write.execute.assert_not_called()
        target_adapter.save_peq_profile.assert_not_called()

    def test_copy_rejects_filter_type_unsupported_for_roomfit_too(
        self, window
    ) -> None:
        """The unsupported-filter-type gate applies to RoomFit copies as well
        as PEQ: RoomFit reuses the exact same LV2 PEQ commands as user PEQ,
        just at EQLevel:2 (docs/wiim_api_notes.md "RoomFit (Room Correction)
        API") -- same plugin, same filter-type support -- so a RoomFit copy
        containing a device-unsupported type must fail cleanly, the same as
        the PEQ case, rather than reaching RoomFitSafeWrite at all."""
        filters = [CanonicalFilter(type="LP", frequency_hz=100.0, gain_db=-3.0, q=1.0)]
        roomfit_settings = MagicMock(
            channel_mode="stereo", bands=filters, bands_l=[], bands_r=[]
        )

        target_adapter = MagicMock()
        target_adapter.capabilities.supported_filter_types = ["PEAK", "LS", "HS"]

        roomfit_safe_write = MagicMock()
        roomfit_safe_write.execute = AsyncMock(return_value=WriteResult(success=True))
        window._secondary_workflows._roomfit_safe_write_factory = (
            lambda adapter: roomfit_safe_write
        )
        window._secondary_workflows._safe_write_factory = lambda adapter: MagicMock()

        import asyncio

        with pytest.raises(RuntimeError, match="LP"):
            asyncio.run(
                window._secondary_workflows._write_preset_to_adapter(
                    target_adapter, "My RoomFit", "RoomFit", "wifi",
                    filters, ChannelMode.STEREO, roomfit_settings,
                )
            )
        roomfit_safe_write.execute.assert_not_called()

    def test_copy_batch_emits_item_failed_detail_for_unsupported_device(
        self, window
    ) -> None:
        """A target device that can't take a copied item (e.g. RoomFit
        unsupported) must surface a clear, per-item reason via
        copy_item_failed -- not just an opaque aggregate failed-count, which
        gives the user no way to tell a capability mismatch from a
        transient connection failure."""
        items = [MagicMock()]
        items[0].name = "Living Room"
        items[0].preset_type = "RoomFit"

        device = MagicMock(ip="192.168.1.201", name="WiiM Mini")

        filters = [_make_filter(100)]
        peq_settings = MagicMock(
            channel_mode="stereo", bands=filters, bands_l=[], bands_r=[]
        )
        read_result = (filters, ChannelMode.STEREO, peq_settings)

        window._secondary_workflows._wiim_http_client_factory = (
            lambda ip: MagicMock(close=AsyncMock())
        )
        window._secondary_workflows._capability_prober_factory = (
            lambda client: MagicMock(probe=AsyncMock(return_value=MagicMock()))
        )
        def _make_target_adapter(client: object, caps: object) -> MagicMock:
            adapter = MagicMock()
            # Only RoomFit is unsupported here, not filter types -- None
            # means "no restriction" for find_unsupported_filter_types()
            # (a MagicMock's default empty __iter__ would otherwise make
            # every real filter type look unsupported).
            adapter.capabilities.supported_filter_types = None
            return adapter

        window._secondary_workflows._target_adapter_factory = _make_target_adapter
        window._secondary_workflows._roomfit_safe_write_factory = (
            lambda adapter: MagicMock(
                execute=AsyncMock(
                    side_effect=RoomFitUnsupportedError(
                        "RoomFit write is not supported by this device "
                        "(missing 'read' capability)"
                    )
                )
            )
        )

        failures: list[str] = []
        window._secondary_workflows.copy_item_failed.connect(failures.append)

        with patch.object(
            window._secondary_workflows, "_read_preset_to_copy",
            new_callable=AsyncMock, return_value=read_result,
        ):
            import asyncio

            asyncio.run(
                window._secondary_workflows._do_copy_presets_batch_multi(
                    items, [device], "wifi", "wifi"
                )
            )

        assert len(failures) == 1
        assert "WiiM Mini" in failures[0]
        assert "Living Room" in failures[0]
        assert "RoomFit" in failures[0]

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

        roomfit_safe_write = MagicMock()
        roomfit_safe_write.undo = AsyncMock(return_value=WriteResult(success=True))
        window._secondary_workflows._roomfit_safe_write_factory = (
            lambda adapter: roomfit_safe_write
        )

        import asyncio

        asyncio.run(
            window._secondary_workflows._do_undo_roomfit(
                str(backup_path), "wifi", "My Profile"
            )
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

        roomfit_safe_write = MagicMock()
        roomfit_safe_write.undo = AsyncMock(
            return_value=WriteResult(
                success=False,
                rollback_success=True,
                error_message="RoomFit verification failed; original profile restored.",
            )
        )
        window._secondary_workflows._roomfit_safe_write_factory = (
            lambda adapter: roomfit_safe_write
        )

        with patch.object(window._status_banner, "show_error") as mock_show_error, \
             patch.object(window._status_banner, "show_success") as mock_show_success:
            import asyncio

            asyncio.run(
                window._secondary_workflows._do_undo_roomfit(
                    str(backup_path), "wifi", "My Profile"
                )
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

        roomfit_safe_write = MagicMock()
        roomfit_safe_write.undo = AsyncMock(return_value=WriteResult(success=True))
        window._secondary_workflows._roomfit_safe_write_factory = (
            lambda adapter: roomfit_safe_write
        )

        import asyncio

        with patch.object(window._status_banner, "show_success") as mock_success:
            asyncio.run(
                window._secondary_workflows._do_undo_roomfit(
                    str(backup_path), "wifi", "My Profile"
                )
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

        roomfit_safe_write = MagicMock()
        roomfit_safe_write.undo = AsyncMock(return_value=WriteResult(success=True))
        window._secondary_workflows._roomfit_safe_write_factory = (
            lambda adapter: roomfit_safe_write
        )

        import asyncio

        with patch.object(window._status_banner, "show_success") as mock_success:
            asyncio.run(
                window._secondary_workflows._do_undo_roomfit(
                    str(backup_path), "wifi", "My Profile"
                )
            )

        message = mock_success.call_args[0][0]
        assert message == "Profile 'My Profile' restored from backup"

    # --- Issue #26: Copy to Another Device actually writes to target ---

    def test_issue26_copy_preset_to_device_writes_to_target(self, window) -> None:
        """#26: A full successful "Copy to Another Device" for a PEQ preset
        must actually write the target device's data (via SafeWrite.execute,
        then save_peq_profile) -- not just pick the right branch (that
        narrower claim is already covered by #34's test). This is the
        happy path for the shared primitive: read from source, connect to
        target, write+verify, persist as a named preset. (The per-item
        success banner was deleted -- docs/backlog.md item 2 Phase D --
        since it was redundant with the batch-level summary shown by
        _do_copy_presets_batch_multi.)
        """
        filters = [_make_filter(100), _make_filter(200)]
        peq_settings = MagicMock(channel_mode="stereo", bands=filters)

        target_adapter = MagicMock()
        target_adapter.save_peq_profile = AsyncMock()
        target_adapter.capabilities.supported_filter_types = None

        safe_write = MagicMock()
        safe_write.execute = AsyncMock(return_value=WriteResult(success=True))
        window._secondary_workflows._safe_write_factory = lambda adapter: safe_write
        # _write_preset_to_adapter asserts both write factories are set
        # unconditionally, even for a PEQ-only call -- irrelevant here, just
        # needs to be non-None.
        window._secondary_workflows._roomfit_safe_write_factory = lambda adapter: MagicMock()

        import asyncio

        asyncio.run(
            window._secondary_workflows._write_preset_to_adapter(
                target_adapter, "Movie Night", "PEQ", "wifi",
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
        SecondaryWorkflowManager._write_preset_to_adapter() (moved from
        MainWindow, docs/backlog.md item 2 Phase D), which already takes
        channel_mode from the source read rather than a hardcoded default --
        this test targets that current path.
        """
        filters_l = [_make_filter(100)]
        filters_r = [_make_filter(200)]
        peq_settings = MagicMock(
            channel_mode="lr", bands_l=filters_l, bands_r=filters_r, bands=[]
        )

        target_adapter = MagicMock()
        target_adapter.save_peq_profile = AsyncMock()
        target_adapter.capabilities.supported_filter_types = None

        safe_write = MagicMock()
        safe_write.execute = AsyncMock(return_value=WriteResult(success=True))
        window._secondary_workflows._safe_write_factory = lambda adapter: safe_write
        # _write_preset_to_adapter asserts both write factories are set
        # unconditionally, even for a PEQ-only call -- irrelevant here, just
        # needs to be non-None.
        window._secondary_workflows._roomfit_safe_write_factory = lambda adapter: MagicMock()

        import asyncio

        asyncio.run(
            window._secondary_workflows._write_preset_to_adapter(
                target_adapter, "LR Preset", "PEQ", "wifi",
                filters_l + filters_r, ChannelMode.LR, peq_settings,
            )
        )

        safe_write.execute.assert_called_once()
        written_settings = safe_write.execute.call_args[0][1]
        assert written_settings.channel_mode == ChannelMode.LR
        assert written_settings.bands_l == filters_l
        assert written_settings.bands_r == filters_r

    # --- Issue #34: _write_preset_to_adapter branches on preset_type ---

    def test_issue34_copy_branches_on_preset_type(self, window) -> None:
        """#34: _write_preset_to_adapter uses PEQ and RoomFit write paths correctly."""
        peq_settings = MagicMock(channel_mode="stereo", bands=[_make_filter(100)])

        roomfit_settings = MagicMock(
            channel_mode="lr",
            bands=[_make_filter(100), _make_filter(200)],
            bands_l=[_make_filter(100)],
            bands_r=[_make_filter(200)],
        )

        target_adapter = MagicMock()
        target_adapter.write_roomfit = AsyncMock()
        target_adapter.save_peq_profile = AsyncMock()
        target_adapter.capabilities.supported_filter_types = None

        safe_write = MagicMock()
        safe_write.execute = AsyncMock(return_value=WriteResult(success=True))
        window._secondary_workflows._safe_write_factory = lambda adapter: safe_write

        roomfit_safe_write = MagicMock()
        roomfit_safe_write.execute = AsyncMock(return_value=WriteResult(success=True))
        window._secondary_workflows._roomfit_safe_write_factory = (
            lambda adapter: roomfit_safe_write
        )

        import asyncio

        asyncio.run(
            window._secondary_workflows._write_preset_to_adapter(
                target_adapter, "Movie Night", "PEQ", "wifi",
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
            window._secondary_workflows._write_preset_to_adapter(
                target_adapter, "RoomFit A", "RoomFit", "wifi",
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
        assert view._rename_btn.isEnabled() is False
        assert view._duplicate_btn.isEnabled() is False
        assert view._delete_btn.isEnabled() is False

        view._list_widget.setCurrentRow(0)
        qtbot.wait(10)

        assert view._rename_btn.isEnabled() is True
        assert view._duplicate_btn.isEnabled() is True
        assert view._delete_btn.isEnabled() is True

        duplicate_calls: list[str] = []
        delete_calls: list[list[str]] = []

        view.duplicate_requested.connect(lambda name: duplicate_calls.append(name))
        view.delete_requested.connect(lambda names: delete_calls.append(names))

        view._duplicate_btn.click()
        with patch(
            "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
            return_value=True,
        ):
            view._delete_btn.click()

        assert duplicate_calls == ["Jazz Night"]
        assert delete_calls == [["Jazz Night"]]

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
        """#39: An L/R profile rendered in MyPresetsView shows per-channel
        "L:"/"R:" band counts in the row text (not "Stereo", and not a flat
        combined count). This is the actual UI-visible manifestation of the
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
        assert item.text() == "LR Test  [L: 2 bands / R: 1 band]"

    def test_issue39_stereo_profile_renders_stereo_badge(self, window) -> None:
        """#39 sibling: a stereo profile still shows "Stereo" (not "L/R")."""
        filters = [_make_filter(100), _make_filter(200), _make_filter(300)]
        profile = build_profile("Stereo Test", filters, "Stereo")

        view = window._my_presets_view
        view.set_presets([profile])

        item = view._list_widget.item(0)
        assert item.text() == "Stereo Test  [Stereo: 3 bands]"

    def test_issue275_band_count_excludes_off_padding(self, window) -> None:
        """#275: User-reported -- every preset showed the device's max band
        count (e.g. 12) regardless of how many filters it actually used.
        A Profile saved from a device read always carries exactly
        capabilities.max_filters slots (read_peq() parses the device's
        full fixed-size band array 1:1), with any unconfigured slot coming
        back as a type="OFF" placeholder rather than being omitted -- so
        counting raw list length showed the device's slot count, not the
        number of real filters. Covers both stereo and L/R, and both
        boundary cases (an OFF-only channel, an OFF-free channel)."""
        off_filter = CanonicalFilter(type="OFF", frequency_hz=1000.0, gain_db=0.0, q=1.0)
        filters_l = [_make_filter(100), off_filter, off_filter]
        filters_r = [off_filter, off_filter, off_filter]
        lr_profile = build_profile(
            "Padded LR", filters_l + filters_r, "L/R",
            filters_l=filters_l, filters_r=filters_r,
        )
        stereo_filters = [_make_filter(100), _make_filter(200), off_filter, off_filter]
        stereo_profile = build_profile("Padded Stereo", stereo_filters, "Stereo")

        view = window._my_presets_view
        view.set_presets([lr_profile, stereo_profile])

        assert view._list_widget.item(0).text() == "Padded LR  [L: 1 band / R: 0 bands]"
        assert view._list_widget.item(1).text() == "Padded Stereo  [Stereo: 2 bands]"

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

    def test_save_filters_to_presets_lr_empty_channel_shows_error_not_crash(
        self, window
    ) -> None:
        """build_profile() raises ValueError for an L/R save with one empty
        channel (require_lr_filters, ca14e26); _save_filters_to_presets must
        show an error banner for that, not let it escape uncaught out of the
        Qt slot (branch-quality review, 2026-07-18)."""
        filters = [_make_filter(100)]
        state = window._wizard_controller.state
        state.filters_l = [_make_filter(100)]
        state.filters_r = []

        with (
            patch.object(window._profile_repository, "save") as mock_save,
            patch.object(window, "_refresh_presets_view") as mock_refresh,
            patch.object(window._status_banner, "show_error") as mock_error,
        ):
            window._save_filters_to_presets("Broken LR Preset", filters, ChannelMode.LR)

        mock_save.assert_not_called()
        mock_refresh.assert_not_called()
        mock_error.assert_called_once()
        assert "Save failed" in mock_error.call_args[0][0]

    def test_issue235_save_filters_to_presets_sanitizes_device_name(self, window) -> None:
        """Smoke #235: _save_filters_to_presets() must sanitize its `name`
        argument via sanitize_device_name() before building the Profile --
        for the Review-page trigger this argument is an auto-generated
        default like "wifi (Stereo)", so every preset saved this way
        carried disallowed characters from the moment it was created,
        before any rename ever touched it."""
        filters = [_make_filter(100)]
        state = window._wizard_controller.state
        state.filters_l = []
        state.filters_r = []

        with (
            patch.object(window._profile_repository, "save") as mock_save,
            patch.object(window._profile_repository, "list_all", return_value=[]),
            patch.object(window._my_presets_view, "set_presets"),
            patch.object(window._status_banner, "show_success"),
        ):
            window._save_filters_to_presets("wifi (Stereo)", filters, ChannelMode.STEREO)

        saved_profile = mock_save.call_args[0][0]
        assert saved_profile.name == "wifi Stereo"

    def test_issue235_profile_duplicate_sanitizes_device_name(self, window) -> None:
        """Smoke #235: _on_profile_duplicate_requested() synthesizes
        f"{name} (copy)" -- parentheses are disallowed by the WiiM device
        naming rule, so the synthesized name must be sanitized before
        reaching ProfileRepository.duplicate()."""
        with patch.object(window._profile_repository, "duplicate") as mock_duplicate, patch.object(
            window, "_refresh_presets_view"
        ), patch.object(window._status_banner, "show_success"):
            window._on_profile_duplicate_requested("My Preset")

        mock_duplicate.assert_called_once_with("My Preset", "My Preset copy")

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
        behind as dead code with its own regression test.

        Updated (branch-quality review, 2026-07-17): _write_preset_copies_to_devices
        now connects once per device (outer loop) instead of once per
        (preset, device) pair, so the write call is _write_preset_to_adapter
        (taking an already-connected adapter) rather than
        _do_copy_preset_to_device (which connected itself, keyed by IP).
        Distinct per-device adapter sentinels replace the old
        `target_ip` positional check, and the expected call order changes
        from preset-major to device-major to match the new loop nesting.
        """
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

        # Distinct sentinel client/adapter per target IP, so calls can be
        # verified against the device actually targeted (not just counted).
        adapters_by_ip = {
            ip: MagicMock(name=f"Adapter-{ip}") for ip in ("192.168.1.201", "192.168.1.202")
        }
        clients_by_ip = {
            ip: MagicMock(name=f"Client-{ip}", close=AsyncMock()) for ip in adapters_by_ip
        }
        ip_by_client_id = {id(client): ip for ip, client in clients_by_ip.items()}

        window._secondary_workflows._wiim_http_client_factory = (
            lambda ip: clients_by_ip[ip]
        )
        window._secondary_workflows._capability_prober_factory = (
            lambda client: MagicMock(probe=AsyncMock(return_value=MagicMock()))
        )
        window._secondary_workflows._target_adapter_factory = (
            lambda client, caps: adapters_by_ip[ip_by_client_id[id(client)]]
        )

        with (
            patch.object(
                window._secondary_workflows, "_read_preset_to_copy",
                new_callable=AsyncMock, return_value=read_result,
            ) as mock_read,
            patch.object(
                window._secondary_workflows, "_write_preset_to_adapter",
                new_callable=AsyncMock,
            ) as mock_write,
        ):
            import asyncio

            asyncio.run(
                window._secondary_workflows._do_copy_presets_batch_multi(
                    items, devices, "wifi", "wifi"
                )
            )
            assert mock_read.call_count == 2
            assert mock_write.call_count == 4
            # _write_preset_to_adapter(target_adapter, preset_name, ...)
            calls = [(c.args[0], c.args[1]) for c in mock_write.call_args_list]
            assert calls == [
                (adapters_by_ip["192.168.1.201"], "Preset1"),
                (adapters_by_ip["192.168.1.201"], "Preset2"),
                (adapters_by_ip["192.168.1.202"], "Preset1"),
                (adapters_by_ip["192.168.1.202"], "Preset2"),
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

        # _write_preset_copies_to_devices connects once per device now
        # (branch-quality review, 2026-07-17) -- stub the connect factories
        # so it doesn't attempt real network calls; the write itself is
        # mocked out below via _write_preset_to_adapter.
        window._secondary_workflows._wiim_http_client_factory = (
            lambda ip: MagicMock(close=AsyncMock())
        )
        window._secondary_workflows._capability_prober_factory = (
            lambda client: MagicMock(probe=AsyncMock(return_value=MagicMock()))
        )
        window._secondary_workflows._target_adapter_factory = (
            lambda client, caps: MagicMock()
        )

        with (
            patch.object(
                window._secondary_workflows, "_read_preset_to_copy",
                new_callable=AsyncMock, return_value=read_result,
            ),
            patch.object(
                window._secondary_workflows, "_write_preset_to_adapter",
                new_callable=AsyncMock,
            ),
            patch.object(window._status_banner, "show_success") as mock_success,
        ):
            import asyncio

            asyncio.run(
                window._secondary_workflows._do_copy_presets_batch_multi(
                    items, devices, "wifi", "wifi"
                )
            )
            mock_success.assert_called_once()
            msg = mock_success.call_args[0][0]
            assert "1 preset(s)" in msg
            assert "3 device(s)" in msg

    def test_copy_batch_skipped_empty_name_item_not_counted_in_total(
        self, window
    ) -> None:
        """An item with an empty name (e.g. wiim_adapter.py:654 coercing a
        missing device "Name" key to "") is skipped via `continue` before
        ever being attempted -- it must not count toward n_items in the
        final copy_batch_complete tally, or n_items * n_devices stops
        matching succeeded + failed (round-4 review finding #5,
        2026-07-19)."""
        _setup_device(window)
        items = [MagicMock(), MagicMock()]
        items[0].name = "Preset1"
        items[0].preset_type = "PEQ"
        items[1].name = ""  # Orphaned/malformed entry -- skipped, not attempted
        items[1].preset_type = "PEQ"

        device1 = MagicMock(ip="192.168.1.201", name="Device A")
        devices = [device1]

        filters = [_make_filter(100)]
        peq_settings = MagicMock(channel_mode="stereo", bands=filters)
        read_result = (filters, ChannelMode.STEREO, peq_settings)

        window._secondary_workflows._wiim_http_client_factory = (
            lambda ip: MagicMock(close=AsyncMock())
        )
        window._secondary_workflows._capability_prober_factory = (
            lambda client: MagicMock(probe=AsyncMock(return_value=MagicMock()))
        )
        window._secondary_workflows._target_adapter_factory = (
            lambda client, caps: MagicMock()
        )

        emitted: list[tuple[int, int, int, int, str]] = []
        window._secondary_workflows.copy_batch_complete.connect(
            lambda *args: emitted.append(args)
        )

        with (
            patch.object(
                window._secondary_workflows, "_read_preset_to_copy",
                new_callable=AsyncMock, return_value=read_result,
            ) as mock_read,
            patch.object(
                window._secondary_workflows, "_write_preset_to_adapter",
                new_callable=AsyncMock,
            ),
        ):
            import asyncio

            asyncio.run(
                window._secondary_workflows._do_copy_presets_batch_multi(
                    items, devices, "wifi", "wifi"
                )
            )

        # Only the real item was ever read -- the empty-name item was
        # skipped, not attempted (and therefore not a failure either).
        mock_read.assert_called_once()
        assert emitted == [(1, 1, 1, 0, "preset")]

    def test_copy_dispatch_ignored_while_batch_in_progress(self, window) -> None:
        """A second copy dispatch (from either copy_presets_to_devices or
        copy_local_profiles_to_devices) while a batch is already running
        must be ignored, not interleaved with it. There's no synchronous
        guarantee that the UI's button-disable already prevents this: a
        run_async() call schedules its coroutine on a background-thread
        event loop and only emits operation_started -- which disables the
        Copy buttons -- once that coroutine actually starts running there,
        not synchronously when run_async() is called, leaving a window
        where a fast double-click isn't caught by the UI alone."""
        manager = window._secondary_workflows
        manager._copy_in_progress = True

        with patch.object(manager, "_dispatch") as mock_dispatch:
            manager.copy_presets_to_devices(
                [MagicMock()], [MagicMock()], "wifi", "wifi"
            )
            manager.copy_local_profiles_to_devices(
                [("Name", ChannelMode.STEREO, [], None, None)],
                "PEQ", [MagicMock()], "wifi",
            )
            mock_dispatch.assert_not_called()

    def test_copy_in_progress_resets_after_batch_completes(self, window) -> None:
        """_copy_in_progress must clear once its batch coroutine finishes,
        or every later copy attempt would be silently ignored forever."""
        manager = window._secondary_workflows
        manager._copy_in_progress = True

        import asyncio

        with patch.object(
            manager, "_write_preset_copies_to_devices",
            new_callable=AsyncMock, return_value=(0, 0),
        ):
            asyncio.run(manager._do_copy_presets_batch_multi([], [], "wifi", "wifi"))

        assert manager._copy_in_progress is False

    def test_copy_in_progress_resets_even_on_unexpected_error(self, window) -> None:
        """An unexpected exception escaping the batch coroutine must still
        clear _copy_in_progress -- otherwise a single bug would permanently
        block every future copy attempt until the app restarts."""
        manager = window._secondary_workflows
        manager._copy_in_progress = True

        items = [MagicMock()]
        items[0].name = "Preset1"
        items[0].preset_type = "PEQ"
        read_result = ([_make_filter(100)], ChannelMode.STEREO, MagicMock())

        import asyncio

        with (
            patch.object(
                manager, "_read_preset_to_copy",
                new_callable=AsyncMock, return_value=read_result,
            ),
            patch.object(
                manager, "_write_preset_copies_to_devices",
                new_callable=AsyncMock, side_effect=RuntimeError("boom"),
            ),
        ):
            with pytest.raises(RuntimeError):
                asyncio.run(
                    manager._do_copy_presets_batch_multi(
                        items, [MagicMock()], "wifi", "wifi"
                    )
                )

        assert manager._copy_in_progress is False

    def test_copy_batch_connects_once_per_device_not_per_preset(self, window) -> None:
        """Regression test (branch-quality review, 2026-07-17):
        _write_preset_copies_to_devices must connect + probe capabilities
        exactly once per target device, not once per (preset, device) pair
        -- copying 2 presets to 2 devices should make 2 connect/probe calls
        total, not 4."""
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

        http_client_factory = MagicMock(
            side_effect=lambda ip: MagicMock(close=AsyncMock())
        )
        prober_factory = MagicMock(
            side_effect=lambda client: MagicMock(probe=AsyncMock(return_value=MagicMock()))
        )
        window._secondary_workflows._wiim_http_client_factory = http_client_factory
        window._secondary_workflows._capability_prober_factory = prober_factory
        window._secondary_workflows._target_adapter_factory = (
            lambda client, caps: MagicMock()
        )

        with (
            patch.object(
                window._secondary_workflows, "_read_preset_to_copy",
                new_callable=AsyncMock, return_value=read_result,
            ),
            patch.object(
                window._secondary_workflows, "_write_preset_to_adapter",
                new_callable=AsyncMock,
            ) as mock_write,
        ):
            import asyncio

            asyncio.run(
                window._secondary_workflows._do_copy_presets_batch_multi(
                    items, devices, "wifi", "wifi"
                )
            )

        assert http_client_factory.call_count == 2
        assert prober_factory.call_count == 2
        assert mock_write.call_count == 4

    def test_copy_batch_device_connect_failure_counts_all_its_presets_failed(
        self, window
    ) -> None:
        """Regression test (branch-quality review, 2026-07-17): if a target
        device fails to connect/probe, all presets destined for it count as
        failed in one step (not attempted individually), while the other
        device's presets still succeed and the totals still balance."""
        _setup_device(window)
        items = [MagicMock(), MagicMock()]
        items[0].name = "Preset1"
        items[0].preset_type = "PEQ"
        items[1].name = "Preset2"
        items[1].preset_type = "PEQ"

        device_ok = MagicMock(ip="192.168.1.201", name="Device OK")
        device_bad = MagicMock(ip="192.168.1.202", name="Device Unreachable")
        devices = [device_ok, device_bad]

        filters = [_make_filter(100)]
        peq_settings = MagicMock(channel_mode="stereo", bands=filters)
        read_result = (filters, ChannelMode.STEREO, peq_settings)

        def _prober_factory(client: object) -> MagicMock:
            prober = MagicMock()
            if client is bad_client:
                prober.probe = AsyncMock(side_effect=RuntimeError("unreachable"))
            else:
                prober.probe = AsyncMock(return_value=MagicMock())
            return prober

        ok_client = MagicMock(close=AsyncMock())
        bad_client = MagicMock(close=AsyncMock())
        clients_by_ip = {"192.168.1.201": ok_client, "192.168.1.202": bad_client}

        window._secondary_workflows._wiim_http_client_factory = (
            lambda ip: clients_by_ip[ip]
        )
        window._secondary_workflows._capability_prober_factory = _prober_factory
        window._secondary_workflows._target_adapter_factory = (
            lambda client, caps: MagicMock()
        )

        captured: list[tuple[int, int, int, int, str]] = []
        window._secondary_workflows.copy_batch_complete.connect(
            lambda n_items, n_devices, succeeded, failed, label: captured.append(
                (n_items, n_devices, succeeded, failed, label)
            )
        )

        with (
            patch.object(
                window._secondary_workflows, "_read_preset_to_copy",
                new_callable=AsyncMock, return_value=read_result,
            ),
            patch.object(
                window._secondary_workflows, "_write_preset_to_adapter",
                new_callable=AsyncMock,
            ) as mock_write,
        ):
            import asyncio

            asyncio.run(
                window._secondary_workflows._do_copy_presets_batch_multi(
                    items, devices, "wifi", "wifi"
                )
            )

        assert mock_write.call_count == 2  # only device_ok's 2 presets were attempted
        assert captured == [(2, 2, 2, 2, "preset")]  # n_items, n_devices, succeeded, failed, label

    # --- Issue #79: Copy L/R RoomFit preserves channel_mode ---

    def test_issue79_copy_lr_roomfit_preserves_channel(self, window) -> None:
        """#79: _write_preset_to_adapter passes L/R for RoomFit copies."""
        # Simulate a RoomFit profile that is L/R
        peq_settings = MagicMock()
        peq_settings.channel_mode = "lr"
        peq_settings.bands_l = [_make_filter(100)]
        peq_settings.bands_r = [_make_filter(200)]
        peq_settings.bands = []

        target_adapter = MagicMock()
        target_adapter.capabilities.supported_filter_types = None

        roomfit_safe_write = MagicMock()
        roomfit_safe_write.execute = AsyncMock(return_value=WriteResult(success=True))
        window._secondary_workflows._roomfit_safe_write_factory = (
            lambda adapter: roomfit_safe_write
        )
        # _write_preset_to_adapter asserts both write factories are set
        # unconditionally, even for a RoomFit-only call -- irrelevant here,
        # just needs to be non-None.
        window._secondary_workflows._safe_write_factory = lambda adapter: MagicMock()

        import asyncio

        asyncio.run(
            window._secondary_workflows._write_preset_to_adapter(
                target_adapter, "My RoomFit", "RoomFit", "wifi",
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

    def test_copy_lr_roomfit_empty_channel_rejected_not_silently_copied(
        self, window
    ) -> None:
        """A RoomFit preset with a genuinely empty right channel (a valid
        device read-state, see WiiMAdapter._parse_lr) must be rejected the
        same way the sibling PEQ copy branch already rejects it via
        build_peq_settings()/resolve_channel_split() -- not silently copied
        to the target device with an incomplete L/R split (round-4 review
        finding #8, 2026-07-19)."""
        _setup_device(window)
        peq_settings = MagicMock()
        peq_settings.channel_mode = "lr"
        peq_settings.bands_l = [_make_filter(100)]
        peq_settings.bands_r = []  # Genuinely empty, not None
        peq_settings.bands = []

        roomfit_safe_write = MagicMock()
        roomfit_safe_write.execute = AsyncMock()
        window._secondary_workflows._roomfit_safe_write_factory = (
            lambda adapter: roomfit_safe_write
        )

        target_adapter = MagicMock()
        target_adapter.capabilities.supported_filter_types = None

        import asyncio

        with pytest.raises(ValueError, match="L/R filters missing"):
            asyncio.run(
                window._secondary_workflows._write_preset_to_adapter(
                    target_adapter, "My RoomFit", "RoomFit", "wifi",
                    peq_settings.bands_l, ChannelMode.LR, peq_settings,
                )
            )
        roomfit_safe_write.execute.assert_not_called()

    # --- Issue #85: Diagnostics raw_command_requested connected ---

    def test_issue85_diagnostics_raw_command_connected(self, window) -> None:
        """#85: Diagnostics raw command signal triggers async command
        execution and actually reaches the adapter with the exact command
        string requested -- not just "some coroutine got run"."""
        mock_adapter = _setup_device(window)
        mock_adapter.raw_command = AsyncMock(return_value={"foo": "bar"})

        def _run_now(coro: object, **_kwargs: object) -> None:
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
    """Direct unit tests guarding against business logic re-accumulating in
    src/gui/ (no Qt needed for any of it).

    #64 originally required a src/gui/shared_helpers.py module as the single
    source of truth for channel-mode/profile logic that had been duplicated
    across call sites. That module has since been fully emptied out one
    function at a time (build_peq_settings/build_profile/is_lr_mode/
    get_lr_filters/extract_filters/read_preset_preview -- see test_models.py,
    test_wiim_adapter.py for their behavior-level coverage) and deleted
    entirely once nothing imported it any more; parse_backup_filters/
    load_backup_json, its last re-exports, already had direct importers in
    src.repository.backup_manager. This test's job now is to confirm that
    outcome and guard against any of these creeping back into src/gui/ as a
    second copy.
    """

    def test_issue64_business_logic_not_reduplicated_in_gui(self) -> None:
        """#64: shared_helpers.py is gone, and none of the business logic it
        used to hold has been reimplemented locally in main_window.py or
        secondary_workflows.py."""
        import importlib
        import inspect

        from src.gui import main_window, secondary_workflows
        from src.models import channel_mode as channel_mode_module
        from src.models import peq
        from src.models import profile as profile_module
        from src.translator import wiim_generator

        with pytest.raises(ModuleNotFoundError):
            importlib.import_module("src.gui.shared_helpers")

        # Each function shared_helpers.py used to hold now lives with the
        # domain model/module it belongs to, and nowhere else.
        assert hasattr(wiim_generator, "validate_filters_for_device")
        assert callable(wiim_generator.validate_filters_for_device)
        assert hasattr(peq, "build_peq_settings")
        assert callable(peq.build_peq_settings)
        assert hasattr(peq, "extract_filters")
        assert callable(peq.extract_filters)
        assert hasattr(profile_module, "build_profile")
        assert callable(profile_module.build_profile)
        for name in ("is_lr_mode", "require_lr_filters"):
            assert hasattr(channel_mode_module, name)
            assert callable(getattr(channel_mode_module, name))

        # secondary_workflows.py legitimately has no equivalent local logic
        # (PEQ redesign, mirrors #191): _do_undo() delegates backup parsing
        # and PEQSettings reconstruction entirely to SafeWrite.undo() rather
        # than calling build_peq_settings()/parse_backup_filters() locally.
        # Assert the delegation instead: no local re-parsing logic
        # duplicating what SafeWrite.undo() now owns.
        main_window_source = inspect.getsource(main_window)
        secondary_workflows_source = inspect.getsource(secondary_workflows)
        for reimplemented_name in (
            "build_peq_settings", "parse_backup_filters", "load_backup_json",
        ):
            assert f"def {reimplemented_name}(" not in secondary_workflows_source
        assert "safe_write.undo(" in secondary_workflows_source

        # Spot-check: no duplicate local reimplementation of is_lr_mode's
        # channel-string matching (the specific bug pattern smoke #55/#69
        # were about) anywhere outside models.channel_mode itself.
        assert "def is_lr_mode" not in main_window_source
        assert "def is_lr_mode" not in secondary_workflows_source
        assert inspect.getsourcefile(
            channel_mode_module.is_lr_mode
        ) == inspect.getsourcefile(channel_mode_module)

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
        hardcoded 'wifi', and never the raw comma string. source_name is
        resolved by the caller (MainWindow, from wizard state) and passed
        in explicitly -- SecondaryWorkflowManager has no wizard state of
        its own (docs/backlog.md item 2 Phase D)."""
        adapter = _setup_device(window)
        window._wizard_controller.state.selected_source = "bluetooth,wifi"
        adapter.read_peq_preset_preview = AsyncMock(
            return_value=self._preview_settings()
        )
        source_name = window._wizard_controller.state.primary_source

        import asyncio

        result = asyncio.run(
            window._secondary_workflows._read_preset_to_copy(
                source_name, "My Preset", "PEQ"
            )
        )

        assert result is not None
        adapter.read_peq_preset_preview.assert_awaited_once_with(
            "bluetooth", "My Preset"
        )
