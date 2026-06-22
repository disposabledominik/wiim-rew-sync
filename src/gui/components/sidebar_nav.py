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
    ACCENT_COLOR,
    LIST_ITEM_HEIGHT,
    SIDEBAR_COLLAPSED,
    SIDEBAR_EXPANDED,
    SPACING_MD,
    SPACING_SM,
)


class _NavItem(QPushButton):
    """Single navigation item: icon area + text label."""

    def __init__(
        self, key: str, label: str, icon_char: str = "", parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.key = key
        self._label_text = label
        self._icon_char = icon_char
        self._active = False

        self.setFixedHeight(LIST_ITEM_HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setCheckable(True)
        self.setText(f"{icon_char}  {label}" if icon_char else label)
        self.setToolTip(label)
        self._apply_style()

    def set_active(self, active: bool) -> None:
        """Mark this item as the active navigation target."""
        self._active = active
        self.setChecked(active)
        self._apply_style()

    def set_collapsed(self, collapsed: bool) -> None:
        """Toggle between icon-only and icon+label display."""
        if collapsed:
            self.setText(self._icon_char)
            self.setToolTip(self._label_text)
        else:
            text = f"{self._icon_char}  {self._label_text}" if self._icon_char else self._label_text
            self.setText(text)
            self.setToolTip("")

    def _apply_style(self) -> None:
        """Apply styling based on active state."""
        if self._active:
            self.setStyleSheet(
                f"QPushButton {{"
                f"  background-color: {ACCENT_COLOR}1A;"
                f"  border-left: 3px solid {ACCENT_COLOR};"
                f"  text-align: left;"
                f"  padding-left: {SPACING_SM}px;"
                f"  font-weight: 600;"
                f"}}"
            )
        else:
            self.setStyleSheet(
                f"QPushButton {{"
                f"  background-color: transparent;"
                f"  border: none;"
                f"  text-align: left;"
                f"  padding-left: {SPACING_SM + 3}px;"
                f"}}"
                f"QPushButton:hover {{"
                f"  background-color: rgba(0, 0, 0, 0.05);"
                f"}}"
            )


class SidebarNav(QWidget):
    """Collapsible icon+label navigation rail.

    Provides persistent navigation between the wizard home view and
    secondary views (Presets on Device, My Saved Presets, Settings, Help).
    Supports collapsed (48px, icons only with tooltips) and expanded
    (200px, icons + labels) modes.
    """

    navigation_requested = Signal(str)
    """Emitted when a navigation item is clicked. Payload is the view key."""

    collapse_toggled = Signal(bool)
    """Emitted when the collapse state changes. True means collapsed (icon-only)."""

    _NAV_ITEMS: tuple[tuple[str, str, str], ...] = (
        ("home", "Back", "\u2190"),
        ("presets_device", "Presets on Device", "\U0001F3B6"),
        ("my_presets", "My Saved Presets", "\U0001F4BE"),
        ("rew_api", "Pull from REW", "\U0001F4C8"),
        ("settings", "Settings", "\u2699"),
        ("help", "Help", "\u2753"),
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
        self._device_label.setFlat(True)
        self._device_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._device_label.setStyleSheet(
            "QPushButton { text-align: left; font-weight: 600; border: none; }"
            "QPushButton:hover { text-decoration: underline; }"
        )
        self._device_label.setToolTip("Go to Connect step")
        self._device_label.clicked.connect(self._on_device_header_clicked)
        header_layout.addWidget(self._device_label)

        layout.addWidget(self._header_widget)

        # Navigation items
        for key, label, icon in self._NAV_ITEMS:
            item = _NavItem(key, label, icon, self)
            item.clicked.connect(self._on_item_clicked)
            self._nav_buttons[key] = item
            layout.addWidget(item)

        # Set initial active state
        self._nav_buttons["home"].set_active(True)

        # Spacer pushes toggle to bottom
        layout.addStretch(1)

        # Collapse/expand toggle button
        self._toggle_btn = QPushButton("\u2630")  # Hamburger icon
        self._toggle_btn.setFixedHeight(LIST_ITEM_HEIGHT)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setToolTip("Collapse sidebar")
        self._toggle_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; font-size: 18px; }"
            "QPushButton:hover { background-color: rgba(0, 0, 0, 0.05); }"
        )
        self._toggle_btn.clicked.connect(self._on_toggle_clicked)
        layout.addWidget(self._toggle_btn)

    def set_device_info(self, name: str, connected: bool) -> None:
        """Update header area with connected device name.

        Args:
            name: Device display name.
            connected: Whether the device is currently connected.
        """
        if connected and name:
            self._device_label.setText(name)
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

        # Update active state
        if key != self._active_key:
            if self._active_key in self._nav_buttons:
                self._nav_buttons[self._active_key].set_active(False)
            self._active_key = key
            sender.set_active(True)

        self.navigation_requested.emit(key)

    def _on_toggle_clicked(self) -> None:
        """Handle collapse/expand toggle click."""
        self.set_collapsed(not self._collapsed)
        self.collapse_toggled.emit(self._collapsed)

    def _on_device_header_clicked(self) -> None:
        """Navigate to Connect step when device name is clicked."""
        self.navigation_requested.emit("connect")
        # Update active state to home (connect = first wizard step)
        if self._active_key != "home":
            if self._active_key in self._nav_buttons:
                self._nav_buttons[self._active_key].set_active(False)
            self._active_key = "home"
            self._nav_buttons["home"].set_active(True)
