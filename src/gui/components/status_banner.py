"""StatusBanner — color-coded contextual message area.

Displays info, success, error, and progress messages at the bottom of the
main content area. Uses the ``status`` dynamic property for QSS styling.

Requirements referenced: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFontMetrics, QResizeEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QWidget,
)

from src.gui.components.action_button import make_action_button
from src.gui.constants import AUTO_DISMISS_MS, STATUS_BANNER_HEIGHT
from src.gui.style_utils import set_qss_property


class StatusBanner(QFrame):
    """Color-coded contextual message area.

    Placed at the bottom of the main content area. Uses the ``status`` dynamic
    property (``info``, ``success``, ``error``, ``warning``) for QSS styling.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatusBanner")
        self.setFixedHeight(STATUS_BANNER_HEIGHT)
        self.setProperty("status", "idle")
        self._raw_message = ""

        # --- Layout -----------------------------------------------------------
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(8)
        self._layout = layout

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
        self._message_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(self._message_label)

        # Close button — styled as a visible "Dismiss" text button
        self._close_button = make_action_button(
            "Dismiss", object_name="StatusBannerClose", style_class="ghost",
            tooltip="Dismiss this message", parent=self,
        )
        self._close_button.setFixedHeight(22)
        self._close_button.clicked.connect(self._on_close_clicked)
        self._close_button.setVisible(False)
        layout.addWidget(self._close_button)

        # Start in idle (empty) state
        self._set_idle()

        # Always visible to reserve layout space; content hidden when idle.
        # Set after building the layout/child widgets, since showing the
        # widget for the first time synchronously fires resizeEvent (which
        # calls _update_display_text(), needing self._layout to exist).
        self.setVisible(True)

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
        """Reset the banner to idle (empty) state."""
        self._auto_dismiss_timer.stop()
        self._set_idle()

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
        set_qss_property(self, "status", status)

        self._raw_message = message
        self._message_label.setVisible(True)
        self._progress_bar.setVisible(show_progress)
        self._close_button.setVisible(dismissible)
        self._update_display_text()

        if auto_dismiss_ms > 0:
            self._auto_dismiss_timer.start(auto_dismiss_ms)

    def _set_idle(self) -> None:
        """Reset banner to idle (reserved space, no content visible)."""
        set_qss_property(self, "status", "idle")
        self._raw_message = ""
        self._message_label.setText("")
        self._message_label.setToolTip("")
        self._message_label.setVisible(False)
        self._progress_bar.setVisible(False)
        self._close_button.setVisible(False)

    def _available_message_width(self) -> int:
        """Message label's available width, computed without depending on a
        pending layout pass (avoids a stale-width race right after _show()
        changes progress-bar/close-button visibility -- see smoke #181)."""
        margins = self._layout.contentsMargins()
        used = margins.left() + margins.right() + self._layout.spacing()
        if self._progress_bar.isVisible():
            used += self._progress_bar.width()
        if self._close_button.isVisible():
            used += self._close_button.sizeHint().width() + self._layout.spacing()
        return max(0, self.width() - used)

    def _update_display_text(self) -> None:
        """Elide the message to fit the available width; keep the full text
        accessible via tooltip (one line per " | "-delimited segment)."""
        # A banner with no parent isn't embedded in MainWindow's real
        # content layout yet (e.g. unit tests that construct StatusBanner()
        # standalone) -- its top-level width is an arbitrary platform
        # default, not a meaningful "available width" to elide against, so
        # show the full text rather than eliding against a bogus size.
        available = self._available_message_width() if self.parent() is not None else 0
        if available <= 0:
            self._message_label.setText(self._raw_message)
            self._message_label.setToolTip("")
            return
        metrics = QFontMetrics(self._message_label.font())
        elided = metrics.elidedText(
            self._raw_message, Qt.TextElideMode.ElideRight, available
        )
        self._message_label.setText(elided)
        self._message_label.setToolTip(
            self._raw_message.replace(" | ", "\n") if elided != self._raw_message else ""
        )

    def resizeEvent(self, event: QResizeEvent) -> None:
        """Re-elide the displayed message when the banner is resized."""
        super().resizeEvent(event)
        self._update_display_text()

    def _on_close_clicked(self) -> None:
        """Handle close button click."""
        self.clear()

    def _on_auto_dismiss(self) -> None:
        """Handle auto-dismiss timer expiry."""
        self.clear()
