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

    def test_finish_does_not_stomp_a_noted_button_re_enabled_mid_operation(
        self, feedback_env
    ) -> None:
        """Smoke #250: a button disabled at start_operation() time (e.g.
        SourcePage's Continue, before any source is selected) that a bridge
        signal handler legitimately re-enables *while the operation is still
        in flight* -- exactly what happens when a capability-probe result
        signal populates SourcePage and enables Continue before the queued
        operation_finished signal calls finish_operation() -- must not be
        reverted back to disabled, provided the handler calls
        note_button_state_changed() as production code does."""
        manager, _banner, _container = feedback_env

        continue_btn = QPushButton("Continue")
        continue_btn.setEnabled(False)

        manager.register_action_buttons([continue_btn])

        manager.start_operation("Probing device...")
        assert not continue_btn.isEnabled()

        # Simulates a result-signal handler (e.g. _on_capabilities_ready ->
        # SourcePage.set_sources()) legitimately enabling the button before
        # operation_finished/finish_operation() runs, and telling the
        # manager about it as MainWindow does.
        continue_btn.setEnabled(True)
        manager.note_button_state_changed(continue_btn)

        manager.finish_operation()

        assert continue_btn.isEnabled()

    def test_finish_still_reverts_an_un_noted_mid_operation_enable(
        self, feedback_env
    ) -> None:
        """The opposite of the case above: a registered button re-enabled
        mid-operation by code that does NOT call note_button_state_changed()
        (e.g. a preset list's selection-changed handler, which doesn't know
        or care whether an unrelated operation is in flight) must still be
        forced back to its pre-operation snapshot at finish -- preserving
        the double-submit protection Req 13.1 requires for every button
        that hasn't explicitly opted into a different restore value."""
        manager, _banner, _container = feedback_env

        load_btn = QPushButton("Load")
        load_btn.setEnabled(False)

        manager.register_action_buttons([load_btn])

        manager.start_operation("Working...")
        assert not load_btn.isEnabled()

        # A selection-changed handler enables it mid-operation without
        # telling the manager -- e.g. the user clicks a preset row while an
        # unrelated operation is still running.
        load_btn.setEnabled(True)

        manager.finish_operation()

        assert not load_btn.isEnabled()

    def test_note_button_state_changed_is_a_noop_when_no_operation_active(
        self, feedback_env
    ) -> None:
        """Calling note_button_state_changed() outside start_operation()/
        finish_operation() (no snapshot exists yet) must not raise or create
        a stale entry that would affect the next operation."""
        manager, _banner, _container = feedback_env

        btn = QPushButton("Continue")
        manager.register_action_buttons([btn])

        manager.note_button_state_changed(btn)  # no snapshot exists -- no-op

        manager.start_operation("Working...")
        assert not btn.isEnabled()
        manager.finish_operation()
        # Restored to the button's actual pre-operation state (True), not
        # anything the earlier no-op call could have poisoned.
        assert btn.isEnabled()
