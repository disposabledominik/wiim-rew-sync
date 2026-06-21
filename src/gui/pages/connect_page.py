"""ConnectPage — device discovery and selection wizard step.

Displays discovered WiiM devices as DeviceCard widgets, handles scanning state,
empty state with troubleshooting guidance, and auto-selects a single device.

Requirements referenced: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.gui.components.device_card import DeviceCard
from src.gui.constants import (
    FONT_SIZE_BODY,
    FONT_SIZE_CAPTION,
    FONT_SIZE_HEADING,
    FONT_WEIGHT_SEMIBOLD,
    MAX_CONTENT_WIDTH,
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
        self._device_cards: list[DeviceCard] = []
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
        if active:
            self._devices_scroll.setVisible(False)
            self._empty_widget.setVisible(False)

    def set_devices(self, devices: list[dict]) -> None:
        """Populate the page with discovered device cards.

        Each dict should have keys: name, model, ip, firmware, role.

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

        for device in devices:
            card = DeviceCard(self._devices_container)
            card.set_device_info(
                name=device.get("name", "Unknown Device"),
                model=device.get("model", ""),
                ip=device.get("ip", ""),
                firmware=device.get("firmware", ""),
                role=device.get("role", ""),
            )
            device_ip = device.get("ip", "")
            card.clicked.connect(lambda _=None, ip=device_ip: self._on_card_clicked(ip))
            self._devices_layout.addWidget(card)
            self._device_cards.append(card)

        # Auto-select single device (Req 2.4)
        if len(devices) == 1:
            ip = devices[0].get("ip", "")
            if ip:
                self.device_selected.emit(ip)

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
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)

        # Content wrapper with max width
        content_wrapper = QWidget(self)
        content_wrapper.setMaximumWidth(MAX_CONTENT_WIDTH)
        content_layout = QVBoxLayout(content_wrapper)
        content_layout.setContentsMargins(SPACING_LG, SPACING_LG, SPACING_LG, SPACING_LG)
        content_layout.setSpacing(SPACING_LG)

        # Page title
        title = QLabel("Connect to Device", content_wrapper)
        title.setObjectName("ConnectPageTitle")
        title.setStyleSheet(
            f"font-size: {FONT_SIZE_HEADING}px; font-weight: {FONT_WEIGHT_SEMIBOLD};"
        )
        content_layout.addWidget(title)

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

        # Center the content wrapper
        wrapper_layout = QHBoxLayout()
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.addStretch()
        wrapper_layout.addWidget(content_wrapper)
        wrapper_layout.addStretch()
        page_layout.addLayout(wrapper_layout)

    def _build_scanning_widget(self, parent: QWidget) -> QWidget:
        """Build the scanning animation state widget."""
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, SPACING_LG, 0, SPACING_LG)
        layout.setSpacing(SPACING_MD)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Scanning indicator (text-based, can be enhanced with animation later)
        spinner_label = QLabel("\u25CF \u25CF \u25CF", widget)
        spinner_label.setObjectName("ConnectPageSpinner")
        spinner_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        spinner_label.setStyleSheet(
            f"font-size: {FONT_SIZE_HEADING}px; color: #00B4D8; letter-spacing: 8px;"
        )
        layout.addWidget(spinner_label)

        # Scanning message (Req 2.2)
        message = QLabel("Searching for WiiM devices on your network...", widget)
        message.setObjectName("ConnectPageScanningMessage")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setStyleSheet(f"font-size: {FONT_SIZE_BODY}px;")
        message.setWordWrap(True)
        layout.addWidget(message)

        return widget

    def _build_empty_widget(self, parent: QWidget) -> QWidget:
        """Build the empty/no-devices-found state widget (Req 2.6)."""
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, SPACING_LG, 0, SPACING_LG)
        layout.setSpacing(SPACING_MD)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # No devices heading
        heading = QLabel("No devices found", widget)
        heading.setObjectName("ConnectPageEmptyHeading")
        heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading.setStyleSheet(
            f"font-size: {FONT_SIZE_HEADING}px; font-weight: {FONT_WEIGHT_SEMIBOLD};"
        )
        layout.addWidget(heading)

        # Common causes explanation
        causes_label = QLabel(
            "Common causes:\n"
            "\u2022 Your WiiM device is powered off or not connected to WiFi\n"
            "\u2022 Your computer and WiiM device are on different subnets\n"
            "\u2022 A firewall is blocking mDNS discovery (port 5353)",
            widget,
        )
        causes_label.setObjectName("ConnectPageEmptyCauses")
        causes_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        causes_label.setStyleSheet(f"font-size: {FONT_SIZE_BODY}px; color: #616161;")
        causes_label.setWordWrap(True)
        layout.addWidget(causes_label)

        # Retry button
        retry_button = QPushButton("Retry", widget)
        retry_button.setObjectName("ConnectPageRetryButton")
        retry_button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        retry_button.setMinimumWidth(120)
        retry_button.clicked.connect(self._on_retry_clicked)
        layout.addWidget(retry_button, alignment=Qt.AlignmentFlag.AlignCenter)

        # Troubleshooting link
        troubleshoot_label = QLabel(
            '<a href="#troubleshoot">Troubleshooting guide</a>',
            widget,
        )
        troubleshoot_label.setObjectName("ConnectPageTroubleshootLink")
        troubleshoot_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        troubleshoot_label.setStyleSheet(f"font-size: {FONT_SIZE_CAPTION}px;")
        troubleshoot_label.setOpenExternalLinks(False)
        layout.addWidget(troubleshoot_label)

        return widget

    def _clear_cards(self) -> None:
        """Remove all device cards from the layout."""
        for card in self._device_cards:
            self._devices_layout.removeWidget(card)
            card.deleteLater()
        self._device_cards.clear()

    @Slot(str)
    def _on_card_clicked(self, ip: str) -> None:
        """Handle device card click — emit device_selected."""
        self.device_selected.emit(ip)

    @Slot()
    def _on_retry_clicked(self) -> None:
        """Handle retry button click — emit refresh_requested."""
        self.refresh_requested.emit()
