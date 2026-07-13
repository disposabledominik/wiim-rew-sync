"""Unit tests for MainWindow settings wiring (task 12.2).

Verifies:
- Theme applied on startup based on saved preference
- Sidebar collapsed state from settings
- Dry Run default from settings
- Onboarding overlay shown when first_run_complete is False
- SettingsView signals trigger persistence
- OnboardingOverlay signals update settings
- Help > User Guide navigates to help view
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.gui.app_settings import AppSettings
from src.gui.main_window import PAGE_INDICES, MainWindow
from src.tests.conftest import close_coroutine_tree


@pytest.fixture()
def mock_bridge() -> MagicMock:
    """Create a MagicMock async bridge with expected signal attributes."""
    bridge = MagicMock()
    bridge.start = MagicMock()
    bridge.shutdown = MagicMock()
    bridge.run_async = MagicMock(side_effect=close_coroutine_tree)
    return bridge


@pytest.fixture()
def default_settings(tmp_path) -> AppSettings:
    """Return fresh default settings that write to tmp_path."""
    with patch("src.gui.app_settings.get_app_data_dir", return_value=tmp_path):
        return AppSettings()


@pytest.fixture()
def make_window(qtbot, mock_bridge, tmp_path):
    """Factory fixture to create MainWindow with custom settings."""

    windows = []

    def _factory(settings: AppSettings | None = None) -> MainWindow:
        if settings is None:
            settings = AppSettings()

        with (
            patch("src.gui.app_settings.AppSettings.load", return_value=settings),
            patch("src.gui.app_settings.AppSettings.save"),
        ):
            window = MainWindow(async_bridge=mock_bridge)
            qtbot.addWidget(window)
            windows.append(window)
            return window

    yield _factory

    for w in windows:
        w._wizard_controller.state.current_filters = []
        w.close()


class TestApplySettingsOnStartup:
    """Settings are applied when MainWindow initializes."""

    def test_sidebar_collapsed_from_settings(self, make_window) -> None:
        """Sidebar collapsed state matches settings value."""
        settings = AppSettings(sidebar_collapsed=True)
        window = make_window(settings)
        assert window.sidebar_nav.collapsed is True

    def test_sidebar_expanded_by_default(self, make_window) -> None:
        """Sidebar is expanded when settings say so."""
        settings = AppSettings(sidebar_collapsed=False)
        window = make_window(settings)
        assert window.sidebar_nav.collapsed is False

    def test_dry_run_default_applied_to_review_page(self, make_window) -> None:
        """ReviewPage dry run toggle is set from settings.dry_run_default."""
        settings = AppSettings(dry_run_default=True)
        window = make_window(settings)
        assert window.review_page._dry_run is True

    def test_dry_run_disabled_when_setting_is_false(self, make_window) -> None:
        """ReviewPage dry run is off when settings say False."""
        settings = AppSettings(dry_run_default=False)
        window = make_window(settings)
        assert window.review_page._dry_run is False

    def test_onboarding_shown_when_first_run_not_complete(self, make_window) -> None:
        """Onboarding overlay is visible when first_run_complete is False."""
        settings = AppSettings(first_run_complete=False)
        window = make_window(settings)
        # Widget visibility is relative to parent; use isVisibleTo for unshown windows
        assert window.onboarding_overlay.isVisibleTo(window) is True

    def test_onboarding_hidden_when_first_run_complete(self, make_window) -> None:
        """Onboarding overlay is hidden when first_run_complete is True."""
        settings = AppSettings(first_run_complete=True)
        window = make_window(settings)
        assert window.onboarding_overlay.isVisibleTo(window) is False

    def test_theme_manager_created(self, make_window) -> None:
        """ThemeManager is created during _apply_settings."""
        window = make_window()
        assert hasattr(window, "_theme_manager")

    def test_settings_view_populated(self, make_window) -> None:
        """SettingsView is populated with current settings values."""
        settings = AppSettings(theme="Dark", discovery_timeout=10)
        window = make_window(settings)
        current = window.settings_view.get_current_settings()
        assert current["theme"] == "Dark"
        assert current["discovery_timeout"] == 10


class TestSettingsViewSignalWiring:
    """SettingsView signals update AppSettings and persist."""

    def test_theme_changed_updates_settings(self, make_window) -> None:
        """Theme change from SettingsView persists to AppSettings."""
        window = make_window()
        with patch.object(window._settings, "save") as mock_save:
            window._settings_view.theme_changed.emit("Dark")
            assert window._settings.theme == "Dark"
            mock_save.assert_called()

    def test_settings_changed_updates_fields(self, make_window) -> None:
        """General settings change persists updated fields."""
        window = make_window()
        with patch.object(window._settings, "save") as mock_save:
            window._settings_view.settings_changed.emit({
                "log_directory": "/new/logs",
                "presets_directory": "/new/presets",
                "rew_folder": "/new/rew",
                "discovery_timeout": 15,
                "dry_run_default": False,
            })
            assert window._settings.log_directory == "/new/logs"
            assert window._settings.presets_directory == "/new/presets"
            assert window._settings.rew_folder == "/new/rew"
            assert window._settings.discovery_timeout == 15
            assert window._settings.dry_run_default is False
            mock_save.assert_called()

    def test_show_onboarding_requested_shows_overlay(self, make_window) -> None:
        """Show onboarding requested from Settings > Support shows overlay."""
        settings = AppSettings(first_run_complete=True)
        window = make_window(settings)
        # Overlay should be hidden initially
        assert window.onboarding_overlay.isVisibleTo(window) is False
        # Emit the signal
        window._settings_view.show_onboarding_requested.emit()
        assert window.onboarding_overlay.isVisibleTo(window) is True


class TestOnboardingSignalWiring:
    """OnboardingOverlay signals update settings and navigate."""

    def test_get_started_marks_first_run_complete(self, make_window) -> None:
        """Get Started sets first_run_complete=True and saves."""
        settings = AppSettings(first_run_complete=False)
        window = make_window(settings)
        with patch.object(window._settings, "save") as mock_save:
            window._onboarding_overlay.get_started_clicked.emit()
            assert window._settings.first_run_complete is True
            mock_save.assert_called()

    def test_get_started_navigates_to_connect(self, make_window) -> None:
        """Get Started navigates to the connect page."""
        settings = AppSettings(first_run_complete=False)
        window = make_window(settings)
        with patch.object(window._settings, "save"):
            window._onboarding_overlay.get_started_clicked.emit()
            assert window.stacked_widget.currentIndex() == PAGE_INDICES["connect"]

    def test_skip_marks_first_run_complete(self, make_window) -> None:
        """Skip sets first_run_complete=True and saves."""
        settings = AppSettings(first_run_complete=False)
        window = make_window(settings)
        with patch.object(window._settings, "save") as mock_save:
            window._onboarding_overlay.skip_clicked.emit()
            assert window._settings.first_run_complete is True
            mock_save.assert_called()

    def test_get_started_invalidates_all_completed_steps(self, make_window) -> None:
        """Re-entering onboarding via Get Started must not leave a later step
        checked while Connect (which precedes it in every flow) is not.

        Reproduces the "Show onboarding again" -> "Get Started" bug: with
        every step completed from a prior run, Get Started must invalidate
        Connect *and everything after it* so no checked step ever follows an
        unchecked one (#reported: Connect loses its checkmark/context while
        later steps stay checked with stale data).
        """
        from src.gui.wizard_controller import WizardStep

        settings = AppSettings(first_run_complete=True)
        window = make_window(settings)
        controller = window._wizard_controller
        sequence = controller.get_steps()
        for step in sequence:
            controller.set_step_summary(step, f"{step.value} summary")
        assert set(controller.completed_steps) == set(sequence)

        with patch.object(window._settings, "save"):
            window._onboarding_overlay.get_started_clicked.emit()

        assert controller.completed_steps == {}
        assert controller.current_step == WizardStep.CONNECT
        assert window.stacked_widget.currentIndex() == PAGE_INDICES["connect"]


class TestUserGuideAction:
    """Help > User Guide opens help dialog window."""

    def test_user_guide_switches_to_help_view(self, make_window) -> None:
        """Triggering user guide action opens the help dialog window."""
        window = make_window()
        window._on_user_guide_triggered()
        assert window._help_dialog.isVisible()
        window._help_dialog.close()


class TestDryRunDefaultPrompt:
    """Toggling Dry Run off while it's still the global default offers to
    disable that default too (smoke #182) -- non-technical users are
    unlikely to find this setting in Settings on their own."""

    def test_no_prompt_when_default_already_false(self, make_window) -> None:
        """No prompt when dry_run_default is already off."""
        settings = AppSettings(dry_run_default=False)
        window = make_window(settings)

        with patch(
            "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm"
        ) as mock_question:
            window._on_dry_run_toggled(False)

        mock_question.assert_not_called()

    def test_no_prompt_when_toggled_on(self, make_window) -> None:
        """No prompt when the checkbox is turned on (only turning off matters)."""
        settings = AppSettings(dry_run_default=True)
        window = make_window(settings)

        with patch(
            "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm"
        ) as mock_question:
            window._on_dry_run_toggled(True)

        mock_question.assert_not_called()

    def test_prompt_shown_when_toggled_off_while_default_true(self, make_window) -> None:
        """Prompt appears the first time Dry Run is turned off while it's
        still the global default."""
        settings = AppSettings(dry_run_default=True)
        window = make_window(settings)

        with patch(
            "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
            return_value=False,
        ) as mock_question:
            window._on_dry_run_toggled(False)

        mock_question.assert_called_once()
        assert window._settings.dry_run_default is True

    def test_answering_yes_disables_default_and_persists(self, make_window) -> None:
        """Accepting the prompt disables the global default, persists it, and
        refreshes SettingsView so it doesn't go stale."""
        settings = AppSettings(dry_run_default=True)
        window = make_window(settings)

        with (
            patch.object(window._settings, "save") as mock_save,
            patch(
                "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
                return_value=True,
            ),
        ):
            window._on_dry_run_toggled(False)

        assert window._settings.dry_run_default is False
        mock_save.assert_called_once()
        assert window.settings_view.get_current_settings()["dry_run_default"] is False
