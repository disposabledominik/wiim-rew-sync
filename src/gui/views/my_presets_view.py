"""MyPresetsView — local preset library with CRUD operations.

Displays saved presets in a list with name, channel mode badge (Stereo/L/R),
and active band count. Supports inline rename (double-click), right-click
context menu (Load, Rename, Duplicate, Delete), and search/filter when more
than 10 items are present.

The view does NOT handle persistence. It receives data via :meth:`set_presets`
and emits action signals for the controller to handle.

Requirements referenced: 8.3, 8.4, 10.9.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QMouseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.gui.constants import (
    ACCENT_COLOR,
    FONT_SIZE_BODY,
    FONT_SIZE_CAPTION,
    FONT_WEIGHT_SEMIBOLD,
    LIST_ITEM_HEIGHT,
    MAX_CONTENT_WIDTH,
    SPACING_LG,
    SPACING_MD,
    SPACING_SM,
    SPACING_XS,
)
from src.models.profile import Profile

# Threshold: show search field when preset count exceeds this value.
_SEARCH_THRESHOLD = 10


class _PresetItemWidget(QWidget):
    """Custom widget displayed for each preset list item.

    Shows the preset name, a channel mode badge (Stereo/L/R), and the
    active band count (e.g. "8/10 bands").
    """

    def __init__(
        self,
        name: str,
        channel_mode: str,
        active_bands: int,
        total_bands: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setMinimumHeight(LIST_ITEM_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(SPACING_MD, SPACING_XS, SPACING_MD, SPACING_XS)
        layout.setSpacing(SPACING_SM)

        # Preset name
        self._name_label = QLabel(name, self)
        self._name_label.setObjectName("PresetItemName")
        self._name_label.setStyleSheet(
            f"font-size: {FONT_SIZE_BODY}px; font-weight: {FONT_WEIGHT_SEMIBOLD};"
        )
        self._name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._name_label)

        # Channel mode badge
        badge_text = _channel_mode_display(channel_mode)
        self._mode_badge = QLabel(badge_text, self)
        self._mode_badge.setObjectName("PresetItemBadge")
        self._mode_badge.setStyleSheet(
            f"font-size: {FONT_SIZE_CAPTION}px; "
            f"background-color: {ACCENT_COLOR}; "
            "color: #FFFFFF; "
            f"border-radius: {SPACING_XS}px; "
            f"padding: 2px {SPACING_SM}px;"
        )
        self._mode_badge.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._mode_badge)

        # Active band count
        band_text = f"{active_bands}/{total_bands} bands"
        self._band_label = QLabel(band_text, self)
        self._band_label.setObjectName("PresetItemBands")
        self._band_label.setStyleSheet(f"font-size: {FONT_SIZE_CAPTION}px; color: #9E9E9E;")
        self._band_label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._band_label)

    @property
    def preset_name(self) -> str:
        """Return the displayed preset name."""
        return self._name_label.text()


class MyPresetsView(QWidget):
    """Local preset library with CRUD operations.

    Signals:
        load_requested: Emitted with the Profile when the user loads a preset.
        rename_requested: Emitted with (old_name, new_name) after inline rename.
        duplicate_requested: Emitted with the preset name to duplicate.
        delete_requested: Emitted with the preset name to delete.
    """

    load_requested = Signal(object)  # Profile
    rename_requested = Signal(str, str)  # old_name, new_name
    duplicate_requested = Signal(str)  # preset name
    delete_requested = Signal(str)  # preset name

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MyPresetsView")

        self._presets: list[Profile] = []
        self._rename_item: QListWidgetItem | None = None

        self._setup_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_presets(self, presets: list[Profile]) -> None:
        """Populate the view with preset data.

        Args:
            presets: List of Profile objects to display.
        """
        self._presets = list(presets)
        self._update_search_visibility()
        self._populate_list()

    def refresh(self) -> None:
        """Re-render the list from the current preset data."""
        self._populate_list()

    def preset_count(self) -> int:
        """Return the number of presets currently held."""
        return len(self._presets)

    # ------------------------------------------------------------------
    # UI Setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Build the widget layout."""
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(SPACING_LG, SPACING_LG, SPACING_LG, SPACING_LG)
        outer_layout.setSpacing(SPACING_MD)

        # Content container (constrained width)
        content = QWidget(self)
        content.setMaximumWidth(MAX_CONTENT_WIDTH)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(SPACING_MD)

        # Title
        title = QLabel("My Saved Presets", content)
        title.setObjectName("MyPresetsTitle")
        title.setStyleSheet(f"font-size: 18px; font-weight: {FONT_WEIGHT_SEMIBOLD};")
        content_layout.addWidget(title)

        # Search/filter field (hidden until > 10 items)
        self._search_field = QLineEdit(content)
        self._search_field.setObjectName("MyPresetsSearch")
        self._search_field.setPlaceholderText("Search presets...")
        self._search_field.setClearButtonEnabled(True)
        self._search_field.setVisible(False)
        self._search_field.textChanged.connect(self._on_search_text_changed)
        content_layout.addWidget(self._search_field)

        # Preset list
        self._list_widget = QListWidget(content)
        self._list_widget.setObjectName("MyPresetsList")
        self._list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list_widget.customContextMenuRequested.connect(self._show_context_menu)
        self._list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list_widget.setSpacing(2)
        content_layout.addWidget(self._list_widget)

        # Empty state label
        self._empty_label = QLabel("No saved presets yet.", content)
        self._empty_label.setObjectName("MyPresetsEmpty")
        self._empty_label.setStyleSheet(f"font-size: {FONT_SIZE_BODY}px; color: #9E9E9E;")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(False)
        content_layout.addWidget(self._empty_label)

        # Inline rename editor (floating, hidden by default)
        self._rename_editor = QLineEdit(self._list_widget.viewport())
        self._rename_editor.setObjectName("MyPresetsRenameEditor")
        self._rename_editor.setVisible(False)
        self._rename_editor.editingFinished.connect(self._on_rename_finished)

        outer_layout.addWidget(content, alignment=Qt.AlignmentFlag.AlignHCenter)

    # ------------------------------------------------------------------
    # List population
    # ------------------------------------------------------------------

    def _populate_list(self, filter_text: str = "") -> None:
        """Rebuild the list widget from internal presets data.

        Args:
            filter_text: Optional text to filter presets by name (case-insensitive).
        """
        self._list_widget.clear()
        self._cancel_rename()

        filter_lower = filter_text.lower()
        visible_presets = [
            p for p in self._presets if filter_lower in p.name.lower()
        ] if filter_lower else self._presets

        if not visible_presets:
            self._empty_label.setVisible(True)
            self._list_widget.setVisible(False)
            return

        self._empty_label.setVisible(False)
        self._list_widget.setVisible(True)

        for profile in visible_presets:
            active_bands, total_bands = _count_bands(profile)
            item_widget = _PresetItemWidget(
                name=profile.name,
                channel_mode=profile.channel_mode,
                active_bands=active_bands,
                total_bands=total_bands,
            )
            item = QListWidgetItem(self._list_widget)
            item.setSizeHint(item_widget.sizeHint())
            item.setData(Qt.ItemDataRole.UserRole, profile)
            self._list_widget.setItemWidget(item, item_widget)

    # ------------------------------------------------------------------
    # Search/filter
    # ------------------------------------------------------------------

    def _update_search_visibility(self) -> None:
        """Show or hide the search field based on preset count."""
        self._search_field.setVisible(len(self._presets) > _SEARCH_THRESHOLD)

    def _on_search_text_changed(self, text: str) -> None:
        """Filter the list as the user types."""
        self._populate_list(filter_text=text)

    # ------------------------------------------------------------------
    # Inline rename
    # ------------------------------------------------------------------

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        """Start inline rename on double-click."""
        self._start_rename(item)

    def _start_rename(self, item: QListWidgetItem) -> None:
        """Show inline editor over the item for renaming."""
        self._rename_item = item
        profile: Profile = item.data(Qt.ItemDataRole.UserRole)

        # Position the editor over the item
        rect = self._list_widget.visualItemRect(item)
        self._rename_editor.setGeometry(rect)
        self._rename_editor.setText(profile.name)
        self._rename_editor.selectAll()
        self._rename_editor.setVisible(True)
        self._rename_editor.setFocus()

    def _on_rename_finished(self) -> None:
        """Complete the inline rename operation."""
        if self._rename_item is None:
            self._rename_editor.setVisible(False)
            return

        profile: Profile = self._rename_item.data(Qt.ItemDataRole.UserRole)
        new_name = self._rename_editor.text().strip()
        old_name = profile.name

        self._rename_editor.setVisible(False)
        self._rename_item = None

        if new_name and new_name != old_name:
            self.rename_requested.emit(old_name, new_name)

    def _cancel_rename(self) -> None:
        """Cancel any in-progress rename operation."""
        self._rename_editor.setVisible(False)
        self._rename_item = None

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _show_context_menu(self, position: object) -> None:
        """Show right-click context menu for the item at position."""
        item = self._list_widget.itemAt(position)  # type: ignore[arg-type]
        if item is None:
            return

        profile: Profile = item.data(Qt.ItemDataRole.UserRole)

        menu = QMenu(self)
        menu.setObjectName("MyPresetsContextMenu")

        load_action = QAction("Load", menu)
        load_action.triggered.connect(lambda: self.load_requested.emit(profile))
        menu.addAction(load_action)

        menu.addSeparator()

        rename_action = QAction("Rename", menu)
        rename_action.triggered.connect(lambda: self._start_rename(item))
        menu.addAction(rename_action)

        duplicate_action = QAction("Duplicate", menu)
        duplicate_action.triggered.connect(
            lambda: self.duplicate_requested.emit(profile.name)
        )
        menu.addAction(duplicate_action)

        menu.addSeparator()

        delete_action = QAction("Delete", menu)
        delete_action.triggered.connect(lambda: self.delete_requested.emit(profile.name))
        menu.addAction(delete_action)

        menu.exec(self._list_widget.viewport().mapToGlobal(position))  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Event overrides
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Cancel rename on click outside the editor."""
        if self._rename_editor.isVisible():
            self._cancel_rename()
        super().mousePressEvent(event)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _channel_mode_display(mode: str) -> str:
    """Convert channel mode value to display badge text.

    Args:
        mode: One of "stereo", "left", "right".

    Returns:
        Display string: "Stereo", "L", or "R".
    """
    mapping = {
        "stereo": "Stereo",
        "left": "L",
        "right": "R",
    }
    return mapping.get(mode, mode.capitalize())


def _count_bands(profile: Profile) -> tuple[int, int]:
    """Count active and total bands for a profile.

    A band is considered active if its gain is non-zero.

    Args:
        profile: The preset profile.

    Returns:
        Tuple of (active_band_count, total_band_count).
    """
    if profile.channel_mode == "stereo":
        filters = profile.filters or []
    else:
        # For L/R mode, combine both channels for display
        filters_l = profile.filters_l or []
        filters_r = profile.filters_r or []
        filters = filters_l + filters_r

    total = len(filters)
    active = sum(1 for f in filters if f.gain != 0.0)
    return active, total
