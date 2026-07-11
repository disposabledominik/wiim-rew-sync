"""Unit tests for DiagnosticsPanel's source-slot overview section."""

from __future__ import annotations

import pytest

from src.gui.panels.diagnostics_panel import DiagnosticsPanel
from src.models.source_slot import SourceSlotInfo


@pytest.fixture(autouse=True)
def _ensure_qapp():
    """Ensure a QApplication exists for QWidget-based tests."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def panel() -> DiagnosticsPanel:
    return DiagnosticsPanel()


class TestSourceSlotsRequested:
    def test_refresh_button_emits_signal(self, panel: DiagnosticsPanel) -> None:
        received = []
        panel.source_slots_requested.connect(lambda: received.append(True))

        panel._refresh_slots_btn.click()

        assert received == [True]


class TestOnSourceSlotsReady:
    def test_populates_table_rows(self, panel: DiagnosticsPanel) -> None:
        slots = [
            SourceSlotInfo(
                source_name="wifi",
                name="M16",
                enabled=True,
                channel_mode="Stereo",
                is_known_source=True,
            ),
            SourceSlotInfo(
                source_name="wifi,bluetooth,auxIn",
                name="",
                enabled=False,
                channel_mode="Stereo",
                is_known_source=False,
            ),
        ]

        panel.on_source_slots_ready(slots)

        assert panel._slots_table.rowCount() == 2
        source0 = panel._slots_table.item(0, 0)
        valid0 = panel._slots_table.item(0, 1)
        source1 = panel._slots_table.item(1, 0)
        valid1 = panel._slots_table.item(1, 1)
        assert source0 is not None and source0.text() == "wifi"
        assert valid0 is not None and valid0.text() == "Yes"
        assert source1 is not None and source1.text() == "wifi,bluetooth,auxIn"
        assert valid1 is not None and valid1.text() == "No"
        assert "1 unknown" in panel._slots_status_label.text()

    def test_all_known_status_message(self, panel: DiagnosticsPanel) -> None:
        slots = [
            SourceSlotInfo(source_name="wifi", is_known_source=True),
        ]

        panel.on_source_slots_ready(slots)

        assert "all recognized" in panel._slots_status_label.text()

    def test_empty_list_clears_table(self, panel: DiagnosticsPanel) -> None:
        panel.on_source_slots_ready([])

        assert panel._slots_table.rowCount() == 0


class TestOnSourceSlotsError:
    def test_shows_error_and_clears_table(self, panel: DiagnosticsPanel) -> None:
        panel.on_source_slots_ready(
            [SourceSlotInfo(source_name="wifi", is_known_source=True)]
        )

        panel.on_source_slots_error("No device connected")

        assert panel._slots_table.rowCount() == 0
        assert "No device connected" in panel._slots_status_label.text()
