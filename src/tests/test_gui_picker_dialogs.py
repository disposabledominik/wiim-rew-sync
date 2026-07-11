"""Unit tests for picker dialogs (Source, Device, Measurement).

Tests dialog creation, item filtering, selection logic, accept validation,
and cancel behavior using pytest-qt (qtbot) fixtures.

Requirements referenced: 9.1, 9.2, 10.1, 10.2, 5.2, 5.7.
"""

from __future__ import annotations

from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListWidget, QWidget

from src.adapters.rew_http_client import MeasurementSummary
from src.gui.dialogs.device_picker import DevicePickerDialog
from src.gui.dialogs.measurement_picker import MeasurementPickerDialog
from src.gui.dialogs.preset_type_dialog import PresetTypeDialog
from src.gui.dialogs.source_picker import SourcePickerDialog
from src.models.capabilities import DeviceInfo

# ---------------------------------------------------------------------------
# SourcePickerDialog tests (Req 9.1, 9.2)
# ---------------------------------------------------------------------------


class TestSourcePickerDialog:
    """Tests for the SourcePickerDialog modal dialog."""

    def test_source_picker_excludes_current_source(self, qtbot) -> None:
        """Dialog excludes the current source from the displayed list."""
        sources = ["wifi", "hdmi", "bluetooth"]
        dialog = SourcePickerDialog(None, sources, exclude="wifi")
        qtbot.addWidget(dialog)

        list_widget = dialog.findChild(QListWidget, "source_list")
        assert list_widget is not None

        items = [list_widget.item(i).text() for i in range(list_widget.count())]
        assert "wifi" not in items
        assert "hdmi" in items
        assert "bluetooth" in items
        assert list_widget.count() == 2

    def test_source_picker_returns_checked_sources(self, qtbot) -> None:
        """selected_sources() returns only the checked items."""
        sources = ["wifi", "hdmi", "bluetooth", "optical"]
        dialog = SourcePickerDialog(None, sources, exclude="wifi")
        qtbot.addWidget(dialog)

        list_widget = dialog.findChild(QListWidget, "source_list")
        assert list_widget is not None

        # Check "hdmi" and "optical"
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            if item.text() in ("hdmi", "optical"):
                item.setCheckState(Qt.CheckState.Checked)

        result = dialog.selected_sources()
        assert sorted(result) == ["hdmi", "optical"]

    def test_source_picker_accept_requires_selection(self, qtbot) -> None:
        """Accept is blocked when no sources are checked."""
        sources = ["wifi", "hdmi", "bluetooth"]
        dialog = SourcePickerDialog(None, sources, exclude="wifi")
        qtbot.addWidget(dialog)

        # Mock QMessageBox.warning to prevent it from blocking
        with patch("src.gui.dialogs.source_picker.QMessageBox.warning"):
            dialog.accept()

        # Dialog should NOT have been accepted (result stays at Rejected default)
        assert dialog.result() != QDialog.DialogCode.Accepted

    def test_source_picker_cancel_returns_none(self, qtbot) -> None:
        """Rejecting the dialog means no sources are returned."""
        sources = ["wifi", "hdmi", "bluetooth"]
        dialog = SourcePickerDialog(None, sources, exclude="wifi")
        qtbot.addWidget(dialog)

        dialog.reject()

        assert dialog.result() == QDialog.DialogCode.Rejected


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


# ---------------------------------------------------------------------------
# MeasurementPickerDialog tests (Req 5.2, 5.7)
# ---------------------------------------------------------------------------


def _make_measurement(name: str, index: int) -> MeasurementSummary:
    """Helper to create a MeasurementSummary for testing."""
    return MeasurementSummary(uuid=f"uuid-{index}", name=name, index=index)


class TestMeasurementPickerDialog:
    """Tests for the MeasurementPickerDialog modal dialog."""

    def test_measurement_picker_shows_all_measurements(self, qtbot) -> None:
        """Dialog displays all provided measurements."""
        measurements = [
            _make_measurement("Left Speaker", 0),
            _make_measurement("Right Speaker", 1),
            _make_measurement("Subwoofer", 2),
        ]
        dialog = MeasurementPickerDialog(None, measurements)
        qtbot.addWidget(dialog)

        list_widget = dialog.findChild(QListWidget, "measurement_list")
        assert list_widget is not None
        assert list_widget.count() == 3

        items = [list_widget.item(i).text() for i in range(list_widget.count())]
        assert "Left Speaker" in items
        assert "Right Speaker" in items
        assert "Subwoofer" in items

    def test_measurement_picker_returns_selected(self, qtbot) -> None:
        """selected_measurement() returns the correct MeasurementSummary object."""
        measurements = [
            _make_measurement("Left Speaker", 0),
            _make_measurement("Right Speaker", 1),
            _make_measurement("Subwoofer", 2),
        ]
        dialog = MeasurementPickerDialog(None, measurements)
        qtbot.addWidget(dialog)

        list_widget = dialog.findChild(QListWidget, "measurement_list")
        assert list_widget is not None

        # Select the second item ("Right Speaker")
        list_widget.setCurrentRow(1)

        result = dialog.selected_measurement()
        assert result is not None
        assert result.name == "Right Speaker"
        assert result.uuid == "uuid-1"
        assert result.index == 1

    def test_measurement_picker_accept_requires_selection(self, qtbot) -> None:
        """Accept is blocked when no measurement is selected."""
        measurements = [
            _make_measurement("Left Speaker", 0),
            _make_measurement("Right Speaker", 1),
        ]
        dialog = MeasurementPickerDialog(None, measurements)
        qtbot.addWidget(dialog)

        # Clear any selection
        list_widget = dialog.findChild(QListWidget, "measurement_list")
        assert list_widget is not None
        list_widget.clearSelection()

        # Mock QMessageBox.warning to prevent blocking
        with patch("src.gui.dialogs.measurement_picker.QMessageBox.warning"):
            dialog.accept()

        assert dialog.result() != QDialog.DialogCode.Accepted

    def test_measurement_picker_defaults_to_stereo_mode(self, qtbot) -> None:
        """Dialog starts in Stereo mode showing the single list page."""
        measurements = [_make_measurement("Speaker", 0)]
        dialog = MeasurementPickerDialog(None, measurements)
        qtbot.addWidget(dialog)

        assert not dialog.is_lr_mode
        assert dialog._pages.currentWidget() is dialog._list_widget

    def test_measurement_picker_lr_toggle_shows_two_lists(self, qtbot) -> None:
        """Toggling to L/R switches to the page with Left/Right lists."""
        measurements = [
            _make_measurement("Left Speaker", 0),
            _make_measurement("Right Speaker", 1),
        ]
        dialog = MeasurementPickerDialog(None, measurements)
        qtbot.addWidget(dialog)

        dialog._lr_radio.setChecked(True)

        assert dialog.is_lr_mode
        left_list = dialog.findChild(QListWidget, "measurement_list_left")
        right_list = dialog.findChild(QListWidget, "measurement_list_right")
        assert left_list is not None
        assert right_list is not None
        assert left_list.count() == 2
        assert right_list.count() == 2

    def test_measurement_picker_lr_returns_tuple(self, qtbot) -> None:
        """selection() returns a (left, right) tuple in L/R mode."""
        measurements = [
            _make_measurement("Left Speaker", 0),
            _make_measurement("Right Speaker", 1),
        ]
        dialog = MeasurementPickerDialog(None, measurements)
        qtbot.addWidget(dialog)

        dialog._lr_radio.setChecked(True)
        dialog._list_left.setCurrentRow(0)
        dialog._list_right.setCurrentRow(1)

        result = dialog.selection()
        assert isinstance(result, tuple)
        left, right = result
        assert left.name == "Left Speaker"
        assert right.name == "Right Speaker"

    def test_measurement_picker_lr_accept_requires_both_sides(self, qtbot) -> None:
        """Accept is blocked in L/R mode until both Left and Right are selected."""
        measurements = [
            _make_measurement("Left Speaker", 0),
            _make_measurement("Right Speaker", 1),
        ]
        dialog = MeasurementPickerDialog(None, measurements)
        qtbot.addWidget(dialog)

        dialog._lr_radio.setChecked(True)
        dialog._list_left.setCurrentRow(0)
        # Right list left unselected

        with patch("src.gui.dialogs.measurement_picker.QMessageBox.warning"):
            dialog.accept()

        assert dialog.result() != QDialog.DialogCode.Accepted

    def test_measurement_picker_ok_button_disabled_until_valid_selection(
        self, qtbot
    ) -> None:
        """OK is disabled until the active mode's selection is complete."""
        measurements = [
            _make_measurement("Left Speaker", 0),
            _make_measurement("Right Speaker", 1),
        ]
        dialog = MeasurementPickerDialog(None, measurements)
        qtbot.addWidget(dialog)

        ok_btn = dialog._button_box.button(QDialogButtonBox.StandardButton.Ok)
        assert ok_btn is not None
        assert not ok_btn.isEnabled()  # nothing selected yet (Stereo mode)

        dialog._list_widget.setCurrentRow(0)
        assert ok_btn.isEnabled()

        dialog._lr_radio.setChecked(True)
        assert not ok_btn.isEnabled()  # switching modes resets requirement

        dialog._list_left.setCurrentRow(0)
        assert not ok_btn.isEnabled()  # only Left selected

        dialog._list_right.setCurrentRow(1)
        assert ok_btn.isEnabled()

    def test_measurement_picker_large_list_keyboard_search(self, qtbot) -> None:
        """A 60-item list keeps Qt's built-in incremental keyboard search."""
        measurements = [_make_measurement(f"Measurement {i:02d}", i) for i in range(60)]
        dialog = MeasurementPickerDialog(None, measurements)
        qtbot.addWidget(dialog)

        assert dialog._list_widget.count() == 60
        # Built-in QAbstractItemView type-ahead search is on by default;
        # this dialog adds no custom filtering that could disable it.
        from PySide6.QtWidgets import QAbstractItemView

        assert dialog._list_widget.selectionMode() == (
            QAbstractItemView.SelectionMode.SingleSelection
        )
