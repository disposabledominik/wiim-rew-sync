"""Collapsible navigation rail for the main window sidebar.

Provides a vertical icon+label navigation panel that supports
collapsed (icon-only, 48px) and expanded (icon+label, 200px) modes.
Emits signals when the user selects a navigation target or toggles
collapse state.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.gui.constants import (
    LIST_ITEM_HEIGHT,
    SIDEBAR_COLLAPSED,
    SIDEBAR_EXPANDED,
    SPACING_MD,
    SPACING_SM,
)
from src.gui.style_utils import set_qss_property


class _NavItem(QPushButton):
    """Single navigation item: icon area + text label."""

    def __init__(
        self,
        key: str,
        label: str,
        icon_char: str = "",
        description: str = "",
        parent: QWidget | None = None,
        checkable: bool = True,
    ) -> None:
        super().__init__(parent)
        self.key = key
        self._label_text = label
        self._icon_char = icon_char
        self._description = description or label
        self._active = False

        self.setFixedHeight(LIST_ITEM_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(checkable)
        self.setText(f"{icon_char}  {label}" if icon_char else label)
        self.setToolTip(self._description)
        self.setObjectName("SidebarNavItem")
        self._apply_style()

    def set_active(self, active: bool) -> None:
        """Mark this item as the active navigation target."""
        self._active = active
        self.setChecked(active)
        self._apply_style()

    def set_collapsed(self, collapsed: bool) -> None:
        """Toggle between icon-only and icon+label display.

        The tooltip always shows the descriptive explanation (not just the
        label) regardless of collapsed state, since the label alone can be
        ambiguous (e.g. "Presets on Device" doesn't say *which* actions --
        browse, export, copy -- are available there).
        """
        if collapsed:
            self.setText(self._icon_char)
        else:
            text = f"{self._icon_char}  {self._label_text}" if self._icon_char else self._label_text
            self.setText(text)
        self.setToolTip(self._description)

    def _apply_style(self) -> None:
        """Apply styling based on active state."""
        set_qss_property(self, "class", "navItemActive" if self._active else "navItem")


class SidebarNav(QWidget):
    """Collapsible icon+label navigation rail.

    Provides persistent navigation between the wizard home view and
    secondary views (Presets on Device, My Saved Presets, Settings, Help).
    Supports collapsed (48px, icons only with tooltips) and expanded
    (200px, icons + labels) modes.
    """

    navigation_requested = Signal(str)
    """Emitted when a navigation item is clicked. Payload is the view key."""

    _NAV_ITEMS: tuple[tuple[str, str, str, str], ...] = (
        (
            "home",
            "Setup Wizard",
            "\U0001F9D9",
            "Return to your current step in the setup wizard",
        ),
        (
            "presets_device",
            "Presets on Device",
            "\U0001F3B6",
            "Browse, export, or copy PEQ and RoomFit presets saved on the connected device",
        ),
        (
            "my_presets",
            "My Saved Presets",
            "\U0001F4BE",
            "Browse and load presets saved locally on this computer",
        ),
        (
            "settings",
            "Settings",
            "\u2699",
            "App preferences: discovery, theme, backup paths, and connection options",
        ),
        (
            "help",
            "Help",
            "\u2753",
            "Open the user guide for this app",
        ),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._collapsed = False
        self._nav_buttons: dict[str, _NavItem] = {}
        self._active_key: str = "home"

        self.setFixedWidth(SIDEBAR_EXPANDED)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the sidebar layout: header, nav items, collapse toggle."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, SPACING_MD, 0, SPACING_SM)
        layout.setSpacing(0)

        # Header area: device name
        self._header_widget = QWidget()
        header_layout = QHBoxLayout(self._header_widget)
        header_layout.setContentsMargins(SPACING_SM, SPACING_SM, SPACING_SM, SPACING_MD)

        self._device_label = QPushButton("No device")
        self._device_label.setObjectName("SidebarDeviceLabel")
        self._device_label.setFlat(True)
        self._device_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._device_label.setToolTip("Device details")
        self._device_label.clicked.connect(self._on_device_header_clicked)
        header_layout.addWidget(self._device_label)

        layout.addWidget(self._header_widget)

        # Navigation items. "help" opens a separate, non-modal window rather
        # than replacing the current page, so it is not checkable/highlighted
        # — leaving it checked would misleadingly suggest it's the active view
        # even after the Help window is closed.
        for key, label, icon, description in self._NAV_ITEMS:
            item = _NavItem(
                key, label, icon, description, parent=self, checkable=key != "help"
            )
            item.clicked.connect(self._on_item_clicked)
            self._nav_buttons[key] = item
            layout.addWidget(item)

        # Set initial active state
        self._nav_buttons["home"].set_active(True)

        # Spacer pushes toggle to bottom
        layout.addStretch(1)

        # Collapse/expand toggle button
        self._toggle_btn = QPushButton("\u2630")  # Hamburger icon
        self._toggle_btn.setObjectName("SidebarToggleButton")
        self._toggle_btn.setFixedHeight(LIST_ITEM_HEIGHT)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setToolTip("Collapse sidebar")
        self._toggle_btn.clicked.connect(self._on_toggle_clicked)
        layout.addWidget(self._toggle_btn)

    def set_device_info(
        self, name: str, connected: bool, capability_warning: str = ""
    ) -> None:
        """Update header area with connected device name.

        Args:
            name: Device display name.
            connected: Whether the device is currently connected.
            capability_warning: When non-empty, appends a warning glyph to
                the label -- e.g. capabilities came from a capability-file
                override or generic defaults rather than live device
                probing. The warning text itself lives in the device-info
                popover (see ``_on_device_header_clicked``), so the
                tooltip stays a stable affordance hint.
        """
        if connected and name:
            label_text = f"{name}  ⚠" if capability_warning else name
            self._device_label.setText(label_text)
            self._device_label.setEnabled(True)
        else:
            self._device_label.setText("No device")
            self._device_label.setEnabled(False)

    def set_collapsed(self, collapsed: bool) -> None:
        """Toggle between full labels and icon-only mode.

        Args:
            collapsed: True for icon-only (48px), False for full (200px).
        """
        if self._collapsed == collapsed:
            return

        self._collapsed = collapsed

        if collapsed:
            self.setFixedWidth(SIDEBAR_COLLAPSED)
            self._toggle_btn.setText("\u276F")  # Right chevron
            self._toggle_btn.setToolTip("Expand sidebar")
            self._device_label.setVisible(False)
        else:
            self.setFixedWidth(SIDEBAR_EXPANDED)
            self._toggle_btn.setText("\u2630")  # Hamburger
            self._toggle_btn.setToolTip("Collapse sidebar")
            self._device_label.setVisible(True)

        for item in self._nav_buttons.values():
            item.set_collapsed(collapsed)

    @property
    def collapsed(self) -> bool:
        """Whether the sidebar is currently in collapsed (icon-only) mode."""
        return self._collapsed

    def _on_item_clicked(self) -> None:
        """Handle navigation item click."""
        sender = self.sender()
        if not isinstance(sender, _NavItem):
            return

        key = sender.key

        # "help" doesn't replace the current page (it opens a separate
        # window), so it never becomes the active highlight — whichever
        # item was already active keeps reflecting the visible page.
        if key != "help" and key != self._active_key:
            if self._active_key in self._nav_buttons:
                self._nav_buttons[self._active_key].set_active(False)
            self._active_key = key
            sender.set_active(True)

        self.navigation_requested.emit(key)

    @property
    def active_key(self) -> str:
        """The navigation key currently highlighted as active."""
        return self._active_key

    def set_active_key(self, key: str) -> None:
        """Sync the active highlight to match the page actually on screen.

        Use this when MainWindow navigates away from a sidebar destination
        through a path other than a sidebar click — e.g. a view's own Back
        button — so the highlighted item never disagrees with what's shown.
        """
        if key == self._active_key or key not in self._nav_buttons:
            return
        if self._active_key in self._nav_buttons:
            self._nav_buttons[self._active_key].set_active(False)
        self._active_key = key
        self._nav_buttons[key].set_active(True)

    def _on_toggle_clicked(self) -> None:
        """Handle collapse/expand toggle click."""
        self.set_collapsed(not self._collapsed)

    def _on_device_header_clicked(self) -> None:
        """Request the read-only device-info popover.

        The header used to navigate to the Connect step, but that
        duplicated the Connect pill while looking like a status readout;
        a details popover gives the capability warning a real home instead
        of hijacking the tooltip (PR #19 review, D2). No page change, so
        the active highlight is left alone.
        """
        self.navigation_requested.emit("device_info")
