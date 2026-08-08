"""Horizontal breadcrumb bar showing wizard progress.

Displays step labels with visual states (completed, active, viewing,
upcoming) and allows navigation by clicking completed steps or the
frontier step. The widget is a pure view: it renders from data pushed in
by MainWindow (completed flags + view/frontier indices) and never decides
wizard state itself.

State semantics (lazy-invalidation model, docs/smoke_test_issues.md #246):
- ACTIVE marks the frontier -- the first not-yet-completed step, "where
  you left off". It is clickable when the user has browsed elsewhere.
- VIEWING marks the step whose page is on screen when that is not the
  frontier -- "where you are". Browsing never destroys completed state.
- When view and frontier coincide, only ACTIVE renders.
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
    VIEWING = auto()


class _StepWidget(QWidget):
    """Single step element: circle + label + optional summary."""

    clicked = Signal(int)

    def __init__(self, index: int, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._index = index
        self._state = _StepState.UPCOMING
        self._label_text = label
        self._dimmed = False
        self._completed = False
        self._clickable = False
        self._summary_text = ""
        self._summary_tooltip = ""

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

    def apply(
        self,
        state: _StepState,
        *,
        completed: bool,
        clickable: bool,
        dimmed: bool,
    ) -> None:
        """Apply the full visual state in one pass.

        The only mutation entry point besides the summary setters: storing
        all four facts before a single ``_apply_state()`` call keeps the
        widget from re-polishing its stylesheet once per field
        (``set_qss_property`` forces a style re-evaluation each time).

        Args:
            state: Visual state (frontier/viewing/completed/upcoming).
            completed: Whether the step's underlying data says "completed" --
                distinct from ``state``: a VIEWING step renders its checkmark
                and summary only when this flag is set.
            clickable: Whether clicking navigates (and the hand cursor shows).
            dimmed: Whether to mute the ACTIVE/VIEWING pill's accent color
                (used while a sidebar destination is on screen).
        """
        self._state = state
        self._completed = completed
        self._clickable = clickable
        self._dimmed = dimmed
        self._apply_state()

    def set_summary(self, text: str, tooltip: str = "") -> None:
        """Store the summary text shown below the label for completed steps,
        and an optional tooltip (e.g. what the loaded filters came from, or
        the full source list behind an "N sources" summary) shown on hover.

        Data-only: callers (StepIndicator) always follow with an
        ``apply()`` pass via ``_refresh()``, which renders it.
        """
        self._summary_text = text
        self._summary_tooltip = tooltip if text else ""

    def clear_summary(self) -> None:
        """Remove summary text and tooltip (data-only, like ``set_summary``)."""
        self._summary_text = ""
        self._summary_tooltip = ""

    def set_label(self, text: str) -> None:
        """Update the step label text."""
        self._label_text = text
        self._label.setText(text)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Emit clicked signal when this step is a navigation target."""
        if self._clickable:
            self.clicked.emit(self._index)
        super().mousePressEvent(event)

    def _set_class(self, widget: QLabel, class_name: str) -> None:
        """Set the QSS ``class`` property and force a style re-evaluation."""
        set_qss_property(widget, "class", class_name)

    def _show_summary(self) -> None:
        """Show the stored summary text (if any) below the label."""
        if self._summary_text:
            self._summary.setText(self._summary_text)
            self._summary.setToolTip(self._summary_tooltip)
            set_qss_property(self._summary, "class", "caption")
            self._summary.show()
        else:
            self._summary.setText("")
            self._summary.setToolTip("")
            self._summary.hide()

    def _apply_circle_and_label(self, checked: bool) -> None:
        """Apply the completed (checkmark) or upcoming (empty ring)
        circle/label classes -- shared by every non-ACTIVE state so the two
        stylings each live in exactly one place."""
        if checked:
            self._set_class(self._circle, "stepCircleCompleted")
            self._circle.setText("\u2713")
            self._set_class(self._label, "stepLabelCompleted")
        else:
            self._set_class(self._circle, "stepCircleUpcoming")
            self._circle.setText("")
            self._set_class(self._label, "stepLabelUpcoming")

    def _apply_state(self) -> None:
        """Apply visual styling based on current state."""
        # Background "pill" behind the whole widget marks a "you are here"
        # zone: accent for the ACTIVE frontier, an outlined treatment for a
        # VIEWING (browsed-to) step -- distinct from the completed
        # checkmark and the plain upcoming style.
        if self._state == _StepState.ACTIVE:
            set_qss_property(
                self, "class", "stepWidgetActiveDimmed" if self._dimmed else "stepWidgetActive"
            )
        elif self._state == _StepState.VIEWING:
            set_qss_property(
                self, "class", "stepWidgetViewingDimmed" if self._dimmed else "stepWidgetViewing"
            )
        else:
            set_qss_property(self, "class", "")

        # A VIEWING step reuses the completed circle/label classes when its
        # data says completed (a browsed-to step is still complete); a
        # non-completed VIEWING step (defensive -- the controller never
        # produces it) falls back to upcoming visuals. The bold label below
        # plus the pill outline above carry the "you are here" cue.
        checked = self._state == _StepState.COMPLETED or (
            self._state == _StepState.VIEWING and self._completed
        )

        if self._state == _StepState.ACTIVE:
            self._set_class(
                self._circle, "stepCircleActiveDimmed" if self._dimmed else "stepCircleActive"
            )
            self._circle.setText("")
            self._set_class(
                self._label, "stepLabelActiveDimmed" if self._dimmed else "stepLabelActive"
            )
        else:
            self._apply_circle_and_label(checked)

        font = self._label.font()
        font.setBold(self._state in (_StepState.ACTIVE, _StepState.VIEWING))
        self._label.setFont(font)

        # Summary shows wherever the checkmark does; a hidden summary also
        # drops its text/tooltip so stale content never lingers on the label.
        if checked:
            self._show_summary()
        else:
            self._summary.setText("")
            self._summary.setToolTip("")
            self._summary.hide()

        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if self._clickable
            else Qt.CursorShape.ArrowCursor
        )


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

    A pure data-driven view: per-step completed flags plus a view index
    (whose page is on screen) and a frontier index (first not-completed
    step) fully determine every widget's state via ``_refresh()``. Emits
    ``step_clicked`` for navigation on completed steps and on the frontier
    step while the user is browsing elsewhere.
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
        self._completed: list[bool] = []
        self._view_index: int = 0
        self._frontier_index: int = 0
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

        self._completed = [False] * len(labels)
        self._view_index = 0
        self._frontier_index = 0
        self._refresh()

    def set_view(self, view_index: int, frontier_index: int) -> None:
        """Set which step's page is on screen and where the frontier is.

        An out-of-range index is ignored (the previous value is kept), but a
        refresh still runs so any pending data changes (``sync``'s summary
        updates) always render.

        Args:
            view_index: Zero-based index of the step whose page is shown.
            frontier_index: Zero-based index of the first not-yet-completed
                step (clamped to the last step when all are complete) --
                rendered ACTIVE, "where you left off".
        """
        if not self._steps:
            return
        if 0 <= view_index < len(self._steps):
            self._view_index = view_index
        if 0 <= frontier_index < len(self._steps):
            self._frontier_index = frontier_index
        self._refresh()

    def sync(
        self,
        completed: list[tuple[str, str] | None],
        view_index: int,
        frontier_index: int,
    ) -> None:
        """Bulk resync of every step's completed data plus the view and
        frontier, with a single refresh.

        The full-resync entry point (flow switch, change-time invalidation):
        per-step ``set_completed``/``clear_completed`` calls would each
        trigger a full refresh, restyling every widget once per step.

        Args:
            completed: Per-step entries, index-aligned with the labels from
                ``set_steps``: ``(summary, tooltip)`` for a completed step,
                ``None`` for a not-completed one. Missing trailing entries
                count as not completed.
            view_index: As in ``set_view``.
            frontier_index: As in ``set_view``.
        """
        for i, step in enumerate(self._steps):
            entry = completed[i] if i < len(completed) else None
            self._completed[i] = entry is not None
            if entry is not None:
                step.set_summary(entry[0], entry[1])
            else:
                step.clear_summary()
        self.set_view(view_index, frontier_index)

    def set_dimmed(self, dimmed: bool) -> None:
        """Mute the viewed step's pill while a sidebar destination is shown.

        NOT CALLED FROM PRODUCTION CODE as of smoke_test_issues.md #267:
        MainWindow now hides the entire indicator (setVisible(False)) for
        sidebar destinations instead of dimming it, since a dimmed-but-
        still-visible breadcrumb wasted screen space those views could use
        instead. Left in place intentionally, not an oversight -- it's the
        cheaper fallback if hiding the indicator ever needs to be dialed
        back to muting it (e.g. a future view that still wants a breadcrumb
        visible, just de-emphasized). The *Dimmed QSS classes it drives
        (fluent_light.qss/fluent_dark.qss) and its _StepWidget plumbing are
        kept in sync for the same reason. See #267's row for the full
        rationale before removing this.

        Args:
            dimmed: True while the user is on a non-wizard page (Presets on
                Device, My Saved Presets, Settings) so the "you are here"
                pill doesn't visually disagree with the sidebar's own
                highlight. False once they're back in the wizard flow.
        """
        self._dimmed = dimmed
        self._refresh()

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

        self._completed[index] = True
        self._steps[index].set_summary(summary, tooltip)
        self._refresh()

    def clear_completed(self, index: int) -> None:
        """Remove the completed state from a step.

        Used when a change-time invalidation removes steps from the
        wizard's completed set.

        Args:
            index: Zero-based index of the step to uncomplete.
        """
        if not self._steps or index < 0 or index >= len(self._steps):
            return

        self._completed[index] = False
        self._steps[index].clear_summary()
        self._refresh()

    def _refresh(self) -> None:
        """Recompute every widget's visual state from the stored data.

        Rendering rules (V = view index, F = frontier index):
        - i == V == F: ACTIVE, not clickable (you are at the frontier);
          COMPLETED if the step's data says so (all-complete clamp, e.g.
          PUSH marked "Done" while still on it -- show the checkmark).
        - i == V != F: VIEWING, not clickable (you are here, browsing).
        - i == F != V: ACTIVE and clickable ("back to where I left off"),
          unless completed (all-complete clamp) -- then plain COMPLETED.
        - otherwise: COMPLETED (clickable) or UPCOMING (not).
        Connector i is accented iff step i is completed.
        """
        view = self._view_index
        frontier = self._frontier_index

        for i, step in enumerate(self._steps):
            completed = self._completed[i]
            if i == view:
                if view != frontier:
                    state = _StepState.VIEWING
                elif completed:
                    state = _StepState.COMPLETED
                else:
                    state = _StepState.ACTIVE
                clickable = False
            elif i == frontier:
                state = _StepState.COMPLETED if completed else _StepState.ACTIVE
                clickable = True
            elif completed:
                state = _StepState.COMPLETED
                clickable = True
            else:
                state = _StepState.UPCOMING
                clickable = False

            step.apply(
                state,
                completed=completed,
                clickable=clickable,
                dimmed=self._dimmed if i == view else False,
            )

        for i, connector in enumerate(self._connectors):
            connector.set_active(self._completed[i])

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
        self._completed = []
