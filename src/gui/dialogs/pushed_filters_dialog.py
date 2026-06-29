"""PushedFiltersDialog — read-only display of filters confirmed on the device.

Shown from PushPage's "Show Pushed Filters" button after a successful push.
Displays the same read-back data used to verify the write (see
WriteResult.read_back in src/adapters/safe_write.py), not just what was
intended -- so it reflects exactly what's on the device right now.
"""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QVBoxLayout, QWidget

from src.gui.components.filter_table import FilterTable
from src.models.canonical import CanonicalFilter


class PushedFiltersDialog(QDialog):
    """Read-only dialog showing the filters confirmed on the device after a push."""

    def __init__(
        self,
        filters: list[CanonicalFilter] | None = None,
        filters_l: list[CanonicalFilter] | None = None,
        filters_r: list[CanonicalFilter] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """Initialize the dialog with the read-back filter data to display.

        Args:
            filters: Stereo-mode bands confirmed on the device. Ignored if
                filters_l/filters_r are given.
            filters_l: Left-channel bands confirmed on the device (L/R mode).
            filters_r: Right-channel bands confirmed on the device (L/R mode).
            parent: Optional parent widget.
        """
        super().__init__(parent)
        self.setWindowTitle("Filters Confirmed on Device")
        self.setMinimumWidth(520)
        self.setMinimumHeight(480)

        layout = QVBoxLayout(self)

        table = FilterTable(self)
        if filters_l is not None or filters_r is not None:
            table.set_lr_filters(filters_l or [], filters_r or [])
        else:
            table.set_filters(filters or [])
        layout.addWidget(table)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
