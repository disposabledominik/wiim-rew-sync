"""Horizontal breadcrumb bar showing wizard progress.

Displays step labels with visual states (completed, active, upcoming)
and allows backward navigation by clicking completed steps.
"""

from __future__ import annotations

from enum import Enum, auto

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from src.gui.components.eliding_label import ElidingLabel
from src.gui.constants import (
    FONT_SIZE_CAPTION,
    SPACING_MD,
    SPACING_SM,
    STEP_INDICATOR_HEIGHT,
)
from src.gui.style_utils import set_qss_property


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
        self._dimmed = False

        # Required for the "stepWidgetActive" background pill (QSS
        # background-color/border-radius) to actually paint on a plain
        # QWidget -- see onboarding_overlay.py for the same convention.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_SM, SPACING_SM, SPACING_SM, SPACING_SM)
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

        self._label = ElidingLabel(label)
        self._label.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        top_row.addWidget(self._label)

        layout.addLayout(top_row)

        # Summary text (shown below label for completed steps)
        self._summary = ElidingLabel()
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

    def set_dimmed(self, dimmed: bool) -> None:
        """Mute the ACTIVE pill's accent color (no-op for other states).

        Used while the user is on a sidebar destination (Presets on
        Device, Settings, etc.) so the step indicator's "you are here"
        pill doesn't visually disagree with the sidebar's own highlight —
        see MainWindow's sidebar/step-indicator sync helpers.
        """
        self._dimmed = dimmed
        self._apply_state()

    def set_summary(self, text: str, tooltip: str = "") -> None:
        """Set the summary text shown below the label for completed steps,
        and an optional tooltip (e.g. what the loaded filters came from, or
        the full source list behind an "N sources" summary) shown on hover."""
        if text:
            self._summary.setText(text)
            self._summary.setToolTip(tooltip)
            self._summary.show()
        else:
            self._summary.setText("")
            self._summary.setToolTip("")
            self._summary.hide()

    def clear_summary(self) -> None:
        """Remove summary text and tooltip."""
        self._summary.setText("")
        self._summary.setToolTip("")
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

    def _set_class(self, widget: QLabel, class_name: str) -> None:
        """Set the QSS ``class`` property and force a style re-evaluation."""
        set_qss_property(widget, "class", class_name)

    def _apply_state(self) -> None:
        """Apply visual styling based on current state."""
        # Background "pill" behind the whole widget marks the active step as
        # a distinct "you are here" zone, separate from the completed
        # checkmark and the plain upcoming style.
        is_active = self._state == _StepState.ACTIVE
        if is_active:
            set_qss_property(
                self, "class", "stepWidgetActiveDimmed" if self._dimmed else "stepWidgetActive"
            )
        else:
            set_qss_property(self, "class", "")

        if self._state == _StepState.COMPLETED:
            self._set_class(self._circle, "stepCircleCompleted")
            self._circle.setText("\u2713")
            self._set_class(self._label, "stepLabelCompleted")
            font = self._label.font()
            font.setBold(False)
            self._label.setFont(font)
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            set_qss_property(self._summary, "class", "caption")

        elif self._state == _StepState.ACTIVE:
            self._set_class(
                self._circle, "stepCircleActiveDimmed" if self._dimmed else "stepCircleActive"
            )
            self._circle.setText("")
            self._set_class(
                self._label, "stepLabelActiveDimmed" if self._dimmed else "stepLabelActive"
            )
            font = self._label.font()
            font.setBold(True)
            self._label.setFont(font)
            self.setCursor(Qt.CursorShape.ArrowCursor)
            self._summary.hide()

        else:  # UPCOMING
            self._set_class(self._circle, "stepCircleUpcoming")
            self._circle.setText("")
            self._set_class(self._label, "stepLabelUpcoming")
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
        self.setProperty("class", "stepConnector")

    def set_active(self, active: bool) -> None:
        """Toggle the connector's accent (completed) styling."""
        set_qss_property(
            self, "class", "stepConnectorActive" if active else "stepConnector"
        )


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
        self._dimmed: bool = False

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
            self._steps[0].set_dimmed(self._dimmed)
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
        # If the target was previously COMPLETED (e.g. navigating back to it
        # via go_to_step), clear its summary and trailing connector through
        # the same path back-navigation invalidation already uses, then
        # force it ACTIVE -- the step you're currently on should never show
        # a stale checkmark or a "completed" connector past it.
        self.clear_completed(index)
        self._steps[index].set_dimmed(self._dimmed)
        self._steps[index].set_state(_StepState.ACTIVE)

    def set_dimmed(self, dimmed: bool) -> None:
        """Mute the active step's pill while a sidebar destination is shown.

        Args:
            dimmed: True while the user is on a non-wizard page (Presets on
                Device, My Saved Presets, Settings, sidebar Pull from REW)
                so the "you are here" pill doesn't visually disagree with
                the sidebar's own highlight. False once they're back in
                the wizard flow.
        """
        self._dimmed = dimmed
        if 0 <= self._current_index < len(self._steps):
            self._steps[self._current_index].set_dimmed(dimmed)

    def set_completed(self, index: int, summary: str = "", tooltip: str = "") -> None:
        """Mark a step as completed with optional summary text.

        Args:
            index: Zero-based index of the step to mark completed.
            summary: Short text shown below the step label (e.g. device name).
            tooltip: Optional longer text shown on hover (e.g. the full
                source list behind an "N sources" summary, or what the
                loaded filters came from).
        """
        if not self._steps or index < 0 or index >= len(self._steps):
            return

        step = self._steps[index]
        step.set_state(_StepState.COMPLETED)
        step.set_summary(summary, tooltip)

        # Update connector line color to accent for completed connections
        if index < len(self._connectors):
            self._connectors[index].set_active(True)

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
                self._connectors[index].set_active(False)

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
                self._connectors[i].set_active(False)

        # Also reset connector before the invalidated step if it exists
        # (connector at index-1 connects step index-1 to step index)
        if index > 0 and index - 1 < len(self._connectors):
            prev_step = self._steps[index - 1]
            if prev_step.state != _StepState.COMPLETED:
                self._connectors[index - 1].set_active(False)

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
