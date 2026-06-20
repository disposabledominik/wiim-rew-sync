"""Property-based tests for MainWindow._is_busy concurrent guard (Property 6).

Feature: gui-bridge-integration, Property 6: Concurrent operation prevention

Validates: Requirements 13.4

Tests three universal properties:
1. When feedback manager is_active is True, _is_busy always returns True.
2. When feedback manager is_active is False, _is_busy always returns False.
3. Multiple rapid calls while active never change the result (no race leakage).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.gui.app_settings import AppSettings
from src.gui.main_window import MainWindow

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def window(qtbot):
    """Create a MainWindow with mocked bridge for _is_busy access."""
    mock_bridge = MagicMock()
    mock_bridge.start = MagicMock()
    mock_bridge.shutdown = MagicMock()

    app_settings = AppSettings(first_run_complete=True)
    with (
        patch("src.gui.app_settings.AppSettings.load", return_value=app_settings),
        patch("src.gui.app_settings.AppSettings.save"),
    ):
        w = MainWindow(async_bridge=mock_bridge)
        qtbot.addWidget(w)
        yield w
        # Clear filters to prevent UnsavedChangesDialog from blocking on close
        w._wizard_controller.state.current_filters = []
        w.close()


# ---------------------------------------------------------------------------
# Property 1: When feedback manager is active, _is_busy always returns True
# ---------------------------------------------------------------------------


@given(dummy=st.integers(min_value=0, max_value=1000))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_is_busy_returns_true_when_active(window, dummy: int) -> None:
    """**Validates: Requirements 13.4**

    For any state where OperationFeedbackManager.is_active is True,
    _is_busy() returns True every time, preventing concurrent operations.
    """
    # Force is_active to True via property mock
    window._feedback_manager._is_active = True

    result = window._is_busy()

    assert result is True, (
        f"_is_busy() returned {result} when is_active=True (dummy={dummy})"
    )


# ---------------------------------------------------------------------------
# Property 2: When feedback manager is NOT active, _is_busy returns False
# ---------------------------------------------------------------------------


@given(dummy=st.integers(min_value=0, max_value=1000))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_is_busy_returns_false_when_not_active(window, dummy: int) -> None:
    """**Validates: Requirements 13.4**

    For any state where OperationFeedbackManager.is_active is False,
    _is_busy() returns False, allowing the operation to proceed.
    """
    # Force is_active to False
    window._feedback_manager._is_active = False

    result = window._is_busy()

    assert result is False, (
        f"_is_busy() returned {result} when is_active=False (dummy={dummy})"
    )


# ---------------------------------------------------------------------------
# Property 3: Multiple rapid calls while active never change the result
# ---------------------------------------------------------------------------


@given(call_count=st.integers(min_value=1, max_value=50))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_rapid_calls_while_active_always_return_true(window, call_count: int) -> None:
    """**Validates: Requirements 13.4**

    For any number of rapid successive calls (1-50) while is_active is True,
    every single call returns True. No race condition leakage allows a second
    operation through.
    """
    # Force is_active to True
    window._feedback_manager._is_active = True

    results = [window._is_busy() for _ in range(call_count)]

    assert all(results), (
        f"Expected all {call_count} calls to return True, "
        f"but got {results.count(False)} False value(s) in {results}"
    )
