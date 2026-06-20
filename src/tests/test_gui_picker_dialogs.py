"""Unit tests for picker dialogs (Source, Device, Measurement).

Tests dialog creation, item filtering, selection logic, accept validation,
and cancel behavior using pytest-qt (qtbot) fixtures.

Requirements referenced: 9.1, 9.2, 10.1, 10.2, 5.2, 5.7.
"""

from __future__ import annotations

from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QListWidget

from src.adapters.rew_http_client import MeasurementSummary
from src.gui.dialogs.device_picker import DevicePickerDialog
from src.gui.dialogs.measurement_picker import MeasurementPickerDialog
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
