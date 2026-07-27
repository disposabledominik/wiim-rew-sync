"""ReviewPage — filter review with actions and toggles.

Displays imported/pulled filters in a FilterTable and offers push, export,
save, copy, and multi-device actions. Supports Dry Run mode and comparison
with current device state.

Requirements referenced: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 9.7, 12.1, 19.1, 19.4, 20.1.
"""

from __future__ import annotations

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QWidget,
)

from src.gui.components.action_button import make_action_button
from src.gui.components.filter_table import FilterTable
from src.gui.components.page_layout import build_centered_content, make_page_title
from src.gui.constants import (
    FILTER_TABLE_MAX_WIDTH,
    SPACING_MD,
)
from src.models.canonical import CanonicalFilter
from src.translator._warnings import FilterRow


class ReviewPage(QWidget):
    """Filter review page with FilterTable, actions, and toggle controls.

    Displays the current filter set in a read-only table and provides action
    buttons for pushing to device, exporting, and saving presets.
    Dry Run mode changes the primary button label and shows a badge.

    Signals:
        push_requested: User wants to push filters to device.
        export_rew_requested: Export filters as REW-compatible file.
        save_preset_requested: Save filters to local preset library.
        dry_run_toggled: Dry run mode changed (bool: enabled).
    """

    push_requested = Signal()
    export_rew_requested = Signal()
    save_preset_requested = Signal()
    dry_run_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ReviewPage")
        self._dry_run: bool = False
        self._setup_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def action_buttons(self) -> list[QWidget]:
        """Return buttons that should be disabled while an operation is in progress."""
        return [self._export_button, self._save_button, self._push_button]

    def set_filters(
        self,
        filters: list[CanonicalFilter],
        clamping_map: dict[int, list[str]] | None = None,
        rows: list[FilterRow] | None = None,
        notes_map: dict[int, list[str]] | None = None,
    ) -> None:
        """Pass filters through to the FilterTable.

        Args:
            filters: List of CanonicalFilter instances.
            clamping_map: Optional mapping of band index to clamping reasons.
            rows: Optional display rows in original order, interleaving
                skipped/truncated band placeholders (see FilterTable.set_filters).
            notes_map: Optional mapping of band index to conversion notes
                (values REW didn't specify and had to be substituted).
        """
        self._filter_table.set_filters(filters, clamping_map, rows, notes_map)

    def set_lr_filters(
        self,
        left: list[CanonicalFilter],
        right: list[CanonicalFilter],
        clamping_map_l: dict[int, list[str]] | None = None,
        clamping_map_r: dict[int, list[str]] | None = None,
        rows_l: list[FilterRow] | None = None,
        rows_r: list[FilterRow] | None = None,
        notes_map_l: dict[int, list[str]] | None = None,
        notes_map_r: dict[int, list[str]] | None = None,
    ) -> None:
        """Pass L/R filters through to the FilterTable.

        Args:
            left: Filters for the left channel.
            right: Filters for the right channel.
            clamping_map_l: Optional clamping map for the left channel.
            clamping_map_r: Optional clamping map for the right channel.
            rows_l: Optional display rows for the left channel.
            rows_r: Optional display rows for the right channel.
            notes_map_l: Optional conversion-notes map for the left channel.
            notes_map_r: Optional conversion-notes map for the right channel.
        """
        self._filter_table.set_lr_filters(
            left,
            right,
            clamping_map_l,
            clamping_map_r,
            rows_l,
            rows_r,
            notes_map_l,
            notes_map_r,
        )

    def set_dry_run(self, enabled: bool) -> None:
        """Update the dry run state.

        When enabled, the primary button shows "Preview Only" and a
        "DRY RUN" badge becomes visible.

        Args:
            enabled: True to enable dry run mode.
        """
        self._dry_run = enabled
        self._dry_run_checkbox.setChecked(enabled)
        self._update_dry_run_ui()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Build the page layout."""
        content_layout, content_wrapper = build_centered_content(self)

        # Page title
        title = make_page_title(
            "Review Filters", content_wrapper, object_name="ReviewPageTitle"
        )
        content_layout.addWidget(title)

        # Dry Run toggle row: checkbox + inline explanation, above the table
        # so the table (below) gets first claim on the page's spare vertical
        # space. Always-visible plain-language explanation so non-technical
        # users don't assume a push silently failed when nothing changes on
        # their device (smoke #182).
        toggles_layout = QHBoxLayout()
        toggles_layout.setContentsMargins(0, 0, 0, 0)
        toggles_layout.setSpacing(SPACING_MD)

        self._dry_run_checkbox = QCheckBox("Dry Run", content_wrapper)
        self._dry_run_checkbox.setObjectName("ReviewPageDryRunToggle")
        self._dry_run_checkbox.toggled.connect(self._on_dry_run_toggled)
        toggles_layout.addWidget(self._dry_run_checkbox)

        self._dry_run_hint = QLabel(
            "When checked, filters are previewed only — nothing is"
            " written to your device until you turn this off.",
            content_wrapper,
        )
        self._dry_run_hint.setObjectName("ReviewPageDryRunHint")
        self._dry_run_hint.setProperty("class", "caption")
        self._dry_run_hint.setWordWrap(True)
        toggles_layout.addWidget(self._dry_run_hint, 1)

        content_layout.addLayout(toggles_layout)

        # FilterTable: fills the content column's width (capped at
        # FILTER_TABLE_MAX_WIDTH, which equals MAX_CONTENT_WIDTH so the cap
        # is a no-op today but stays meaningful if the column width changes
        # again later) and gets a stretch factor of 1 so it grows into the
        # page's spare vertical space instead of that space collecting below
        # the action buttons at the trailing addStretch() below.
        self._filter_table = FilterTable(content_wrapper)
        self._filter_table.setMaximumWidth(FILTER_TABLE_MAX_WIDTH)
        content_layout.addWidget(self._filter_table, 1)

        # Leading stretch (not trailing) so the action row below is pinned
        # to the bottom of the page -- matching every other wizard step's
        # primary-button position -- regardless of how much vertical space
        # the FilterTable above ends up using.
        content_layout.addStretch()

        # Primary action row. Push to Device (the primary/step-advancing
        # action) is rightmost, matching the position of the primary button
        # on every other step; Export/Save are secondary, so they lead.
        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(SPACING_MD)
        action_layout.addStretch()

        self._export_button = make_action_button(
            "Export as REW File", object_name="ReviewPageExportButton",
            style_class="secondary", parent=content_wrapper,
        )
        self._export_button.clicked.connect(self.export_rew_requested.emit)
        action_layout.addWidget(self._export_button)

        self._save_button = make_action_button(
            "Save to My Presets", object_name="ReviewPageSaveButton",
            style_class="ghost", parent=content_wrapper,
        )
        self._save_button.clicked.connect(self.save_preset_requested.emit)
        action_layout.addWidget(self._save_button)

        self._push_button = make_action_button(
            "Push to Device", object_name="ReviewPagePushButton", style_class="primary",
            parent=content_wrapper,
        )
        self._push_button.clicked.connect(self._on_push_clicked)
        action_layout.addWidget(self._push_button)

        content_layout.addLayout(action_layout)

    def _update_dry_run_ui(self) -> None:
        """Sync UI elements with current dry run state."""
        self._push_button.setText("Preview Only" if self._dry_run else "Push to Device")

    @Slot(bool)
    def _on_dry_run_toggled(self, checked: bool) -> None:
        """Handle dry run checkbox toggle."""
        self._dry_run = checked
        self._update_dry_run_ui()
        self.dry_run_toggled.emit(checked)

    @Slot()
    def _on_push_clicked(self) -> None:
        """Handle push button click."""
        self.push_requested.emit()
