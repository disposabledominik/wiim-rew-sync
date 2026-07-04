"""Wizard Controller — adaptive flow state machine for the guided wizard UI.

Manages step sequencing, branching logic, and navigation state. Pure logic — no
UI rendering. Emits Qt signals consumed by pages, StepIndicator, and StatusBanner.

The controller does NOT import or call AsyncBridge directly; it is wired via
signals externally (in MainWindow or integration setup).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from PySide6.QtCore import QObject, Signal

from src.models.canonical import CanonicalFilter
from src.models.channel_mode import ChannelMode
from src.translator._warnings import FilterRow


class WizardStep(Enum):
    """Individual steps in the wizard flow."""

    CONNECT = "connect"
    EQ_TYPE = "eq_type"
    SOURCE = "source"
    FILTERS = "filters"
    REVIEW = "review"
    NAME_PROFILE = "name_profile"
    PUSH = "push"


class FlowType(Enum):
    """Wizard flow variants based on device capabilities and user choice."""

    PEQ = "peq"
    ROOMFIT = "roomfit"
    PEQ_ONLY = "peq_only"


@dataclass
class WizardState:
    """Internal state held by WizardController. Not persisted."""

    flow_type: FlowType = FlowType.PEQ
    current_step: WizardStep = WizardStep.CONNECT
    selected_device: str | None = None
    selected_source: str = ""
    channel_mode: ChannelMode = ChannelMode.STEREO
    current_filters: list[CanonicalFilter] = field(default_factory=list)
    # Snapshot of current_filters as of the last successful push -- lets
    # _has_unsaved_changes() distinguish "filters loaded" from "filters
    # loaded but not yet pushed". Cleared on device switch and on undo,
    # since neither leaves the device holding this snapshot's state.
    last_pushed_filters: list[CanonicalFilter] = field(default_factory=list)
    device_filters: list[CanonicalFilter] = field(default_factory=list)
    filters_l: list[CanonicalFilter] = field(default_factory=list)
    filters_r: list[CanonicalFilter] = field(default_factory=list)
    # Display rows for the next peq_ready, set by REW-parsing producers right
    # before they emit; consumed and reset to [] by _on_peq_ready so a stale
    # set never leaks into an unrelated later flow (e.g. device/preset pulls,
    # which never have skipped bands and don't need to set these themselves).
    pending_rows: list[FilterRow] = field(default_factory=list)
    pending_rows_l: list[FilterRow] = field(default_factory=list)
    pending_rows_r: list[FilterRow] = field(default_factory=list)
    # Same consume-and-reset contract as pending_rows above, but for notes
    # about values REW didn't specify and had to be substituted (e.g. the
    # fixed Q applied to a bare LP/HP) -- keyed by 0-based index into the
    # filter list that will be passed to set_filters()/set_lr_filters().
    pending_conversion_notes: dict[int, list[str]] = field(default_factory=dict)
    pending_conversion_notes_l: dict[int, list[str]] = field(default_factory=dict)
    pending_conversion_notes_r: dict[int, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    roomfit_profile_name: str = ""
    dry_run: bool = False
    last_backup_path: str = ""
    completed_steps: dict[WizardStep, str] = field(default_factory=dict)
    # Optional longer text shown on hover for a completed step's summary
    # (e.g. the full source list behind an "N sources" summary, or what the
    # loaded filters came from) -- keyed the same as completed_steps, but a
    # step may be present in one dict without the other (empty tooltip).
    completed_step_tooltips: dict[WizardStep, str] = field(default_factory=dict)
    # Persists across producer swaps describing *what current_filters
    # currently is* (unlike pending_rows/pending_conversion_notes below,
    # which are transient and reset per-load) -- set by whichever producer
    # populates current_filters, shown as the Filters step's tooltip (#162d).
    filters_origin: str = ""

    @property
    def filters(self) -> list[CanonicalFilter]:
        """Computed filter accessor — returns the correct list for the current mode.

        For L/R mode: returns combined filters_l + filters_r (if populated).
        For Stereo: returns current_filters directly.
        Falls back to current_filters if L/R lists are empty.
        """
        if self.channel_mode.is_lr and (self.filters_l or self.filters_r):
            return self.filters_l + self.filters_r
        return self.current_filters


def steps_for_flow(flow_type: FlowType) -> list[WizardStep]:
    """Return the ordered step sequence for a given flow type.

    Step sequences per flow:
    - PEQ: CONNECT → EQ_TYPE → SOURCE → FILTERS → REVIEW → PUSH
    - ROOMFIT: CONNECT → EQ_TYPE → FILTERS → REVIEW → NAME_PROFILE → PUSH
    - PEQ_ONLY: CONNECT → SOURCE → FILTERS → REVIEW → PUSH
    """
    if flow_type == FlowType.PEQ:
        return [
            WizardStep.CONNECT,
            WizardStep.EQ_TYPE,
            WizardStep.SOURCE,
            WizardStep.FILTERS,
            WizardStep.REVIEW,
            WizardStep.PUSH,
        ]
    if flow_type == FlowType.ROOMFIT:
        return [
            WizardStep.CONNECT,
            WizardStep.EQ_TYPE,
            WizardStep.FILTERS,
            WizardStep.REVIEW,
            WizardStep.NAME_PROFILE,
            WizardStep.PUSH,
        ]
    # FlowType.PEQ_ONLY
    return [
        WizardStep.CONNECT,
        WizardStep.SOURCE,
        WizardStep.FILTERS,
        WizardStep.REVIEW,
        WizardStep.PUSH,
    ]


class WizardController(QObject):
    """Manages wizard state, step sequencing, and branching logic.

    Emits signals on state transitions consumed by UI components (pages,
    StepIndicator, StatusBanner). Does not perform any network I/O itself.
    """

    # Signals
    step_changed = Signal(object)  # WizardStep
    flow_type_changed = Signal(object)  # FlowType
    wizard_reset = Signal()
    step_summary_updated = Signal(object, str, str)  # (WizardStep, summary_text, tooltip)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._state = WizardState()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> WizardState:
        """Return the current wizard state (read-only access)."""
        return self._state

    @property
    def current_step(self) -> WizardStep:
        """Return the current active step."""
        return self._state.current_step

    @property
    def flow_type(self) -> FlowType:
        """Return the current flow type."""
        return self._state.flow_type

    @property
    def completed_steps(self) -> dict[WizardStep, str]:
        """Return the dictionary of completed steps and their summaries."""
        return self._state.completed_steps

    # ------------------------------------------------------------------
    # Step sequencing
    # ------------------------------------------------------------------

    def get_steps(self) -> list[WizardStep]:
        """Return the step sequence for the current flow type."""
        return steps_for_flow(self._state.flow_type)

    def set_step_summary(self, step: WizardStep, summary: str, tooltip: str = "") -> None:
        """Set one step's summary + tooltip directly and emit immediately,
        without transitioning ``current_step``.

        This is the shared primitive ``advance()`` uses internally for the
        current step; it's also used directly for out-of-band single-step
        updates that aren't a forward transition (e.g. marking PUSH done,
        where there's no next step to advance to).
        """
        self._state.completed_steps[step] = summary
        self._state.completed_step_tooltips[step] = tooltip
        self.step_summary_updated.emit(step, summary, tooltip)

    def advance(self, summary: str = "", tooltip: str = "") -> None:
        """Move to the next step in the current flow sequence.

        Adds the current step to the completed set with the given summary
        (and optional tooltip), then advances to the immediately next step.
        Emits ``step_changed`` and ``step_summary_updated``.

        Does nothing if the current step is the final step in the sequence.
        """
        sequence = self.get_steps()
        current_idx = sequence.index(self._state.current_step)

        # Already at the last step — cannot advance further
        if current_idx >= len(sequence) - 1:
            return

        # Mark current step as completed
        self.set_step_summary(self._state.current_step, summary, tooltip)

        # Move to next step
        next_step = sequence[current_idx + 1]
        self._state.current_step = next_step
        self.step_changed.emit(next_step)

    def go_to_step(self, step: WizardStep) -> None:
        """Navigate to a previously completed step, invalidating subsequent steps.

        The target step must be in the completed set or be the current step.
        All steps after the target in the sequence are removed from the
        completed set.  Emits ``step_changed``.
        """
        sequence = self.get_steps()

        if step not in sequence:
            return

        target_idx = sequence.index(step)

        # Invalidate all steps after the target
        for s in sequence[target_idx:]:
            self._state.completed_steps.pop(s, None)

        self._state.current_step = step
        self.step_changed.emit(step)

    def reset(self) -> None:
        """Reset the wizard to the initial Connect step, clearing all state."""
        self._state = WizardState()
        self.wizard_reset.emit()
        self.step_changed.emit(WizardStep.CONNECT)

    # ------------------------------------------------------------------
    # Flow type management
    # ------------------------------------------------------------------

    def set_flow_type(self, flow_type: FlowType) -> None:
        """Switch the flow type, rebuilding the step sequence.

        Emits ``flow_type_changed``.  Does not change the current step —
        the caller should call ``advance()`` or ``go_to_step()`` after this
        if a step transition is needed.
        """
        if self._state.flow_type == flow_type:
            return

        self._state.flow_type = flow_type
        self.flow_type_changed.emit(flow_type)

    # ------------------------------------------------------------------
    # Push prerequisites
    # ------------------------------------------------------------------

    def can_push(self) -> bool:
        """Return True if all push prerequisites are met.

        Prerequisites:
        1. A device is connected (selected_device is not None).
        2. A source is selected OR flow is RoomFit (source is implicit).
        3. Filters are loaded (current_filters is non-empty).
        4. Dry run mode is False.
        """
        state = self._state

        # 1. Device connected
        if state.selected_device is None:
            return False

        # 2. Source selected (RoomFit is source-agnostic)
        if state.flow_type != FlowType.ROOMFIT and not state.selected_source:
            return False

        # 3. Filters loaded
        if not state.current_filters:
            return False

        # 4. Not in dry run
        if state.dry_run:
            return False

        return True
