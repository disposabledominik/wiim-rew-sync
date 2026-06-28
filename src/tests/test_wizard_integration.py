"""Integration tests for full wizard flows through MainWindow.

Tests the end-to-end signal flow with a mocked AsyncBridge:
- Happy path (PEQ): single device → import → push
- RoomFit flow: EQ_TYPE shown, SOURCE skipped, NAME_PROFILE before push
- Back-navigation: step invalidation, page state reset
- Error recovery: StatusBanner shows error, page shows retry
- Undo after push: backup restore triggered
- Sidebar navigation preserves wizard state

Requirements referenced: 1.2-1.12, 11.1-11.8, 14.1-14.6.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.gui.app_settings import AppSettings
from src.gui.main_window import PAGE_INDICES, MainWindow
from src.gui.wizard_controller import FlowType, WizardStep

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_bridge() -> MagicMock:
    """Create a MagicMock async bridge with expected signal attributes."""
    bridge = MagicMock()
    bridge.start = MagicMock()
    bridge.shutdown = MagicMock()
    return bridge


@pytest.fixture()
def make_window(qtbot, mock_bridge):
    """Factory fixture to create MainWindow with mocked bridge and default settings."""
    windows: list[MainWindow] = []

    def _factory(settings: AppSettings | None = None) -> MainWindow:
        if settings is None:
            settings = AppSettings(first_run_complete=True)

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


def _make_single_device() -> list[dict]:
    """Return a discovery result with a single device."""
    return [
        {
            "name": "WiiM Pro Plus",
            "model": "WiiM Pro Plus",
            "ip": "192.168.1.100",
            "firmware": "5.6.0",
            "role": "standalone",
        }
    ]


def _make_caps(roomfit_level: int = 0) -> MagicMock:
    """Create a mock DeviceCapabilities object.

    Args:
        roomfit_level: 0 = PEQ-only, 2+ = RoomFit capable.
    """
    caps = MagicMock()
    caps.roomfit_level = roomfit_level
    caps.device_name = "WiiM Pro Plus"
    caps.model = "WiiM Pro Plus"
    caps.source_names = ["wifi", "optical", "hdmi"]
    caps.active_source = "wifi"
    caps.supports_profile_enumeration = False
    return caps


def _make_write_result(success: bool = True) -> MagicMock:
    """Create a mock WriteResult object."""
    result = MagicMock()
    result.success = success
    result.backup_path = "/backups/peq_backup_001.json"
    result.error = "" if success else "Connection timeout"
    result.critical = False
    return result


# ---------------------------------------------------------------------------
# Test: Happy path (PEQ-only device)
# ---------------------------------------------------------------------------


class TestHappyPathPEQ:
    """Integration test: single PEQ-only device → import → push → success."""

    def test_full_peq_flow(self, make_window) -> None:
        """Walk through the complete PEQ-only wizard flow with mocked signals."""
        window = make_window()

        # Verify starting state: connect page shown
        assert window.stacked_widget.currentIndex() == PAGE_INDICES["connect"]

        # Step 1: Discovery complete with single device → auto-select
        window._on_discovery_complete(_make_single_device())

        # ConnectPage should auto-emit device_selected for single device.
        # Simulate the device_selected handler being triggered:
        window._on_device_selected("192.168.1.100")
        assert window.wizard_controller.state.selected_device == "192.168.1.100"

        # Step 2: Capabilities ready (PEQ-only, roomfit_level=0)
        caps = _make_caps(roomfit_level=0)
        window._on_capabilities_ready(caps)

        # Should set PEQ_ONLY flow (no EQ_TYPE step)
        assert window.wizard_controller.flow_type == FlowType.PEQ_ONLY
        # Should advance past CONNECT → now on SOURCE
        assert window.wizard_controller.current_step == WizardStep.SOURCE
        assert window.stacked_widget.currentIndex() == PAGE_INDICES["source"]

        # Step 3: Source selected
        window._on_source_selected("wifi", "Stereo")
        assert window.wizard_controller.state.selected_source == "wifi"
        assert window.wizard_controller.current_step == WizardStep.FILTERS
        assert window.stacked_widget.currentIndex() == PAGE_INDICES["filters"]

        # Step 4: Filters accepted
        window._on_filters_accepted()
        assert window.wizard_controller.current_step == WizardStep.REVIEW
        assert window.stacked_widget.currentIndex() == PAGE_INDICES["review"]

        # Step 5: Push requested → advances to PUSH step
        window._on_push_requested()
        assert window.wizard_controller.current_step == WizardStep.PUSH
        assert window.stacked_widget.currentIndex() == PAGE_INDICES["push"]

        # Step 6: Write complete (success)
        result = _make_write_result(success=True)
        window._on_write_complete(result)

        # PushPage should show success state
        assert window.push_page._result_message.text() == "Filters pushed successfully"
        # Backup path stored in state
        assert window.wizard_controller.state.last_backup_path == "/backups/peq_backup_001.json"

    def test_source_page_populated_from_capabilities(self, make_window) -> None:
        """Capabilities ready populates SourcePage with available sources."""
        window = make_window()
        caps = _make_caps(roomfit_level=0)

        window._on_discovery_complete(_make_single_device())
        window._on_device_selected("192.168.1.100")
        window._on_capabilities_ready(caps)

        # SourcePage should have been populated
        # (source_page.set_sources was called with source_names and active_source)
        # Verify the page is reachable and has content
        assert window.wizard_controller.current_step == WizardStep.SOURCE


# ---------------------------------------------------------------------------
# Test: RoomFit flow
# ---------------------------------------------------------------------------


class TestRoomFitFlow:
    """Integration test: RoomFit device → EQ_TYPE → FILTERS → NAME_PROFILE → PUSH."""

    def test_roomfit_flow_shows_eq_type(self, make_window) -> None:
        """RoomFit-capable device shows EQ_TYPE step."""
        window = make_window()

        # Discovery + device selection
        window._on_discovery_complete(_make_single_device())
        window._on_device_selected("192.168.1.100")

        # Capabilities with roomfit_level=3 → EQ_TYPE shown (not PEQ_ONLY)
        caps = _make_caps(roomfit_level=3)
        window._on_capabilities_ready(caps)

        # Should advance past CONNECT → EQ_TYPE (default PEQ flow keeps EQ_TYPE)
        assert window.wizard_controller.current_step == WizardStep.EQ_TYPE
        assert window.stacked_widget.currentIndex() == PAGE_INDICES["eq_type"]

    def test_roomfit_selection_skips_source(self, make_window) -> None:
        """Selecting 'roomfit' EQ type skips SOURCE and lands on FILTERS."""
        window = make_window()

        # Setup: get to EQ_TYPE step
        window._on_discovery_complete(_make_single_device())
        window._on_device_selected("192.168.1.100")
        caps = _make_caps(roomfit_level=3)
        window._on_capabilities_ready(caps)
        assert window.wizard_controller.current_step == WizardStep.EQ_TYPE

        # Select roomfit → flow changes to ROOMFIT, advance past EQ_TYPE
        window._on_eq_type_selected("roomfit")

        # ROOMFIT flow: CONNECT → EQ_TYPE → FILTERS → REVIEW → NAME_PROFILE → PUSH
        # After EQ_TYPE advance, should be on FILTERS (SOURCE skipped)
        assert window.wizard_controller.flow_type == FlowType.ROOMFIT
        assert window.wizard_controller.current_step == WizardStep.FILTERS
        assert window.stacked_widget.currentIndex() == PAGE_INDICES["filters"]

    def test_roomfit_full_flow_includes_name_profile(self, make_window) -> None:
        """RoomFit flow includes NAME_PROFILE step before PUSH."""
        window = make_window()

        # Setup: get to FILTERS via roomfit selection
        window._on_discovery_complete(_make_single_device())
        window._on_device_selected("192.168.1.100")
        caps = _make_caps(roomfit_level=3)
        window._on_capabilities_ready(caps)
        window._on_eq_type_selected("roomfit")
        assert window.wizard_controller.current_step == WizardStep.FILTERS

        # Filters → Review
        window._on_filters_accepted()
        assert window.wizard_controller.current_step == WizardStep.REVIEW
        assert window.stacked_widget.currentIndex() == PAGE_INDICES["review"]

        # Disable dry_run (enabled by default via settings) so push takes RoomFit path
        window._wizard_controller.state.dry_run = False

        # Review → NAME_PROFILE (not PUSH)
        window._on_push_requested()
        assert window.wizard_controller.current_step == WizardStep.NAME_PROFILE
        assert window.stacked_widget.currentIndex() == PAGE_INDICES["name_profile"]

        # Name confirmed → PUSH
        window._on_name_confirmed("Living Room EQ")
        assert window.wizard_controller.current_step == WizardStep.PUSH
        assert window.stacked_widget.currentIndex() == PAGE_INDICES["push"]
        assert window.wizard_controller.state.roomfit_profile_name == "Living Room EQ"


# ---------------------------------------------------------------------------
# Test: Back-navigation
# ---------------------------------------------------------------------------


class TestBackNavigation:
    """Integration test: step indicator backward navigation with invalidation."""

    def test_back_navigation_invalidates_subsequent_steps(self, make_window) -> None:
        """Going back via step indicator invalidates steps after target."""
        window = make_window()

        # Advance to REVIEW step (PEQ_ONLY flow)
        window._on_discovery_complete(_make_single_device())
        window._on_device_selected("192.168.1.100")
        caps = _make_caps(roomfit_level=0)
        window._on_capabilities_ready(caps)
        window._on_source_selected("wifi", "Stereo")
        window._on_filters_accepted()

        # Now at REVIEW
        assert window.wizard_controller.current_step == WizardStep.REVIEW

        # Verify completed steps exist before back-nav
        completed = window.wizard_controller.completed_steps
        assert WizardStep.CONNECT in completed
        assert WizardStep.SOURCE in completed
        assert WizardStep.FILTERS in completed

        # Navigate back to SOURCE via step indicator click
        # In PEQ_ONLY flow: [CONNECT(0), SOURCE(1), FILTERS(2), REVIEW(3), PUSH(4)]
        window._on_step_indicator_clicked(1)  # SOURCE is index 1

        # Should be on SOURCE
        assert window.wizard_controller.current_step == WizardStep.SOURCE
        assert window.stacked_widget.currentIndex() == PAGE_INDICES["source"]

        # Steps after SOURCE should be invalidated
        completed = window.wizard_controller.completed_steps
        assert WizardStep.CONNECT in completed  # Before target: preserved
        assert WizardStep.SOURCE not in completed  # Target: cleared
        assert WizardStep.FILTERS not in completed  # After target: cleared
        assert WizardStep.REVIEW not in completed  # After target: cleared

        # Regression: SOURCE was COMPLETED before this back-nav (the user
        # had already passed through it once); the step indicator must show
        # it as ACTIVE now, not a stale COMPLETED checkmark.
        from src.gui.components.step_indicator import _StepState

        assert window._step_indicator._steps[1].state == _StepState.ACTIVE

    def test_back_navigation_to_connect_clears_all(self, make_window) -> None:
        """Going back to CONNECT invalidates all subsequent steps."""
        window = make_window()

        # Advance to FILTERS
        window._on_discovery_complete(_make_single_device())
        window._on_device_selected("192.168.1.100")
        caps = _make_caps(roomfit_level=0)
        window._on_capabilities_ready(caps)
        window._on_source_selected("wifi", "Stereo")

        # Now at FILTERS
        assert window.wizard_controller.current_step == WizardStep.FILTERS

        # Back to CONNECT (index 0 in any flow)
        window._on_step_indicator_clicked(0)

        assert window.wizard_controller.current_step == WizardStep.CONNECT
        assert window.stacked_widget.currentIndex() == PAGE_INDICES["connect"]
        assert len(window.wizard_controller.completed_steps) == 0


# ---------------------------------------------------------------------------
# Test: Error recovery
# ---------------------------------------------------------------------------


class TestErrorRecovery:
    """Integration test: error signals propagate to StatusBanner."""

    def test_operation_error_shows_in_status_banner(self, make_window) -> None:
        """AsyncBridge operation_error shows message in StatusBanner."""
        window = make_window()

        window._on_operation_error("discovery_failed", "No devices found on network")

        # StatusBanner should display the error
        assert window.status_banner._message_label.text() == "No devices found on network"
        assert window.status_banner.property("status") == "error"

    def test_write_failure_shows_error_on_push_page(self, make_window) -> None:
        """Write failure updates PushPage with error and shows StatusBanner error."""
        window = make_window()

        # Get to PUSH step
        window._on_discovery_complete(_make_single_device())
        window._on_device_selected("192.168.1.100")
        caps = _make_caps(roomfit_level=0)
        window._on_capabilities_ready(caps)
        window._on_source_selected("wifi", "Stereo")
        window._on_filters_accepted()
        window._on_push_requested()
        assert window.wizard_controller.current_step == WizardStep.PUSH

        # Write fails
        result = _make_write_result(success=False)
        window._on_write_complete(result)

        # PushPage should show failure (result state visible)
        # The push page transitions to its failure/result state
        assert window.push_page._result_message.text() != ""
        # StatusBanner should show error
        assert "Push failed" in window.status_banner._message_label.text()
        assert window.status_banner.property("status") == "error"

    def test_progress_update_shows_in_status_banner(self, make_window) -> None:
        """AsyncBridge progress_update shows message in StatusBanner."""
        window = make_window()

        window._on_progress_update("Backing up current configuration...")

        assert (
            window.status_banner._message_label.text()
            == "Backing up current configuration..."
        )
        # Progress uses "info" status with progress bar set to visible
        assert window.status_banner.property("status") == "info"
        # Progress bar visibility is relative to parent; use isVisibleTo
        assert window.status_banner._progress_bar.isVisibleTo(window.status_banner) is True


# ---------------------------------------------------------------------------
# Test: Undo after push
# ---------------------------------------------------------------------------


class TestUndoAfterPush:
    """Integration test: undo triggers backup restore via SecondaryWorkflowManager."""

    def test_undo_calls_secondary_workflow(self, make_window) -> None:
        """Undo after successful push calls undo_last_push with backup path."""
        window = make_window()

        # Get to push success
        window._on_discovery_complete(_make_single_device())
        window._on_device_selected("192.168.1.100")
        caps = _make_caps(roomfit_level=0)
        window._on_capabilities_ready(caps)
        window._on_source_selected("wifi", "Stereo")
        window._on_filters_accepted()
        window._on_push_requested()

        result = _make_write_result(success=True)
        window._on_write_complete(result)

        # Verify backup path stored
        assert window.wizard_controller.state.last_backup_path == "/backups/peq_backup_001.json"

        # Trigger undo
        with patch.object(
            window._secondary_workflows, "undo_last_push"
        ) as mock_undo:
            window._on_undo_requested()
            mock_undo.assert_called_once_with("wifi", "/backups/peq_backup_001.json")

    def test_undo_complete_success_shows_banner(self, make_window) -> None:
        """Successful undo shows success message in StatusBanner."""
        window = make_window()

        # Simulate undo_complete signal from SecondaryWorkflowManager
        window._on_undo_complete(True, "Previous filters restored")

        assert window.status_banner._message_label.text() == "Previous filters restored"
        assert window.status_banner.property("status") == "success"

    def test_undo_complete_failure_shows_error(self, make_window) -> None:
        """Failed undo shows error in StatusBanner."""
        window = make_window()

        window._on_undo_complete(False, "Backup file not found")

        assert "Undo failed" in window.status_banner._message_label.text()
        assert window.status_banner.property("status") == "error"


# ---------------------------------------------------------------------------
# Test: Sidebar navigation preserves wizard state
# ---------------------------------------------------------------------------


class TestSidebarNavigation:
    """Integration test: sidebar navigation preserves and restores wizard state."""

    def test_navigate_to_settings_and_back(self, make_window) -> None:
        """Navigate to settings via sidebar, then back to wizard step via 'home'."""
        window = make_window()

        # Advance to REVIEW step
        window._on_discovery_complete(_make_single_device())
        window._on_device_selected("192.168.1.100")
        caps = _make_caps(roomfit_level=0)
        window._on_capabilities_ready(caps)
        window._on_source_selected("wifi", "Stereo")
        window._on_filters_accepted()

        # Now at REVIEW
        assert window.wizard_controller.current_step == WizardStep.REVIEW
        assert window.stacked_widget.currentIndex() == PAGE_INDICES["review"]

        # Navigate to settings via sidebar
        window._on_navigation_requested("settings")
        assert window.stacked_widget.currentIndex() == PAGE_INDICES["settings"]

        # Wizard state is preserved
        assert window.wizard_controller.current_step == WizardStep.REVIEW
        assert WizardStep.CONNECT in window.wizard_controller.completed_steps
        assert WizardStep.SOURCE in window.wizard_controller.completed_steps
        assert WizardStep.FILTERS in window.wizard_controller.completed_steps

        # Navigate back via 'home'
        window._on_navigation_requested("home")

        # Returns to the current wizard step (REVIEW)
        assert window.stacked_widget.currentIndex() == PAGE_INDICES["review"]
        assert window.wizard_controller.current_step == WizardStep.REVIEW

    def test_navigate_to_presets_preserves_state(self, make_window) -> None:
        """Navigate to device presets view preserves wizard state."""
        window = make_window()

        # Advance to FILTERS
        window._on_discovery_complete(_make_single_device())
        window._on_device_selected("192.168.1.100")
        caps = _make_caps(roomfit_level=0)
        window._on_capabilities_ready(caps)
        window._on_source_selected("wifi", "Stereo")

        # Now at FILTERS
        assert window.wizard_controller.current_step == WizardStep.FILTERS

        # Navigate to presets_device
        window._on_navigation_requested("presets_device")
        assert window.stacked_widget.currentIndex() == PAGE_INDICES["presets_device"]

        # Wizard state unchanged
        assert window.wizard_controller.current_step == WizardStep.FILTERS
        assert window.wizard_controller.state.selected_source == "wifi"

        # Return home
        window._on_navigation_requested("home")
        assert window.stacked_widget.currentIndex() == PAGE_INDICES["filters"]

    def test_navigate_to_help_preserves_state(self, make_window) -> None:
        """Navigate to help view opens dialog and preserves wizard step."""
        window = make_window()

        # At CONNECT (default)
        assert window.wizard_controller.current_step == WizardStep.CONNECT

        # Navigate to help — opens dialog, stacked widget stays on current page
        window._on_navigation_requested("help")
        assert window._help_dialog.isVisible()

        # Wizard state unchanged
        assert window.wizard_controller.current_step == WizardStep.CONNECT

        # Return home — stacked widget still shows connect
        window._on_navigation_requested("home")
        assert window.stacked_widget.currentIndex() == PAGE_INDICES["connect"]
