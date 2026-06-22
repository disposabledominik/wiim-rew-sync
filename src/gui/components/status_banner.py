"""StatusBanner — color-coded contextual message area.

Displays info, success, error, and progress messages at the bottom of the
main content area. Uses the ``status`` dynamic property for QSS styling and
emits a ``dismissed`` signal when the banner is hidden (by timer or close button).

Requirements referenced: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from src.gui.constants import AUTO_DISMISS_MS, STATUS_BANNER_HEIGHT


class StatusBanner(QFrame):
    """Color-coded contextual message area.

    Placed at the bottom of the main content area. Uses the ``status`` dynamic
    property (``info``, ``success``, ``error``, ``warning``) for QSS styling.

    Signals:
        dismissed: Emitted when the banner hides, either by auto-dismiss timer
            or by the user clicking the close button.
    """

    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatusBanner")
        self.setFixedHeight(STATUS_BANNER_HEIGHT)
        self.setProperty("status", "idle")

        # Always visible to reserve layout space; content hidden when idle.
        self.setVisible(True)

        # --- Layout -----------------------------------------------------------
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(8)

        # Progress bar (indeterminate spinner, hidden by default)
        self._progress_bar = QProgressBar(self)
        self._progress_bar.setFixedWidth(80)
        self._progress_bar.setFixedHeight(16)
        self._progress_bar.setRange(0, 0)  # Indeterminate
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        # Message label — larger, bolder for prominence
        self._message_label = QLabel(self)
        self._message_label.setObjectName("StatusBannerMessage")
        self._message_label.setStyleSheet(
            "font-size: 14px; font-weight: 600; padding: 0px;"
        )
        self._message_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(self._message_label)

        # Close button
        self._close_button = QPushButton("\u2715", self)
        self._close_button.setObjectName("StatusBannerClose")
        self._close_button.setFixedSize(24, 24)
        self._close_button.setFlat(True)
        self._close_button.setToolTip("Dismiss")
        self._close_button.clicked.connect(self._on_close_clicked)
        self._close_button.setVisible(False)
        layout.addWidget(self._close_button)

        # Start in idle (empty) state
        self._set_idle()

        # --- Auto-dismiss timer -----------------------------------------------
        self._auto_dismiss_timer = QTimer(self)
        self._auto_dismiss_timer.setSingleShot(True)
        self._auto_dismiss_timer.timeout.connect(self._on_auto_dismiss)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_info(self, message: str, auto_dismiss: int = 0) -> None:
        """Display an informational message with neutral styling.

        Args:
            message: Plain-language message to display.
            auto_dismiss: Milliseconds before auto-dismissing. 0 means persist.
        """
        self._show(message, status="info", auto_dismiss_ms=auto_dismiss, dismissible=True)

    def show_success(self, message: str, auto_dismiss: int = AUTO_DISMISS_MS) -> None:
        """Display a success message with green styling.

        Auto-dismisses after *auto_dismiss* milliseconds (default 5 seconds).

        Args:
            message: Plain-language success message.
            auto_dismiss: Milliseconds before auto-dismissing.
        """
        self._show(message, status="success", auto_dismiss_ms=auto_dismiss, dismissible=True)

    def show_error(self, message: str, dismissible: bool = True) -> None:
        """Display an error message with red styling.

        Error messages persist until dismissed by the user.

        Args:
            message: Plain-language error description with actionable guidance.
            dismissible: Whether the close button is shown.
        """
        self._show(message, status="error", auto_dismiss_ms=0, dismissible=dismissible)

    def show_progress(self, message: str) -> None:
        """Display a progress message with an indeterminate spinner.

        Progress messages are not dismissible; call :meth:`clear` or another
        ``show_*`` method to replace them.

        Args:
            message: Plain-language description of the ongoing operation.
        """
        self._show(
            message,
            status="info",
            auto_dismiss_ms=0,
            dismissible=False,
            show_progress=True,
        )

    def clear(self) -> None:
        """Reset the banner to idle (empty) state and emit the dismissed signal."""
        self._auto_dismiss_timer.stop()
        self._set_idle()
        self.dismissed.emit()

    def is_progress(self) -> bool:
        """Return True if the banner is currently showing a progress indicator.

        Used by OperationFeedbackManager to decide whether finish_operation
        should clear the banner (only clears progress, not result messages).
        """
        return self._progress_bar.isVisible()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _show(
        self,
        message: str,
        *,
        status: str,
        auto_dismiss_ms: int,
        dismissible: bool,
        show_progress: bool = False,
    ) -> None:
        """Configure and display the banner.

        Args:
            message: Text to display.
            status: QSS property value (info, success, error, warning).
            auto_dismiss_ms: Timer duration; 0 disables auto-dismiss.
            dismissible: Whether the close button is visible.
            show_progress: Whether to show the indeterminate progress bar.
        """
        self._auto_dismiss_timer.stop()

        # Update dynamic property for QSS styling
        self.setProperty("status", status)
        # Force style re-evaluation after property change
        self.style().unpolish(self)
        self.style().polish(self)

        self._message_label.setText(message)
        self._message_label.setVisible(True)
        self._progress_bar.setVisible(show_progress)
        self._close_button.setVisible(dismissible)

        if auto_dismiss_ms > 0:
            self._auto_dismiss_timer.start(auto_dismiss_ms)

    def _set_idle(self) -> None:
        """Reset banner to idle (reserved space, no content visible)."""
        self.setProperty("status", "idle")
        self.style().unpolish(self)
        self.style().polish(self)
        self._message_label.setText("")
        self._message_label.setVisible(False)
        self._progress_bar.setVisible(False)
        self._close_button.setVisible(False)

    def _on_close_clicked(self) -> None:
        """Handle close button click."""
        self.clear()

    def _on_auto_dismiss(self) -> None:
        """Handle auto-dismiss timer expiry."""
        self.clear()
