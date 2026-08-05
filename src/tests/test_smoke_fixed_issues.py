import logging
import sys
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QDialog

from src.adapters import wiim_adapter
from src.gui import main_window
from src.gui.components.sidebar_nav import SidebarNav
from src.gui.pages.push_page import PushPage
from src.gui.primary_workflows import PrimaryWorkflowManager
from src.gui.wizard_controller import FlowType, WizardState, WizardStep
from src.logging.setup import configure_logging, install_crash_handler
from src.models import constants as model_constants
from src.models.canonical import CanonicalFilter
from src.models.channel_mode import ChannelMode
from src.tests.conftest import close_coroutine_tree


# Issue 101: Band-param helper _flat_array_to_band_params used across adapter write paths
def test_flat_array_to_band_params_roundtrip():
    band_array = [1.0, 100.0, 1.5, 1.0, 2.0, 200.0, -2.0, 0.71]
    params = wiim_adapter._flat_array_to_band_params(band_array, num_bands=2)

    names = [p["param_name"] for p in params]
    assert names[:4] == ["a_mode", "a_freq", "a_gain", "a_q"]
    assert names[4:] == ["b_mode", "b_freq", "b_gain", "b_q"]

    band_dicts = wiim_adapter._params_to_band_dicts(params)
    assert len(band_dicts) == 2
    assert band_dicts[0]["mode"] == 1
    assert pytest.approx(band_dicts[0]["freq"]) == 100.0
    assert pytest.approx(band_dicts[1]["gain"]) == -2.0


# Issue 100: Hardware limit constants consolidated in src/models/constants.py
def test_hardware_constants_present():
    assert model_constants.GAIN_MIN < model_constants.GAIN_MAX
    assert model_constants.Q_MIN > 0
    assert model_constants.Q_MIN < model_constants.Q_MAX


# Issue 100: wiim_generator must import the shared constants rather than
# defining its own independent literals. Numeric equality (the previous
# test's only real check) can't catch a reintroduced duplicate that merely
# happens to match today's values -- `is` identity on the private
# module-level aliases proves they're the *same object* bound from
# src.models.constants, so any future duplicate literal (numerically equal
# or not) fails this test immediately.
#
# shared_helpers no longer has its own copies of these aliases:
# validate_filters_for_device() (the only thing in that module that needed
# them) moved to src.translator.wiim_generator, since it's business logic
# with no Qt dependency, not GUI code -- see TestSharedHelpers.
# test_issue64_shared_helpers_created in test_smoke_regression_operations.py
# for the regression guard against it moving back.
def test_hardware_constants_imported_not_duplicated():
    import src.translator.wiim_generator as wiim_generator

    assert wiim_generator._GAIN_MIN is model_constants.GAIN_MIN
    assert wiim_generator._GAIN_MAX is model_constants.GAIN_MAX
    assert wiim_generator._Q_MIN is model_constants.Q_MIN
    assert wiim_generator._Q_MAX is model_constants.Q_MAX


# Issue 102: install_crash_handler should log unhandled exceptions to app.log
def test_install_crash_handler_writes_log(tmp_path, monkeypatch):
    logs_dir = tmp_path / "logs"
    configure_logging(logs_dir, level=logging.DEBUG)

    monkeypatch.setattr(sys, "excepthook", lambda *a, **k: None)

    install_crash_handler(logs_dir)
    sys.excepthook(TypeError, TypeError("boom"), None)

    log_file = logs_dir / "app.log"
    assert log_file.exists()
    text = log_file.read_text(encoding="utf-8")
    assert "Unhandled exception" in text


# Issue 94: _mark_prior_steps_completed must mark CONNECT/EQ_TYPE/SOURCE/FILTERS when appropriate
def test_mark_prior_steps_completed_marks_connect_and_sources():
    """#162: CONNECT's summary is now the resolved device name
    (_resolve_connect_summary(), same wording used by every entry point)
    instead of the literal "Connected" -- bind the real shared-summary
    helper methods onto the SimpleNamespace stand-in so this test exercises
    the actual current behavior rather than a stale hardcoded literal."""
    func = main_window.MainWindow._mark_prior_steps_completed

    state = WizardState()
    state.selected_device = "device-1"

    dummy_self = SimpleNamespace()
    dummy_self._wizard_controller = SimpleNamespace(flow_type=FlowType.PEQ, state=state)
    dummy_self._device_caps = None
    dummy_self._primary_workflows = SimpleNamespace(discovered_devices=[])
    dummy_self._lookup_device_name = (
        main_window.MainWindow._lookup_device_name.__get__(dummy_self)
    )
    dummy_self._resolve_connect_summary = (
        main_window.MainWindow._resolve_connect_summary.__get__(dummy_self)
    )
    dummy_self._compute_source_summary = (
        main_window.MainWindow._compute_source_summary.__get__(dummy_self)
    )
    dummy_self._apply_source_summary = (
        main_window.MainWindow._apply_source_summary.__get__(dummy_self)
    )
    dummy_self._resolve_filters_summary = (
        main_window.MainWindow._resolve_filters_summary.__get__(dummy_self)
    )

    func(dummy_self, state)

    assert WizardStep.CONNECT in state.completed_steps
    # No discovered-device match and no caps -> _resolve_connect_summary()'s
    # generic fallback name, not the device IP or the old "Connected" literal.
    assert state.completed_steps[WizardStep.CONNECT] == "WiiM Device"
    assert WizardStep.EQ_TYPE in state.completed_steps
    assert WizardStep.SOURCE in state.completed_steps
    assert WizardStep.FILTERS in state.completed_steps


# Issue 101: _flat_array_to_band_params supports start_band offset for sequential writes
def test_flat_array_to_band_params_start_band():
    band_array = [1.0, 50.0, 0.0, 1.0, 1.0, 60.0, 0.0, 1.0]
    params = wiim_adapter._flat_array_to_band_params(band_array, num_bands=2, start_band=2)
    names = [p["param_name"] for p in params]
    assert str(names[0]).startswith("c_")
    assert str(names[4]).startswith("d_")


# Issue 113: _do_load_peq_preset must update wizard state.channel_mode from device response
@pytest.mark.asyncio
async def test_do_load_peq_preset_updates_channel_mode_and_emits():
    # _do_load_peq_preset moved to PrimaryWorkflowManager (docs/backlog.md
    # item 2, Phase 2).
    manager = PrimaryWorkflowManager()

    class DummyAdapter:
        async def load_peq_profile(self, source_name, preset_name):
            return None

        async def read_peq(self, source_name):
            return SimpleNamespace(
                channel_mode=ChannelMode.LR,
                bands_l=[CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=1.0, q=1.0)],
                bands_r=[CanonicalFilter(type="PEAK", frequency_hz=200.0, gain_db=0.5, q=1.0)],
            )

        async def read_peq_preset_preview(self, source_name, preset_name):
            # _do_load_peq_preset now reads via read_peq_preset_preview (#166)
            return await self.read_peq(source_name)

    manager._current_adapter = cast(Any, DummyAdapter())
    wizard_controller = cast(Any, SimpleNamespace(state=WizardState()))
    manager._wizard_controller = wizard_controller

    emitted = {}

    class Emitter:
        def emit(self, value):
            emitted["val"] = value

    manager._bridge = cast(Any, SimpleNamespace(peq_ready=Emitter()))

    await manager._do_load_peq_preset("preset-name")

    assert wizard_controller.state.channel_mode == ChannelMode.LR
    assert wizard_controller.state.current_filters
    assert "val" in emitted


# Issue 100/Phase B3/Issue 150: validate_filters_for_device tests moved to
# test_wiim_generator.py (TestValidateFiltersForDevice) -- the function
# itself moved from src.gui.shared_helpers to src.translator.wiim_generator
# (no Qt dependency; it's business logic, not GUI code), and its tests
# moved with it to mirror the project's src/ <-> tests/ structure.


# Issue 98: PushPage.reset must clear stale DRY RUN content from previous runs
def test_pushpage_reset_clears_dry_run_badge(qtbot):
    page = PushPage()
    qtbot.addWidget(page)
    page.show()
    page.set_dry_run_result("Preview")
    assert page._status_badge.isVisible()
    page.reset()
    assert not page._status_badge.isVisible()


# Issue 151: PushPage's inline filter table didn't fit on screen alongside
# the result summary -- replaced with a "Show Pushed Filters" button that
# opens a dialog instead.
def test_pushpage_show_filters_button_visible_only_with_data(qtbot):
    page = PushPage()
    qtbot.addWidget(page)
    page.show()

    page.set_success("backup.json")
    assert not page._show_pushed_filters_button.isVisible()

    filters = [CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=1.0, q=1.0)]
    page.set_success("backup.json", filters=filters)
    assert page._show_pushed_filters_button.isVisible()

    page.set_failure("verification failed", "backup.json")
    assert not page._show_pushed_filters_button.isVisible()


def test_pushpage_show_filters_button_opens_dialog(qtbot, monkeypatch):
    page = PushPage()
    qtbot.addWidget(page)
    page.show()

    filters_l = [CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=1.0, q=1.0)]
    filters_r = [CanonicalFilter(type="PEAK", frequency_hz=200.0, gain_db=2.0, q=1.0)]
    page.set_success("backup.json", filters_l=filters_l, filters_r=filters_r)

    opened: list[Any] = []

    def fake_exec(self: QDialog) -> int:
        opened.append(self)
        return int(QDialog.DialogCode.Accepted)

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    page._on_show_pushed_filters_clicked()

    assert len(opened) == 1


# Issue 111 (superseded by #246 Stage 2 / PR #19 review D2): the sidebar
# device label now requests the read-only device-info popover instead of
# navigating to Connect -- the Connect pill covers navigation, and the
# popover gives the capability warning a real home.
def test_sidebar_device_header_click_requests_device_info(qtbot):
    nav = SidebarNav()
    qtbot.addWidget(nav)
    nav.set_device_info("Bedroom", connected=True)

    captured = {}

    def on_nav(key: str):
        captured["key"] = key

    nav.navigation_requested.connect(on_nav)

    from PySide6.QtCore import Qt

    qtbot.mouseClick(nav._device_label, Qt.MouseButton.LeftButton)

    assert captured.get("key") == "device_info"
    # No page change, so the active highlight is left alone
    assert nav._active_key == "home"


# Issue 89: UnsavedChangesDialog Cancel/Continue Working button should use no inline
# styles (styled entirely via QSS class) so it stays visible in dark theme.
def test_unsaved_changes_dialog_cancel_button_style(qtbot):
    from src.gui.dialogs.unsaved_changes_dialog import UnsavedChangesDialog

    dialog = UnsavedChangesDialog(None)
    qtbot.addWidget(dialog)

    cancel_btn = dialog.findChild(type(dialog._cancel_btn), "cancel_button")
    assert cancel_btn is not None
    assert cancel_btn.property("class") == "primary"
    assert cancel_btn.styleSheet() == ""


# Issue 90: Settings screen should populate default paths when settings are empty
def test_settings_apply_populates_default_paths(qtbot, tmp_path):
    from src.gui.app_settings import AppSettings
    from src.gui.main_window import MainWindow

    settings = AppSettings(log_directory="", presets_directory="", first_run_complete=True)

    with patch("src.gui.app_settings.AppSettings.load", return_value=settings):
        with patch("src.gui.main_window.get_app_data_dir", return_value=tmp_path):
            with patch("src.gui.main_window.get_log_dir", return_value=tmp_path / "logs"):
                mock_bridge = MagicMock()
                mock_bridge.run_async = MagicMock(side_effect=close_coroutine_tree)
                window = MainWindow(async_bridge=mock_bridge)
                qtbot.addWidget(window)

                current = window.settings_view.get_current_settings()
                assert current["log_directory"] == str(tmp_path / "logs")
                assert current["presets_directory"] == str(tmp_path)


# Issue 91 & 117: Onboarding overlay themes via QSS and has no Skip button
def test_onboarding_overlay_theme_and_no_skip(qtbot):
    """Overlay colors come from the QSS theme files (objectName-targeted), not Python.

    Regression note: this previously sniffed app.styleSheet() text for a dark-mode
    marker and applied colors via setStyleSheet() in Python. That hack was removed
    as part of the QSS decoupling refactor; theming is now handled entirely by the
    QLabel#onboarding_title selector in fluent_dark.qss / fluent_light.qss.

    Also guards against a regression where both theme files resolve
    QLabel#onboarding_title to the *same* color -- which would silently defeat
    the original bug's fix (overlay always looked like one theme) without
    breaking the "no inline stylesheet" / "selector exists" checks above.
    """
    import re
    from pathlib import Path

    from src.gui.dialogs.onboarding_overlay import OnboardingOverlay

    overlay = OnboardingOverlay(None)
    qtbot.addWidget(overlay)
    overlay.show()

    from PySide6.QtWidgets import QLabel

    title = overlay.findChild(QLabel, "onboarding_title")
    assert title is not None
    # No more per-widget inline stylesheet; QSS theme files own the styling now.
    assert title.styleSheet() == ""

    dark_qss = Path("src/gui/assets/styles/fluent_dark.qss").read_text(encoding="utf-8")
    light_qss = Path("src/gui/assets/styles/fluent_light.qss").read_text(encoding="utf-8")
    assert "QLabel#onboarding_title" in dark_qss
    assert "QLabel#onboarding_title" in light_qss

    def _onboarding_title_color(qss_text: str) -> str:
        """Extract the `color:` hex value from the QLabel#onboarding_title rule block."""
        match = re.search(
            r"QLabel#onboarding_title\s*\{([^}]*)\}", qss_text, re.DOTALL
        )
        assert match is not None, "QLabel#onboarding_title rule block not found"
        color_match = re.search(r"color:\s*(#[0-9A-Fa-f]{3,8})\s*;", match.group(1))
        assert color_match is not None, "no color: value in QLabel#onboarding_title block"
        return color_match.group(1).lower()

    dark_color = _onboarding_title_color(dark_qss)
    light_color = _onboarding_title_color(light_qss)
    # Regression guard: dark and light themes must resolve to visibly
    # different colors -- if they matched, the overlay would render
    # identically regardless of active theme (the original #91/#117 bug).
    assert dark_color != light_color

    # Skip button was removed; ensure no skip_button exists
    skip = overlay.findChild(QLabel, "skip_button")
    assert skip is None


# Issue 112: Help dialog should be a QDialog with native controls (visible window)
def test_help_dialog_is_dialog_and_visible(qtbot):
    from src.gui.main_window import MainWindow
    with patch.object(MainWindow, "_apply_settings", lambda self: None):
        mock_bridge = MagicMock()
        mock_bridge.run_async = MagicMock(side_effect=close_coroutine_tree)
        window = MainWindow(async_bridge=mock_bridge)
        qtbot.addWidget(window)

        window._on_user_guide_triggered()
        assert isinstance(window._help_dialog, QDialog)
        assert window._help_dialog.isVisible()
        window._help_dialog.close()


# Issue 114: StatusBanner close/dismiss button should be visible and appropriately sized
def test_status_banner_close_button_visibility_and_size(qtbot):
    from src.gui.components.status_banner import StatusBanner

    banner = StatusBanner()
    qtbot.addWidget(banner)
    banner.show_info("Testing", auto_dismiss=0)
    assert banner._close_button.isVisible()
    assert banner._close_button.text() == "Dismiss"
    assert banner._close_button.height() >= 22


# Issue 124 successor (#246 Stage 2, PR #19 review D2): the sidebar header's
# 'device_info' request shows the read-only device popover -- name, IP, and
# the capability warning, which previously only lived in a hijacked tooltip.
def test_navigation_device_info_shows_popover():
    from src.gui.main_window import MainWindow

    with patch.object(MainWindow, "_apply_settings", lambda self: None):
        mock_bridge = MagicMock()
        mock_bridge.run_async = MagicMock(side_effect=close_coroutine_tree)
        window = MainWindow(async_bridge=mock_bridge)

        window._wizard_controller.state.selected_device = "192.168.1.50"
        with patch("PySide6.QtWidgets.QMessageBox.information") as info:
            window._on_navigation_requested("device_info")

        assert info.call_count == 1
        text = info.call_args.args[2]
        assert "192.168.1.50" in text

        # No device connected -> header is disabled anyway, but the handler
        # must stay a silent no-op if reached.
        window._wizard_controller.state.selected_device = None
        with patch("PySide6.QtWidgets.QMessageBox.information") as info:
            window._on_navigation_requested("device_info")
        assert info.call_count == 0


# Fix: sidebar "Back" from a secondary view (e.g. Settings) while the wizard
# is sitting on a completed PUSH/dry-run page must redisplay that page as-is,
# not reset it. _on_step_changed resets the Push page as an entry side
# effect, which is correct for a real step transition but wrong for "Back"
# just redisplaying the current step.
def test_sidebar_back_from_secondary_view_preserves_push_dry_run_result(qtbot):
    from src.gui.main_window import PAGE_INDICES, MainWindow

    with patch.object(MainWindow, "_apply_settings", lambda self: None):
        mock_bridge = MagicMock()
        mock_bridge.run_async = MagicMock(side_effect=close_coroutine_tree)
        window = MainWindow(async_bridge=mock_bridge)
        qtbot.addWidget(window)
        window.show()

        # Reach PUSH the way a real session does: every prior step is
        # completed, so PUSH is the frontier -- "Resume Setup" must then
        # redisplay it rather than jumping (and resetting) anything.
        ctrl = window._wizard_controller
        for step in ctrl.get_steps()[:-1]:
            ctrl.set_step_summary(step, "done")
        ctrl.go_to_step(WizardStep.PUSH)
        window._push_page.set_dry_run_result("3 filters mapped")
        assert window._push_page._status_badge.isVisible()

        # User navigates to Settings via sidebar, then clicks "Back"
        window._stacked_widget.setCurrentIndex(PAGE_INDICES["settings"])
        window._on_navigation_requested("home")

        assert window._stacked_widget.currentIndex() == PAGE_INDICES["push"]
        assert window._push_page._status_badge.isVisible()


# Fix: secondary pages (e.g. Presets on Device) could render squished on
# their first visit after a fresh launch since QStackedLayout only resizes
# its *current* widget — every other page kept its construction-time
# geometry until first navigated to. _warm_up_stacked_pages resizes every
# page up front so this can't happen, without touching visibility (so it
# must not double-fire ConnectPage's showEvent-driven discovery).
def test_warm_up_stacked_pages_resizes_every_page_without_reshowing(qtbot):
    from src.gui.main_window import MainWindow

    with patch.object(MainWindow, "_apply_settings", lambda self: None):
        mock_bridge = MagicMock()
        mock_bridge.run_async = MagicMock(side_effect=close_coroutine_tree)
        window = MainWindow(async_bridge=mock_bridge)
        qtbot.addWidget(window)
        window.resize(1000, 700)
        window.show()

        refresh_calls = []
        window._connect_page.refresh_requested.connect(
            lambda: refresh_calls.append(1)
        )

        for i in range(window._stacked_widget.count()):
            page = window._stacked_widget.widget(i)
            if page is not None:
                page.resize(1, 1)

        window._warm_up_stacked_pages()

        target_size = window._stacked_widget.size()
        for i in range(window._stacked_widget.count()):
            page = window._stacked_widget.widget(i)
            if page is not None:
                assert page.size() == target_size
        assert refresh_calls == []


# Fix: issue #141's one-time _warm_up_stacked_pages() call only protects a
# page's geometry up to the moment it fires — QStackedLayout keeps resizing
# only the *current* widget on every later window resize too, so a page
# that sits non-current through a resize (visit while empty, navigate away,
# window settles, revisit once populated) can go stale again despite having
# been warmed up once already. _resync_current_page_geometry, wired to
# QStackedWidget.currentChanged, re-applies the same resize + full layout
# re-activation every time *any* page becomes current, not just at startup
# — a stronger guarantee than relying on QStackedLayout's own switch-time
# resize, which does not force nested layouts to recompute.
def test_resync_current_page_geometry_resizes_and_reactivates_layout(qtbot):
    from src.gui.main_window import PAGE_INDICES, MainWindow

    with patch.object(MainWindow, "_apply_settings", lambda self: None):
        mock_bridge = MagicMock()
        mock_bridge.run_async = MagicMock(side_effect=close_coroutine_tree)
        window = MainWindow(async_bridge=mock_bridge)
        qtbot.addWidget(window)
        window.resize(1000, 700)
        window.show()

        presets_page = window._presets_device_view
        presets_page.resize(1, 1)

        window._resync_current_page_geometry(PAGE_INDICES["presets_device"])

        assert presets_page.size() == window._stacked_widget.size()


# Fix: currentChanged fires on every navigation, including the many
# existing setCurrentIndex() call sites scattered across MainWindow — the
# hook must be a no-op (not raise) for an out-of-range index rather than
# assuming the index always maps to a real widget.
def test_resync_current_page_geometry_ignores_invalid_index(qtbot):
    from src.gui.main_window import MainWindow

    with patch.object(MainWindow, "_apply_settings", lambda self: None):
        mock_bridge = MagicMock()
        mock_bridge.run_async = MagicMock(side_effect=close_coroutine_tree)
        window = MainWindow(async_bridge=mock_bridge)
        qtbot.addWidget(window)

        window._resync_current_page_geometry(-1)


# Fix: jumping directly to Review from a sidebar load (e.g. "Load into
# Editor" from Presets on Device / My Presets) bypasses
# wizard_controller.advance()/go_to_step(), so step_changed never fires and
# _on_step_changed's set_current() call — the only place that normally syncs
# the StepIndicator's highlighted pill — is skipped. Without an explicit
# set_current() call in this branch, Review renders with no step highlighted.
def test_sidebar_load_into_review_highlights_review_step(qtbot):
    from src.gui.main_window import PAGE_INDICES, MainWindow
    from src.models.canonical import CanonicalFilter

    with patch.object(MainWindow, "_apply_settings", lambda self: None):
        mock_bridge = MagicMock()
        mock_bridge.run_async = MagicMock(side_effect=close_coroutine_tree)
        window = MainWindow(async_bridge=mock_bridge)
        qtbot.addWidget(window)

        state = window._wizard_controller.state
        state.selected_device = "device-1"
        state.selected_source = "wifi"
        state.current_filters = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=1.0, q=1.0)
        ]

        window._sidebar_load_in_progress = True
        window._on_peq_ready(SimpleNamespace())

        assert window._stacked_widget.currentIndex() == PAGE_INDICES["review"]

        sequence = window._wizard_controller.get_steps()
        review_index = sequence.index(WizardStep.REVIEW)
        assert window._step_indicator._view_index == review_index
        assert window._step_indicator._steps[review_index]._dimmed is False


# Fix: a sidebar load that resolves to zero filters (count == 0 in
# _on_peq_ready) never reset _sidebar_load_in_progress -- only the count > 0
# branch did. Left stuck True, the flag would corrupt the *next*, unrelated
# peq_ready by jumping straight to Review instead of advancing normally.
def test_sidebar_load_empty_filters_resets_sidebar_load_flag(qtbot):
    from src.gui.main_window import MainWindow

    with patch.object(MainWindow, "_apply_settings", lambda self: None):
        mock_bridge = MagicMock()
        mock_bridge.run_async = MagicMock(side_effect=close_coroutine_tree)
        window = MainWindow(async_bridge=mock_bridge)
        qtbot.addWidget(window)

        state = window._wizard_controller.state
        state.selected_device = "device-1"
        state.current_filters = []

        window._sidebar_load_in_progress = True
        window._on_peq_ready(SimpleNamespace())

        assert window._sidebar_load_in_progress is False


# Fix: "My Saved Presets" Load goes through a *different* handler
# (_on_profile_recalled, via SecondaryWorkflowManager.recall_profile) than
# Presets-on-Device / sidebar-"Pull from REW" Load (_on_peq_ready) — #144
# only patched the latter, so loading from My Saved Presets still landed on
# Review with no step-indicator pill highlighted, and (additionally) never
# reset the sidebar highlight back to "home", leaving "My Saved Presets"
# highlighted even though Review was now on screen.
def test_profile_recalled_from_my_presets_highlights_review_and_resets_sidebar(qtbot):
    from src.gui.main_window import PAGE_INDICES, MainWindow
    from src.models.canonical import CanonicalFilter

    with patch.object(MainWindow, "_apply_settings", lambda self: None):
        mock_bridge = MagicMock()
        mock_bridge.run_async = MagicMock(side_effect=close_coroutine_tree)
        window = MainWindow(async_bridge=mock_bridge)
        qtbot.addWidget(window)

        state = window._wizard_controller.state
        state.selected_device = "device-1"
        state.selected_source = "wifi"

        # Simulate having been on "My Saved Presets" (sidebar highlighted there)
        window._sidebar_nav.set_active_key("my_presets")

        window._on_profile_recalled(
            [CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=1.0, q=1.0)]
        )

        assert window._stacked_widget.currentIndex() == PAGE_INDICES["review"]

        sequence = window._wizard_controller.get_steps()
        review_index = sequence.index(WizardStep.REVIEW)
        assert window._step_indicator._view_index == review_index
        assert window._step_indicator._steps[review_index]._dimmed is False
        assert window._sidebar_nav.active_key == "home"


# Fix: clicking a step-indicator pill (a finished/completed step) while
# viewing a sidebar destination (Presets on Device, My Saved Presets,
# Settings, sidebar Pull from REW) left *both* the sidebar item and the
# step pill highlighted at once — _on_step_indicator_clicked routes through
# wizard_controller.go_to_step(), which only ever touched the step
# indicator, never the sidebar highlight. This was the same root cause as
# #138/#142/#144/#147 (a navigation path forgetting to sync sidebar +
# step-indicator chrome) recurring on yet another path, which is why the
# fix is now a single handler (_sync_navigation_chrome, wired to
# QStackedWidget.currentChanged) instead of one more hand-added call.
def test_step_indicator_click_from_sidebar_destination_resets_sidebar_highlight(qtbot):
    from src.gui.main_window import PAGE_INDICES, MainWindow

    with patch.object(MainWindow, "_apply_settings", lambda self: None):
        mock_bridge = MagicMock()
        mock_bridge.run_async = MagicMock(side_effect=close_coroutine_tree)
        window = MainWindow(async_bridge=mock_bridge)
        qtbot.addWidget(window)

        # Viewing a sidebar destination — sidebar highlighted there, step
        # pill dimmed.
        window._on_navigation_requested("presets_device")
        assert window._sidebar_nav.active_key == "presets_device"
        assert window._step_indicator._steps[window._step_indicator._view_index]._dimmed

        # Click the first (CONNECT) step pill, as if jumping back to a
        # finished step from within a sidebar destination.
        window._on_step_indicator_clicked(0)

        assert window._stacked_widget.currentIndex() == PAGE_INDICES["connect"]
        assert window._sidebar_nav.active_key == "home"
        assert window._step_indicator._view_index == 0
        assert not window._step_indicator._steps[0]._dimmed


# Fix: a capability probe for a superseded device selection must not advance
# the wizard. Without the generation guard, reselecting a device while the
# previous probe is still in flight could let the stale probe's
# capabilities_ready.emit still fire, double-advancing the wizard / marking
# the wrong step "Connected".
@pytest.mark.asyncio
async def test_stale_capability_probe_is_discarded():
    from unittest.mock import AsyncMock

    from src.gui.main_window import MainWindow

    with patch.object(MainWindow, "_apply_settings", lambda self: None):
        mock_bridge = MagicMock()
        mock_bridge.run_async = MagicMock(side_effect=close_coroutine_tree)
        window = MainWindow(async_bridge=mock_bridge)

        stale_prober = SimpleNamespace(probe=AsyncMock(return_value=MagicMock()))
        # snapshot before "reselection"
        stale_generation = window._primary_workflows._probe_generation
        # simulates a newer _on_device_selected call
        window._primary_workflows.bump_probe_generation()

        await window._primary_workflows._do_probe(cast(Any, stale_prober), stale_generation)

        mock_bridge.capabilities_ready.emit.assert_not_called()
