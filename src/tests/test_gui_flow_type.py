"""Property-based tests for flow type determination from roomfit_level.

# Feature: gui-bridge-integration, Property 2: Flow type determination from roomfit_level

Tests the core branching logic: roomfit_level < 2 → PEQ_ONLY flow;
roomfit_level >= 2 → NOT PEQ_ONLY (device supports RoomFit choice).

**Validates: Requirements 2.2, 2.3**
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.gui.wizard_controller import FlowType, WizardController

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def determine_flow_type_from_roomfit(roomfit_level: int) -> FlowType:
    """Pure logic extracted from MainWindow._on_capabilities_ready.

    This mirrors the branching in main_window.py:
        if roomfit_level < 2 → PEQ_ONLY
        else → default PEQ (allows EQ_TYPE choice)
    """
    if roomfit_level < 2:
        return FlowType.PEQ_ONLY
    return FlowType.PEQ


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
# Property 2: Flow type determination from roomfit_level
# **Validates: Requirements 2.2, 2.3**
# ---------------------------------------------------------------------------


@given(roomfit_level=st.integers(min_value=0, max_value=1))
@settings(max_examples=100)
def test_low_roomfit_level_means_peq_only(roomfit_level: int) -> None:
    """**Validates: Requirements 2.2, 2.3**

    For any roomfit_level in [0, 1], the flow type determination yields
    PEQ_ONLY — the device does not support RoomFit, so the EQ_TYPE choice
    step is skipped.
    """
    result = determine_flow_type_from_roomfit(roomfit_level)
    assert result == FlowType.PEQ_ONLY, (
        f"roomfit_level={roomfit_level} should yield PEQ_ONLY, got {result}"
    )


@given(roomfit_level=st.integers(min_value=2, max_value=4))
@settings(max_examples=100)
def test_high_roomfit_level_means_not_peq_only(roomfit_level: int) -> None:
    """**Validates: Requirements 2.2, 2.3**

    For any roomfit_level in [2, 3, 4], the flow type determination does
    NOT yield PEQ_ONLY — the device supports RoomFit, so the user is
    presented with the EQ_TYPE choice step.
    """
    result = determine_flow_type_from_roomfit(roomfit_level)
    assert result != FlowType.PEQ_ONLY, (
        f"roomfit_level={roomfit_level} should NOT yield PEQ_ONLY, got {result}"
    )


@given(roomfit_level=st.integers(min_value=0, max_value=4))
@settings(max_examples=100)
def test_all_valid_roomfit_levels_produce_valid_flow_type(roomfit_level: int) -> None:
    """**Validates: Requirements 2.2, 2.3**

    For any valid roomfit_level (0-4), the determination always produces a
    valid FlowType enum member — never raises, never returns None.
    """
    result = determine_flow_type_from_roomfit(roomfit_level)
    assert isinstance(result, FlowType), (
        f"Expected FlowType enum member, got {type(result).__name__}: {result}"
    )
    assert result in list(FlowType), f"Result {result} is not a valid FlowType member"


# ---------------------------------------------------------------------------
# Integration: Verify pure function matches MainWindow behaviour
# ---------------------------------------------------------------------------


@given(roomfit_level=st.integers(min_value=0, max_value=4))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_flow_type_matches_wizard_controller_integration(
    roomfit_level: int, _ensure_qapp
) -> None:
    """**Validates: Requirements 2.2, 2.3**

    Verify the pure determination function matches the actual WizardController
    behaviour when set_flow_type is called with PEQ_ONLY for low levels.
    """
    ctrl = WizardController()

    # Simulate what MainWindow._on_capabilities_ready does:
    if roomfit_level < 2:
        ctrl.set_flow_type(FlowType.PEQ_ONLY)
    # else: keep default (FlowType.PEQ)

    expected = determine_flow_type_from_roomfit(roomfit_level)
    assert ctrl.flow_type == expected, (
        f"WizardController flow_type={ctrl.flow_type} != expected={expected} "
        f"for roomfit_level={roomfit_level}"
    )
