"""Device Picker Dialog - modal selector for target WiiM devices.

Displays discovered devices in a checkable list (excluding the current device)
and returns the user's selection. Used by multi-device push and copy-to-device
workflows (Req 10.1, 10.2, 15.1, 15.2).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from src.gui.components.list_item_style import size_list_item, style_checkable_list
from src.gui.components.warning_box import add_optional_warning_box
from src.models.capabilities import DeviceInfo
from src.utils.device_identity import device_display_name


class _CheckableListWidget(QListWidget):
    """QListWidget where a left-click anywhere on a row toggles its checkbox.

    Qt only toggles a checkable item's check state when the click lands
    exactly on the small checkbox glyph -- everywhere else in the row
    selects it (or, with selection disabled, does nothing visible at all).
    This takes over left-clicks entirely instead of also connecting
    itemClicked: that signal fires *after* Qt's own glyph-click toggle has
    already run, so unconditionally toggling there would flip a glyph click
    back to its original state (toggle, then immediately un-toggle) --
    empirically confirmed by testing a plain super().mousePressEvent()
    fallthrough after the manual toggle, which reproduced exactly that.

    A toggle calls setCurrentItem() directly rather than falling through to
    super() afterward, for the same double-toggle reason -- but skipping
    super() entirely would also skip QAbstractItemView's own current-item
    bookkeeping, leaving arrow-key navigation stuck wherever it was before
    the click instead of continuing from the row just toggled.
    setCurrentItem() restores that continuity without re-running the
    glyph-click handling that caused the double-toggle in the first place.
    Right/middle-clicks fall through to super() unchanged (a no-op, since
    the list has no context menu and NoSelection makes selection-handling
    inert) rather than toggling -- confirmed by testing that a fallthrough
    left non-glyph areas fully inert for those buttons.
    """

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Toggle the clicked row's checkbox on left-click; pass through otherwise."""
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        item = self.itemAt(event.position().toPoint())
        if item is None or not (item.flags() & Qt.ItemFlag.ItemIsUserCheckable):
            super().mousePressEvent(event)
            return
        item.setCheckState(
            Qt.CheckState.Unchecked
            if item.checkState() == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )
        self.setCurrentItem(item)


class DevicePickerDialog(QDialog):
    """Modal dialog for selecting target WiiM devices.

    Presents discovered devices (minus the currently-connected device),
    sorted alphabetically by name, as checkable list items. The user must
    select at least one device to proceed.

    Use the static ``get_devices()`` method for standard usage.
    """

    def __init__(
        self,
        parent: QWidget | None,
        discovered_devices: list[DeviceInfo],
        exclude_ip: str,
        warning: tuple[str, str] | None = None,
    ) -> None:
        """Initialize the device picker dialog.

        Args:
            parent: Parent widget (may be None).
            discovered_devices: All discovered WiiM devices on the network.
            exclude_ip: IP address of the current device to exclude from the list.
            warning: Optional (header, body_html) shown above the device
                list -- lets callers fold a preceding confirmation dialog
                into this one instead of showing it as a separate step.
        """
        super().__init__(parent)
        self.setWindowTitle("Select Target Devices")
        self.setMinimumWidth(420 if warning else 380)
        self.setModal(True)

        # discovered_devices arrives in mDNS/subnet-scan discovery order
        # (whichever device answers first), not name order -- sorted here to
        # match ConnectPage's own device list (_device_sort_key(), same
        # casefold-by-name convention via the shared device_display_name()
        # fallback), so device order doesn't flip between the two screens a
        # user sees during a session, including for a blank-named device.
        self._devices = sorted(
            (d for d in discovered_devices if d.ip != exclude_ip),
            key=lambda d: device_display_name(d.name).casefold(),
        )
        self._warning = warning
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the dialog layout."""
        layout = QVBoxLayout(self)

        add_optional_warning_box(
            layout,
            self._warning,
            frame_object_name="device_picker_warning_frame",
            body_object_name="device_picker_warning_body",
        )

        # Header
        header = QLabel("Select one or more target devices:")
        layout.addWidget(header)

        # Checkable device list
        self._list_widget = _CheckableListWidget()
        self._list_widget.setObjectName("device_list")
        style_checkable_list(self._list_widget)
        for device in self._devices:
            item = QListWidgetItem(f"{device_display_name(device.name)} ({device.ip})")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, device)
            size_list_item(item)
            self._list_widget.addItem(item)
        layout.addWidget(self._list_widget)

        # Button box (Ok / Cancel)
        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._button_box.setObjectName("button_box")
        if self._warning is not None:
            ok_button = self._button_box.button(QDialogButtonBox.StandardButton.Ok)
            if ok_button is not None:
                ok_button.setText("Copy")
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)
        layout.addWidget(self._button_box)

    def selected_devices(self) -> list[DeviceInfo]:
        """Return the list of checked DeviceInfo objects.

        Returns:
            List of DeviceInfo for all checked items.
        """
        result: list[DeviceInfo] = []
        for i in range(self._list_widget.count()):
            item = self._list_widget.item(i)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                device = item.data(Qt.ItemDataRole.UserRole)
                result.append(device)
        return result

    def accept(self) -> None:
        """Validate at least one device is selected before accepting."""
        if not self.selected_devices():
            QMessageBox.warning(
                self,
                "No Selection",
                "Please select at least one target device.",
            )
            return
        super().accept()

    @staticmethod
    def get_devices(
        parent: QWidget | None,
        discovered_devices: list[DeviceInfo],
        exclude_ip: str,
        warning: tuple[str, str] | None = None,
    ) -> list[DeviceInfo] | None:
        """Show the device picker and return selected devices or None on cancel.

        This is the primary entry point for device selection workflows.

        Args:
            parent: Parent widget (may be None).
            discovered_devices: All discovered WiiM devices.
            exclude_ip: IP address of current device to exclude.
            warning: Optional (header, body_html) shown above the device
                list.

        Returns:
            List of selected DeviceInfo objects, or None if the user cancelled.
        """
        dialog = DevicePickerDialog(parent, discovered_devices, exclude_ip, warning)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.selected_devices()
        return None
