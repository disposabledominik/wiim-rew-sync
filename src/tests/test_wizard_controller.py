"""Unit tests for WizardController — adaptive flow state machine.

Tests flow branching, navigation, signal emission, can_push prerequisites,
and step summary management.

Requirements referenced: 1.2-1.12, 11.1-11.8.
"""

from __future__ import annotations

from src.gui.wizard_controller import FlowType, WizardController, WizardStep, steps_for_flow
from src.models.canonical import CanonicalFilter

# ---------------------------------------------------------------------------
# TestWizardControllerFlowBranching
# ---------------------------------------------------------------------------


class TestWizardControllerFlowBranching:
    """Tests for flow type branching and step sequences."""

    def test_peq_flow_sequence(self, qtbot) -> None:
        """PEQ flow follows CONNECT → EQ_TYPE → SOURCE → FILTERS → REVIEW → PUSH."""
        ctrl = WizardController()

        ctrl.set_flow_type(FlowType.PEQ)

        expected = [
            WizardStep.CONNECT,
            WizardStep.EQ_TYPE,
            WizardStep.SOURCE,
            WizardStep.FILTERS,
            WizardStep.REVIEW,
            WizardStep.PUSH,
        ]
        assert ctrl.get_steps() == expected

    def test_roomfit_flow_sequence(self, qtbot) -> None:
        """ROOMFIT flow follows CONNECT → EQ_TYPE → FILTERS → REVIEW → NAME_PROFILE → PUSH."""
        ctrl = WizardController()

        ctrl.set_flow_type(FlowType.ROOMFIT)

        expected = [
            WizardStep.CONNECT,
            WizardStep.EQ_TYPE,
            WizardStep.FILTERS,
            WizardStep.REVIEW,
            WizardStep.NAME_PROFILE,
            WizardStep.PUSH,
        ]
        assert ctrl.get_steps() == expected

    def test_peq_only_flow_sequence(self, qtbot) -> None:
        """PEQ_ONLY flow follows CONNECT → SOURCE → FILTERS → REVIEW → PUSH (no EQ_TYPE)."""
        ctrl = WizardController()

        ctrl.set_flow_type(FlowType.PEQ_ONLY)

        expected = [
            WizardStep.CONNECT,
            WizardStep.SOURCE,
            WizardStep.FILTERS,
            WizardStep.REVIEW,
            WizardStep.PUSH,
        ]
        assert ctrl.get_steps() == expected

    def test_set_flow_type_emits_signal(self, qtbot) -> None:
        """set_flow_type emits flow_type_changed with the new FlowType."""
        ctrl = WizardController()

        with qtbot.waitSignal(ctrl.flow_type_changed, timeout=1000) as blocker:
            ctrl.set_flow_type(FlowType.ROOMFIT)

        assert blocker.args == [FlowType.ROOMFIT]

    def test_set_same_flow_type_does_not_emit(self, qtbot) -> None:
        """set_flow_type with the current type does not emit flow_type_changed."""
        ctrl = WizardController()
        # Default is PEQ

        signals_received: list[FlowType] = []
        ctrl.flow_type_changed.connect(signals_received.append)

        ctrl.set_flow_type(FlowType.PEQ)

        assert signals_received == []

    def test_steps_for_flow_function(self, qtbot) -> None:
        """steps_for_flow returns correct sequences for each FlowType."""
        peq = steps_for_flow(FlowType.PEQ)
        roomfit = steps_for_flow(FlowType.ROOMFIT)
        peq_only = steps_for_flow(FlowType.PEQ_ONLY)

        assert WizardStep.EQ_TYPE in peq
        assert WizardStep.EQ_TYPE in roomfit
        assert WizardStep.EQ_TYPE not in peq_only
        assert WizardStep.NAME_PROFILE in roomfit
        assert WizardStep.NAME_PROFILE not in peq
        assert WizardStep.SOURCE not in roomfit


# ---------------------------------------------------------------------------
# TestWizardControllerNavigation
# ---------------------------------------------------------------------------


class TestWizardControllerNavigation:
    """Tests for advance, go_to_step, and reset navigation."""

    def test_advance_moves_to_next_step(self, qtbot) -> None:
        """advance() moves current_step to the next step in the sequence."""
        ctrl = WizardController()

        ctrl.advance("Device connected")

        assert ctrl.current_step == WizardStep.EQ_TYPE

    def test_advance_at_final_step_does_nothing(self, qtbot) -> None:
        """advance() at the last step does not change current_step."""
        ctrl = WizardController()
        # Navigate to the last step (PUSH)
        ctrl._state.current_step = WizardStep.PUSH

        ctrl.advance()

        assert ctrl.current_step == WizardStep.PUSH

    def test_advance_emits_step_changed(self, qtbot) -> None:
        """advance() emits step_changed with the new step."""
        ctrl = WizardController()

        with qtbot.waitSignal(ctrl.step_changed, timeout=1000) as blocker:
            ctrl.advance()

        assert blocker.args == [WizardStep.EQ_TYPE]

    def test_advance_adds_to_completed(self, qtbot) -> None:
        """advance() adds the previous step to completed_steps."""
        ctrl = WizardController()

        ctrl.advance("WiiM Pro Plus")

        assert WizardStep.CONNECT in ctrl.completed_steps
        assert ctrl.completed_steps[WizardStep.CONNECT] == "WiiM Pro Plus"

    def test_go_to_step_invalidates_subsequent(self, qtbot) -> None:
        """go_to_step invalidates all steps after the target in completed_steps."""
        ctrl = WizardController()

        # Advance through several steps
        ctrl.advance("Connected")  # CONNECT → EQ_TYPE
        ctrl.advance("PEQ")  # EQ_TYPE → SOURCE
        ctrl.advance("WiFi")  # SOURCE → FILTERS

        # Now go back to EQ_TYPE
        ctrl.go_to_step(WizardStep.EQ_TYPE)

        assert ctrl.current_step == WizardStep.EQ_TYPE
        # CONNECT should remain completed
        assert WizardStep.CONNECT in ctrl.completed_steps
        # EQ_TYPE and beyond should be invalidated
        assert WizardStep.EQ_TYPE not in ctrl.completed_steps
        assert WizardStep.SOURCE not in ctrl.completed_steps

    def test_go_to_step_emits_step_changed(self, qtbot) -> None:
        """go_to_step emits step_changed with the target step."""
        ctrl = WizardController()
        ctrl.advance("Connected")  # CONNECT → EQ_TYPE

        with qtbot.waitSignal(ctrl.step_changed, timeout=1000) as blocker:
            ctrl.go_to_step(WizardStep.CONNECT)

        assert blocker.args == [WizardStep.CONNECT]

    def test_go_to_step_not_in_sequence_does_nothing(self, qtbot) -> None:
        """go_to_step with a step not in the current flow sequence does nothing."""
        ctrl = WizardController()
        ctrl.set_flow_type(FlowType.PEQ_ONLY)
        # EQ_TYPE is not in PEQ_ONLY flow

        signals_received: list[WizardStep] = []
        ctrl.step_changed.connect(signals_received.append)

        ctrl.go_to_step(WizardStep.EQ_TYPE)

        # Should not emit and step should remain unchanged
        assert signals_received == []
        assert ctrl.current_step == WizardStep.CONNECT

    def test_reset_clears_state(self, qtbot) -> None:
        """reset() restores initial state (CONNECT step, PEQ flow, no completed)."""
        ctrl = WizardController()

        # Modify state
        ctrl.set_flow_type(FlowType.ROOMFIT)
        ctrl.advance("Device")
        ctrl._state.selected_device = "WiiM Pro"
        ctrl._state.current_filters = [
            CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=3.0, q=1.0)
        ]

        ctrl.reset()

        assert ctrl.current_step == WizardStep.CONNECT
        assert ctrl.flow_type == FlowType.PEQ
        assert ctrl._state.selected_device is None
        assert ctrl._state.current_filters == []
        assert ctrl.completed_steps == {}

    def test_reset_emits_wizard_reset(self, qtbot) -> None:
        """reset() emits wizard_reset signal."""
        ctrl = WizardController()
        ctrl.advance("Connected")

        with qtbot.waitSignal(ctrl.wizard_reset, timeout=1000):
            ctrl.reset()

    def test_reset_emits_step_changed_connect(self, qtbot) -> None:
        """reset() emits step_changed with CONNECT."""
        ctrl = WizardController()
        ctrl.advance("Connected")

        with qtbot.waitSignal(ctrl.step_changed, timeout=1000) as blocker:
            ctrl.reset()

        assert blocker.args == [WizardStep.CONNECT]


# ---------------------------------------------------------------------------
# TestWizardControllerCanPush
# ---------------------------------------------------------------------------


class TestWizardControllerCanPush:
    """Tests for can_push prerequisite checks."""

    def _setup_pushable(self, ctrl: WizardController) -> None:
        """Set up state so that can_push returns True."""
        ctrl._state.selected_device = "WiiM Pro Plus"
        ctrl._state.selected_source = "wifi"
        ctrl._state.current_filters = [
            CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=3.0, q=1.0)
        ]
        ctrl._state.dry_run = False

    def test_can_push_all_conditions_met(self, qtbot) -> None:
        """can_push returns True when all prerequisites are satisfied."""
        ctrl = WizardController()
        self._setup_pushable(ctrl)

        assert ctrl.can_push() is True

    def test_cannot_push_no_device(self, qtbot) -> None:
        """can_push returns False when no device is selected."""
        ctrl = WizardController()
        self._setup_pushable(ctrl)
        ctrl._state.selected_device = None

        assert ctrl.can_push() is False

    def test_cannot_push_no_source_peq(self, qtbot) -> None:
        """can_push returns False for PEQ flow when no source is selected."""
        ctrl = WizardController()
        self._setup_pushable(ctrl)
        ctrl._state.flow_type = FlowType.PEQ
        ctrl._state.selected_source = ""

        assert ctrl.can_push() is False

    def test_can_push_roomfit_no_source(self, qtbot) -> None:
        """can_push returns True for ROOMFIT flow even without a source selected."""
        ctrl = WizardController()
        self._setup_pushable(ctrl)
        ctrl._state.flow_type = FlowType.ROOMFIT
        ctrl._state.selected_source = ""

        assert ctrl.can_push() is True

    def test_cannot_push_no_filters(self, qtbot) -> None:
        """can_push returns False when current_filters is empty."""
        ctrl = WizardController()
        self._setup_pushable(ctrl)
        ctrl._state.current_filters = []

        assert ctrl.can_push() is False

    def test_cannot_push_dry_run(self, qtbot) -> None:
        """can_push returns False when dry_run is True."""
        ctrl = WizardController()
        self._setup_pushable(ctrl)
        ctrl._state.dry_run = True

        assert ctrl.can_push() is False


# ---------------------------------------------------------------------------
# TestWizardControllerSummaries
# ---------------------------------------------------------------------------


class TestWizardControllerSummaries:
    """Tests for step summary storage and signal emission."""

    def test_advance_with_summary_stored(self, qtbot) -> None:
        """advance(summary) stores the summary in completed_steps."""
        ctrl = WizardController()

        ctrl.advance("WiiM Pro Plus connected")
        ctrl.advance("PEQ selected")

        assert ctrl.completed_steps[WizardStep.CONNECT] == "WiiM Pro Plus connected"
        assert ctrl.completed_steps[WizardStep.EQ_TYPE] == "PEQ selected"

    def test_step_summary_updated_signal(self, qtbot) -> None:
        """advance() emits step_summary_updated with step, summary, and tooltip."""
        ctrl = WizardController()

        with qtbot.waitSignal(ctrl.step_summary_updated, timeout=1000) as blocker:
            ctrl.advance("Device found")

        assert blocker.args == [WizardStep.CONNECT, "Device found", ""]

    def test_step_summary_updated_signal_carries_tooltip(self, qtbot) -> None:
        """advance(summary, tooltip) emits the tooltip alongside the summary."""
        ctrl = WizardController()

        with qtbot.waitSignal(ctrl.step_summary_updated, timeout=1000) as blocker:
            ctrl.advance("3 sources", "wifi, optical, HDMI")

        assert blocker.args == [WizardStep.CONNECT, "3 sources", "wifi, optical, HDMI"]
        assert ctrl.state.completed_step_tooltips[WizardStep.CONNECT] == "wifi, optical, HDMI"

    def test_set_step_summary_emits_without_transitioning(self, qtbot) -> None:
        """set_step_summary() writes both dicts and emits, but doesn't move
        current_step -- used for out-of-band single-step updates (e.g. PUSH)."""
        ctrl = WizardController()
        original_step = ctrl.current_step

        with qtbot.waitSignal(ctrl.step_summary_updated, timeout=1000) as blocker:
            ctrl.set_step_summary(WizardStep.PUSH, "Done")

        assert blocker.args == [WizardStep.PUSH, "Done", ""]
        assert ctrl.completed_steps[WizardStep.PUSH] == "Done"
        assert ctrl.current_step == original_step

    def test_advance_empty_summary(self, qtbot) -> None:
        """advance() with no summary stores empty string."""
        ctrl = WizardController()

        ctrl.advance()

        assert ctrl.completed_steps[WizardStep.CONNECT] == ""

    def test_go_to_step_clears_summaries(self, qtbot) -> None:
        """go_to_step removes summaries for invalidated steps."""
        ctrl = WizardController()

        ctrl.advance("Connected")
        ctrl.advance("PEQ")
        ctrl.advance("WiFi")

        # Go back to CONNECT
        ctrl.go_to_step(WizardStep.CONNECT)

        # All summaries after CONNECT should be cleared
        assert WizardStep.CONNECT not in ctrl.completed_steps
        assert WizardStep.EQ_TYPE not in ctrl.completed_steps
        assert WizardStep.SOURCE not in ctrl.completed_steps
