"""Operation feedback manager — responsive UI feedback for async operations.

Manages button disabling, loading states, long-operation messages, and
cancellation support for all AsyncBridge-driven operations.

Requirements referenced: 13.1, 13.2, 13.3, 13.4, 13.5, 13.6.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QWidget

from src.gui.components.action_button import ElidingPushButton, make_action_button

if TYPE_CHECKING:
    from src.gui.components.status_banner import StatusBanner

logger = logging.getLogger("wiim_rew_sync.app")

# Threshold before showing "This may take a moment..." (ms)
_LONG_OPERATION_THRESHOLD_MS = 3000

# Threshold before showing Cancel button (ms)
_CANCEL_THRESHOLD_MS = 2000

# Absolute safety net — force-finish after this duration (ms)
_HARD_TIMEOUT_MS = 30000


class OperationFeedbackManager(QObject):
    """Manages responsive operation feedback and button state.

    Coordinates:
    - Disabling action buttons on operation start (prevents double-submit)
    - Showing loading state in StatusBanner within 100ms
    - Displaying "This may take a moment..." for operations > 3 seconds
    - Providing Cancel button for operations > 2 seconds

    Signals:
        cancel_requested: Emitted when the user clicks Cancel on a
            long-running operation.
    """

    cancel_requested = Signal()

    def __init__(
        self,
        status_banner: StatusBanner,
        parent: QObject | None = None,
    ) -> None:
        """Initialize the feedback manager.

        Args:
            status_banner: The StatusBanner widget to display messages in.
            parent: Optional Qt parent object.
        """
        super().__init__(parent)
        self._status_banner = status_banner
        self._action_buttons: list[QWidget] = []
        # Snapshot of each button's isEnabled() at start_operation(), keyed by
        # id() -- restored on finish rather than a blanket setEnabled(True),
        # since some registered buttons (e.g. preset Load/Rename/Delete) are
        # normally gated on an unrelated condition like list selection and
        # would otherwise come back enabled with nothing selected.
        self._prior_enabled: dict[int, bool] = {}
        self._is_active = False
        self._current_message = ""

        # Timer for showing "This may take a moment..." after 3 seconds
        self._long_op_timer = QTimer(self)
        self._long_op_timer.setSingleShot(True)
        self._long_op_timer.setInterval(_LONG_OPERATION_THRESHOLD_MS)
        self._long_op_timer.timeout.connect(self._on_long_operation)

        # Timer for showing Cancel button after 2 seconds
        self._cancel_timer = QTimer(self)
        self._cancel_timer.setSingleShot(True)
        self._cancel_timer.setInterval(_CANCEL_THRESHOLD_MS)
        self._cancel_timer.timeout.connect(self._on_cancel_available)

        # Hard timeout timer -- absolute safety net (Req 13.5)
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.setInterval(_HARD_TIMEOUT_MS)
        self._timeout_timer.timeout.connect(self._on_timeout)

        # Cancel button (created lazily, inserted into StatusBanner layout)
        self._cancel_button: ElidingPushButton | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_action_buttons(self, buttons: list[QWidget]) -> None:
        """Register action buttons to be disabled during operations.

        Args:
            buttons: List of QPushButton or similar widgets to manage.
        """
        self._action_buttons = list(buttons)

    def start_operation(self, message: str = "Working...") -> None:
        """Signal that an async operation has started.

        Disables registered action buttons immediately and shows a loading
        indicator in the StatusBanner.

        Args:
            message: Description of the operation shown in the banner.
        """
        self._is_active = True
        self._current_message = message

        # Req 13.1: Disable buttons immediately (prevent double-submit)
        self._prior_enabled = {id(btn): btn.isEnabled() for btn in self._action_buttons}
        for btn in self._action_buttons:
            btn.setEnabled(False)

        # Req 13.2: Show loading state in banner
        self._status_banner.show_progress(message)

        # Start timers for long-operation and cancel thresholds
        self._long_op_timer.start()
        self._cancel_timer.start()
        self._timeout_timer.start()

        logger.debug("Operation started: %s", message)

    def finish_operation(self) -> None:
        """Signal that the async operation has completed.

        Restores each action button to its pre-operation enabled state, stops
        timers, hides cancel button. Does NOT clear the status banner —
        success/error messages shown by operation handlers manage their own
        lifecycle (smoke #32 fix). Only clears the progress indicator if no
        result message was posted.
        """
        self._is_active = False

        # Stop timers
        self._long_op_timer.stop()
        self._cancel_timer.stop()
        self._timeout_timer.stop()

        # Restore buttons to their pre-operation enabled state
        self._restore_button_states()

        # Hide cancel button if visible
        self._hide_cancel_button()

        # Only clear if banner is still showing the progress message (not a result)
        # Result messages (success/error/info) are posted by operation handlers
        # and should persist for the user to read.
        if self._status_banner.is_progress():
            self._status_banner.clear()

        logger.debug("Operation finished")

    @property
    def is_active(self) -> bool:
        """Whether an operation is currently in progress."""
        return self._is_active

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _restore_button_states(self) -> None:
        """Restore each registered button to its pre-operation enabled state."""
        for btn in self._action_buttons:
            btn.setEnabled(self._prior_enabled.get(id(btn), True))

    # ------------------------------------------------------------------
    # Private slots
    # ------------------------------------------------------------------

    def _on_long_operation(self) -> None:
        """Handle long-operation threshold (3s) — show supplementary message."""
        if self._is_active:
            self._status_banner.show_progress(
                f"{self._current_message} \u2014 This may take a moment..."
            )

    def _on_cancel_available(self) -> None:
        """Handle cancel threshold (2s) — show Cancel button in banner."""
        if self._is_active:
            self._show_cancel_button()

    def _show_cancel_button(self) -> None:
        """Insert a Cancel button into the StatusBanner layout."""
        if self._cancel_button is None:
            self._cancel_button = make_action_button(
                "Cancel", object_name="OperationCancelButton", style_class="secondary"
            )
            self._cancel_button.setFixedHeight(28)
            self._cancel_button.setMinimumWidth(60)
            self._cancel_button.clicked.connect(self._on_cancel_clicked)

        # Insert before the close button in the banner layout
        layout = self._status_banner.layout()
        if layout is not None and self._cancel_button.parent() is None:
            # Insert at position before last widget (close button)
            hbox = layout if isinstance(layout, QHBoxLayout) else None
            if hbox is not None:
                hbox.insertWidget(hbox.count() - 1, self._cancel_button)

        self._cancel_button.setVisible(True)

    def _hide_cancel_button(self) -> None:
        """Hide the Cancel button from the banner."""
        if self._cancel_button is not None:
            self._cancel_button.setVisible(False)

    def _on_cancel_clicked(self) -> None:
        """Handle Cancel button click."""
        logger.info("Operation cancel requested by user")
        self.cancel_requested.emit()
        self.finish_operation()

    def _on_timeout(self) -> None:
        """Handle hard timeout (30s) -- force-finish with error message.

        This is an absolute safety net. If an operation hasn't completed
        after 30 seconds, the UI is forced back to an interactive state
        with an error displayed (Req 13.5).
        """
        if self._is_active:
            logger.warning("Operation hard timeout after 30s")
            self._status_banner.show_error("Operation timed out")
            # Force finish -- restore buttons, clear state
            self._is_active = False
            self._long_op_timer.stop()
            self._cancel_timer.stop()
            self._restore_button_states()
            self._hide_cancel_button()
