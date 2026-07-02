"""PushPage — push execution progress and result display.

Shows the Safe Write Protocol progress as a vertical stepper
(Backing up -> Writing -> Verifying -> Done), success/failure states,
and post-push actions (OK, Undo, Export, Save to Presets).

Requirements referenced: 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 18.1.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

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

_STAGES: list[str] = ["backing_up", "writing", "verifying", "done"]
_STAGE_LABELS: dict[str, str] = {
    "backing_up": "Backing up",
    "writing": "Writing",
    "verifying": "Verifying",
    "done": "Done",
}


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
            stage: One of "backing_up", "writing", "verifying", "done".
        """
        self._show_progress_state()
        stage_index = _STAGES.index(stage) if stage in _STAGES else 0
        for i, key in enumerate(_STAGES):
            row = self._stage_rows[key]
            if i < stage_index:
                row.set_status("complete")
            elif i == stage_index:
                row.set_status("active" if stage != "done" else "complete")
            else:
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
        self._failure_row.setVisible(False)

    def set_failure(self, message: str, backup_path: str, critical: bool = False) -> None:
        """Transition to failure state.

        Shows warning/critical icon, error message, and recovery info.

        Args:
            message: Human-readable error description.
            backup_path: Path to the backup file for manual recovery.
            critical: True if rollback also failed (critical state).
        """
        # Mark last active stage as failed
        for key in reversed(_STAGES):
            row = self._stage_rows[key]
            if row.status == "active":
                row.set_status("failed")
                break

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
        self._failure_row.setVisible(True)

    def set_dry_run_result(self, summary: str) -> None:
        """Show dry run translation result (no network operations).

        Hides the progress stepper and displays a DRY RUN badge
        with the translation summary.

        Args:
            summary: Multi-line text describing the translation result.
        """
        self._progress_container.setVisible(False)
        self._show_result_state()
        self._dry_run_badge.setVisible(True)
        self._result_icon.setText("\u2139")  # info icon
        self._set_result_class("info")
        self._result_message.setText("Translation Preview (Dry Run)")
        self._detail_label.setText(summary)
        self._detail_label.setVisible(True)
        self._backup_path_label.setVisible(False)
        self._clear_success_filters()

        # Only OK button for dry run
        self._ok_button.setVisible(True)
        self._undo_button.setVisible(False)
        self._secondary_row.setVisible(False)
        self._failure_row.setVisible(False)

    def reset(self) -> None:
        """Reset to initial state (all stages pending, no result)."""
        self._progress_container.setVisible(True)
        self._result_container.setVisible(False)
        self._dry_run_badge.setVisible(False)
        self._backup_path_label.setVisible(False)
        self._clear_success_filters()
        for row in self._stage_rows.values():
            row.set_status("pending")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

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
        """Set the result icon/message QSS class (success/error/warning/info)."""
        for widget in (self._result_icon, self._result_message):
            set_qss_property(widget, "class", status)

    def _show_progress_state(self) -> None:
        """Ensure progress stepper is visible and result area hidden."""
        self._progress_container.setVisible(True)
        self._result_container.setVisible(False)
        self._dry_run_badge.setVisible(False)

    def _show_result_state(self) -> None:
        """Show the result area (keeps stepper visible for context)."""
        self._result_container.setVisible(True)

    def _setup_ui(self) -> None:
        """Build the page layout."""
        content_layout, content_wrapper = build_centered_content(self)

        # Page title
        title = make_page_title(
            "Push to Device", content_wrapper, object_name="PushPageTitle"
        )
        content_layout.addWidget(title)

        # Dry Run badge (hidden by default). Reserves its layout space even
        # while hidden so toggling it via set_dry_run_result()/reset() doesn't
        # shift the progress/result content below it (#109).
        self._dry_run_badge = QLabel("DRY RUN", content_wrapper)
        self._dry_run_badge.setObjectName("PushPageDryRunBadge")
        size_policy = QSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        size_policy.setRetainSizeWhenHidden(True)
        self._dry_run_badge.setSizePolicy(size_policy)
        self._dry_run_badge.setVisible(False)
        content_layout.addWidget(self._dry_run_badge)

        # Progress stepper container
        self._progress_container = QWidget(content_wrapper)
        progress_layout = QVBoxLayout(self._progress_container)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        progress_layout.setSpacing(4)

        progress_title = QLabel("Push Progress", self._progress_container)
        progress_title.setProperty("class", "sectionTitle")
        progress_layout.addWidget(progress_title)

        self._stage_rows: dict[str, _StageRow] = {}
        for stage_key in _STAGES:
            row = _StageRow(stage_key, self._progress_container)
            self._stage_rows[stage_key] = row
            progress_layout.addWidget(row)

        content_layout.addWidget(self._progress_container)

        # Result container (success/failure/dry-run)
        self._result_container = QWidget(content_wrapper)
        result_layout = QVBoxLayout(self._result_container)
        result_layout.setContentsMargins(0, SPACING_LG, 0, 0)
        result_layout.setSpacing(SPACING_MD)
        result_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # Large result icon
        self._result_icon = QLabel("", self._result_container)
        self._result_icon.setObjectName("PushPageResultIcon")
        self._result_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        result_layout.addWidget(self._result_icon)

        # Result message
        self._result_message = QLabel("", self._result_container)
        self._result_message.setObjectName("PushPageResultMessage")
        self._result_message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        result_layout.addWidget(self._result_message)

        # Detail/recovery text (multi-line)
        self._detail_label = QLabel("", self._result_container)
        self._detail_label.setObjectName("PushPageDetailLabel")
        self._detail_label.setWordWrap(True)
        self._detail_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self._detail_label.setProperty("class", "caption")
        self._detail_label.setVisible(False)
        result_layout.addWidget(self._detail_label)

        # Backup path (copyable, selectable text)
        self._backup_path_label = QLabel("", self._result_container)
        self._backup_path_label.setObjectName("PushPageBackupPath")
        self._backup_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._backup_path_label.setVisible(False)
        result_layout.addWidget(self._backup_path_label)

        # Opens a dialog showing the read-back filters confirmed on the
        # device (success only; not shown on failure since the rolled-back
        # or deleted state isn't useful to display). A dialog rather than an
        # inline table, since a full 10-band (or L/R, 2x10-band) table does
        # not comfortably fit on this page alongside the result summary.
        self._show_pushed_filters_button = QPushButton(
            "Show Pushed Filters", self._result_container
        )
        self._show_pushed_filters_button.setObjectName("PushPageShowFiltersButton")
        self._show_pushed_filters_button.setFlat(True)
        self._show_pushed_filters_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._show_pushed_filters_button.setProperty("class", "linkButton")
        self._show_pushed_filters_button.clicked.connect(
            self._on_show_pushed_filters_clicked
        )
        self._show_pushed_filters_button.setVisible(False)
        result_layout.addWidget(self._show_pushed_filters_button)

        # Primary action buttons row (OK + Undo)
        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(0, SPACING_MD, 0, 0)
        action_layout.setSpacing(SPACING_MD)
        action_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._ok_button = QPushButton("OK", self._result_container)
        self._ok_button.setObjectName("PushPageOKButton")
        self._ok_button.setProperty("class", "success")
        self._ok_button.clicked.connect(self.done_acknowledged.emit)
        self._ok_button.setVisible(False)
        action_layout.addWidget(self._ok_button)

        self._undo_button = QPushButton("Undo", self._result_container)
        self._undo_button.setObjectName("PushPageUndoButton")
        self._undo_button.setProperty("class", "warning")
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

        export_link = QPushButton("Export as REW File", self._secondary_row)
        export_link.setObjectName("PushPageExportLink")
        export_link.setFlat(True)
        export_link.setCursor(Qt.CursorShape.PointingHandCursor)
        export_link.setProperty("class", "linkButton")
        export_link.clicked.connect(self.export_requested.emit)
        secondary_layout.addWidget(export_link)

        separator = QLabel("|", self._secondary_row)
        separator.setObjectName("PushPageLinkSeparator")
        secondary_layout.addWidget(separator)

        save_link = QPushButton("Save to My Presets", self._secondary_row)
        save_link.setObjectName("PushPageSavePresetLink")
        save_link.setFlat(True)
        save_link.setCursor(Qt.CursorShape.PointingHandCursor)
        save_link.setProperty("class", "linkButton")
        save_link.clicked.connect(self.save_preset_requested.emit)
        secondary_layout.addWidget(save_link)

        self._secondary_row.setVisible(False)
        result_layout.addWidget(self._secondary_row)

        # Failure-specific row (OK returns to wizard)
        self._failure_row = QWidget(self._result_container)
        failure_layout = QHBoxLayout(self._failure_row)
        failure_layout.setContentsMargins(0, 0, 0, 0)
        failure_layout.setSpacing(SPACING_MD)
        failure_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._failure_row.setVisible(False)
        result_layout.addWidget(self._failure_row)

        self._result_container.setVisible(False)
        content_layout.addWidget(self._result_container)

        content_layout.addStretch()
