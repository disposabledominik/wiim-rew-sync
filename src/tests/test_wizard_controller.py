"""Unit tests for WizardController — adaptive flow state machine.

Tests flow branching, navigation, signal emission, can_push prerequisites,
and step summary management.

Requirements referenced: 1.2-1.12, 11.1-11.8.
"""

from __future__ import annotations

import pytest

from src.gui.wizard_controller import (
    FlowType,
    WizardController,
    WizardState,
    WizardStep,
    steps_for_flow,
)
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

    def test_go_to_step_preserves_completed_steps(self, qtbot) -> None:
        """go_to_step is purely navigational (lazy invalidation, #246):
        browsing back to a completed step keeps every checkmark -- looking
        is not changing. Invalidation happens only at change-time via
        invalidate_from()."""
        ctrl = WizardController()

        # Advance through several steps
        ctrl.advance("Connected")  # CONNECT → EQ_TYPE
        ctrl.advance("PEQ")  # EQ_TYPE → SOURCE
        ctrl.advance("WiFi")  # SOURCE → FILTERS

        # Now browse back to EQ_TYPE
        ctrl.go_to_step(WizardStep.EQ_TYPE)

        assert ctrl.current_step == WizardStep.EQ_TYPE
        # Everything stays completed -- browsing destroys nothing
        assert WizardStep.CONNECT in ctrl.completed_steps
        assert WizardStep.EQ_TYPE in ctrl.completed_steps
        assert WizardStep.SOURCE in ctrl.completed_steps

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

    def test_go_to_step_connect_retains_device_and_filter_state(self, qtbot) -> None:
        """go_to_step(CONNECT) only invalidates completed_steps for CONNECT and
        later -- unlike reset(), it must NOT clear selected_device, filters,
        or flow_type. Navigating back to look at Connect is not the same as
        switching devices (docs/smoke_test_issues.md #246 follow-up: an
        earlier version of this fix conflated the two)."""
        ctrl = WizardController()
        ctrl.set_flow_type(FlowType.ROOMFIT)
        ctrl._state.selected_device = "WiiM Pro Plus"
        ctrl._state.current_filters = [
            CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=3.0, q=1.0)
        ]
        ctrl.advance("Connected")

        ctrl.go_to_step(WizardStep.CONNECT)

        assert ctrl.current_step == WizardStep.CONNECT
        assert ctrl.flow_type == FlowType.ROOMFIT
        assert ctrl._state.selected_device == "WiiM Pro Plus"
        assert ctrl._state.current_filters != []

    def test_invalidate_from_pops_tooltips_too(self, qtbot) -> None:
        """invalidate_from() must pop completed_step_tooltips alongside
        completed_steps -- an earlier version only popped the summary dict,
        leaving a stale tooltip behind (benign while set_step_summary()
        always overwrites on re-completion, but latent drift worth covering
        directly)."""
        ctrl = WizardController()
        ctrl.advance("Connected", tooltip="192.168.1.100")

        ctrl.invalidate_from(WizardStep.CONNECT)

        assert WizardStep.CONNECT not in ctrl.completed_steps
        assert WizardStep.CONNECT not in ctrl._state.completed_step_tooltips

    @pytest.mark.parametrize("flow_type", [FlowType.PEQ, FlowType.ROOMFIT, FlowType.PEQ_ONLY])
    def test_invalidate_from_first_step_clears_whole_sequence(
        self, qtbot, flow_type: FlowType
    ) -> None:
        """invalidate_from() is sequence-driven per flow_type, so it can't
        silently miss a flow-specific step (e.g. NAME_PROFILE, RoomFit-only)
        the way a hardcoded step tuple can (#246 follow-up, bug 1c)."""
        ctrl = WizardController()
        ctrl.set_flow_type(flow_type)
        sequence = ctrl.get_steps()
        for step in sequence:
            ctrl.set_step_summary(step, "done")

        ctrl.invalidate_from(sequence[0])

        for step in sequence:
            assert step not in ctrl.completed_steps
            assert step not in ctrl._state.completed_step_tooltips

    def test_frontier_is_first_incomplete_step(self, qtbot) -> None:
        """frontier_step derives the first step not in completed_steps, and
        browsing (go_to_step) never moves it."""
        ctrl = WizardController()
        assert ctrl.frontier_step == WizardStep.CONNECT

        ctrl.advance("Connected")  # CONNECT done
        ctrl.advance("PEQ")  # EQ_TYPE done
        assert ctrl.frontier_step == WizardStep.SOURCE

        ctrl.go_to_step(WizardStep.CONNECT)
        assert ctrl.current_step == WizardStep.CONNECT
        assert ctrl.frontier_step == WizardStep.SOURCE

    def test_frontier_clamps_to_last_step_when_all_complete(self, qtbot) -> None:
        """With every step completed, frontier_step clamps to the sequence's
        last step instead of walking off the end."""
        ctrl = WizardController()
        for step in ctrl.get_steps():
            ctrl.set_step_summary(step, "done")

        assert ctrl.frontier_step == WizardStep.PUSH

    def test_frontier_ignores_stale_off_sequence_entries(self, qtbot) -> None:
        """A completed entry for a step that would fall outside the new
        flow's sequence doesn't disturb frontier_step's derivation --
        set_flow_type() invalidates it outright now (see
        TestWizardControllerFlowTypeInvalidation; #266), so this is no
        longer even a "stale but invisible" entry, just gone."""
        ctrl = WizardController()
        ctrl.advance("Connected")  # CONNECT done
        ctrl.advance("PEQ")  # EQ_TYPE done (PEQ flow)
        ctrl.set_flow_type(FlowType.PEQ_ONLY)  # sequence loses EQ_TYPE

        assert WizardStep.EQ_TYPE not in ctrl.completed_steps
        assert ctrl.frontier_step == WizardStep.SOURCE

    @pytest.mark.parametrize("flow_type", [FlowType.PEQ, FlowType.ROOMFIT, FlowType.PEQ_ONLY])
    def test_invalidate_after_pops_only_later_steps(
        self, qtbot, flow_type: FlowType
    ) -> None:
        """invalidate_after(step) clears everything strictly after `step` in
        the current sequence, leaving `step` itself completed -- the single
        owner of the index math every change-time handler used to hand-roll
        (one of them hardcoding sequence[1])."""
        ctrl = WizardController()
        ctrl.set_flow_type(flow_type)
        sequence = ctrl.get_steps()
        for step in sequence:
            ctrl.set_step_summary(step, "done")

        ctrl.invalidate_after(sequence[0])

        assert sequence[0] in ctrl.completed_steps
        for step in sequence[1:]:
            assert step not in ctrl.completed_steps

    def test_invalidate_after_missing_step_is_a_noop(self, qtbot) -> None:
        """invalidate_after with a step not in the current sequence must not
        guess a fallback index -- nothing is invalidated (the old inline
        `else 0` fallback would have cleared an arbitrary range)."""
        ctrl = WizardController()
        ctrl.set_flow_type(FlowType.PEQ_ONLY)  # sequence has no EQ_TYPE
        for step in ctrl.get_steps():
            ctrl.set_step_summary(step, "done")

        ctrl.invalidate_after(WizardStep.EQ_TYPE)

        for step in ctrl.get_steps():
            assert step in ctrl.completed_steps

    def test_invalidate_after_last_step_pops_nothing(self, qtbot) -> None:
        """invalidate_after on the sequence's last step has nothing after it
        to clear."""
        ctrl = WizardController()
        sequence = ctrl.get_steps()
        for step in sequence:
            ctrl.set_step_summary(step, "done")

        ctrl.invalidate_after(sequence[-1])

        for step in sequence:
            assert step in ctrl.completed_steps

    def test_clear_filter_payload_spares_device_and_sources(self, qtbot) -> None:
        """clear_filter_payload() clears the loaded payload (filters, rows,
        notes, warnings, origin) but keeps device identity, source
        selection, and push/backup context -- the EQ-type switch needs
        exactly this subset, and hand-picking fields at the call site is the
        drift pattern that produced #246 bug 1b."""
        ctrl = WizardController()
        state = ctrl.state
        state.selected_device = "192.168.1.100"
        state.selected_sources = ["wifi"]
        state.current_filters = [
            CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=3.0, q=1.0)
        ]
        state.filters_l = list(state.current_filters)
        state.filters_r = list(state.current_filters)
        state.last_pushed_filters = list(state.current_filters)
        state.warnings = ["clamped"]
        state.filters_origin = "REW file"

        state.clear_filter_payload()

        assert state.current_filters == []
        assert state.filters_l == []
        assert state.filters_r == []
        assert state.warnings == []
        assert state.filters_origin == ""
        # Device identity, source selection, and push context survive
        assert state.selected_device == "192.168.1.100"
        assert state.selected_sources == ["wifi"]
        assert state.last_pushed_filters != []

    def test_invalidate_from_emits_steps_invalidated(self, qtbot) -> None:
        """invalidate_from() emits steps_invalidated when it actually pops
        something, and stays silent when there was nothing to pop -- views
        resync off this signal, so a spurious emission means wasted repaints
        and a missing one means a stale indicator."""
        ctrl = WizardController()
        ctrl.advance("Connected")

        with qtbot.waitSignal(ctrl.steps_invalidated, timeout=1000):
            ctrl.invalidate_from(WizardStep.CONNECT)

        emissions: list[bool] = []
        ctrl.steps_invalidated.connect(lambda: emissions.append(True))
        ctrl.invalidate_from(WizardStep.CONNECT)  # already empty
        assert emissions == []

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
# TestWizardControllerFlowTypeInvalidation
# ---------------------------------------------------------------------------


class TestWizardControllerFlowTypeInvalidation:
    """set_flow_type() invalidates whatever's orphaned by the switch on its
    own (docs/smoke_test_issues.md #266's confirmed root cause: a call site
    -- FiltersPage's Device-panel preset selection -- changed flow_type with
    no invalidation at all, leaving SOURCE stale). This is a general
    property of *any* flow_type change, derived from comparing the old and
    new sequences rather than a hardcoded anchor step, so it covers every
    step that's flow-specific -- SOURCE (PEQ-only), NAME_PROFILE
    (RoomFit-only), and EQ_TYPE (absent from PEQ_ONLY) -- not just the one
    that was reported, and protects every current and future call site
    uniformly rather than requiring each one to remember."""

    def test_peq_to_roomfit_invalidates_source(self, qtbot) -> None:
        """SOURCE exists in PEQ's sequence but not RoomFit's -- switching
        away from PEQ must invalidate it immediately, not leave it as an
        orphaned entry invisible only until something makes it relevant
        again (the exact #266 mechanism)."""
        ctrl = WizardController()
        ctrl.set_flow_type(FlowType.PEQ)
        for step in ctrl.get_steps():
            ctrl.set_step_summary(step, "done")
        assert WizardStep.SOURCE in ctrl.completed_steps

        ctrl.set_flow_type(FlowType.ROOMFIT)

        assert WizardStep.SOURCE not in ctrl.completed_steps
        assert WizardStep.CONNECT in ctrl.completed_steps
        assert WizardStep.EQ_TYPE in ctrl.completed_steps

    def test_roomfit_to_peq_invalidates_name_profile(self, qtbot) -> None:
        """The mirror image of the above: NAME_PROFILE exists only in
        RoomFit's sequence, so switching away from RoomFit must invalidate
        it too -- the same bug class the user asked about directly."""
        ctrl = WizardController()
        ctrl.set_flow_type(FlowType.ROOMFIT)
        for step in ctrl.get_steps():
            ctrl.set_step_summary(step, "done")
        assert WizardStep.NAME_PROFILE in ctrl.completed_steps

        ctrl.set_flow_type(FlowType.PEQ)

        assert WizardStep.NAME_PROFILE not in ctrl.completed_steps
        assert WizardStep.CONNECT in ctrl.completed_steps
        assert WizardStep.EQ_TYPE in ctrl.completed_steps

    @pytest.mark.parametrize("from_flow", [FlowType.PEQ, FlowType.ROOMFIT])
    def test_to_peq_only_invalidates_eq_type(self, qtbot, from_flow: FlowType) -> None:
        """EQ_TYPE doesn't exist in PEQ_ONLY's sequence -- switching to it
        from either PEQ or RoomFit must invalidate EQ_TYPE (and everything
        after it), matching the real _on_capabilities_ready path (a
        RoomFit-capable device's re-probe reporting PEQ-only support)."""
        ctrl = WizardController()
        ctrl.set_flow_type(from_flow)
        for step in ctrl.get_steps():
            ctrl.set_step_summary(step, "done")

        ctrl.set_flow_type(FlowType.PEQ_ONLY)

        assert WizardStep.EQ_TYPE not in ctrl.completed_steps
        assert WizardStep.CONNECT in ctrl.completed_steps

    def test_no_stale_entry_resurfaces_after_a_later_switch_back(self, qtbot) -> None:
        """The specific resurrection shape #266 reported: a step orphaned
        by one flow_type switch must not come back as completed once a
        later switch makes it part of the sequence again."""
        ctrl = WizardController()
        ctrl.set_flow_type(FlowType.PEQ)
        for step in ctrl.get_steps():
            ctrl.set_step_summary(step, "done")

        ctrl.set_flow_type(FlowType.ROOMFIT)  # SOURCE invalidated here
        ctrl.set_flow_type(FlowType.PEQ)  # SOURCE re-enters the sequence

        assert WizardStep.SOURCE not in ctrl.completed_steps

    def test_common_prefix_is_preserved(self, qtbot) -> None:
        """Steps shared by both sequences at the same position (CONNECT,
        and EQ_TYPE for a PEQ<->RoomFit switch) are untouched -- only the
        point of divergence onward is invalidated."""
        ctrl = WizardController()
        ctrl.set_flow_type(FlowType.PEQ)
        ctrl.set_step_summary(WizardStep.CONNECT, "WiiM Pro")
        ctrl.set_step_summary(WizardStep.EQ_TYPE, "PEQ")

        ctrl.set_flow_type(FlowType.ROOMFIT)

        assert ctrl.completed_steps[WizardStep.CONNECT] == "WiiM Pro"
        assert ctrl.completed_steps[WizardStep.EQ_TYPE] == "PEQ"

    def test_same_flow_type_invalidates_nothing(self, qtbot) -> None:
        """Setting the flow_type to its current value is a no-op (existing
        behavior) -- must not spuriously invalidate anything."""
        ctrl = WizardController()
        ctrl.set_flow_type(FlowType.PEQ)
        for step in ctrl.get_steps():
            ctrl.set_step_summary(step, "done")

        emissions: list[bool] = []
        ctrl.steps_invalidated.connect(lambda: emissions.append(True))
        ctrl.set_flow_type(FlowType.PEQ)

        assert emissions == []
        for step in ctrl.get_steps():
            assert step in ctrl.completed_steps

    def test_emits_steps_invalidated_when_something_is_popped(self, qtbot) -> None:
        """The consolidated invalidation still emits steps_invalidated, the
        same signal views already resync off -- callers that dropped their
        own invalidate_after() call in favor of this one don't lose the
        re-render trigger."""
        ctrl = WizardController()
        ctrl.set_flow_type(FlowType.PEQ)
        ctrl.set_step_summary(WizardStep.SOURCE, "wifi")

        with qtbot.waitSignal(ctrl.steps_invalidated, timeout=1000):
            ctrl.set_flow_type(FlowType.ROOMFIT)

    def test_no_emission_when_nothing_to_invalidate(self, qtbot) -> None:
        """A flow_type switch where the old sequence is fully a prefix of
        the new one (nothing completed past the divergence point) must not
        spuriously emit steps_invalidated."""
        ctrl = WizardController()
        ctrl.set_flow_type(FlowType.PEQ)
        ctrl.set_step_summary(WizardStep.CONNECT, "WiiM Pro")

        emissions: list[bool] = []
        ctrl.steps_invalidated.connect(lambda: emissions.append(True))
        ctrl.set_flow_type(FlowType.ROOMFIT)

        assert emissions == []


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

    def test_go_to_step_keeps_summaries(self, qtbot) -> None:
        """go_to_step keeps every completed step's summary -- browsing is
        purely navigational under lazy invalidation (#246)."""
        ctrl = WizardController()

        ctrl.advance("Connected")
        ctrl.advance("PEQ")
        ctrl.advance("WiFi")

        # Browse back to CONNECT
        ctrl.go_to_step(WizardStep.CONNECT)

        assert ctrl.completed_steps[WizardStep.CONNECT] == "Connected"
        assert ctrl.completed_steps[WizardStep.EQ_TYPE] == "PEQ"
        assert ctrl.completed_steps[WizardStep.SOURCE] == "WiFi"


class TestWizardStateSourceSelection:
    """WizardState source-selection accessors (docs/smoke_test_issues.md #194).

    ``selected_sources`` (list) is the authoritative store; ``selected_source``
    is a comma-joined compatibility property whose setter parses back into the
    list (the Qt signal boundary still speaks comma-joined strings);
    ``primary_source`` is the single-source accessor every single-source
    device operation must use.
    """

    def test_single_source_passthrough(self) -> None:
        state = WizardState()
        state.selected_source = "optical"
        assert state.selected_sources == ["optical"]
        assert state.primary_source == "optical"

    def test_comma_joined_returns_first(self) -> None:
        state = WizardState()
        state.selected_source = "wifi,bluetooth,auxIn"
        assert state.selected_sources == ["wifi", "bluetooth", "auxIn"]
        assert state.primary_source == "wifi"

    def test_whitespace_stripped(self) -> None:
        state = WizardState()
        state.selected_source = "wifi, optical"
        assert state.selected_sources == ["wifi", "optical"]
        assert state.primary_source == "wifi"
        state.selected_source = " bluetooth , wifi"
        assert state.primary_source == "bluetooth"

    def test_empty_defaults_to_wifi(self) -> None:
        state = WizardState()
        state.selected_source = ""
        assert state.selected_sources == []
        assert state.primary_source == "wifi"

    def test_leading_empty_parts_skipped(self) -> None:
        state = WizardState()
        state.selected_source = " , ,optical"
        assert state.selected_sources == ["optical"]
        assert state.primary_source == "optical"

    def test_getter_round_trips_comma_joined(self) -> None:
        state = WizardState()
        state.selected_source = "wifi, optical"
        assert state.selected_source == "wifi,optical"
