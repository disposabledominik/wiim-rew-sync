"""Property-based tests for MainWindow._map_error (Property 5: Error mapping completeness).

Feature: gui-bridge-integration, Property 5: Error mapping completeness

Validates: Requirements 12.2

Tests three universal properties:
1. Known exceptions map to their expected user-friendly messages.
2. Arbitrary exceptions always return a non-empty string (never None, never raise).
3. ParseError and ValidationError include the original message in the mapped output.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.gui.app_settings import AppSettings
from src.gui.main_window import MainWindow
from src.models.errors import (
    ParseError,
    REWNotConnectedError,
    ValidationError,
    WiiMConnectionError,
    WiiMTimeoutError,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def window(qtbot):
    """Create a MainWindow with mocked bridge for _map_error access."""
    mock_bridge = MagicMock()
    mock_bridge.start = MagicMock()
    mock_bridge.shutdown = MagicMock()

    settings = AppSettings(first_run_complete=True)
    with (
        patch("src.gui.app_settings.AppSettings.load", return_value=settings),
        patch("src.gui.app_settings.AppSettings.save"),
    ):
        w = MainWindow(async_bridge=mock_bridge)
        qtbot.addWidget(w)
        yield w
        # Clear filters to prevent UnsavedChangesDialog from blocking on close
        w._wizard_controller.state.current_filters = []
        w.close()


# ---------------------------------------------------------------------------
# Known exception type → expected message mapping
# ---------------------------------------------------------------------------

KNOWN_EXCEPTION_MAP: dict[type[Exception], str] = {
    WiiMTimeoutError: "Device not responding",
    WiiMConnectionError: "Could not reach device",
    REWNotConnectedError: "REW is not connected",
    FileNotFoundError: "File not found",
    PermissionError: "Permission denied",
    OSError: "File could not be written",
}


# ---------------------------------------------------------------------------
# Property 1: Known exceptions map to correct messages
# ---------------------------------------------------------------------------


@given(exc_type=st.sampled_from([
    WiiMTimeoutError,
    WiiMConnectionError,
    REWNotConnectedError,
    FileNotFoundError,
    PermissionError,
    OSError,
]))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_known_exceptions_map_to_correct_message(window, exc_type: type[Exception]) -> None:
    """**Validates: Requirements 12.2**

    For any exception type in the known mapping set, _map_error returns
    the corresponding user-friendly message string.
    """
    exc = exc_type("test error")
    result = window._map_error(exc)

    expected = KNOWN_EXCEPTION_MAP[exc_type]
    assert result == expected, (
        f"Expected '{expected}' for {exc_type.__name__}, got '{result}'"
    )


# ---------------------------------------------------------------------------
# Property 2: Arbitrary exceptions always return a non-empty string
# ---------------------------------------------------------------------------


@given(msg=st.text())
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_arbitrary_exceptions_return_string_never_none(window, msg: str) -> None:
    """**Validates: Requirements 12.2**

    For any Exception with an arbitrary message, _map_error returns a
    non-empty string, never None, and never raises.
    """
    exc = Exception(msg)
    result = window._map_error(exc)

    assert result is not None, "_map_error returned None"
    assert isinstance(result, str), f"_map_error returned {type(result)}, expected str"
    assert len(result) > 0, "_map_error returned empty string"
    assert result == "An unexpected error occurred"


# ---------------------------------------------------------------------------
# Property 3: ParseError and ValidationError include details in message
# ---------------------------------------------------------------------------


@given(msg=st.text(min_size=1))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_parse_error_includes_details(window, msg: str) -> None:
    """**Validates: Requirements 12.2**

    ParseError mapped output includes the original exception message.
    """
    exc = ParseError(msg)
    result = window._map_error(exc)

    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0
    # The mapped message should contain the original error text
    assert msg in result, (
        f"ParseError message '{msg}' not found in mapped output '{result}'"
    )
    assert result.startswith("Could not read file: ")


@given(msg=st.text(min_size=1))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_validation_error_includes_details(window, msg: str) -> None:
    """**Validates: Requirements 12.2**

    ValidationError mapped output includes the original exception message.
    """
    exc = ValidationError(msg)
    result = window._map_error(exc)

    assert result is not None
    assert isinstance(result, str)
    assert len(result) > 0
    # The mapped message should contain the original error text
    assert msg in result, (
        f"ValidationError message '{msg}' not found in mapped output '{result}'"
    )
    assert result.startswith("Invalid data: ")
