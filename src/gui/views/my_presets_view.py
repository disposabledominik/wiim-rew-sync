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

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QAction, QMouseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QSizePolicy,
    QWidget,
)

from src.gui.components.action_button import make_action_button
from src.gui.components.page_layout import build_centered_content, make_page_title
from src.gui.constants import (
    LIST_ITEM_HEIGHT,
    SPACING_MD,
    SPACING_SM,
    SPACING_XS,
)
from src.models.channel_mode import ChannelMode
from src.models.profile import Profile
from src.utils.device_name import sanitize_device_name

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
        channel_mode: str | ChannelMode,
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
        self._name_label.setProperty("class", "subheading")
        self._name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._name_label)

        # Channel mode badge
        badge_text = _channel_mode_display(channel_mode)
        self._mode_badge = QLabel(badge_text, self)
        self._mode_badge.setObjectName("PresetItemBadge")
        self._mode_badge.setProperty("class", "badge")
        self._mode_badge.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._mode_badge)

        # Active band count
        band_text = f"{active_bands}/{total_bands} bands"
        self._band_label = QLabel(band_text, self)
        self._band_label.setObjectName("PresetItemBands")
        self._band_label.setProperty("class", "caption")
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
    copy_to_device_requested = Signal(object)  # Profile

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
        content_layout, content = build_centered_content(self)
        content_layout.setSpacing(SPACING_MD)

        # Title
        title = make_page_title("My Saved Presets", content, object_name="MyPresetsTitle")
        content_layout.addWidget(title)

        # Search/filter field (hidden until > 10 items)
        self._search_field = QLineEdit(content)
        self._search_field.setObjectName("MyPresetsSearch")
        self._search_field.setPlaceholderText("Search presets...")
        self._search_field.setClearButtonEnabled(True)
        self._search_field.setVisible(False)
        self._search_field.textChanged.connect(self._on_search_text_changed)
        content_layout.addWidget(self._search_field)

        # Preset list (stretch factor 1 so it claims the page's spare
        # vertical space, matching every other wizard/view's convention of
        # letting its main content grow while the action row stays pinned
        # below it at page bottom -- previously this toolbar sat above the
        # list, the only view in the app whose actions weren't
        # bottom-anchored, smoke #227).
        self._list_widget = QListWidget(content)
        self._list_widget.setObjectName("MyPresetsList")
        self._list_widget.setProperty("class", "selectableList")
        self._list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list_widget.customContextMenuRequested.connect(self._show_context_menu)
        self._list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._list_widget.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self._list_widget.setSpacing(2)
        self._list_widget.currentItemChanged.connect(self._on_selection_changed)
        content_layout.addWidget(self._list_widget, 1)

        # Empty state label
        self._empty_label = QLabel("No saved presets yet.", content)
        self._empty_label.setObjectName("MyPresetsEmpty")
        self._empty_label.setProperty("class", "secondary")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(False)
        content_layout.addWidget(self._empty_label)

        # Action toolbar (visible when an item is selected), bottom-anchored
        # below the list. Order: Load (primary recall action) first, then
        # Copy to Another Device right after it -- grouping the two
        # "send this preset somewhere" actions together -- then the local
        # Rename/Duplicate edits, with the destructive Delete last.
        self._toolbar = QWidget(content)
        toolbar_layout = QHBoxLayout(self._toolbar)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(SPACING_SM)

        self._load_btn = make_action_button(
            "Load into Editor",
            object_name="btn_load_into_editor",
            style_class="secondary",
            tooltip="Load preset into Review for push/export",
            parent=self._toolbar,
        )
        self._load_btn.clicked.connect(self._on_load_clicked)
        toolbar_layout.addWidget(self._load_btn)

        self._copy_btn = make_action_button(
            "Copy to Another Device",
            object_name="btn_copy_device_local",
            style_class="secondary",
            parent=self._toolbar,
        )
        self._copy_btn.clicked.connect(self._on_copy_clicked)
        toolbar_layout.addWidget(self._copy_btn)

        self._rename_btn = make_action_button(
            "Rename", object_name="btn_rename_preset", style_class="secondary",
            parent=self._toolbar,
        )
        self._rename_btn.clicked.connect(self._on_rename_clicked)
        toolbar_layout.addWidget(self._rename_btn)

        self._duplicate_btn = make_action_button(
            "Duplicate", object_name="btn_duplicate_preset", style_class="secondary",
            parent=self._toolbar,
        )
        self._duplicate_btn.clicked.connect(self._on_duplicate_clicked)
        toolbar_layout.addWidget(self._duplicate_btn)

        self._delete_btn = make_action_button(
            "Delete", object_name="btn_delete_preset_local", style_class="danger",
            parent=self._toolbar,
        )
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        toolbar_layout.addWidget(self._delete_btn)

        toolbar_layout.addStretch()
        self._toolbar.setVisible(True)
        self._load_btn.setEnabled(False)
        self._rename_btn.setEnabled(False)
        self._duplicate_btn.setEnabled(False)
        self._copy_btn.setEnabled(False)
        self._delete_btn.setEnabled(False)
        content_layout.addWidget(self._toolbar)

        # Inline rename editor (floating, hidden by default)
        self._rename_editor = QLineEdit(self._list_widget.viewport())
        self._rename_editor.setObjectName("MyPresetsRenameEditor")
        self._rename_editor.setVisible(False)
        self._rename_editor.editingFinished.connect(self._on_rename_finished)

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
            item.setSizeHint(QSize(0, LIST_ITEM_HEIGHT))
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

        # Completely remove the item widget to prevent any background text showing.
        # Qt may repaint item widgets even when hidden; removing is the only reliable fix.
        item_widget = self._list_widget.itemWidget(item)
        if item_widget:
            self._list_widget.removeItemWidget(item)
            item_widget.deleteLater()

        # Position the editor over the item
        rect = self._list_widget.visualItemRect(item)
        self._rename_editor.setGeometry(rect)
        self._rename_editor.setText(profile.name)
        self._rename_editor.selectAll()
        self._rename_editor.setVisible(True)
        self._rename_editor.setFocus()
        self._rename_editor.raise_()

    def _on_rename_finished(self) -> None:
        """Complete the inline rename operation."""
        if self._rename_item is None:
            self._rename_editor.setVisible(False)
            return

        profile: Profile = self._rename_item.data(Qt.ItemDataRole.UserRole)
        new_name = sanitize_device_name(self._rename_editor.text()).strip()
        old_name = profile.name

        self._rename_editor.setVisible(False)

        # Rebuild the item widget (was removed during rename)
        self._rebuild_item_widget(self._rename_item, profile)
        self._rename_item = None

        if new_name and new_name != old_name:
            self.rename_requested.emit(old_name, new_name)

    def _cancel_rename(self) -> None:
        """Cancel any in-progress rename operation."""
        if self._rename_item is not None:
            profile: Profile = self._rename_item.data(Qt.ItemDataRole.UserRole)
            self._rebuild_item_widget(self._rename_item, profile)
        self._rename_editor.setVisible(False)
        self._rename_item = None

    def _rebuild_item_widget(self, item: QListWidgetItem, profile: Profile) -> None:
        """Recreate the item widget after inline editing is complete."""
        active_bands, total_bands = _count_bands(profile)
        new_widget = _PresetItemWidget(
            name=profile.name,
            channel_mode=profile.channel_mode,
            active_bands=active_bands,
            total_bands=total_bands,
        )
        self._list_widget.setItemWidget(item, new_widget)

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _show_context_menu(self, position: QPoint) -> None:
        """Show right-click context menu for the item at position."""
        item = self._list_widget.itemAt(position)
        if item is None:
            return

        menu = self._build_context_menu(item)
        menu.exec(self._list_widget.viewport().mapToGlobal(position))

    def _build_context_menu(self, item: QListWidgetItem) -> QMenu:
        """Build (without showing) the context menu for *item*.

        Split from _show_context_menu() so the menu's action set/order can
        be tested directly without exercising QMenu.exec()'s real modal
        popup (which isn't safely mockable in headless test environments).

        Action order matches the toolbar's: Load, Copy to Another Device,
        Rename, Duplicate, Delete.
        """
        profile: Profile = item.data(Qt.ItemDataRole.UserRole)

        menu = QMenu(self)
        menu.setObjectName("MyPresetsContextMenu")

        load_action = QAction("Load", menu)
        load_action.triggered.connect(lambda: self.load_requested.emit(profile))
        menu.addAction(load_action)

        copy_action = QAction("Copy to Another Device", menu)
        copy_action.triggered.connect(
            lambda: self.copy_to_device_requested.emit(profile)
        )
        menu.addAction(copy_action)

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

        return menu

    # ------------------------------------------------------------------
    # Toolbar button handlers
    # ------------------------------------------------------------------

    def _on_selection_changed(self, current: QListWidgetItem | None, _prev: object) -> None:
        """Enable/disable toolbar buttons based on selection state."""
        has_selection = current is not None
        self._load_btn.setEnabled(has_selection)
        self._rename_btn.setEnabled(has_selection)
        self._duplicate_btn.setEnabled(has_selection)
        self._copy_btn.setEnabled(has_selection)
        self._delete_btn.setEnabled(has_selection)

    def _get_selected_profile(self) -> Profile | None:
        """Return the currently selected Profile, or None."""
        item = self._list_widget.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)  # type: ignore[no-any-return]

    def _on_load_clicked(self) -> None:
        """Handle Load button click."""
        profile = self._get_selected_profile()
        if profile:
            self.load_requested.emit(profile)

    def _on_rename_clicked(self) -> None:
        """Handle Rename button click — start inline rename."""
        item = self._list_widget.currentItem()
        if item:
            self._start_rename(item)

    def _on_duplicate_clicked(self) -> None:
        """Handle Duplicate button click."""
        profile = self._get_selected_profile()
        if profile:
            self.duplicate_requested.emit(profile.name)

    def _on_delete_clicked(self) -> None:
        """Handle Delete button click."""
        profile = self._get_selected_profile()
        if profile:
            self.delete_requested.emit(profile.name)

    def _on_copy_clicked(self) -> None:
        """Handle Copy to Another Device button click."""
        profile = self._get_selected_profile()
        if profile:
            self.copy_to_device_requested.emit(profile)

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


def _channel_mode_display(mode: str | ChannelMode) -> str:
    """Convert channel mode value to display badge text.

    Args:
        mode: ChannelMode enum or legacy string ("stereo", "left", "right").

    Returns:
        Display string: "Stereo" or "L/R".
    """
    if isinstance(mode, ChannelMode):
        return mode.display_value
    if mode in ("left", "right"):
        return "L/R"
    return "Stereo"


def _count_bands(profile: Profile) -> tuple[int, int]:
    """Count active and total bands for a profile.

    A band is considered active if its gain is non-zero.

    For L/R profiles, returns per-channel counts (each channel separately).

    Args:
        profile: The preset profile.

    Returns:
        Tuple of (active_band_count, total_band_count).
    """
    if profile.channel_mode == ChannelMode.STEREO:
        filters = profile.filters or []
    else:
        # For L/R mode, show per-channel count (use left channel as representative)
        filters = profile.filters_l or []

    total = len(filters)
    active = sum(1 for f in filters if f.gain_db != 0.0)
    return active, total
