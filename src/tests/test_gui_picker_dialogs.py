"""Unit tests for picker dialogs (PresetType, Device).

Tests dialog creation, item filtering, selection logic, accept validation,
and cancel behavior using pytest-qt (qtbot) fixtures.

Requirements referenced: 10.1, 10.2.
"""

from __future__ import annotations

from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListWidget, QWidget

from src.gui.dialogs.device_picker import DevicePickerDialog
from src.gui.dialogs.preset_type_dialog import PresetTypeDialog
from src.models.capabilities import DeviceInfo

# ---------------------------------------------------------------------------
# PresetTypeDialog tests
# ---------------------------------------------------------------------------


class TestPresetTypeDialog:
    """Tests for the PresetTypeDialog PEQ/RoomFit choice."""

    def test_defaults_to_peq(self, qtbot) -> None:
        """PEQ Preset is checked by default."""
        dialog = PresetTypeDialog(None)
        qtbot.addWidget(dialog)

        assert dialog.selected_type() == "PEQ"

    def test_selecting_roomfit_radio_changes_type(self, qtbot) -> None:
        """Checking the RoomFit radio changes the returned type."""
        dialog = PresetTypeDialog(None)
        qtbot.addWidget(dialog)

        dialog._roomfit_radio.setChecked(True)

        assert dialog.selected_type() == "RoomFit"

    def test_get_type_returns_none_on_cancel(self, qtbot) -> None:
        """get_type() returns None when the dialog is rejected."""
        with patch.object(PresetTypeDialog, "exec", return_value=QDialog.DialogCode.Rejected):
            result = PresetTypeDialog.get_type(None)

        assert result is None

    def test_get_type_returns_selected_type_on_accept(self, qtbot) -> None:
        """get_type() returns the selected type when the dialog is accepted."""
        with patch.object(PresetTypeDialog, "exec", return_value=QDialog.DialogCode.Accepted):
            result = PresetTypeDialog.get_type(None)

        assert result == "PEQ"


# ---------------------------------------------------------------------------
# DevicePickerDialog tests (Req 10.1, 10.2)
# ---------------------------------------------------------------------------


def _make_device(name: str, ip: str) -> DeviceInfo:
    """Helper to create a DeviceInfo for testing."""
    return DeviceInfo(
        name=name,
        ip=ip,
        model="WiiM Pro",
        firmware="5.0.0",
        uuid=f"uuid-{ip}",
    )


class TestDevicePickerDialog:
    """Tests for the DevicePickerDialog modal dialog."""

    def test_device_picker_excludes_current_device(self, qtbot) -> None:
        """Dialog excludes the device matching exclude_ip from the list."""
        devices = [
            _make_device("Living Room", "192.168.1.10"),
            _make_device("Bedroom", "192.168.1.11"),
            _make_device("Kitchen", "192.168.1.12"),
        ]
        dialog = DevicePickerDialog(None, devices, exclude_ip="192.168.1.10")
        qtbot.addWidget(dialog)

        list_widget = dialog.findChild(QListWidget, "device_list")
        assert list_widget is not None
        assert list_widget.count() == 2

        items_text = [list_widget.item(i).text() for i in range(list_widget.count())]
        assert any("Bedroom" in t for t in items_text)
        assert any("Kitchen" in t for t in items_text)
        assert not any("Living Room" in t for t in items_text)

    def test_device_picker_returns_checked_devices(self, qtbot) -> None:
        """selected_devices() returns correct DeviceInfo objects for checked items."""
        devices = [
            _make_device("Living Room", "192.168.1.10"),
            _make_device("Bedroom", "192.168.1.11"),
            _make_device("Kitchen", "192.168.1.12"),
        ]
        dialog = DevicePickerDialog(None, devices, exclude_ip="192.168.1.10")
        qtbot.addWidget(dialog)

        list_widget = dialog.findChild(QListWidget, "device_list")
        assert list_widget is not None

        # Check the first item (Bedroom)
        list_widget.item(0).setCheckState(Qt.CheckState.Checked)

        result = dialog.selected_devices()
        assert len(result) == 1
        assert result[0].ip == "192.168.1.11"
        assert result[0].name == "Bedroom"

    def test_device_picker_accept_requires_selection(self, qtbot) -> None:
        """Accept is blocked when no devices are checked."""
        devices = [
            _make_device("Living Room", "192.168.1.10"),
            _make_device("Bedroom", "192.168.1.11"),
        ]
        dialog = DevicePickerDialog(None, devices, exclude_ip="192.168.1.10")
        qtbot.addWidget(dialog)

        # Mock QMessageBox.warning to prevent blocking
        with patch("src.gui.dialogs.device_picker.QMessageBox.warning"):
            dialog.accept()

        assert dialog.result() != QDialog.DialogCode.Accepted

    def test_device_picker_without_warning_has_no_warning_box(self, qtbot) -> None:
        """No `warning` arg -- no warning box, default Ok label."""
        devices = [_make_device("Living Room", "192.168.1.10")]
        dialog = DevicePickerDialog(None, devices, exclude_ip="")
        qtbot.addWidget(dialog)

        assert dialog.findChild(QWidget, "device_picker_warning_frame") is None
        ok_button = dialog._button_box.button(QDialogButtonBox.StandardButton.Ok)
        assert ok_button is not None
        assert ok_button.text() == "OK"

    def test_device_picker_with_warning_shows_box_and_relabels_ok(self, qtbot) -> None:
        """A `warning` arg renders a warning box above the list and relabels Ok to Copy."""
        devices = [_make_device("Living Room", "192.168.1.10")]
        dialog = DevicePickerDialog(
            None, devices, exclude_ip="", warning=("Heads Up", "This will do a thing.")
        )
        qtbot.addWidget(dialog)

        assert dialog.findChild(QWidget, "device_picker_warning_frame") is not None
        body_label = dialog.findChild(QLabel, "device_picker_warning_body")
        assert body_label is not None
        assert "This will do a thing." in body_label.text()
        ok_button = dialog._button_box.button(QDialogButtonBox.StandardButton.Ok)
        assert ok_button is not None
        assert ok_button.text() == "Copy"

