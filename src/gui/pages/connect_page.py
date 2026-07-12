"""ConnectPage — device discovery and selection wizard step.

Displays discovered WiiM devices as DeviceCard widgets, handles scanning state,
empty state with troubleshooting guidance, and auto-selects a single device.

Requirements referenced: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.gui.components.action_button import make_action_button
from src.gui.components.device_card import DeviceCard
from src.gui.components.page_layout import (
    build_centered_content,
    center_column,
    make_page_title,
)
from src.gui.constants import (
    SPACING_LG,
    SPACING_MD,
)


class ConnectPage(QWidget):
    """Device discovery and selection page.

    Displays discovered WiiM devices as clickable cards. Supports three visual
    states: scanning (spinner + message), device list, and empty/timeout
    (retry button + troubleshooting guidance).

    The page does NOT call the network directly — it exposes signals that the
    WizardController connects to AsyncBridge.

    Signals:
        device_selected: Emitted with the device IP when a card is clicked
            or when a single device is auto-selected.
        refresh_requested: Emitted when the user clicks Retry or Refresh.
    """

    device_selected = Signal(str)
    refresh_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ConnectPage")
        # (card, ip, sort_key) triples, kept in the same order as the cards
        # appear in self._devices_layout so list index == layout index.
        self._device_cards: list[tuple[DeviceCard, str, str]] = []
        self._setup_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_scanning(self, active: bool) -> None:
        """Toggle the scanning state.

        Args:
            active: If True, show the scanning animation and message.
                If False, hide the scanning state (devices or empty state
                should be shown via set_devices).
        """
        self._scanning_widget.setVisible(active)
        self._rescan_btn.setEnabled(not active)
        if active:
            self._devices_scroll.setVisible(False)
            self._empty_widget.setVisible(False)

    def set_devices(self, devices: list[dict[str, Any]]) -> None:
        """Populate the page with discovered device cards (replaces all current cards).

        Each dict should have keys: name, model, ip.

        If exactly one device is found, it is auto-selected and
        device_selected is emitted immediately (Req 2.4).

        Args:
            devices: List of device info dicts.
        """
        self._scanning_widget.setVisible(False)
        self._clear_cards()

        if not devices:
            self._devices_scroll.setVisible(False)
            self._empty_widget.setVisible(True)
            return

        self._empty_widget.setVisible(False)
        self._devices_scroll.setVisible(True)

        for device in sorted(devices, key=self._device_sort_key):
            self._add_device_card(device)

        # Auto-select single device (Req 2.4)
        if len(devices) == 1:
            ip = devices[0].get("ip", "")
            if ip:
                self.device_selected.emit(ip)

    def update_devices(self, devices: list[dict[str, Any]]) -> None:
        """Progressively update device cards (add new ones, keep existing).

        Called during progressive discovery — adds cards for newly-discovered
        devices without clearing existing ones. Hides scanning state once at
        least one device is shown.

        Args:
            devices: Cumulative list of all devices found so far.
        """
        # Build set of IPs already shown
        shown_ips = {ip for _card, ip, _sort_key in self._device_cards}

        new_devices = [d for d in devices if d.get("ip", "") not in shown_ips]
        if not new_devices:
            return

        # First progressive update — switch from scanning to device list
        if not self._device_cards:
            self._scanning_widget.setVisible(False)
            self._empty_widget.setVisible(False)
            self._devices_scroll.setVisible(True)

        for device in new_devices:
            insert_index = self._sorted_insert_index(self._device_sort_key(device))
            self._add_device_card(device, insert_index=insert_index)

    def clear(self) -> None:
        """Reset the page to its initial scanning state."""
        self._clear_cards()
        self._empty_widget.setVisible(False)
        self._devices_scroll.setVisible(False)
        self._scanning_widget.setVisible(True)

    def showEvent(self, event) -> None:  # noqa: ANN001
        """Auto-trigger discovery when the page becomes visible."""
        super().showEvent(event)
        # Only auto-discover if no devices are currently shown (avoid re-scanning on back-nav)
        if not self._device_cards:
            self.refresh_requested.emit()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Build the page layout with scanning, devices, and empty states."""
        content_layout, content_wrapper = build_centered_content(self)

        # Page title + manual rescan button
        title = make_page_title(
            "Connect to Device", content_wrapper, object_name="ConnectPageTitle"
        )
        self._rescan_btn = make_action_button(
            "⟳", object_name="ConnectPageRescanButton", style_class="ghost",
            tooltip="Rescan for devices", parent=content_wrapper,
        )
        self._rescan_btn.setFixedSize(32, 32)
        self._rescan_btn.clicked.connect(self.refresh_requested.emit)

        title_row = QHBoxLayout()
        title_row.setContentsMargins(0, 0, 0, 0)
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(self._rescan_btn)
        content_layout.addLayout(title_row)

        # --- Scanning state ---
        self._scanning_widget = self._build_scanning_widget(content_wrapper)
        content_layout.addWidget(self._scanning_widget)

        # --- Device list (scrollable) ---
        self._devices_scroll = QScrollArea(content_wrapper)
        self._devices_scroll.setObjectName("ConnectPageDeviceScroll")
        self._devices_scroll.setWidgetResizable(True)
        self._devices_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._devices_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._devices_scroll.setVisible(False)

        self._devices_container = QWidget()
        self._devices_layout = QVBoxLayout(self._devices_container)
        self._devices_layout.setContentsMargins(0, 0, 0, 0)
        self._devices_layout.setSpacing(SPACING_MD)
        self._devices_layout.addStretch()
        self._devices_scroll.setWidget(self._devices_container)

        content_layout.addWidget(self._devices_scroll, 1)

        # --- Empty state ---
        self._empty_widget = self._build_empty_widget(content_wrapper)
        self._empty_widget.setVisible(False)
        content_layout.addWidget(self._empty_widget)

        content_layout.addStretch()

    def _build_scanning_widget(self, parent: QWidget) -> QWidget:
        """Build the scanning animation state widget."""
        widget = QWidget(parent)
        widget.setMinimumHeight(140)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, SPACING_LG, 0, SPACING_LG)
        layout.setSpacing(SPACING_MD)

        # Scanning indicator (text-based, can be enhanced with animation later)
        spinner_label = QLabel("\u25CF \u25CF \u25CF", widget)
        spinner_label.setObjectName("ConnectPageSpinner")
        spinner_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(spinner_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Scanning message (Req 2.2)
        message = QLabel("Searching for WiiM devices on your network...", widget)
        message.setObjectName("ConnectPageScanningMessage")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setWordWrap(True)
        layout.addWidget(message)

        center_column(layout)
        return widget

    def _build_empty_widget(self, parent: QWidget) -> QWidget:
        """Build the empty/no-devices-found state widget (Req 2.6)."""
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, SPACING_LG, 0, SPACING_LG)
        layout.setSpacing(SPACING_MD)

        # No devices heading
        heading = QLabel("No devices found", widget)
        heading.setObjectName("ConnectPageEmptyHeading")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.setProperty("class", "heading")
        layout.addWidget(heading, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Common causes explanation
        causes_label = QLabel(
            "Common causes:\n"
            "\u2022 Your WiiM device is powered off or not connected to WiFi\n"
            "\u2022 Your computer and WiiM device are on different subnets\n"
            "\u2022 A firewall is blocking mDNS discovery (port 5353) -- on "
            "Windows, check that your network is set to \"Private\", not "
            "\"Public\"",
            widget,
        )
        causes_label.setObjectName("ConnectPageEmptyCauses")
        causes_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        causes_label.setProperty("class", "secondary")
        causes_label.setWordWrap(True)
        layout.addWidget(causes_label)

        # Retry button
        retry_button = make_action_button(
            "Retry", object_name="ConnectPageRetryButton", style_class="secondary",
            parent=widget,
        )
        retry_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        retry_button.setMinimumWidth(120)
        retry_button.clicked.connect(self._on_retry_clicked)
        layout.addWidget(retry_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Troubleshooting link
        troubleshoot_label = QLabel(
            '<a href="#troubleshoot">Troubleshooting guide</a>',
            widget,
        )
        troubleshoot_label.setObjectName("ConnectPageTroubleshootLink")
        troubleshoot_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        troubleshoot_label.setProperty("class", "caption")
        troubleshoot_label.setOpenExternalLinks(False)
        layout.addWidget(troubleshoot_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        center_column(layout)
        return widget

    def _clear_cards(self) -> None:
        """Remove all device cards from the layout."""
        for card, _ip, _sort_key in self._device_cards:
            self._devices_layout.removeWidget(card)
            card.deleteLater()
        self._device_cards.clear()

    @staticmethod
    def _device_display_name(device: dict[str, Any]) -> str:
        """Display name for a device, falling back for a missing or blank name.

        `.get("name", "Unknown Device")` alone only covers a missing key --
        a device dict with a present-but-empty "name" (real for some
        mDNS/subnet-scan responses) needs the same fallback so the sort key
        and the on-card label never disagree about what an unnamed device
        is called.
        """
        return device.get("name") or "Unknown Device"

    @classmethod
    def _device_sort_key(cls, device: dict[str, Any]) -> str:
        """Sort key for alphabetical ordering by the device's display name."""
        return cls._device_display_name(device).casefold()

    def _sorted_insert_index(self, sort_key: str) -> int:
        """Find the layout/list index to insert a card with *sort_key* at,
        keeping self._device_cards (and the mirrored layout order) sorted.
        """
        for index, (_card, _ip, existing_key) in enumerate(self._device_cards):
            if existing_key > sort_key:
                return index
        return len(self._device_cards)

    def _add_device_card(
        self, device: dict[str, Any], insert_index: int | None = None
    ) -> None:
        """Create and add a single device card to the layout.

        Args:
            device: Device info dict.
            insert_index: Position among the device cards to insert at
                (0-based, matching self._device_cards' order). Defaults to
                appending at the end.
        """
        card = DeviceCard(self._devices_container)
        card.set_device_info(
            name=self._device_display_name(device),
            model=device.get("model", ""),
            ip=device.get("ip", ""),
        )
        device_ip = device.get("ip", "")
        sort_key = self._device_sort_key(device)
        card.clicked.connect(lambda _=None, ip=device_ip: self._on_card_clicked(ip))
        if insert_index is None:
            insert_index = len(self._device_cards)
        self._devices_layout.insertWidget(insert_index, card)
        self._device_cards.insert(insert_index, (card, device_ip, sort_key))

    @Slot(str)
    def _on_card_clicked(self, ip: str) -> None:
        """Handle device card click — emit device_selected."""
        self.device_selected.emit(ip)

    @Slot()
    def _on_retry_clicked(self) -> None:
        """Handle retry button click — emit refresh_requested."""
        self.refresh_requested.emit()
