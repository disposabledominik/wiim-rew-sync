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
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.gui.components.filter_table import FilterTable
from src.gui.constants import (
    ACCENT_COLOR,
    MAX_CONTENT_WIDTH,
    SPACING_LG,
    SPACING_MD,
)
from src.models.canonical import CanonicalFilter


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
    ) -> None:
        """Pass filters through to the FilterTable.

        Args:
            filters: List of CanonicalFilter instances.
            clamping_map: Optional mapping of band index to clamping reasons.
        """
        self._filter_table.set_filters(filters, clamping_map)

    def set_lr_filters(
        self,
        left: list[CanonicalFilter],
        right: list[CanonicalFilter],
        clamping_map: dict[int, list[str]] | None = None,
    ) -> None:
        """Pass L/R filters through to the FilterTable.

        Args:
            left: Filters for the left channel.
            right: Filters for the right channel.
            clamping_map: Optional clamping map applied to both channels.
        """
        self._filter_table.set_lr_filters(left, right, clamping_map)

    def set_summary(
        self,
        device: str,
        source: str,
        channel: str,
        band_count: int,
    ) -> None:
        """Update the summary header text.

        Displays: "{band_count} bands -> {device} / {source} / {channel}"

        Args:
            device: Device name (e.g. "WiiM Pro Plus").
            source: Audio source name (e.g. "wifi").
            channel: Channel mode (e.g. "Stereo").
            band_count: Number of active filter bands.
        """
        self._summary_label.setText(
            f"{band_count} bands \u2192 {device} / {source} / {channel}"
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
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        # Content wrapper with max width
        content_wrapper = QWidget(self)
        content_wrapper.setMaximumWidth(MAX_CONTENT_WIDTH)
        content_layout = QVBoxLayout(content_wrapper)
        content_layout.setContentsMargins(SPACING_LG, SPACING_LG, SPACING_LG, SPACING_LG)
        content_layout.setSpacing(SPACING_LG)

        # Summary header
        self._summary_label = QLabel("", content_wrapper)
        self._summary_label.setObjectName("ReviewPageSummary")
        self._summary_label.setStyleSheet("font-size: 13px; color: #616161;")
        content_layout.addWidget(self._summary_label)

        # Dry Run badge (accent-colored pill, always reserves space)
        self._dry_run_badge = QLabel("DRY RUN", content_wrapper)
        self._dry_run_badge.setObjectName("ReviewPageDryRunBadge")
        self._dry_run_badge.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        # Start hidden visually (transparent) but still taking up layout space
        self._dry_run_badge.setStyleSheet(
            "background-color: transparent; color: transparent; "
            "border-radius: 10px; padding: 2px 10px; font-size: 11px; "
            "font-weight: 600;"
        )
        content_layout.addWidget(self._dry_run_badge)

        # FilterTable (centered, ~400px max)
        self._filter_table = FilterTable(content_wrapper)
        content_layout.addWidget(self._filter_table, 1)

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

        # Primary action row
        action_layout = QHBoxLayout()
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(SPACING_MD)

        self._push_button = QPushButton("Push to Device", content_wrapper)
        self._push_button.setObjectName("ReviewPagePushButton")
        self._push_button.setProperty("class", "primary")
        self._push_button.clicked.connect(self._on_push_clicked)
        action_layout.addWidget(self._push_button)

        export_button = QPushButton("Export as REW File", content_wrapper)
        export_button.setObjectName("ReviewPageExportButton")
        export_button.setProperty("class", "secondary")
        export_button.clicked.connect(self.export_rew_requested.emit)
        action_layout.addWidget(export_button)

        save_button = QPushButton("Save to My Presets", content_wrapper)
        save_button.setObjectName("ReviewPageSaveButton")
        save_button.setProperty("class", "ghost")
        save_button.clicked.connect(self.save_preset_requested.emit)
        action_layout.addWidget(save_button)

        action_layout.addStretch()
        content_layout.addLayout(action_layout)

        content_layout.addStretch()

        # Add content wrapper directly (fills available space)
        page_layout.addWidget(content_wrapper)

    def _setup_shortcuts(self) -> None:
        """Configure keyboard shortcuts."""
        # Ctrl+Enter → emit push_requested
        shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        shortcut.activated.connect(self._on_push_clicked)

    def _update_dry_run_ui(self) -> None:
        """Sync UI elements with current dry run state."""
        if self._dry_run:
            self._push_button.setText("Preview Only")
            self._dry_run_badge.setStyleSheet(
                f"background-color: {ACCENT_COLOR}; color: #FFFFFF; "
                f"border-radius: 10px; padding: 2px 10px; font-size: 11px; "
                f"font-weight: 600;"
            )
        else:
            self._push_button.setText("Push to Device")
            self._dry_run_badge.setStyleSheet(
                "background-color: transparent; color: transparent; "
                "border-radius: 10px; padding: 2px 10px; font-size: 11px; "
                "font-weight: 600;"
            )

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
