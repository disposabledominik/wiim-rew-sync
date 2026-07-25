"""PushPage — push execution progress and result display.

Shows the Safe Write Protocol progress as a vertical stepper
(Backing up -> Writing -> Verifying -> Done), success/failure states,
and post-push actions (OK, Undo, Export, Save to Presets).

Requirements referenced: 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 18.1.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.gui.components.action_button import make_action_button
from src.gui.components.page_layout import build_centered_content, make_page_title
from src.gui.constants import (
    SPACING_LG,
    SPACING_MD,
)
from src.gui.dialogs.pushed_filters_dialog import PushedFiltersDialog
from src.gui.style_utils import set_qss_property
from src.models.canonical import CanonicalFilter

# ---------------------------------------------------------------------------
# Stage definitions
# ---------------------------------------------------------------------------

_STAGES: list[str] = ["backing_up", "writing", "verifying"]
_STAGE_LABELS: dict[str, str] = {
    "backing_up": "Backing up",
    "writing": "Writing",
    "verifying": "Verifying",
}

logger = logging.getLogger(__name__)


class _StageRow(QWidget):
    """Single row in the vertical stepper showing a stage label and status icon."""

    def __init__(self, stage_key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stage_key = stage_key
        self._status: str = "pending"  # pending | active | complete | failed

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(SPACING_MD)

        self._icon_label = QLabel("\u25CB", self)  # hollow circle (pending)
        self._icon_label.setFixedWidth(24)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon_label)

        self._icon_label.setObjectName("PushPageStageIcon")
        self._text_label = QLabel(_STAGE_LABELS[stage_key], self)
        self._text_label.setObjectName("PushPageStageText")
        layout.addWidget(self._text_label)
        layout.addStretch()

    @property
    def status(self) -> str:
        """Current status of this stage row."""
        return self._status

    def set_status(self, status: str) -> None:
        """Set the visual status of this stage.

        Args:
            status: One of "pending", "active", "complete", "failed".
        """
        self._status = status
        icons = {"pending": "\u25CB", "active": "\u25CF", "complete": "\u2713", "failed": "\u2717"}
        self._icon_label.setText(icons[status])
        self._set_class(self._icon_label, f"stage{status.capitalize()}")
        self._set_class(self._text_label, f"stage{status.capitalize()}")

    @staticmethod
    def _set_class(widget: QLabel, class_name: str) -> None:
        """Set the QSS ``class`` property and force a style re-evaluation."""
        set_qss_property(widget, "class", class_name)


class PushPage(QWidget):
    """Push execution progress and result display.

    Shows a vertical stepper for the Safe Write Protocol stages and
    transitions to success/failure/dry-run result states.

    Signals:
        undo_requested: User clicked Undo after successful push.
        export_requested: User clicked Export as REW File.
        save_preset_requested: User clicked Save to My Presets.
        done_acknowledged: User clicked OK after success.
    """

    undo_requested = Signal()
    export_requested = Signal()
    save_preset_requested = Signal()
    done_acknowledged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PushPage")
        self._success_filters: list[CanonicalFilter] | None = None
        self._success_filters_l: list[CanonicalFilter] | None = None
        self._success_filters_r: list[CanonicalFilter] | None = None
        self._undo_mode: bool = False
        self._setup_ui()
        self.reset()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_stage(self, stage: str) -> None:
        """Advance the progress stepper to the given stage.

        Marks all stages before *stage* as complete and the specified
        stage as active. Stages after it remain pending.

        Args:
            stage: One of "backing_up", "writing", "verifying", or "done"
                (the backend's final on_stage callback before returning
                success -- there's no dedicated "Done" row to mark active,
                since it would be immediately redundant with the terminal
                result card set_success() shows right after; "done" instead
                marks every real stage complete).
        """
        self._show_progress_state()
        if stage == "done":
            for row in self._stage_rows.values():
                row.set_status("complete")
            return
        if stage not in _STAGES:
            logger.warning("set_stage() received unrecognized stage %r", stage)
        stage_index = _STAGES.index(stage) if stage in _STAGES else 0
        for i, key in enumerate(_STAGES):
            row = self._stage_rows[key]
            if i < stage_index:
                row.set_status("complete")
            elif i == stage_index:
                row.set_status("active")
            else:
                row.set_status("pending")

    def set_push_round(self, source_name: str, index: int, total: int) -> None:
        """Show which source/round a multi-source push (or undo) is on.

        Hidden entirely for a single-source operation (`total <= 1`), since
        there's nothing to disambiguate in that case.

        The AsyncBridge's push_round_changed signal is reused verbatim for
        multi-source undo (SecondaryWorkflowManager._do_undo_multi_source),
        so the label wording here switches on start_undo()'s mode flag
        rather than needing a second signal/handler pair.

        Args:
            source_name: The source currently being written to.
            index: 1-based index of this source among the selected sources.
            total: Total number of sources in this operation.
        """
        if total <= 1:
            self._round_label.setVisible(False)
            return
        verb = "Restoring" if self._undo_mode else "Pushing to"
        self._round_label.setText(f"{verb} {source_name} ({index} of {total})")
        self._round_label.setVisible(True)

    def start_undo(self) -> None:
        """Enter undo mode and show the progress stepper for the undo run.

        Undo follows the same Safe Write Protocol as a push (SafeWrite.undo()/
        RoomFitSafeWrite.undo() forward on_stage into their internal
        execute() call), so the same stepper this page already has is reused
        rather than building a second one. The "UNDO" badge stays visible
        through both the stepper and the terminal result card so the user
        can always tell this run is the undo, not the original push.
        """
        self._undo_mode = True
        self._show_progress_state()
        self._status_badge.setText("UNDO")
        set_qss_property(self._status_badge, "class", "undo")
        self._status_badge.setVisible(True)
        self._round_label.setVisible(False)
        for row in self._stage_rows.values():
            row.set_status("pending")

    def set_success(
        self,
        backup_path: str = "",
        filters: list[CanonicalFilter] | None = None,
        filters_l: list[CanonicalFilter] | None = None,
        filters_r: list[CanonicalFilter] | None = None,
    ) -> None:
        """Transition to success state.

        Shows green checkmark, success message, OK/Undo buttons,
        and secondary action links.

        Args:
            backup_path: Optional path to the backup file (for reference).
            filters: Stereo-mode bands read back from the device after the
                write (i.e. what's actually on the device now, not just what
                was intended). Ignored if filters_l/filters_r are given.
            filters_l: Left-channel bands read back from the device (L/R mode).
            filters_r: Right-channel bands read back from the device (L/R mode).
        """
        # Mark all stages complete
        for row in self._stage_rows.values():
            row.set_status("complete")

        # Hide the stepper on success -- once every stage reads "complete"
        # it's fully redundant with the result checkmark/message directly
        # below it, so collapsing it here reclaims real vertical space in
        # the most common outcome. Failure keeps the stepper visible (see
        # set_failure()) since it's the only place showing *which* stage
        # failed.
        self._progress_container.setVisible(False)

        self._show_result_state()
        self._result_icon.setText("\u2713")
        self._set_result_class("success")
        self._result_message.setText("Filters pushed successfully")
        self._detail_label.setVisible(False)

        self._success_filters = filters
        self._success_filters_l = filters_l
        self._success_filters_r = filters_r
        has_filter_data = filters is not None or filters_l is not None or filters_r is not None
        self._show_pushed_filters_button.setVisible(has_filter_data)

        # Show success actions
        self._ok_button.setVisible(True)
        self._undo_button.setVisible(True)
        self._secondary_row.setVisible(True)

    def set_failure(self, message: str, backup_path: str, critical: bool = False) -> None:
        """Transition to failure state.

        Shows warning/critical icon, error message, and recovery info.

        Args:
            message: Human-readable error description.
            backup_path: Path to the backup file for manual recovery.
            critical: True if rollback also failed (critical state).
        """
        if not self._fail_active_stage():
            # Nothing ever reached "active" (e.g. the write never started),
            # so a stepper of three untouched pending circles would only
            # look like nothing was attempted -- collapse it, same as a
            # clean success.
            self._progress_container.setVisible(False)

        self._show_result_state()
        if critical:
            self._result_icon.setText("\u26A0")  # warning triangle
            self._set_result_class("error")
            self._result_message.setText("Critical: Manual recovery required")
            detail_text = (
                f"{message}\n\n"
                f"Recovery steps:\n"
                f"1. Open the backup file below\n"
                f"2. Use Settings > Restore from Backup\n"
                f"3. Or manually restore via CLI\n\n"
                f"Backup: {backup_path}"
            )
        else:
            self._result_icon.setText("\u26A0")  # warning triangle
            self._set_result_class("warning")
            self._result_message.setText("Push failed - device safely restored")
            detail_text = (
                f"{message}\n\n"
                f"Your device was safely restored to its previous state.\n"
                f"Backup: {backup_path}"
            )

        self._detail_label.setText(detail_text)
        self._detail_label.setVisible(True)
        self._backup_path_label.setText(backup_path)
        self._backup_path_label.setVisible(bool(backup_path))

        # No filter data on failure — the rolled-back/deleted state isn't
        # useful to show, only the failure message matters here.
        self._clear_success_filters()

        # Show failure actions
        self._ok_button.setVisible(True)
        self._undo_button.setVisible(False)
        self._secondary_row.setVisible(False)

    def set_dry_run_result(self, summary: str) -> None:
        """Show dry run translation result (no network operations).

        Hides the progress stepper and displays a DRY RUN badge
        with the translation summary.

        Args:
            summary: Multi-line text describing the translation result.
        """
        self._progress_container.setVisible(False)
        self._show_result_state()
        self._status_badge.setText("DRY RUN")
        set_qss_property(self._status_badge, "class", "dryRun")
        self._status_badge.setVisible(True)
        self._result_icon.setText("\u2139")  # info icon
        self._set_result_class("info")
        self._result_message.setText("Dry Run Complete - Nothing Was Changed")
        self._detail_label.setText(summary)
        self._detail_label.setVisible(True)
        self._backup_path_label.setVisible(False)
        self._clear_success_filters()

        # Only OK button for dry run
        self._ok_button.setVisible(True)
        self._undo_button.setVisible(False)
        self._secondary_row.setVisible(False)

    def set_undo_success(self, message: str) -> None:
        """Transition to the undo-success result state.

        Reuses the same result card as set_success(), but hides Undo and
        the secondary links (Export/Save to Presets) -- there's nothing
        sensible to undo-the-undo, export, or save-as-preset from a
        restored-from-backup state -- and keeps the "UNDO" badge visible so
        this card unambiguously reads as the undo's result, not the
        original push's.

        Args:
            message: Human-readable result text (e.g. "Previous filters
                restored"), as reported by SecondaryWorkflowManager.
        """
        for row in self._stage_rows.values():
            row.set_status("complete")
        self._progress_container.setVisible(False)

        self._show_result_state()
        self._result_icon.setText("\u2713")
        self._set_result_class("success")
        self._result_message.setText(message)
        self._detail_label.setVisible(False)
        self._backup_path_label.setVisible(False)
        self._clear_success_filters()

        self._ok_button.setVisible(True)
        self._undo_button.setVisible(False)
        self._secondary_row.setVisible(False)

    def set_undo_failure(self, message: str) -> None:
        """Transition to the undo-failure result state.

        Keeps the Undo button visible/enabled so the user can retry --
        mirrors the previous mark_undo_complete(False) behavior -- and
        keeps the "UNDO" badge visible so the failure clearly reads as the
        undo's result, not the original push's.

        Args:
            message: Human-readable error text, as reported by
                SecondaryWorkflowManager.
        """
        if not self._fail_active_stage():
            # Same collapse as set_failure(): an undo that failed before any
            # stage activated (e.g. the backup file was already missing)
            # shouldn't show three untouched pending circles.
            self._progress_container.setVisible(False)

        self._show_result_state()
        self._result_icon.setText("\u26A0")  # warning triangle
        self._set_result_class("warning")
        self._result_message.setText("Undo failed")
        self._detail_label.setText(message)
        self._detail_label.setVisible(True)
        self._backup_path_label.setVisible(False)
        self._clear_success_filters()

        self._ok_button.setVisible(True)
        self._undo_button.setVisible(True)
        self._secondary_row.setVisible(False)

    def reset(self) -> None:
        """Reset to initial state (all stages pending, no result)."""
        self._undo_mode = False
        self._progress_container.setVisible(True)
        self._result_container.setVisible(False)
        self._status_badge.setVisible(False)
        self._round_label.setVisible(False)
        self._backup_path_label.setVisible(False)
        self._clear_success_filters()
        for row in self._stage_rows.values():
            row.set_status("pending")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fail_active_stage(self) -> bool:
        """Mark whichever stage row is currently "active" as "failed".

        Shared by set_failure() and set_undo_failure() -- both terminate a
        run at whatever stage it was interrupted on, so both need the same
        "find the active row" lookup.

        Returns:
            True if a row was active and marked failed. False if the run
            never reached an on_stage callback at all (e.g. the backup file
            was already missing) -- every row is still "pending" in that
            case, and the caller should collapse the stepper entirely
            rather than show three untouched circles next to a failure.
        """
        for key in reversed(_STAGES):
            row = self._stage_rows[key]
            if row.status == "active":
                row.set_status("failed")
                return True
        return False

    def _clear_success_filters(self) -> None:
        """Clear stored read-back filter data and hide the "Show" button."""
        self._success_filters = None
        self._success_filters_l = None
        self._success_filters_r = None
        self._show_pushed_filters_button.setVisible(False)

    def _on_show_pushed_filters_clicked(self) -> None:
        """Open the read-only dialog showing the device's confirmed filters."""
        dialog = PushedFiltersDialog(
            filters=self._success_filters,
            filters_l=self._success_filters_l,
            filters_r=self._success_filters_r,
            parent=self,
        )
        dialog.exec()

    def _set_result_class(self, status: str) -> None:
        """Set the result frame/icon/message QSS class (success/error/warning/info).

        The stepper's "complete" color already matches the generic "success"
        label color in both themes (see fluent_dark/light.qss), so the big
        result checkmark and the 4 completed stage checkmarks read as one
        continuous story without needing a separate color mapping here.
        """
        for widget in (self._result_frame, self._result_icon, self._result_message):
            set_qss_property(widget, "class", status)

    def _show_progress_state(self) -> None:
        """Ensure progress stepper is visible and result area hidden.

        Clears a leftover DRY RUN badge from a previous run, but not the
        UNDO badge -- start_undo() calls this once before showing the UNDO
        badge, and every subsequent set_stage() call during the undo's own
        progress must leave it alone rather than blanking it out stage by
        stage.
        """
        self._progress_container.setVisible(True)
        self._result_container.setVisible(False)
        if not self._undo_mode:
            self._status_badge.setVisible(False)

    def _show_result_state(self) -> None:
        """Show the result area (keeps stepper visible for context).

        Also hides the multi-source round label -- once a terminal result
        is reached there's no "currently pushing to X" round left to show,
        so leaving it visible would contradict the result message.
        """
        self._result_container.setVisible(True)
        self._round_label.setVisible(False)

    @staticmethod
    def _make_badge(text: str, object_name: str, parent: QWidget) -> QLabel:
        """Build a small pill-shaped status badge (DRY RUN / UNDO).

        Uses setRetainSizeWhenHidden so toggling a badge's visibility never
        shifts the layout of the content below it.
        """
        badge = QLabel(text, parent)
        badge.setObjectName(object_name)
        size_policy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        size_policy.setRetainSizeWhenHidden(True)
        badge.setSizePolicy(size_policy)
        badge.setVisible(False)
        return badge

    def _setup_ui(self) -> None:
        """Build the page layout."""
        content_layout, content_wrapper = build_centered_content(self)

        # Page title
        title = make_page_title(
            "Push to Device", content_wrapper, object_name="PushPageTitle"
        )
        content_layout.addWidget(title)

        # Scrollable body -- the stepper + result card (especially a
        # critical failure's full recovery text) can exceed the available
        # window height, and MainWindow's central area has no scroll area
        # of its own, so without this the bottom of the content silently
        # gets clipped by the window edge rather than staying reachable
        # (#179). Same setWidgetResizable/NoFrame/no-horizontal-scrollbar
        # pattern ConnectPage already uses for its device list.
        scroll_area = QScrollArea(content_wrapper)
        scroll_area.setObjectName("PushPageScrollArea")
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(SPACING_MD)

        # Status badge (DRY RUN / UNDO), hidden by default. The two states
        # are mutually exclusive -- undo is never reachable from a dry run,
        # and a dry run never happens mid-undo -- so one widget whose text
        # and QSS class are set at show time (set_dry_run_result()/
        # start_undo()) covers both, reserving only a single hidden slot
        # instead of one per state. Reserve that slot's layout space even
        # while hidden so toggling it doesn't shift the progress/result
        # content below it (#109).
        self._status_badge = self._make_badge("", "PushPageStatusBadge", body)
        body_layout.addWidget(self._status_badge)

        # Multi-source round indicator (hidden for a single-source push).
        # Shows which source is currently being written and how many rounds
        # remain, since the Safe Write Protocol repeats once per selected
        # source but nothing on this page previously said so.
        self._round_label = QLabel("", body)
        self._round_label.setObjectName("PushPageRoundLabel")
        self._round_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._round_label.setProperty("class", "secondary")
        self._round_label.setVisible(False)
        body_layout.addWidget(self._round_label)

        # Progress stepper container. Rows fill the container's width so
        # every row's icon sits at the same x position (a column of
        # checkmarks, not one shifting per row with its label's text
        # length) -- the container itself is then centered as a single
        # block, so the whole page still shares one alignment scheme with
        # the result section below. No page title is repeated here since
        # the page-level title above already establishes context (#179).
        self._progress_container = QWidget(body)
        self._progress_container.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        progress_layout = QVBoxLayout(self._progress_container)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(4)

        self._stage_rows: dict[str, _StageRow] = {}
        for stage_key in _STAGES:
            row = _StageRow(stage_key, self._progress_container)
            self._stage_rows[stage_key] = row
            progress_layout.addWidget(row)

        body_layout.addWidget(
            self._progress_container, alignment=Qt.AlignmentFlag.AlignHCenter
        )

        # Result container (success/failure/dry-run)
        self._result_container = QWidget(body)
        result_layout = QVBoxLayout(self._result_container)
        result_layout.setContentsMargins(0, SPACING_MD, 0, 0)
        result_layout.setSpacing(SPACING_MD)

        # Result card: icon + message + detail + backup path, framed in a
        # state-colored card instead of floating labels (#179). Only
        # _detail_label word-wraps, so it's added with a plain addWidget()
        # (no item alignment) -- see center_column()'s docstring in
        # page_layout.py for why item-aligning a wrapped label breaks its
        # height-for-width sizing.
        self._result_frame = QFrame(self._result_container)
        self._result_frame.setObjectName("PushPageResultFrame")
        frame_layout = QVBoxLayout(self._result_frame)
        frame_layout.setContentsMargins(SPACING_LG, SPACING_MD, SPACING_LG, SPACING_MD)
        frame_layout.setSpacing(SPACING_MD)

        self._result_icon = QLabel("", self._result_frame)
        self._result_icon.setObjectName("PushPageResultIcon")
        self._result_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        frame_layout.addWidget(self._result_icon, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._result_message = QLabel("", self._result_frame)
        self._result_message.setObjectName("PushPageResultMessage")
        self._result_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        frame_layout.addWidget(self._result_message, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Detail/recovery text (multi-line)
        self._detail_label = QLabel("", self._result_frame)
        self._detail_label.setObjectName("PushPageDetailLabel")
        self._detail_label.setWordWrap(True)
        self._detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._detail_label.setProperty("class", "caption")
        self._detail_label.setVisible(False)
        frame_layout.addWidget(self._detail_label)

        # Backup path (copyable, selectable text)
        self._backup_path_label = QLabel("", self._result_frame)
        self._backup_path_label.setObjectName("PushPageBackupPath")
        self._backup_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._backup_path_label.setVisible(False)
        frame_layout.addWidget(
            self._backup_path_label, alignment=Qt.AlignmentFlag.AlignHCenter
        )

        # Plain addWidget (no item alignment) -- the frame spans the full
        # content column width, like push_confirmation.py's info_frame/
        # clamping_frame, so its own sizeHint() is never computed at an
        # artificially centered/unconstrained width (the same bug class
        # this whole page's redesign fixes for _detail_label).
        result_layout.addWidget(self._result_frame)

        # Opens a dialog showing the read-back filters confirmed on the
        # device (success only; not shown on failure since the rolled-back
        # or deleted state isn't useful to display). A dialog rather than an
        # inline table, since a full 10-band (or L/R, 2x10-band) table does
        # not comfortably fit on this page alongside the result summary.
        self._show_pushed_filters_button = make_action_button(
            "Show Pushed Filters",
            object_name="PushPageShowFiltersButton",
            style_class="linkButton",
            parent=self._result_container,
        )
        self._show_pushed_filters_button.setFlat(True)
        self._show_pushed_filters_button.clicked.connect(
            self._on_show_pushed_filters_clicked
        )
        self._show_pushed_filters_button.setVisible(False)
        result_layout.addWidget(
            self._show_pushed_filters_button, alignment=Qt.AlignmentFlag.AlignHCenter
        )

        # Primary action buttons row (OK + Undo)
        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(0, SPACING_MD, 0, 0)
        action_layout.setSpacing(SPACING_MD)
        action_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._ok_button = make_action_button(
            "OK", object_name="PushPageOKButton", style_class="success",
            parent=self._result_container,
        )
        self._ok_button.clicked.connect(self.done_acknowledged.emit)
        self._ok_button.setVisible(False)
        action_layout.addWidget(self._ok_button)

        self._undo_button = make_action_button(
            "Undo", object_name="PushPageUndoButton", style_class="warning",
            parent=self._result_container,
        )
        self._undo_button.clicked.connect(self.undo_requested.emit)
        self._undo_button.setVisible(False)
        action_layout.addWidget(self._undo_button)

        result_layout.addLayout(action_layout)

        # Secondary links row (Export + Save to Presets)
        self._secondary_row = QWidget(self._result_container)
        secondary_layout = QHBoxLayout(self._secondary_row)
        secondary_layout.setContentsMargins(0, 0, 0, 0)
        secondary_layout.setSpacing(SPACING_MD)
        secondary_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        export_link = make_action_button(
            "Export as REW File", object_name="PushPageExportLink",
            style_class="linkButton", parent=self._secondary_row,
        )
        export_link.setFlat(True)
        export_link.clicked.connect(self.export_requested.emit)
        secondary_layout.addWidget(export_link)

        separator = QLabel("|", self._secondary_row)
        separator.setObjectName("PushPageLinkSeparator")
        secondary_layout.addWidget(separator)

        save_link = make_action_button(
            "Save to My Presets", object_name="PushPageSavePresetLink",
            style_class="linkButton", parent=self._secondary_row,
        )
        save_link.setFlat(True)
        save_link.clicked.connect(self.save_preset_requested.emit)
        secondary_layout.addWidget(save_link)

        self._secondary_row.setVisible(False)
        result_layout.addWidget(self._secondary_row)

        self._result_container.setVisible(False)
        body_layout.addWidget(self._result_container)

        body_layout.addStretch()
        scroll_area.setWidget(body)
        content_layout.addWidget(scroll_area, 1)
