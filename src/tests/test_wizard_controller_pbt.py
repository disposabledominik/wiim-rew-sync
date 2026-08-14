"""Property-based tests for WizardController.

Tests the core state-machine logic of the wizard flow: step sequencing,
classification, advancement, and back-navigation.
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.gui.wizard_controller import (
    FlowType,
    WizardController,
    WizardStep,
    steps_for_flow,
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

st_flow_type = st.sampled_from(list(FlowType))
st_wizard_step = st.sampled_from(list(WizardStep))


@st.composite
def st_advancement_index(draw: st.DrawFn) -> tuple[FlowType, int]:
    """Generate a (flow_type, step_index) where step_index is NOT the final step."""
    flow = draw(st_flow_type)
    seq = steps_for_flow(flow)
    # Pick any index except the last
    idx = draw(st.integers(min_value=0, max_value=len(seq) - 2))
    return (flow, idx)


@st.composite
def st_back_nav_scenario(draw: st.DrawFn) -> tuple[FlowType, int, int]:
    """Generate (flow_type, advance_count, back_target_idx).

    advance_count: how many times to advance from the start (at least 2).
    back_target_idx: where to navigate back to (< advance_count).
    """
    flow = draw(st_flow_type)
    seq = steps_for_flow(flow)
    max_advances = len(seq) - 1  # can advance at most (len-1) times
    advance_count = draw(st.integers(min_value=2, max_value=max_advances))
    back_target_idx = draw(st.integers(min_value=0, max_value=advance_count - 1))
    return (flow, advance_count, back_target_idx)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _ensure_qapp():
    """Ensure a QApplication exists for WizardController (QObject) tests."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


# ---------------------------------------------------------------------------
# Property 1: Flow step sequence correctness
# **Validates: Requirements 1.2, 1.9, 1.10, 1.11**
# ---------------------------------------------------------------------------

EXPECTED_SEQUENCES = {
    FlowType.PEQ: [
        WizardStep.CONNECT,
        WizardStep.EQ_TYPE,
        WizardStep.SOURCE,
        WizardStep.FILTERS,
        WizardStep.REVIEW,
        WizardStep.PUSH,
    ],
    FlowType.ROOMFIT: [
        WizardStep.CONNECT,
        WizardStep.EQ_TYPE,
        WizardStep.FILTERS,
        WizardStep.REVIEW,
        WizardStep.NAME_PROFILE,
        WizardStep.PUSH,
    ],
    FlowType.PEQ_ONLY: [
        WizardStep.CONNECT,
        WizardStep.SOURCE,
        WizardStep.FILTERS,
        WizardStep.REVIEW,
        WizardStep.PUSH,
    ],
}


@given(flow_type=st_flow_type)
@settings(max_examples=100)
def test_flow_step_sequence_correctness(flow_type: FlowType) -> None:
    """**Validates: Requirements 1.2, 1.9, 1.10, 1.11**

    For any valid FlowType, steps_for_flow() returns the exact documented
    sequence. No SOURCE for RoomFit, no EQ_TYPE for PEQ-only, NAME_PROFILE
    only for RoomFit.
    """
    result = steps_for_flow(flow_type)

    # Exact sequence match
    assert result == EXPECTED_SEQUENCES[flow_type]

    # Structural invariants
    if flow_type == FlowType.ROOMFIT:
        assert WizardStep.SOURCE not in result
        assert WizardStep.NAME_PROFILE in result
    elif flow_type == FlowType.PEQ_ONLY:
        assert WizardStep.EQ_TYPE not in result
        assert WizardStep.NAME_PROFILE not in result
    else:  # PEQ
        assert WizardStep.NAME_PROFILE not in result
        assert WizardStep.SOURCE in result
        assert WizardStep.EQ_TYPE in result

    # All sequences start with CONNECT and end with PUSH
    assert result[0] == WizardStep.CONNECT
    assert result[-1] == WizardStep.PUSH


# ---------------------------------------------------------------------------
# Property 2: Step classification invariant
# **Validates: Requirements 1.3**
# ---------------------------------------------------------------------------


@given(data=st.data())
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_step_classification_invariant(data: st.DataObject, _ensure_qapp) -> None:
    """**Validates: Requirements 1.3**

    For any valid wizard state, every step in the flow is classified as
    exactly one of: completed, active, or upcoming. No step can be in two
    categories simultaneously, and exactly one step is active.
    """
    flow_type = data.draw(st_flow_type)
    sequence = steps_for_flow(flow_type)

    # Pick how far we've advanced (0 = still on first step, max = last step)
    advance_count = data.draw(st.integers(min_value=0, max_value=len(sequence) - 1))

    ctrl = WizardController()
    ctrl.set_flow_type(flow_type)
    ctrl._state.current_step = sequence[0]

    # Advance the controller the specified number of times
    for i in range(advance_count):
        ctrl.advance(summary=f"step {i}")

    # Classify all steps
    current = ctrl.current_step
    completed = set(ctrl.completed_steps.keys())
    upcoming = set()

    current_idx = sequence.index(current)
    for idx, step in enumerate(sequence):
        if idx > current_idx:
            upcoming.add(step)

    # Assertions
    # Exactly one active step
    assert current in sequence

    # No overlap between categories
    assert current not in completed, "Active step should not be in completed"
    assert current not in upcoming, "Active step should not be in upcoming"
    assert completed.isdisjoint(upcoming), "Completed and upcoming must not overlap"

    # Every step is in exactly one category
    for step in sequence:
        in_completed = step in completed
        is_active = step == current
        in_upcoming = step in upcoming
        categories = sum([in_completed, is_active, in_upcoming])
        assert categories == 1, (
            f"Step {step} is in {categories} categories "
            f"(completed={in_completed}, active={is_active}, upcoming={in_upcoming})"
        )


# ---------------------------------------------------------------------------
# Property 3: Forward advancement preserves sequence order
# **Validates: Requirements 1.5**
# ---------------------------------------------------------------------------


@given(scenario=st_advancement_index())
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_forward_advancement_preserves_sequence_order(
    scenario: tuple[FlowType, int], _ensure_qapp
) -> None:
    """**Validates: Requirements 1.5**

    For any non-final step, advance() moves to the next step in sequence.
    The previous step is added to the completed set; the new step is not
    in the completed set.
    """
    flow_type, target_idx = scenario
    sequence = steps_for_flow(flow_type)

    ctrl = WizardController()
    ctrl.set_flow_type(flow_type)
    ctrl._state.current_step = sequence[0]

    # Advance to the target index
    for i in range(target_idx):
        ctrl.advance(summary=f"step {i}")

    # Now we should be at sequence[target_idx]
    assert ctrl.current_step == sequence[target_idx]
    step_before_advance = ctrl.current_step

    # Perform one more advance
    ctrl.advance(summary="advancing")

    # After advance: current should be the next step in sequence
    expected_next = sequence[target_idx + 1]
    assert ctrl.current_step == expected_next

    # Previous step should now be in completed set
    assert step_before_advance in ctrl.completed_steps

    # New current step should NOT be in completed set
    assert expected_next not in ctrl.completed_steps


# ---------------------------------------------------------------------------
# Property 4: Back-navigation never mutates completed steps (lazy
# invalidation, docs/smoke_test_issues.md #246) -- and the frontier is
# always derived as the first incomplete step, unmoved by browsing.
# **Validates: Requirements 1.6**
# ---------------------------------------------------------------------------


@given(scenario=st_back_nav_scenario())
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_back_navigation_preserves_completed_steps(
    scenario: tuple[FlowType, int, int], _ensure_qapp
) -> None:
    """**Validates: Requirements 1.6**

    go_to_step is purely navigational: for any flow, any progress depth,
    and any back-navigation target, the completed set and every summary are
    identical before and after, current_step becomes the target, and the
    derived frontier (first step not in completed_steps) does not move.
    """
    flow_type, advance_count, back_target_idx = scenario
    sequence = steps_for_flow(flow_type)

    ctrl = WizardController()
    ctrl.set_flow_type(flow_type)
    ctrl._state.current_step = sequence[0]

    # Advance multiple times to build up completed steps
    for i in range(advance_count):
        ctrl.advance(summary=f"step {i}")

    completed_before = dict(ctrl.completed_steps)
    frontier_before = ctrl.frontier_step

    # Browse back to target
    target_step = sequence[back_target_idx]
    ctrl.go_to_step(target_step)

    # Current step should be the target
    assert ctrl.current_step == target_step

    # Browsing destroys nothing and never moves the frontier
    assert dict(ctrl.completed_steps) == completed_before
    assert ctrl.frontier_step == frontier_before
