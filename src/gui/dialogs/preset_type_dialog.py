"""Preset Type Dialog - PEQ vs RoomFit choice for a locally saved profile.

A locally saved `Profile` (see src/models/profile.py) carries filters and a
channel mode, but no record of whether it originated as a device PEQ preset
or a RoomFit profile -- that distinction is discarded when "Save to My
Presets" persists a device preset. Pushing a saved profile to another device
therefore needs to ask the user which target write-mode to use.
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from src.gui.constants import SPACING_MD


class PresetTypeDialog(QDialog):
    """Modal dialog for choosing whether to push a saved profile as a PEQ
    preset or a RoomFit profile.

    Use the static ``get_type()`` method for standard usage.
    """

    def __init__(self, parent: QWidget | None) -> None:
        """Initialize the preset type dialog.

        Args:
            parent: Parent widget (may be None).
        """
        super().__init__(parent)
        self.setWindowTitle("Choose Preset Type")
        self.setMinimumWidth(360)
        self.setModal(True)

        self._setup_ui()

    def _setup_ui(self) -> None:
        """Build the dialog layout with a PEQ/RoomFit radio choice."""
        layout = QVBoxLayout(self)
        layout.setSpacing(SPACING_MD)

        header = QLabel(
            "This preset has no device context — choose how to push it"
            " to the target device."
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        self._type_group = QButtonGroup(self)

        self._peq_radio = QRadioButton("PEQ Preset")
        self._peq_radio.setObjectName("preset_type_peq")
        self._peq_radio.setChecked(True)
        self._type_group.addButton(self._peq_radio)
        layout.addWidget(self._peq_radio)

        self._roomfit_radio = QRadioButton("RoomFit Profile")
        self._roomfit_radio.setObjectName("preset_type_roomfit")
        self._type_group.addButton(self._roomfit_radio)
        layout.addWidget(self._roomfit_radio)

        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._button_box.setObjectName("button_box")
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)
        layout.addWidget(self._button_box)

    def selected_type(self) -> Literal["PEQ", "RoomFit"]:
        """Return the chosen preset type."""
        return "RoomFit" if self._roomfit_radio.isChecked() else "PEQ"

    @staticmethod
    def get_type(parent: QWidget | None) -> Literal["PEQ", "RoomFit"] | None:
        """Show the preset type dialog and return the user's choice.

        Args:
            parent: Parent widget (may be None).

        Returns:
            "PEQ" or "RoomFit" if the user accepted, or None if cancelled.
        """
        dialog = PresetTypeDialog(parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.selected_type()
        return None
