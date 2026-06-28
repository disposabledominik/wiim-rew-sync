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
from src.gui.shared_helpers import validate_filters_for_device
from src.gui.wizard_controller import FlowType, WizardController, WizardState, WizardStep
from src.logging.setup import configure_logging, install_crash_handler
from src.models import constants as model_constants
from src.models.canonical import CanonicalFilter
from src.models.channel_mode import ChannelMode
from src.tests.conftest import close_coroutine_tree
from src.translator._warnings import FilterRow, SkippedBand


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
    func = main_window.MainWindow._mark_prior_steps_completed

    dummy_self = SimpleNamespace()
    dummy_self._wizard_controller = SimpleNamespace(flow_type=FlowType.PEQ)

    state = WizardState()
    state.selected_device = "device-1"

    func(dummy_self, state)

    assert WizardStep.CONNECT in state.completed_steps
    assert state.completed_steps[WizardStep.CONNECT] == "Connected"
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
    func = main_window.MainWindow._do_load_peq_preset

    dummy_self = SimpleNamespace()

    class DummyAdapter:
        async def load_peq_profile(self, source_name, preset_name):
            return None

        async def read_peq(self, source_name):
            return SimpleNamespace(
                channel_mode=ChannelMode.LR,
                bands_l=[CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=1.0, q=1.0)],
                bands_r=[CanonicalFilter(type="PEAK", frequency_hz=200.0, gain_db=0.5, q=1.0)],
            )

    dummy_self._wiim_adapter = DummyAdapter()
    dummy_self._wizard_controller = SimpleNamespace(state=WizardState())

    emitted = {}

    class Emitter:
        def emit(self, value):
            emitted["val"] = value

    dummy_self._bridge = SimpleNamespace(peq_ready=Emitter())

    await func(dummy_self, "preset-name")

    assert dummy_self._wizard_controller.state.channel_mode == ChannelMode.LR
    assert dummy_self._wizard_controller.state.current_filters
    assert "val" in emitted


# Issue 100: validate_filters_for_device should truncate to device max and flag clamped bands
def test_validate_filters_for_device_truncation_and_clamping():
    filters = []
    for i in range(12):
        freq = 100.0 + i
        gain = 20.0 if i % 2 == 0 else -20.0
        q_val = 100.0 if i % 3 == 0 else 0.001
        filters.append(
            CanonicalFilter(
                type="PEAK",
                frequency_hz=freq,
                gain_db=gain,
                q=q_val,
            )
        )

    truncated, warnings, clamping_map, rows = validate_filters_for_device(filters, max_filters=10)
    assert len(truncated) == 10
    assert any("Only the first" in w for w in warnings)
    assert clamping_map
    assert rows


# Phase B3: bands cut for exceeding the device's band cap render as disabled
# placeholders (not silently dropped), preserving their original position.
def test_validate_filters_for_device_truncated_bands_become_skipped_rows():
    filters = [
        CanonicalFilter(type="PEAK", frequency_hz=100.0 + i, gain_db=1.0, q=1.0)
        for i in range(12)
    ]

    _truncated, _warnings, _clamping_map, rows = validate_filters_for_device(
        filters, max_filters=10
    )

    assert len(rows) == 12
    kept, cut = rows[:10], rows[10:]
    assert all(isinstance(r, CanonicalFilter) for r in kept)
    assert all(isinstance(r, SkippedBand) for r in cut)
    first_cut = cut[0]
    assert isinstance(first_cut, SkippedBand)
    assert first_cut.original_type == "PEAK"
    assert "10-band limit" in first_cut.reason
    # Truncated bands keep their original values for display
    assert first_cut.frequency_hz == filters[10].frequency_hz


def test_validate_filters_for_device_preserves_parser_skip_rows():
    """Skip placeholders from the parser survive truncation untouched."""
    filters = [CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=1.0, q=1.0)]
    skip = SkippedBand(original_type="Notch", reason="No WiiM equivalent")
    rows_in: list[FilterRow] = [skip, filters[0]]

    _truncated, _warnings, _clamping_map, rows_out = validate_filters_for_device(
        filters, max_filters=10, rows=rows_in
    )

    assert rows_out == [skip, filters[0]]


# Issue 98: PushPage.reset must clear stale DRY RUN content from previous runs
def test_pushpage_reset_clears_dry_run_badge(qtbot):
    page = PushPage()
    qtbot.addWidget(page)
    page.show()
    page.set_dry_run_result("Preview")
    assert page._dry_run_badge.isVisible()
    page.reset()
    assert not page._dry_run_badge.isVisible()


# Issue 111: Sidebar device label click should emit 'connect' and set home active
def test_sidebar_device_header_click_emits_connect_and_sets_home_active(qtbot):
    nav = SidebarNav()
    qtbot.addWidget(nav)
    nav.set_device_info("Bedroom", connected=True)

    captured = {}

    def on_nav(key: str):
        captured["key"] = key

    nav.navigation_requested.connect(on_nav)

    from PySide6.QtCore import Qt

    qtbot.mouseClick(nav._device_label, Qt.MouseButton.LeftButton)

    assert captured.get("key") == "connect"
    assert nav._active_key == "home"


# Issue 89: UnsavedChangesDialog Cancel button should use ghost class and no inline styles
def test_unsaved_changes_dialog_cancel_button_style(qtbot):
    from src.gui.dialogs.unsaved_changes_dialog import UnsavedChangesDialog

    dialog = UnsavedChangesDialog(None)
    qtbot.addWidget(dialog)

    cancel_btn = dialog.findChild(type(dialog._cancel_btn), "cancel_button")
    assert cancel_btn is not None
    assert cancel_btn.property("class") == "ghost"
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
    """
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
    assert "QLabel#onboarding_title" in dark_qss

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


# Issue 124: Navigation to 'connect' should call wizard_controller.go_to_step(CONNECT)
def test_navigation_connect_uses_wizard_go_to_step():
    from src.gui.main_window import MainWindow
    with patch.object(MainWindow, "_apply_settings", lambda self: None):
        mock_bridge = MagicMock()
        mock_bridge.run_async = MagicMock(side_effect=close_coroutine_tree)
        window = MainWindow(async_bridge=mock_bridge)

        called: dict[str, WizardStep] = {}

        class FakeWizard:
            def go_to_step(self, step: WizardStep) -> None:
                called["step"] = step

        window._wizard_controller = cast(WizardController, FakeWizard())
        window._on_navigation_requested("connect")
        assert called.get("step") == WizardStep.CONNECT


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

        window._wizard_controller.go_to_step(WizardStep.PUSH)
        window._push_page.set_dry_run_result("3 filters mapped")
        assert window._push_page._dry_run_badge.isVisible()

        # User navigates to Settings via sidebar, then clicks "Back"
        window._stacked_widget.setCurrentIndex(PAGE_INDICES["settings"])
        window._on_navigation_requested("home")

        assert window._stacked_widget.currentIndex() == PAGE_INDICES["push"]
        assert window._push_page._dry_run_badge.isVisible()


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
        assert window._step_indicator._current_index == review_index
        assert window._step_indicator._steps[review_index]._dimmed is False


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
        assert window._step_indicator._current_index == review_index
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
        assert window._step_indicator._steps[window._step_indicator._current_index]._dimmed

        # Click the first (CONNECT) step pill, as if jumping back to a
        # finished step from within a sidebar destination.
        window._on_step_indicator_clicked(0)

        assert window._stacked_widget.currentIndex() == PAGE_INDICES["connect"]
        assert window._sidebar_nav.active_key == "home"
        assert window._step_indicator._current_index == 0
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
        stale_generation = window._probe_generation  # snapshot before "reselection"
        window._probe_generation += 1  # simulates a newer _on_device_selected call

        await window._do_probe(cast(Any, stale_prober), stale_generation)

        mock_bridge.capabilities_ready.emit.assert_not_called()
