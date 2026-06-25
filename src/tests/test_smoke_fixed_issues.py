import logging
import sys
from types import SimpleNamespace
from typing import cast
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

    truncated, warnings, clamping_map = validate_filters_for_device(filters, max_filters=10)
    assert len(truncated) == 10
    assert any("Only the first" in w for w in warnings)
    assert clamping_map


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
                window = MainWindow(async_bridge=mock_bridge)
                qtbot.addWidget(window)

                current = window.settings_view.get_current_settings()
                assert current["log_directory"] == str(tmp_path / "logs")
                assert current["presets_directory"] == str(tmp_path)


# Issue 91 & 117: Onboarding overlay rebuilds for dark theme and has no Skip button
def test_onboarding_overlay_theme_and_no_skip(qtbot):
    from PySide6.QtWidgets import QApplication

    from src.gui.constants import COLORS_DARK
    from src.gui.dialogs.onboarding_overlay import OnboardingOverlay

    app = cast(QApplication, QApplication.instance())
    assert app is not None

    # Simulate dark theme via stylesheet detection string
    app.setStyleSheet("background-color: #1E1E1E;")

    overlay = OnboardingOverlay(None)
    qtbot.addWidget(overlay)
    overlay.show()

    from PySide6.QtWidgets import QLabel

    title = overlay.findChild(QLabel, "onboarding_title")
    assert title is not None
    assert COLORS_DARK.text_primary in title.styleSheet()

    # Skip button was removed; ensure no skip_button exists
    skip = overlay.findChild(QLabel, "skip_button")
    assert skip is None


# Issue 112: Help dialog should be a QDialog with native controls (visible window)
def test_help_dialog_is_dialog_and_visible(qtbot):
    from src.gui.main_window import MainWindow
    with patch.object(MainWindow, "_apply_settings", lambda self: None):
        mock_bridge = MagicMock()
        window = MainWindow(async_bridge=mock_bridge)
        qtbot.addWidget(window)

        window._on_user_guide_triggered()
        assert isinstance(window._help_dialog, QDialog)
        assert window._help_dialog.isVisible()


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
        window = MainWindow(async_bridge=mock_bridge)

        called: dict[str, WizardStep] = {}

        class FakeWizard:
            def go_to_step(self, step: WizardStep) -> None:
                called["step"] = step

        window._wizard_controller = cast(WizardController, FakeWizard())
        window._on_navigation_requested("connect")
        assert called.get("step") == WizardStep.CONNECT
