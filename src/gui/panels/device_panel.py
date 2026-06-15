"""Device discovery panel.

Displays discovered WiiM devices in a list and provides refresh controls.
Emits signals for device selection and refresh requests — does NOT perform
any network I/O directly.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.models.capabilities import DeviceInfo


class DevicePanel(QWidget):
    """Panel showing discovered WiiM devices with refresh controls.

    Signals:
        device_selected: Emitted when the user selects a device. Payload is DeviceInfo.
        refresh_requested: Emitted when the user clicks the Refresh button.
    """

    device_selected = Signal(object)  # DeviceInfo
    refresh_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the device panel.

        Args:
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)
        self._devices: list[DeviceInfo] = []
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        """Build the panel layout with stacked views and refresh button."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Header row: title + refresh button
        header = QHBoxLayout()
        title_label = QLabel("Devices")
        title_label.setStyleSheet("font-weight: bold;")
        header.addWidget(title_label)
        header.addStretch()

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setFixedWidth(80)
        header.addWidget(self._refresh_btn)
        layout.addLayout(header)

        # Stacked widget: page 0 = empty state, page 1 = device list
        self._stack = QStackedWidget()

        # Page 0: empty state
        empty_page = QWidget()
        empty_layout = QVBoxLayout(empty_page)
        self._empty_label = QLabel("No devices found. Click Refresh to try again.")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        empty_layout.addWidget(self._empty_label)
        self._stack.addWidget(empty_page)

        # Page 1: device list
        self._device_list = QListWidget()
        self._device_list.setAlternatingRowColors(True)
        self._stack.addWidget(self._device_list)

        layout.addWidget(self._stack)

        # Start with empty state
        self._stack.setCurrentIndex(0)

    def _connect_signals(self) -> None:
        """Wire internal widget signals to panel behaviour."""
        self._refresh_btn.clicked.connect(self._on_refresh_clicked)
        self._device_list.currentRowChanged.connect(self._on_row_changed)

    def _on_refresh_clicked(self) -> None:
        """Handle refresh button click."""
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.setText("Scanning...")
        self.refresh_requested.emit()

    def _on_row_changed(self, row: int) -> None:
        """Handle device list selection change.

        Args:
            row: The newly selected row index, or -1 if deselected.
        """
        if 0 <= row < len(self._devices):
            self.device_selected.emit(self._devices[row])

    def on_discovery_complete(self, devices: list[DeviceInfo]) -> None:
        """Slot: update the device list after discovery finishes.

        Called by the controller/MainWindow when AsyncBridge.discovery_complete fires.

        Args:
            devices: List of discovered devices.
        """
        self._devices = list(devices)
        self._refresh_btn.setEnabled(True)
        self._refresh_btn.setText("Refresh")
        self._device_list.clear()

        if not devices:
            self._stack.setCurrentIndex(0)
            return

        self._stack.setCurrentIndex(1)
        for device in devices:
            item = QListWidgetItem()
            item.setText(self._format_device(device))
            self._device_list.addItem(item)

    def update_device_capabilities(self, index: int, caps_line: str) -> None:
        """Update a device item with probed capability information.

        Args:
            index: The row index of the device to update.
            caps_line: Formatted capability string (e.g. "PEQ checkmark  L/R checkmark  RF:4").
        """
        if 0 <= index < self._device_list.count():
            item = self._device_list.item(index)
            if item is not None:
                device = self._devices[index]
                base = self._format_device(device)
                item.setText(f"{base}\n{caps_line}")

    @staticmethod
    def _format_device(device: DeviceInfo) -> str:
        """Format a DeviceInfo for display in the list.

        Args:
            device: The device to format.

        Returns:
            Multi-line string with name, role badge, IP, model, and firmware.
        """
        role_badge = f"[{device.role}]"
        line1 = f"{device.name}  {role_badge}"
        line2 = f"{device.ip} | {device.model} | fw {device.firmware}"
        return f"{line1}\n{line2}"

    @property
    def devices(self) -> list[DeviceInfo]:
        """Currently displayed devices."""
        return list(self._devices)

    @property
    def selected_device(self) -> DeviceInfo | None:
        """Return the currently selected device, or None."""
        row = self._device_list.currentRow()
        if 0 <= row < len(self._devices):
            return self._devices[row]
        return None
