"""ReviewPage — filter review with actions, toggles, and keyboard shortcuts.

Displays imported/pulled filters in a FilterTable and offers push, export,
save, copy, and multi-device actions. Supports Dry Run mode and comparison
with current device state.

Requirements referenced: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 9.7, 12.1, 19.1, 19.4, 20.1.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QWidget,
)

from src.gui.components.action_button import make_action_button
from src.gui.components.filter_table import FilterTable
from src.gui.components.page_layout import build_centered_content, make_page_title
from src.gui.constants import (
    FILTER_TABLE_MAX_WIDTH,
    SPACING_MD,
)
from src.gui.style_utils import set_qss_property
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
        self._setup_shortcuts()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

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

        # Dry Run badge (accent-colored pill, always reserves space)
        self._dry_run_badge = QLabel("DRY RUN", content_wrapper)
        self._dry_run_badge.setObjectName("ReviewPageDryRunBadge")
        self._dry_run_badge.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        # Start hidden visually (transparent) but still taking up layout space
        self._dry_run_badge.setProperty("active", False)
        content_layout.addWidget(self._dry_run_badge)

        # FilterTable (centered, capped so its 5 short columns don't stretch
        # across the full content column -- see FilterTable's own docstring).
        # Centered via a stretch-widget-stretch sandwich, NOT
        # addWidget(..., alignment=...) -- an alignment flag on addWidget
        # sizes the widget to its sizeHint() instead of letting its Expanding
        # size policy fill up to setMaximumWidth(), and FilterTable's
        # Stretch-mode columns don't contribute meaningfully to sizeHint, so
        # the table collapsed to a tiny sliver instead of the intended
        # 600px-wide, stretch-filled table (same root cause page_layout.py's
        # build_centered_content docstring already documents for smoke #179).
        self._filter_table = FilterTable(content_wrapper)
        self._filter_table.setMaximumWidth(FILTER_TABLE_MAX_WIDTH)
        filter_table_row = QHBoxLayout()
        filter_table_row.setContentsMargins(0, 0, 0, 0)
        filter_table_row.addStretch()
        filter_table_row.addWidget(self._filter_table, 1)
        filter_table_row.addStretch()
        content_layout.addLayout(filter_table_row)

        # Toggles row
        toggles_layout = QHBoxLayout()
        toggles_layout.setContentsMargins(0, 0, 0, 0)
        toggles_layout.setSpacing(SPACING_MD)

        self._dry_run_checkbox = QCheckBox("Dry Run", content_wrapper)
        self._dry_run_checkbox.setObjectName("ReviewPageDryRunToggle")
        self._dry_run_checkbox.toggled.connect(self._on_dry_run_toggled)
        toggles_layout.addWidget(self._dry_run_checkbox)

        toggles_layout.addStretch()
        content_layout.addLayout(toggles_layout)

        # Always-visible plain-language explanation of Dry Run, so
        # non-technical users don't assume a push silently failed when
        # nothing changes on their device (smoke #182).
        self._dry_run_hint = QLabel(
            "When 'Dry Run' is checked, filters are previewed only"
            " — nothing is written to your device until you turn"
            " this off.",
            content_wrapper,
        )
        self._dry_run_hint.setObjectName("ReviewPageDryRunHint")
        self._dry_run_hint.setProperty("class", "caption")
        self._dry_run_hint.setWordWrap(True)
        content_layout.addWidget(self._dry_run_hint)

        # Primary action row
        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(SPACING_MD)

        self._push_button = make_action_button(
            "Push to Device", object_name="ReviewPagePushButton", style_class="primary",
            parent=content_wrapper,
        )
        self._push_button.clicked.connect(self._on_push_clicked)
        action_layout.addWidget(self._push_button)

        export_button = make_action_button(
            "Export as REW File", object_name="ReviewPageExportButton",
            style_class="secondary", parent=content_wrapper,
        )
        export_button.clicked.connect(self.export_rew_requested.emit)
        action_layout.addWidget(export_button)

        save_button = make_action_button(
            "Save to My Presets", object_name="ReviewPageSaveButton",
            style_class="ghost", parent=content_wrapper,
        )
        save_button.clicked.connect(self.save_preset_requested.emit)
        action_layout.addWidget(save_button)

        action_layout.addStretch()
        content_layout.addLayout(action_layout)

        content_layout.addStretch()

    def _setup_shortcuts(self) -> None:
        """Configure keyboard shortcuts."""
        # Ctrl+Enter → emit push_requested
        shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self._on_push_clicked)

    def _update_dry_run_ui(self) -> None:
        """Sync UI elements with current dry run state."""
        self._push_button.setText("Preview Only" if self._dry_run else "Push to Device")
        set_qss_property(self._dry_run_badge, "active", self._dry_run)

    @Slot(bool)
    def _on_dry_run_toggled(self, checked: bool) -> None:
        """Handle dry run checkbox toggle."""
        self._dry_run = checked
        self._update_dry_run_ui()
        self.dry_run_toggled.emit(checked)

    @Slot()
    def _on_push_clicked(self) -> None:
        """Handle push button click or Ctrl+Enter shortcut."""
        self.push_requested.emit()
