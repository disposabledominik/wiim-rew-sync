"""Unit tests for OperationFeedbackManager timeout behavior.

Tests the 30-second hard timeout safety net: timer firing, button re-enabling,
is_active state reset, cancel button hiding, and no-timeout on early finish.

Requirements referenced: 13.1, 13.2, 13.3, 13.5.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QPushButton, QWidget

from src.gui.operation_feedback import OperationFeedbackManager


@pytest.fixture()
def feedback_env(qtbot):
    """Create an OperationFeedbackManager with mock banner for testing."""
    banner = MagicMock()
    banner.show_error = MagicMock()
    banner.show_progress = MagicMock()
    banner.clear = MagicMock()
    banner.layout = MagicMock(return_value=None)

    # Use a real QWidget as parent so the QObject tree stays alive
    container = QWidget()
    qtbot.addWidget(container)
    container.show()

    manager = OperationFeedbackManager(status_banner=banner, parent=container)
    return manager, banner, container


class TestTimeoutFiresAndShowsError:
    """Test that timeout fires and shows error message in the banner."""

    def test_timeout_fires_and_shows_error(self, qtbot, feedback_env) -> None:
        """After timeout, show_error('Operation timed out') is called on banner.

        Validates: Requirements 13.5
        """
        manager, banner, _container = feedback_env

        # Shorten the timeout BEFORE starting operation
        manager._timeout_timer.setInterval(10)

        manager.start_operation("Testing...")

        # Wait until the timeout fires (is_active becomes False)
        qtbot.waitUntil(lambda: not manager.is_active, timeout=500)

        banner.show_error.assert_called_once_with("Operation timed out")


class TestTimeoutReEnablesButtons:
    """Test that buttons are re-enabled after timeout."""

    def test_timeout_re_enables_buttons(self, qtbot, feedback_env) -> None:
        """Registered buttons are re-enabled after timeout fires.

        Validates: Requirements 13.1, 13.5
        """
        manager, _banner, _container = feedback_env

        btn1 = QPushButton("Action 1")
        btn2 = QPushButton("Action 2")
        qtbot.addWidget(btn1)
        qtbot.addWidget(btn2)

        manager.register_action_buttons([btn1, btn2])

        # Shorten the timeout BEFORE starting operation
        manager._timeout_timer.setInterval(10)

        manager.start_operation("Working...")

        # Buttons should be disabled
        assert not btn1.isEnabled()
        assert not btn2.isEnabled()

        # Wait for timeout
        qtbot.waitUntil(lambda: not manager.is_active, timeout=500)

        # Buttons should be re-enabled
        assert btn1.isEnabled()
        assert btn2.isEnabled()


class TestNoTimeoutWhenFinishedEarly:
    """Test that timeout does not fire if operation finishes before 30s."""

    def test_no_timeout_when_finished_early(self, qtbot, feedback_env) -> None:
        """Calling finish_operation() stops the timeout timer.

        Validates: Requirements 13.2, 13.5
        """
        manager, banner, _container = feedback_env

        manager.start_operation("Working...")

        # Finish immediately (before any timers fire)
        manager.finish_operation()

        # The timeout timer should be stopped
        assert not manager._timeout_timer.isActive()
        # is_active should be False
        assert not manager.is_active
        # show_error should NOT have been called
        banner.show_error.assert_not_called()


class TestIsActiveFalseAfterTimeout:
    """Test that is_active is set to False after timeout."""

    def test_is_active_false_after_timeout(self, qtbot, feedback_env) -> None:
        """manager.is_active is False after timeout fires.

        Validates: Requirements 13.5
        """
        manager, _banner, _container = feedback_env

        # Shorten the timeout BEFORE starting operation
        manager._timeout_timer.setInterval(10)

        manager.start_operation("Probing...")
        assert manager.is_active

        # Wait for timeout
        qtbot.waitUntil(lambda: not manager.is_active, timeout=500)

        assert not manager.is_active


class TestCancelButtonHiddenAfterTimeout:
    """Test that cancel button is hidden after timeout."""

    def test_cancel_button_hidden_after_timeout(self, qtbot, feedback_env) -> None:
        """Cancel button is hidden when timeout fires.

        Validates: Requirements 13.3, 13.5
        """
        manager, _banner, _container = feedback_env

        # Shorten the timeout BEFORE starting operation
        manager._timeout_timer.setInterval(10)

        manager.start_operation("Long operation...")

        # Manually trigger cancel button creation by calling _show_cancel_button
        manager._show_cancel_button()
        assert manager._cancel_button is not None
        assert manager._cancel_button.isVisible()

        # Wait for timeout
        qtbot.waitUntil(lambda: not manager.is_active, timeout=500)

        # Cancel button should be hidden
        assert not manager._cancel_button.isVisible()


class TestFinishRestoresPriorButtonState:
    """finish_operation()/timeout restore each button's pre-operation enabled
    state instead of blanket-enabling -- a button that was already disabled
    for an unrelated reason (e.g. no list selection) must stay disabled."""

    def test_finish_restores_previously_disabled_button(self, feedback_env) -> None:
        manager, _banner, _container = feedback_env

        already_disabled = QPushButton("Delete")
        already_disabled.setEnabled(False)
        normally_enabled = QPushButton("Rescan")

        manager.register_action_buttons([already_disabled, normally_enabled])

        manager.start_operation("Working...")
        assert not already_disabled.isEnabled()
        assert not normally_enabled.isEnabled()

        manager.finish_operation()

        assert not already_disabled.isEnabled()
        assert normally_enabled.isEnabled()

    def test_timeout_restores_previously_disabled_button(self, qtbot, feedback_env) -> None:
        manager, _banner, _container = feedback_env

        already_disabled = QPushButton("Delete")
        already_disabled.setEnabled(False)
        normally_enabled = QPushButton("Rescan")

        manager.register_action_buttons([already_disabled, normally_enabled])
        manager._timeout_timer.setInterval(10)

        manager.start_operation("Working...")
        qtbot.waitUntil(lambda: not manager.is_active, timeout=500)

        assert not already_disabled.isEnabled()
        assert normally_enabled.isEnabled()
