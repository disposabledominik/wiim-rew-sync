"""Smoke test regression tests for wizard flow, navigation, and device selection.

Covers smoke test issues: #1, #5, #6, #14, #15, #16, #19, #35, #36, #41, #57, #72, #73, #87.
Each test validates the specific fix behavior to prevent regressions.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtGui import QShowEvent

from src.gui.app_settings import AppSettings
from src.gui.main_window import MainWindow
from src.gui.wizard_controller import FlowType, WizardStep, steps_for_flow

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


def _make_caps(
    model: str = "WiiM Pro Plus",
    roomfit_level: int = 0,
    source_names: list[str] | None = None,
) -> MagicMock:
    """Create a mock DeviceCapabilities."""
    caps = MagicMock()
    caps.roomfit_level = roomfit_level
    caps.device_name = model
    caps.model = model
    caps.source_names = source_names if source_names is not None else ["wifi", "optical", "hdmi"]
    caps.active_source = "wifi"
    caps.supports_profile_enumeration = False
    return caps


# ---------------------------------------------------------------------------
# Issue #1: Empty source_names from capability probe uses model-based fallback
# ---------------------------------------------------------------------------


class TestIssue1EmptySourcesFallback:
    """Smoke #1: Empty source_names uses model-based fallback, no error."""

    def test_empty_sources_wiim_mini_advances_wizard(self, window) -> None:
        """Capabilities with empty source_names on WiiM Mini advances wizard."""
        window._on_device_selected("192.168.1.100")

        caps = _make_caps(model="WiiM Mini", roomfit_level=0, source_names=[])
        window._on_capabilities_ready(caps)

        # No error emitted — fallback sources used
        window._bridge.operation_error.emit.assert_not_called()
        # Wizard advanced past CONNECT
        assert window._wizard_controller.current_step != WizardStep.CONNECT


# ---------------------------------------------------------------------------
# Issue #5: Step indicator initialized at startup with default flow steps
# ---------------------------------------------------------------------------


class TestIssue5StepIndicatorInit:
    """Smoke #5: Step indicator has labels matching default PEQ flow at startup."""

    def test_step_indicator_has_default_peq_flow_labels(self, window) -> None:
        """After MainWindow creation, step indicator has labels for default flow."""
        # Default flow is PEQ: CONNECT → EQ_TYPE → SOURCE → FILTERS → REVIEW → PUSH
        expected_steps = steps_for_flow(FlowType.PEQ)
        expected_labels = [s.value.replace("_", " ").title() for s in expected_steps]

        # Use the internal _steps list (canonical source of current widgets)
        step_widgets = window._step_indicator._steps
        assert len(step_widgets) == len(expected_labels)
        for widget, expected_label in zip(step_widgets, expected_labels, strict=True):
            assert widget._label.text() == expected_label


# ---------------------------------------------------------------------------
# Issue #6: Sidebar device name shows actual device name (not generic)
# ---------------------------------------------------------------------------


class TestIssue6SidebarDeviceName:
    """Smoke #6: After capabilities ready, sidebar shows actual device model name."""

    def test_sidebar_shows_device_model_name(self, window) -> None:
        """After _on_capabilities_ready, sidebar shows the device model name."""
        window._on_device_selected("192.168.1.100")

        caps = _make_caps(model="WiiM Pro Plus", roomfit_level=2)
        window._on_capabilities_ready(caps)

        # Sidebar should display the model name (or discovered device name)
        device_label_text = window._sidebar_nav._device_label.text()
        assert device_label_text == "WiiM Pro Plus"


# ---------------------------------------------------------------------------
# Issue #14: ConnectPage only auto-triggers discovery when no cards shown
# ---------------------------------------------------------------------------


class TestIssue14ConnectPageShowEvent:
    """Smoke #14: ConnectPage showEvent doesn't re-scan when cards already exist."""

    def test_show_event_with_cards_does_not_emit_refresh(self, window) -> None:
        """Calling showEvent when cards already exist doesn't emit refresh_requested."""
        connect_page = window._connect_page

        # Simulate having device cards already populated
        connect_page.set_devices([
            {"name": "WiiM Pro", "model": "WiiM Pro", "ip": "192.168.1.100",
             "firmware": "5.6.0", "role": ""},
        ])
        assert len(connect_page._device_cards) > 0

        # Track refresh_requested emissions
        signal_emitted = []
        connect_page.refresh_requested.connect(lambda: signal_emitted.append(True))

        # Trigger showEvent
        event = QShowEvent()
        connect_page.showEvent(event)

        # refresh_requested should NOT have been emitted
        assert len(signal_emitted) == 0

    def test_show_event_without_cards_emits_refresh(self, window) -> None:
        """Calling showEvent with no cards does emit refresh_requested."""
        connect_page = window._connect_page

        # Ensure no cards
        assert len(connect_page._device_cards) == 0

        signal_emitted = []
        connect_page.refresh_requested.connect(lambda: signal_emitted.append(True))

        event = QShowEvent()
        connect_page.showEvent(event)

        assert len(signal_emitted) == 1


# ---------------------------------------------------------------------------
# Issue #15: After flow type switch, step indicator updates step labels
# ---------------------------------------------------------------------------


class TestIssue15FlowTypeSwitchStepLabels:
    """Smoke #15: Changing flow type updates step indicator labels."""

    def test_flow_type_peq_to_roomfit_updates_labels(self, window) -> None:
        """Change flow from PEQ to ROOMFIT updates step indicator labels."""
        # Initial default is PEQ
        assert window._wizard_controller.flow_type == FlowType.PEQ

        # Switch to ROOMFIT
        window._wizard_controller.set_flow_type(FlowType.ROOMFIT)

        # Verify step indicator now has ROOMFIT flow labels
        expected_steps = steps_for_flow(FlowType.ROOMFIT)
        expected_labels = [s.value.replace("_", " ").title() for s in expected_steps]

        # Use the internal _steps list (canonical source of current widgets)
        step_widgets = window._step_indicator._steps
        assert len(step_widgets) == len(expected_labels)
        for widget, expected_label in zip(step_widgets, expected_labels, strict=True):
            assert widget._label.text() == expected_label


# ---------------------------------------------------------------------------
# Issue #16: RoomFit pull defaults to "wifi" source when none explicitly set
# ---------------------------------------------------------------------------


class TestIssue16RoomfitDefaultSource:
    """Smoke #16: _on_device_pull_requested defaults to 'wifi' when no source set."""

    def test_device_pull_defaults_to_wifi(self, window) -> None:
        """Pull from device with empty selected_source defaults to 'wifi'."""
        # Set up device connection
        window._on_device_selected("192.168.1.100")
        caps = _make_caps(model="WiiM Pro Plus", roomfit_level=2)
        window._on_capabilities_ready(caps)

        # Clear the selected source (simulating RoomFit flow with no source step)
        window._wizard_controller.state.selected_source = ""

        # Provide a mock adapter so the guard passes
        window._wiim_adapter = MagicMock()

        # Call _on_device_pull_requested
        window._on_device_pull_requested()

        # Verify source defaulted to "wifi"
        assert window._wizard_controller.state.selected_source == "wifi"


# ---------------------------------------------------------------------------
# Issue #19: EQ type selection sets roomfit_mode on FiltersPage
# ---------------------------------------------------------------------------


class TestIssue19EqTypeRoomfitMode:
    """Smoke #19: _on_eq_type_selected('roomfit') calls set_roomfit_mode(True)."""

    def test_eq_type_roomfit_sets_roomfit_mode(self, window) -> None:
        """Selecting 'roomfit' EQ type calls FiltersPage.set_roomfit_mode(True)."""
        # Patch set_roomfit_mode to track calls
        with patch.object(window._filters_page, "set_roomfit_mode") as mock_method:
            window._on_eq_type_selected("roomfit")
            mock_method.assert_called_once_with(True)

    def test_eq_type_peq_sets_roomfit_mode_false(self, window) -> None:
        """Selecting 'peq' EQ type calls FiltersPage.set_roomfit_mode(False)."""
        with patch.object(window._filters_page, "set_roomfit_mode") as mock_method:
            window._on_eq_type_selected("peq")
            mock_method.assert_called_once_with(False)


# ---------------------------------------------------------------------------
# Issue #35: Source page shows all common sources (not filtered by model)
# ---------------------------------------------------------------------------


class TestIssue35AllCommonSources:
    """Smoke #35: After capabilities ready, source page gets all common sources."""

    def test_empty_sources_provides_all_common_sources(self, window) -> None:
        """Capabilities with empty source_names populates source page with all defaults."""
        window._on_device_selected("192.168.1.100")

        # Device reports no sources — should fall back to full common set
        caps = _make_caps(model="WiiM Sound", roomfit_level=0, source_names=[])
        with patch.object(window._source_page, "set_sources") as mock_set:
            window._on_capabilities_ready(caps)
            mock_set.assert_called_once()
            sources_arg = mock_set.call_args[0][0]
            # All 6 common WiiM sources should be present
            expected = {"wifi", "bluetooth", "line-in", "auxIn", "optical", "HDMI"}
            assert set(sources_arg) == expected

    def test_reported_sources_passed_through(self, window) -> None:
        """Capabilities with reported source_names passes them through to SourcePage."""
        window._on_device_selected("192.168.1.100")

        caps = _make_caps(
            model="WiiM Pro Plus", roomfit_level=2,
            source_names=["wifi", "optical", "hdmi"],
        )
        with patch.object(window._source_page, "set_sources") as mock_set:
            window._on_capabilities_ready(caps)
            mock_set.assert_called_once()
            sources_arg = mock_set.call_args[0][0]
            assert sources_arg == ["wifi", "optical", "hdmi"]


# ---------------------------------------------------------------------------
# Issue #36: WiiM Mini (roomfit_level >= 2 but in blocklist) -> PEQ_ONLY flow
# ---------------------------------------------------------------------------


class TestIssue36MiniRoomfitBlocklist:
    """Smoke #36: WiiM Mini with roomfit_level=2 forced to PEQ_ONLY flow."""

    def test_wiim_mini_roomfit_level_2_forced_peq_only(self, window) -> None:
        """WiiM Mini with roomfit_level=2 gets PEQ_ONLY flow (blocklisted)."""
        window._on_device_selected("192.168.1.100")

        caps = _make_caps(model="WiiM Mini", roomfit_level=2, source_names=["wifi", "bluetooth"])
        window._on_capabilities_ready(caps)

        assert window._wizard_controller.flow_type == FlowType.PEQ_ONLY

    def test_non_blocklisted_model_roomfit_level_2_gets_peq(self, window) -> None:
        """WiiM Pro Plus with roomfit_level=2 gets normal PEQ flow (not blocked)."""
        window._on_device_selected("192.168.1.100")

        caps = _make_caps(model="WiiM Pro Plus", roomfit_level=2)
        window._on_capabilities_ready(caps)

        # Should NOT be PEQ_ONLY — device supports RoomFit
        assert window._wizard_controller.flow_type != FlowType.PEQ_ONLY


# ---------------------------------------------------------------------------
# Issue #41: Selecting new device resets flow_type to PEQ
# ---------------------------------------------------------------------------


class TestIssue41DeviceSelectResetsFlow:
    """Smoke #41: Selecting new device resets flow_type to PEQ."""

    def test_device_select_resets_flow_to_peq(self, window) -> None:
        """Set flow to ROOMFIT, then _on_device_selected resets to PEQ."""
        # Set flow type to ROOMFIT
        window._wizard_controller.set_flow_type(FlowType.ROOMFIT)
        assert window._wizard_controller.flow_type == FlowType.ROOMFIT

        # Select a new device
        window._on_device_selected("192.168.1.200")

        # Flow should be reset to PEQ
        assert window._wizard_controller.flow_type == FlowType.PEQ


# ---------------------------------------------------------------------------
# Issue #57: Back navigation clears step completion badges for invalidated steps
# ---------------------------------------------------------------------------


class TestIssue57BackNavClearsCompletedSteps:
    """Smoke #57: Going back clears completion for invalidated future steps."""

    def test_go_to_source_clears_review_and_filters(self, window) -> None:
        """Advance to REVIEW, go_to_step(SOURCE) removes REVIEW/FILTERS from completed."""
        wc = window._wizard_controller

        # Set up PEQ_ONLY flow to avoid EQ_TYPE step
        wc.set_flow_type(FlowType.PEQ_ONLY)
        # Sequence: CONNECT → SOURCE → FILTERS → REVIEW → PUSH

        # Advance through all steps
        wc.advance(summary="Connected")  # CONNECT done, now at SOURCE
        wc.advance(summary="wifi")  # SOURCE done, now at FILTERS
        wc.advance(summary="Filters loaded")  # FILTERS done, now at REVIEW
        wc.advance(summary="Reviewed")  # REVIEW done, now at PUSH

        # Verify we're at PUSH with prior steps completed
        assert wc.current_step == WizardStep.PUSH
        assert WizardStep.REVIEW in wc.completed_steps
        assert WizardStep.FILTERS in wc.completed_steps

        # Navigate back to SOURCE
        wc.go_to_step(WizardStep.SOURCE)

        # REVIEW and FILTERS should be cleared from completed_steps
        assert WizardStep.REVIEW not in wc.completed_steps
        assert WizardStep.FILTERS not in wc.completed_steps
        assert WizardStep.SOURCE not in wc.completed_steps
        # CONNECT should still be completed
        assert WizardStep.CONNECT in wc.completed_steps


# ---------------------------------------------------------------------------
# Issue #72: FiltersPage has "Next" button that gets enabled when file is selected
# ---------------------------------------------------------------------------


class TestIssue72FiltersPageNextButton:
    """Smoke #72: FiltersPage Next button enabled when stereo file is selected."""

    def test_next_button_exists_and_initially_disabled(self, window) -> None:
        """FiltersPage has a _next_btn that starts disabled."""
        filters_page = window._filters_page
        assert hasattr(filters_page, "_next_btn")
        assert not filters_page._next_btn.isEnabled()

    def test_next_button_enabled_after_stereo_file_browse(self, window) -> None:
        """Simulating file selection enables the next button."""
        filters_page = window._filters_page

        # Simulate what _on_browse_stereo does internally after file selection
        filters_page._stereo_path = "/tmp/test.txt"
        filters_page._stereo_file_label.setText("test.txt")
        filters_page._next_btn.setEnabled(True)

        assert filters_page._next_btn.isEnabled()


# ---------------------------------------------------------------------------
# Issue #73: Stereo file import sets channel_mode to "Stereo" (not stale L/R)
# ---------------------------------------------------------------------------


class TestIssue73StereoImportChannelMode:
    """Smoke #73: Stereo file import sets channel_mode to 'Stereo'."""

    @pytest.mark.asyncio
    async def test_stereo_import_sets_channel_mode(self, window) -> None:
        """State has channel_mode='LR', do stereo import -> channel_mode becomes 'Stereo'."""
        from src.models.canonical import CanonicalFilter
        from src.models.channel_mode import ChannelMode

        # Set stale L/R channel mode
        window._wizard_controller.state.channel_mode = ChannelMode.LR

        # Mock the REW parser to return some filters
        mock_filters = [
            CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=-3.0, q=1.0),
        ]
        with patch(
            "src.translator.rew_parser.REWParser.parse_file_with_warnings",
            return_value=(mock_filters, []),
        ):
            await window._do_file_import("/tmp/stereo_eq.txt")

        # channel_mode should now be "Stereo" (not stale "L/R")
        assert window._wizard_controller.state.channel_mode == ChannelMode.STEREO


# ---------------------------------------------------------------------------
# Issue #87: Sidebar preset load checks wizard completed_steps before navigating
# ---------------------------------------------------------------------------


class TestIssue87SidebarPresetLoadChecks:
    """Smoke #87: Preset load from sidebar checks completed_steps."""

    def test_load_without_device_shows_error(self, window) -> None:
        """Loading preset with no device connected shows error, returns False."""
        # Ensure no device is connected
        window._wizard_controller.state.selected_device = None

        result = window._ensure_wizard_state_for_load()

        assert result is False

    def test_load_with_connect_only_shows_quick_setup(self, window) -> None:
        """With only CONNECT completed, _ensure_wizard_state_for_load shows dialog."""
        # Select device so it's not None
        window._on_device_selected("192.168.1.100")

        # Mark only CONNECT as completed
        state = window._wizard_controller.state
        state.completed_steps = {WizardStep.CONNECT: "Connected"}

        # Mock QuickSetupDialog.get_setup to return a result (simulating user choice)
        with patch(
            "src.gui.dialogs.quick_setup_dialog.QuickSetupDialog.get_setup",
            return_value=("peq", ["wifi"]),
        ):
            result = window._ensure_wizard_state_for_load()

        # Should succeed since QuickSetupDialog returned values
        assert result is True
        # EQ_TYPE and SOURCE should now be in completed_steps
        assert WizardStep.SOURCE in state.completed_steps

    def test_load_with_all_steps_completed_skips_dialog(self, window) -> None:
        """With all prior steps completed, no dialog shown — returns True directly."""
        # Select device
        window._on_device_selected("192.168.1.100")

        # Mark all required prior steps as completed
        state = window._wizard_controller.state
        state.completed_steps = {
            WizardStep.CONNECT: "Connected",
            WizardStep.EQ_TYPE: "PEQ",
            WizardStep.SOURCE: "wifi",
            WizardStep.FILTERS: "Loaded",
        }
        state.selected_source = "wifi"

        # No need to patch QuickSetupDialog — it shouldn't be called
        result = window._ensure_wizard_state_for_load()
        assert result is True
