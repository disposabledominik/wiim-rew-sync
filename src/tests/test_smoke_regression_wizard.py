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


def _make_caps(
    model: str = "WiiM Pro Plus",
    roomfit_level: int = 0,
    source_names: list[str] | None = None,
) -> MagicMock:
    """Create a mock DeviceCapabilities."""
    caps = MagicMock()
    caps.supports_roomfit = roomfit_level >= 1
    caps.supports_roomfit_read = roomfit_level >= 2
    caps.supports_roomfit_write = roomfit_level >= 4
    caps.device_name = model
    caps.model = model
    caps.source_names = source_names if source_names is not None else ["wifi", "optical", "hdmi"]
    caps.active_source = "wifi"
    caps.supports_profile_enumeration = False
    caps.capability_file_override = False
    caps.used_generic_capabilities = False
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


class TestCapabilityFallbackSidebarWarning:
    """_on_capabilities_ready warns via the sidebar when capabilities came
    from a capability-file override or generic/conservative defaults,
    rather than pure live device probing."""

    def test_no_fallback_shows_no_warning(self, window) -> None:
        """Fully live-probed capabilities -- no warning glyph, and no
        warning in the device-info popover text."""
        window._on_device_selected("192.168.1.100")

        caps = _make_caps(model="WiiM Pro Plus", roomfit_level=2)
        window._on_capabilities_ready(caps)

        assert window._sidebar_nav._device_label.text() == "WiiM Pro Plus"
        assert window._capability_warning_text() == ""

    def test_generic_capabilities_shows_warning(self, window) -> None:
        """used_generic_capabilities=True -- sidebar shows the warning glyph
        and the device-info popover carries the explanation (PR #19 review
        D2: the warning lives in the popover, not a hijacked tooltip)."""
        window._on_device_selected("192.168.1.100")

        caps = _make_caps(model="WiiM Pro Plus", roomfit_level=2)
        caps.used_generic_capabilities = True
        window._on_capabilities_ready(caps)

        assert window._sidebar_nav._device_label.text() == "WiiM Pro Plus  ⚠"
        assert "generic defaults" in window._capability_warning_text()
        with patch(
            "src.gui.dialogs.device_info_dialog.DeviceInfoDialog.show_info"
        ) as info:
            window._show_device_info()
        assert "generic defaults" in info.call_args.args[4]

    def test_capability_file_override_shows_warning(self, window) -> None:
        """capability_file_override=True -- sidebar shows the warning glyph
        and the popover carries the explanation."""
        window._on_device_selected("192.168.1.100")

        caps = _make_caps(model="WiiM Pro Plus", roomfit_level=2)
        caps.capability_file_override = True
        window._on_capabilities_ready(caps)

        assert window._sidebar_nav._device_label.text() == "WiiM Pro Plus  ⚠"
        assert "capability-file override" in window._capability_warning_text()


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
            {"name": "WiiM Pro", "model": "WiiM Pro", "ip": "192.168.1.100"},
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


class TestCtrlRRescanShortcut:
    """Ctrl+R must actually re-trigger discovery, not just toggle the
    scanning UI state -- it previously called only set_scanning(True) and
    never reached _do_discovery(), a dead-end fixed alongside the new
    Connect-step rescan button."""

    def test_shortcut_reaches_discovery(self, window) -> None:
        """_on_shortcut_refresh delegates to _on_refresh_requested, which
        schedules the real discovery coroutine via the bridge."""
        with patch.object(
            window._primary_workflows, "_do_discovery"
        ) as mock_do_discovery:
            window._on_shortcut_refresh()

        window._bridge.run_async.assert_called_once()
        mock_do_discovery.assert_called_once()


# ---------------------------------------------------------------------------
# Issue #15: After flow type switch, step indicator updates step labels
# ---------------------------------------------------------------------------


class TestIssue15FlowTypeSwitchStepLabels:
    """Smoke #15: Changing flow type updates step indicator labels and
    replays completed-step checkmarks (regression: _on_flow_type_changed
    used to rebuild the indicator via set_steps() without replaying
    completed_steps, so the CONNECT checkmark vanished on flow switch)."""

    def test_flow_type_peq_to_roomfit_updates_labels(self, window) -> None:
        """Change flow from PEQ to ROOMFIT updates labels and keeps checkmarks."""
        from src.gui.components.step_indicator import _StepState

        wc = window._wizard_controller

        # Initial default is PEQ
        assert wc.flow_type == FlowType.PEQ

        # Complete the CONNECT step via the real controller API (same
        # pattern as TestIssue57) so completed_steps is populated with a
        # real summary before the flow switch.
        wc.advance(summary="Connected")
        assert WizardStep.CONNECT in wc.completed_steps
        assert wc.completed_steps[WizardStep.CONNECT] == "Connected"

        # Switch to ROOMFIT — triggers the real flow_type_changed signal,
        # which runs _on_flow_type_changed and rebuilds the step indicator.
        wc.set_flow_type(FlowType.ROOMFIT)

        # Verify step indicator now has ROOMFIT flow labels
        expected_steps = steps_for_flow(FlowType.ROOMFIT)
        expected_labels = [s.value.replace("_", " ").title() for s in expected_steps]

        # Use the internal _steps list (canonical source of current widgets)
        step_widgets = window._step_indicator._steps
        assert len(step_widgets) == len(expected_labels)
        for widget, expected_label in zip(step_widgets, expected_labels, strict=True):
            assert widget._label.text() == expected_label

        # CONNECT is step 0 in both PEQ and ROOMFIT sequences — its
        # checkmark (COMPLETED state) and summary must have been replayed,
        # not wiped by the set_steps() rebuild.
        connect_index = expected_steps.index(WizardStep.CONNECT)
        connect_widget = step_widgets[connect_index]
        assert connect_widget.state == _StepState.COMPLETED
        assert connect_widget._summary.text() == "Connected"


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

        # Verify the pull resolves to "wifi" via primary_source's default
        # (no source-selection guard needed -- _do_device_pull reads
        # primary_source directly, which already falls back to "wifi").
        assert window._wizard_controller.state.primary_source == "wifi"


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

    def test_empty_sources_passed_through_unchanged(self, window) -> None:
        """#167b: the "fall back to the common set when the device reports no
        sources" responsibility moved from _on_capabilities_ready to
        merge_into() (single source of truth, DEFAULT_SOURCE_NAMES) --
        _on_capabilities_ready now trusts caps.source_names completely and
        passes it straight through, even when empty. The fallback itself is
        covered directly at the merge_into() level in
        test_device_capability_file.py::TestMergeInto::
        test_empty_source_names_falls_back_to_default_list -- this test only
        documents that this component no longer duplicates that logic.
        """
        window._on_device_selected("192.168.1.100")

        # Simulates capabilities that skipped merge_into() (which would
        # normally have already applied the DEFAULT_SOURCE_NAMES fallback) --
        # a real caller always goes through merge_into() first.
        caps = _make_caps(model="WiiM Sound", roomfit_level=0, source_names=[])
        with patch.object(window._source_page, "set_sources") as mock_set:
            window._on_capabilities_ready(caps)
            mock_set.assert_called_once()
            sources_arg = mock_set.call_args[0][0]
            assert sources_arg == []

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
# Issue #36: a model known not to support RoomFit -> PEQ_ONLY flow, even if
# it reports otherwise (model-name distrust now lives in CapabilityProber,
# not here -- see the class docstring below).
# ---------------------------------------------------------------------------


class TestIssue36MiniRoomfitBlocklist:
    """Smoke #36: a model known not to support RoomFit gets PEQ_ONLY flow
    even if it reports otherwise.

    The correction lives entirely in CapabilityProber, not here (see
    test_capability_prober.py::TestRoomfitCapabilityFileOverride and
    TestRoomFitFallbackProbe, exercised through the real probe() flow rather
    than a hand-built caps mock): the WiiM_Mini/Muzo_Mini capability-file
    entry force-overrides supports_roomfit* for that exact model, and
    CapabilityProber's generic protocol-level detection (empty RoomFit
    profile list / no acoustic-capability subsystem) independently gets the
    right answer for any device without needing its name at all -- there is
    no model-string special-casing anywhere, in CapabilityProber or here.
    _on_capabilities_ready() simply trusts caps.supports_roomfit_read, which
    the prober has already corrected by the time this handler runs. The test
    below confirms that trust: given an already-corrected caps object
    (supports_roomfit_read=False, regardless of what model name it carries),
    the wizard still ends up PEQ_ONLY.
    """

    def test_roomfit_read_false_forces_peq_only_regardless_of_model(self, window) -> None:
        """caps.supports_roomfit_read=False (however it was determined)
        always yields PEQ_ONLY -- no model-name logic left in this handler."""
        window._on_device_selected("192.168.1.100")

        caps = _make_caps(model="WiiM Mini", roomfit_level=0, source_names=["wifi", "bluetooth"])
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

    def test_device_switch_clears_lr_filters(self, window) -> None:
        """docs/smoke_test_issues.md #246 follow-up, bug 1b: switching devices
        while in L/R mode must clear filters_l/filters_r too, not just
        current_filters -- otherwise device A's L/R filters stay readable via
        state.filters (which prefers filters_l/filters_r whenever channel_mode
        is L/R and either list is non-empty)."""
        from src.models.canonical import CanonicalFilter
        from src.models.channel_mode import ChannelMode

        state = window._wizard_controller.state
        window._on_device_selected("192.168.1.100")
        state.channel_mode = ChannelMode.LR
        state.filters_l = [
            CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=3.0, q=1.0)
        ]
        state.filters_r = [
            CanonicalFilter(type="PEAK", frequency_hz=2000.0, gain_db=-2.0, q=1.0)
        ]
        assert state.filters != []

        window._on_device_selected("192.168.1.200")

        assert state.filters_l == []
        assert state.filters_r == []
        assert state.filters == []

    def test_device_switch_resets_filters_page_channel_mode_radio(self, window) -> None:
        """PR #19 review follow-up: FiltersPage keeps its own Stereo/L-R radio
        selection independent of state.channel_mode (it's the source of truth
        for a fresh import, not a mirror of it). Without also resetting the
        radio, switching devices while L/R was selected would leave the page
        showing L/R controls even though clear_device_scoped_state() just
        reset state.channel_mode to STEREO -- most visible in the RoomFit
        flow, which has no SOURCE step to force a resync."""
        window._on_device_selected("192.168.1.100")
        window._filters_page.set_channel_mode("lr")
        assert window._filters_page._channel_mode == "lr"

        window._on_device_selected("192.168.1.200")

        assert window._filters_page._channel_mode == "stereo"
        assert window._filters_page._stereo_radio.isChecked()

    def test_device_switch_in_roomfit_clears_name_profile_completed(self, window) -> None:
        """docs/smoke_test_issues.md #246 follow-up, bug 1c: switching devices
        while NAME_PROFILE is completed (RoomFit-only step) must invalidate
        it too -- a hardcoded PEQ-flow step tuple silently leaves it
        completed forever, violating the "no checked step may follow an
        unchecked one" invariant (#124) the moment the user switches back to
        RoomFit."""
        wc = window._wizard_controller
        window._on_device_selected("192.168.1.100")
        wc.set_flow_type(FlowType.ROOMFIT)
        wc.set_step_summary(WizardStep.NAME_PROFILE, "My Profile")
        assert WizardStep.NAME_PROFILE in wc.completed_steps

        window._on_device_selected("192.168.1.200")

        assert WizardStep.NAME_PROFILE not in wc.completed_steps
        assert WizardStep.NAME_PROFILE not in wc.state.completed_step_tooltips

    def test_reselecting_same_device_preserves_filters(self, window) -> None:
        """Re-selecting the already-connected device is a no-op past the busy
        check -- nothing is invalid, so loaded filters/sources/completed
        steps must survive (the probe still re-runs; capabilities can change
        server-side)."""
        from src.models.canonical import CanonicalFilter

        window._on_device_selected("192.168.1.100")
        state = window._wizard_controller.state
        state.current_filters = [
            CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=3.0, q=1.0)
        ]
        state.selected_source = "wifi"
        window._wizard_controller.set_step_summary(WizardStep.EQ_TYPE, "PEQ")

        window._on_device_selected("192.168.1.100")

        assert state.current_filters != []
        assert state.selected_source == "wifi"
        assert WizardStep.EQ_TYPE in window._wizard_controller.completed_steps


# ---------------------------------------------------------------------------
# Issue #57: Back navigation clears step completion badges for invalidated steps
# ---------------------------------------------------------------------------


class TestIssue57BackNavClearsCompletedSteps:
    """Smoke #57, superseded by #246 Stage 2 (lazy invalidation): browsing
    back keeps every checkmark; only an actual selection *change* on the
    revisited step invalidates downstream. Both halves covered here so the
    old eager-clear can't silently return in either direction."""

    def test_go_to_source_preserves_checkmarks_until_change(self, window) -> None:
        """Browse back to SOURCE: nothing clears. Re-pick the same source:
        still nothing. Pick a different source: downstream checkmarks clear."""
        wc = window._wizard_controller

        # Set up PEQ_ONLY flow to avoid EQ_TYPE step
        wc.set_flow_type(FlowType.PEQ_ONLY)
        # Sequence: CONNECT → SOURCE → FILTERS → REVIEW → PUSH

        wc.state.selected_source = "wifi"
        wc.advance(summary="Connected")  # CONNECT done, now at SOURCE
        wc.advance(summary="wifi")  # SOURCE done, now at FILTERS
        wc.advance(summary="Filters loaded")  # FILTERS done, now at REVIEW
        wc.advance(summary="Reviewed")  # REVIEW done, now at PUSH

        # Browse back to SOURCE -- looking is not changing
        wc.go_to_step(WizardStep.SOURCE)
        assert WizardStep.REVIEW in wc.completed_steps
        assert WizardStep.FILTERS in wc.completed_steps
        assert WizardStep.SOURCE in wc.completed_steps

        # Re-confirm the same source/mode -- still no invalidation
        window._on_source_selected("wifi", "Stereo")
        assert WizardStep.REVIEW in wc.completed_steps
        assert WizardStep.FILTERS in wc.completed_steps

        # Actually change the source -- downstream checkmarks clear
        wc.go_to_step(WizardStep.SOURCE)
        window._on_source_selected("optical", "Stereo")
        assert WizardStep.REVIEW not in wc.completed_steps
        assert WizardStep.FILTERS not in wc.completed_steps
        # SOURCE itself was just re-completed by the advance()
        assert WizardStep.SOURCE in wc.completed_steps
        assert WizardStep.CONNECT in wc.completed_steps

    def test_source_reorder_is_not_a_change(self, window) -> None:
        """The selection is a set of sources: the same sources arriving in a
        different order must not count as a change (and must not invalidate
        downstream checkmarks)."""
        wc = window._wizard_controller
        wc.set_flow_type(FlowType.PEQ_ONLY)
        wc.state.selected_source = "wifi,optical"
        wc.advance(summary="Connected")  # CONNECT done, at SOURCE
        wc.advance(summary="2 sources")  # SOURCE done, at FILTERS
        wc.advance(summary="Filters loaded")  # FILTERS done, at REVIEW

        wc.go_to_step(WizardStep.SOURCE)
        window._on_source_selected("optical,wifi", "Stereo")  # same set

        assert WizardStep.FILTERS in wc.completed_steps

    def test_eq_type_change_invalidates_downstream_same_type_does_not(
        self, window
    ) -> None:
        """EQ-type change detection: re-picking the current type keeps
        downstream checkmarks; switching types clears them -- including a
        step that only exists in the flow being left (NAME_PROFILE,
        RoomFit-only, the #248 class of bug)."""
        wc = window._wizard_controller

        # RoomFit flow, advanced through NAME_PROFILE
        wc.advance(summary="Connected")  # CONNECT done, at EQ_TYPE
        window._on_eq_type_selected("roomfit")  # EQ_TYPE done, at FILTERS
        wc.advance(summary="Profile A")  # FILTERS done, at REVIEW
        wc.advance(summary="Reviewed")  # REVIEW done, at NAME_PROFILE
        wc.advance(summary="MyProfile")  # NAME_PROFILE done, at PUSH

        # Browse back and re-confirm RoomFit -- nothing clears
        wc.go_to_step(WizardStep.EQ_TYPE)
        window._on_eq_type_selected("roomfit")
        assert WizardStep.NAME_PROFILE in wc.completed_steps
        assert WizardStep.REVIEW in wc.completed_steps

        # Re-confirming the same type also keeps the loaded payload
        wc.state.current_filters = [MagicMock()]
        wc.state.filters_origin = "RoomFit profile"
        wc.go_to_step(WizardStep.EQ_TYPE)
        window._on_eq_type_selected("roomfit")
        assert wc.state.current_filters != []

        # Browse back and switch to PEQ -- everything after EQ_TYPE clears,
        # including RoomFit-only NAME_PROFILE (checked via the old sequence)
        wc.go_to_step(WizardStep.EQ_TYPE)
        window._on_eq_type_selected("peq")
        assert WizardStep.NAME_PROFILE not in wc.completed_steps
        assert WizardStep.REVIEW not in wc.completed_steps
        assert WizardStep.FILTERS not in wc.completed_steps
        # EQ_TYPE re-completed by the advance(); CONNECT untouched
        assert WizardStep.EQ_TYPE in wc.completed_steps
        assert WizardStep.CONNECT in wc.completed_steps
        # PEQ and RoomFit are different pipelines: the old pipeline's loaded
        # payload must not carry into the new flow (review fix on top of
        # #246 Stage 2 -- same clear the device switch uses).
        assert wc.state.current_filters == []
        assert wc.state.filters_origin == ""


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
        """Calling the real browse handler with a chosen file enables Next."""
        filters_page = window._filters_page
        assert not filters_page._next_btn.isEnabled()

        # Patch the file dialog at the exact import path used by
        # FiltersPage._on_stereo_browse (src.gui.pages.filters_page.QFileDialog),
        # then invoke the real handler -- not a hand-rolled simulation of its
        # effects -- so a regression in the handler itself would be caught.
        with patch(
            "src.gui.pages.filters_page.QFileDialog.getOpenFileName",
            return_value=("/tmp/test.txt", "REW Text Files (*.txt)"),
        ):
            filters_page._on_stereo_browse()

        assert filters_page._next_btn.isEnabled()
        assert filters_page._stereo_path == "/tmp/test.txt"
        assert filters_page._stereo_file_label.text() == "test.txt"


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
            "src.translator.rew_parser.REWParser.parse_file_with_rows",
            return_value=(mock_filters, [], list(mock_filters), {}),
        ):
            await window._primary_workflows._do_file_import("/tmp/stereo_eq.txt")

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
        # The dialog's answers land in wizard *state* only -- steps are
        # marked completed on load success (_jump_to_review), never before
        # the async load resolves, so a failed load can't leave phantom
        # checkmarks or move the frontier.
        assert state.selected_sources == ["wifi"]
        assert WizardStep.SOURCE not in state.completed_steps
        assert WizardStep.FILTERS not in state.completed_steps

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

    def test_load_gate_never_marks_steps_before_load_resolves(self, window) -> None:
        """The load gate must not pre-mark steps completed: the load it
        gates is async and can fail, and pre-marking would leave
        completed_steps (and the derived frontier) claiming progress that
        never happened -- e.g. "Resume Setup" jumping to Review after a
        failed preset load. Steps are marked on success by _jump_to_review."""
        window._on_device_selected("192.168.1.100")
        state = window._wizard_controller.state
        state.completed_steps = {WizardStep.CONNECT: "Connected"}
        state.current_step = WizardStep.FILTERS  # at-FILTERS early return

        assert window._ensure_wizard_state_for_load() is True

        assert set(state.completed_steps) == {WizardStep.CONNECT}
        assert window._wizard_controller.frontier_step == WizardStep.EQ_TYPE

    def test_preview_items_merged_into_quick_setup_warning(self, window) -> None:
        """When QuickSetupDialog is about to show, a preview-warning body is
        passed into it as `warning=`, folding what used to be a separate
        standalone confirmation into the same dialog."""
        window._on_device_selected("192.168.1.100")
        state = window._wizard_controller.state
        state.completed_steps = {WizardStep.CONNECT: "Connected"}

        item = MagicMock(name="Movie Night", preset_type="PEQ")
        item.name = "Movie Night"

        with patch(
            "src.gui.dialogs.quick_setup_dialog.QuickSetupDialog.get_setup",
            return_value=("peq", ["wifi"]),
        ) as mock_get_setup:
            result = window._ensure_wizard_state_for_load(preview_items=[item])

        assert result is True
        mock_get_setup.assert_called_once()
        warning = mock_get_setup.call_args.kwargs["warning"]
        assert warning is not None
        assert "Movie Night" in warning[1]

    def test_preview_items_confirmed_standalone_when_nothing_missing(self, window) -> None:
        """When wizard state is already complete, the preview warning is
        shown as its own standalone confirmation (QuickSetupDialog never
        shows), matching the pre-existing single-dialog behavior."""
        window._on_device_selected("192.168.1.100")
        state = window._wizard_controller.state
        state.completed_steps = {
            WizardStep.CONNECT: "Connected",
            WizardStep.EQ_TYPE: "PEQ",
            WizardStep.SOURCE: "wifi",
            WizardStep.FILTERS: "Loaded",
        }
        state.selected_source = "wifi"

        item = MagicMock(name="Movie Night", preset_type="PEQ")
        item.name = "Movie Night"

        with patch.object(
            window, "_confirm_preset_preview", return_value=False
        ) as mock_confirm:
            result = window._ensure_wizard_state_for_load(preview_items=[item])

        mock_confirm.assert_called_once_with([item])
        assert result is False

# ---------------------------------------------------------------------------
# Issue #95: Wizard state skips QuickSetupDialog if current step is FILTERS or beyond
# ---------------------------------------------------------------------------


class TestIssue95WizardStateSkipsDialog:
    def test_ensure_wizard_state_skips_dialog_if_at_filters_step(self, window) -> None:
        """#95: If current step is FILTERS or beyond, skip dialog and return True."""
        # Select device
        window._on_device_selected("192.168.1.100")

        # Advance wizard to FILTERS step
        window._wizard_controller.state.current_step = WizardStep.FILTERS

        # Verify it returns True without triggering QuickSetupDialog
        with patch("src.gui.dialogs.quick_setup_dialog.QuickSetupDialog.get_setup") as mock_dialog:
            result = window._ensure_wizard_state_for_load()
            assert result is True
            mock_dialog.assert_not_called()

    def test_ensure_wizard_state_at_filters_step_confirms_preview_items(
        self, window
    ) -> None:
        """#200: the "already at/past FILTERS" early-return must still honor
        `preview_items` -- it used to skip the "Preset Will Briefly Activate
        on Device" warning entirely whenever the wizard was already on the
        Review/Push step, unlike the "nothing missing" branch which always
        checked it."""
        window._on_device_selected("192.168.1.100")
        window._wizard_controller.state.current_step = WizardStep.FILTERS

        item = MagicMock(name="Movie Night", preset_type="PEQ")
        item.name = "Movie Night"

        with patch.object(
            window, "_confirm_preset_preview", return_value=True
        ) as mock_confirm:
            result = window._ensure_wizard_state_for_load(preview_items=[item])

        mock_confirm.assert_called_once_with([item])
        assert result is True

    def test_ensure_wizard_state_at_filters_step_declined_preview_returns_false(
        self, window
    ) -> None:
        """#200: declining the folded-in preview warning at the FILTERS-step
        early return must block the load, not silently proceed."""
        window._on_device_selected("192.168.1.100")
        window._wizard_controller.state.current_step = WizardStep.FILTERS

        item = MagicMock(name="Movie Night", preset_type="PEQ")
        item.name = "Movie Night"

        with patch.object(window, "_confirm_preset_preview", return_value=False):
            result = window._ensure_wizard_state_for_load(preview_items=[item])

        assert result is False


# ---------------------------------------------------------------------------
# #162: identical step summaries regardless of which entry point completes
# a step (normal flow, sidebar jump, QuickSetupDialog) -- these three paths
# used to reimplement the same wording independently and had drifted
# (e.g. "ROOMFIT" vs "RoomFit", "N filters" vs "Loaded from preset").
# ---------------------------------------------------------------------------


class TestIssue162ConsistentStepSummaries:
    """All three completion paths must agree on wording for the same input."""

    def test_eq_type_summary_matches_normal_flow_and_sidebar_jump(self, window) -> None:
        window._on_device_selected("192.168.1.100")
        window._on_capabilities_ready(_make_caps(roomfit_level=4))

        # Path A: normal flow
        window._on_eq_type_selected("roomfit")
        normal_summary = window._wizard_controller.state.completed_steps[WizardStep.EQ_TYPE]

        # Path B: sidebar jump -- reset EQ_TYPE and let _mark_prior_steps_completed
        # (used by the sidebar-jump and QuickSetupDialog paths) fill it back in.
        state = window._wizard_controller.state
        state.completed_steps.pop(WizardStep.EQ_TYPE, None)
        window._mark_prior_steps_completed(state)
        sidebar_summary = state.completed_steps[WizardStep.EQ_TYPE]

        assert normal_summary == sidebar_summary == "RoomFit"

    def test_source_summary_and_tooltip_match_normal_flow_and_sidebar_jump(
        self, window
    ) -> None:
        window._on_device_selected("192.168.1.100")
        window._on_capabilities_ready(
            _make_caps(roomfit_level=0, source_names=["wifi", "optical", "hdmi"])
        )

        # Path A: normal flow
        window._on_source_selected("wifi,optical", "Stereo")
        state = window._wizard_controller.state
        normal_summary = state.completed_steps[WizardStep.SOURCE]
        normal_tooltip = state.completed_step_tooltips[WizardStep.SOURCE]

        # Path B: sidebar jump / QuickSetupDialog (both delegate to
        # _mark_prior_steps_completed -> _apply_source_summary)
        state.completed_steps.pop(WizardStep.SOURCE, None)
        state.completed_step_tooltips.pop(WizardStep.SOURCE, None)
        window._mark_prior_steps_completed(state)
        sidebar_summary = state.completed_steps[WizardStep.SOURCE]
        sidebar_tooltip = state.completed_step_tooltips[WizardStep.SOURCE]

        assert normal_summary == sidebar_summary == "2 sources"
        assert normal_tooltip == sidebar_tooltip == "wifi, optical"

    def test_filters_summary_matches_normal_flow_and_sidebar_jump(self, window) -> None:
        window._on_device_selected("192.168.1.100")
        window._on_capabilities_ready(_make_caps(roomfit_level=0))
        window._on_source_selected("wifi", "Stereo")  # PEQ_ONLY: CONNECT->SOURCE->FILTERS
        window._wizard_controller.state.current_filters = [
            MagicMock(), MagicMock(), MagicMock(),
        ]

        # Path A: normal flow
        window._on_filters_accepted()
        state = window._wizard_controller.state
        normal_summary = state.completed_steps[WizardStep.FILTERS]

        # Path B: sidebar jump / QuickSetupDialog
        state.completed_steps.pop(WizardStep.FILTERS, None)
        window._mark_prior_steps_completed(state)
        sidebar_summary = state.completed_steps[WizardStep.FILTERS]

        assert normal_summary == sidebar_summary == "3 filters"


# ---------------------------------------------------------------------------
# Issue #246 Stage 2: lazy invalidation -- entry side effects, push cycle,
# and the device-switch confirmation
# ---------------------------------------------------------------------------


class TestLazyInvalidationEntrySideEffects:
    """Entry side effects (Push page reset, Name Profile repopulate) run only
    when a step is entered fresh at the frontier -- browsing back to a
    completed step must not re-run them (#246 Stage 2)."""

    def _complete_through_push(self, window) -> None:
        """Drive the PEQ_ONLY flow to PUSH with every prior step completed.

        Shows the window first: these tests assert on isVisible(), which is
        always False while every ancestor is hidden.
        """
        window.show()
        window._on_device_selected("192.168.1.100")
        window._on_capabilities_ready(_make_caps(roomfit_level=0))
        window._on_source_selected("wifi", "Stereo")
        window._wizard_controller.state.current_filters = [MagicMock()]
        window._on_filters_accepted()  # -> REVIEW
        window._wizard_controller.advance("Ready")  # REVIEW done -> PUSH

    def test_browsing_back_to_completed_push_keeps_result_view(self, window) -> None:
        """After a completed push, browsing away and back to PUSH must not
        reset the page -- the result view stays on screen."""
        self._complete_through_push(window)
        wc = window._wizard_controller
        wc.set_step_summary(WizardStep.PUSH, "Done")
        window._push_page.set_dry_run_result("3 filters mapped")
        assert window._push_page._status_badge.isVisible()

        wc.go_to_step(WizardStep.FILTERS)  # browse away
        wc.go_to_step(WizardStep.PUSH)  # browse back

        assert window._push_page._status_badge.isVisible()

    def test_entering_fresh_push_frontier_resets_page(self, window) -> None:
        """Entering PUSH while it is NOT completed (the frontier) still runs
        the reset entry side effect, clearing stale dry-run results."""
        self._complete_through_push(window)
        wc = window._wizard_controller
        window._push_page.set_dry_run_result("stale dry run")
        assert window._push_page._status_badge.isVisible()

        wc.go_to_step(WizardStep.FILTERS)  # browse away
        wc.go_to_step(WizardStep.PUSH)  # PUSH not completed -> fresh entry

        assert not window._push_page._status_badge.isVisible()

    def test_done_acknowledged_invalidates_review_and_push_only(self, window) -> None:
        """OK after a push returns to FILTERS keeping its checkmark; REVIEW
        and PUSH are invalidated so the next cycle re-enters PUSH fresh."""
        self._complete_through_push(window)
        wc = window._wizard_controller
        wc.set_step_summary(WizardStep.PUSH, "Done")

        window._on_done_acknowledged()

        assert wc.current_step == WizardStep.FILTERS
        assert WizardStep.FILTERS in wc.completed_steps
        assert WizardStep.REVIEW not in wc.completed_steps
        assert WizardStep.PUSH not in wc.completed_steps
        assert wc.frontier_step == WizardStep.REVIEW


class TestDeviceSwitchConfirmation:
    """Switching devices with unpushed filter work prompts first -- the one
    change-time invalidation that destroys real payload, not just
    checkmarks (#246 Stage 2)."""

    def test_decline_aborts_switch_entirely(self, window, monkeypatch) -> None:
        """Declining the confirmation leaves device, filters, and checkmarks
        untouched and skips the probe."""
        # The forced-True patch below can still be active when qtbot closes
        # the window at teardown; without this closeEvent would block on the
        # (unmocked, custom) UnsavedChangesDialog (see CLAUDE.md).
        window._skip_unsaved_prompt = True
        window._on_device_selected("192.168.1.100")
        window._on_capabilities_ready(_make_caps(roomfit_level=0))
        window._wizard_controller.state.current_filters = [MagicMock()]

        monkeypatch.setattr(MainWindow, "_has_unsaved_changes", lambda self: True)
        completed_before = dict(window._wizard_controller.completed_steps)
        with patch(
            "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
            return_value=False,
        ):
            window._on_device_selected("192.168.1.200")

        state = window._wizard_controller.state
        assert state.selected_device == "192.168.1.100"
        assert state.current_filters != []
        assert dict(window._wizard_controller.completed_steps) == completed_before

    def test_accept_proceeds_with_switch(self, window, monkeypatch) -> None:
        """Accepting the confirmation performs the normal switch-clearing."""
        window._skip_unsaved_prompt = True  # see test above
        window._on_device_selected("192.168.1.100")
        window._on_capabilities_ready(_make_caps(roomfit_level=0))
        window._wizard_controller.state.current_filters = [MagicMock()]

        monkeypatch.setattr(MainWindow, "_has_unsaved_changes", lambda self: True)
        with patch(
            "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
            return_value=True,
        ):
            window._on_device_selected("192.168.1.200")

        state = window._wizard_controller.state
        assert state.selected_device == "192.168.1.200"
        assert state.current_filters == []

    def test_lr_only_filters_trigger_prompt(self, window, monkeypatch) -> None:
        """docs/smoke_test_issues.md #249: unpushed work living only in
        filters_l/filters_r (L/R mode, current_filters empty) must trigger
        the prompt too. _has_unsaved_changes reads state.filters, which
        prefers the L/R lists -- checking only current_filters would let a
        device switch destroy L/R-only payload silently (the same
        field-subset gap class as #247)."""
        from src.models.canonical import CanonicalFilter
        from src.models.channel_mode import ChannelMode

        # Restore the real _has_unsaved_changes (stubbed False by the
        # conftest autouse fixture); the escape hatch keeps closeEvent from
        # blocking on the unmocked UnsavedChangesDialog at teardown.
        monkeypatch.undo()
        window._skip_unsaved_prompt = True
        window._on_device_selected("192.168.1.100")
        state = window._wizard_controller.state
        state.channel_mode = ChannelMode.LR
        state.filters_l = [
            CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=3.0, q=1.0)
        ]
        state.filters_r = [
            CanonicalFilter(type="PEAK", frequency_hz=2000.0, gain_db=-2.0, q=1.0)
        ]
        assert state.current_filters == []

        with patch(
            "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm",
            return_value=False,
        ) as confirm:
            window._on_device_selected("192.168.1.200")

        confirm.assert_called_once()
        assert state.selected_device == "192.168.1.100"
        assert state.filters_l != []
        assert state.filters_r != []

    def test_no_unsaved_changes_switches_without_prompt(self, window) -> None:
        """No unsaved filter work -- the switch proceeds silently (the
        autouse fixture forces _has_unsaved_changes to False)."""
        window._on_device_selected("192.168.1.100")
        with patch(
            "src.gui.dialogs.warning_confirm_dialog.WarningConfirmDialog.confirm"
        ) as confirm:
            window._on_device_selected("192.168.1.200")

        confirm.assert_not_called()
        assert window._wizard_controller.state.selected_device == "192.168.1.200"
