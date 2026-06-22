"""Horizontal breadcrumb bar showing wizard progress.

Displays step labels with visual states (completed, active, upcoming)
and allows backward navigation by clicking completed steps.
"""

from __future__ import annotations

from enum import Enum, auto

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from src.gui.constants import (
    ACCENT_COLOR,
    FONT_SIZE_CAPTION,
    SPACING_MD,
    SPACING_SM,
    STEP_INDICATOR_HEIGHT,
)


class _StepState(Enum):
    """Internal visual state of a single step."""

    UPCOMING = auto()
    ACTIVE = auto()
    COMPLETED = auto()


class _StepWidget(QWidget):
    """Single step element: circle + label + optional summary."""

    clicked = Signal(int)

    def __init__(self, index: int, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._index = index
        self._state = _StepState.UPCOMING
        self._label_text = label

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_SM, 0, SPACING_SM, 0)
        layout.setSpacing(2)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Top row: circle + label
        top_row = QHBoxLayout()
        top_row.setSpacing(SPACING_SM)
        top_row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._circle = QLabel()
        self._circle.setFixedSize(20, 20)
        self._circle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        top_row.addWidget(self._circle)

        self._label = QLabel(label)
        self._label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        top_row.addWidget(self._label)

        layout.addLayout(top_row)

        # Summary text (shown below label for completed steps)
        self._summary = QLabel()
        self._summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = self._summary.font()
        font.setPixelSize(FONT_SIZE_CAPTION)
        self._summary.setFont(font)
        self._summary.hide()
        layout.addWidget(self._summary)

        self._apply_state()

    @property
    def state(self) -> _StepState:
        """Current visual state."""
        return self._state

    def set_state(self, state: _StepState) -> None:
        """Update the visual state of this step."""
        self._state = state
        self._apply_state()

    def set_summary(self, text: str) -> None:
        """Set the summary text shown below the label for completed steps."""
        if text:
            self._summary.setText(text)
            self._summary.show()
        else:
            self._summary.setText("")
            self._summary.hide()

    def clear_summary(self) -> None:
        """Remove summary text."""
        self._summary.setText("")
        self._summary.hide()

    def set_label(self, text: str) -> None:
        """Update the step label text."""
        self._label_text = text
        self._label.setText(text)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Emit clicked signal for completed steps only."""
        if self._state == _StepState.COMPLETED:
            self.clicked.emit(self._index)
        super().mousePressEvent(event)

    def _apply_state(self) -> None:
        """Apply visual styling based on current state."""
        if self._state == _StepState.COMPLETED:
            self._circle.setStyleSheet(
                f"background-color: {ACCENT_COLOR};"
                f"border-radius: 10px;"
                f"color: white;"
                f"font-weight: bold;"
                f"font-size: 12px;"
            )
            self._circle.setText("\u2713")
            self._label.setStyleSheet(f"color: {ACCENT_COLOR};")
            font = self._label.font()
            font.setBold(False)
            self._label.setFont(font)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self._summary.setStyleSheet("color: #616161;")

        elif self._state == _StepState.ACTIVE:
            self._circle.setStyleSheet(
                f"background-color: transparent;"
                f"border: 2px solid {ACCENT_COLOR};"
                f"border-radius: 10px;"
                f"color: {ACCENT_COLOR};"
                f"font-weight: bold;"
                f"font-size: 12px;"
            )
            self._circle.setText("")
            self._label.setStyleSheet(f"color: {ACCENT_COLOR}; font-weight: bold;")
            font = self._label.font()
            font.setBold(True)
            self._label.setFont(font)
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self._summary.hide()

        else:  # UPCOMING
            self._circle.setStyleSheet(
                "background-color: transparent;"
                "border: 2px solid #9E9E9E;"
                "border-radius: 10px;"
                "color: #9E9E9E;"
            )
            self._circle.setText("")
            self._label.setStyleSheet("color: #9E9E9E;")
            font = self._label.font()
            font.setBold(False)
            self._label.setFont(font)
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self._summary.hide()


class _ConnectorLine(QLabel):
    """Horizontal line connecting two step circles."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(2)
        self.setMinimumWidth(SPACING_MD)
        self.setStyleSheet("background-color: #E0E0E0;")


class StepIndicator(QWidget):
    """Horizontal breadcrumb bar showing wizard progress.

    Shows step labels with visual states (completed, active, upcoming)
    and emits step_clicked for backward navigation on completed steps.
    """

    step_clicked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(STEP_INDICATOR_HEIGHT)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(SPACING_MD, 0, SPACING_MD, 0)
        self._layout.setSpacing(0)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._steps: list[_StepWidget] = []
        self._connectors: list[_ConnectorLine] = []
        self._current_index: int = 0

    def set_steps(self, labels: list[str]) -> None:
        """Set the step labels, rebuilding the indicator layout.

        Args:
            labels: Ordered list of step label strings.
        """
        self._clear_layout()
        self._steps = []
        self._connectors = []

        for i, label in enumerate(labels):
            step_widget = _StepWidget(i, label, self)
            step_widget.clicked.connect(self._on_step_clicked)
            self._steps.append(step_widget)
            self._layout.addWidget(step_widget)

            if i < len(labels) - 1:
                connector = _ConnectorLine(self)
                self._connectors.append(connector)
                self._layout.addWidget(connector)

        self._current_index = 0
        if self._steps:
            self._steps[0].set_state(_StepState.ACTIVE)

    def set_current(self, index: int) -> None:
        """Set which step is active.

        Args:
            index: Zero-based index of the step to mark as active.
        """
        if not self._steps or index < 0 or index >= len(self._steps):
            return

        # Only change the active step marker, don't touch completed states
        if 0 <= self._current_index < len(self._steps):
            old = self._steps[self._current_index]
            if old.state == _StepState.ACTIVE:
                old.set_state(_StepState.UPCOMING)

        self._current_index = index
        step = self._steps[index]
        if step.state != _StepState.COMPLETED:
            step.set_state(_StepState.ACTIVE)

    def set_completed(self, index: int, summary: str = "") -> None:
        """Mark a step as completed with optional summary text.

        Args:
            index: Zero-based index of the step to mark completed.
            summary: Short text shown below the step label (e.g. device name).
        """
        if not self._steps or index < 0 or index >= len(self._steps):
            return

        step = self._steps[index]
        step.set_state(_StepState.COMPLETED)
        step.set_summary(summary)

        # Update connector line color to accent for completed connections
        if index < len(self._connectors):
            self._connectors[index].setStyleSheet(f"background-color: {ACCENT_COLOR};")

    def clear_completed(self, index: int) -> None:
        """Remove the completed state from a step (revert to upcoming).

        Used when back-navigation invalidates subsequent steps.

        Args:
            index: Zero-based index of the step to uncomplete.
        """
        if not self._steps or index < 0 or index >= len(self._steps):
            return

        step = self._steps[index]
        if step.state == _StepState.COMPLETED:
            step.set_state(_StepState.UPCOMING)
            step.clear_summary()
            # Revert connector line color
            if index < len(self._connectors):
                self._connectors[index].setStyleSheet("background-color: #E0E0E0;")

    def invalidate_from(self, index: int) -> None:
        """Remove completed state from this index onward.

        Args:
            index: Zero-based index from which to invalidate steps.
        """
        if not self._steps or index < 0 or index >= len(self._steps):
            return

        for i in range(index, len(self._steps)):
            step = self._steps[i]
            step.set_state(_StepState.UPCOMING)
            step.clear_summary()

            # Reset connector lines from this point
            if i < len(self._connectors):
                self._connectors[i].setStyleSheet("background-color: #E0E0E0;")

        # Also reset connector before the invalidated step if it exists
        # (connector at index-1 connects step index-1 to step index)
        if index > 0 and index - 1 < len(self._connectors):
            prev_step = self._steps[index - 1]
            if prev_step.state != _StepState.COMPLETED:
                self._connectors[index - 1].setStyleSheet("background-color: #E0E0E0;")

    def _on_step_clicked(self, index: int) -> None:
        """Forward step click to the public signal."""
        self.step_clicked.emit(index)

    def _clear_layout(self) -> None:
        """Remove all widgets from the layout."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
        self._steps = []
        self._connectors = []
