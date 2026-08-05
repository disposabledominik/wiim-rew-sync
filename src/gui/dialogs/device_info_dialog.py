"""Device Info Dialog - read-only popover for the sidebar device header.

Shows the connected device's identity (name, model, IP) and, when
capabilities aren't purely from live probing, the capability warning --
using the shared `make_warning_box()` treatment every other warning in the
app uses, instead of a plain-text glyph line in a native message box.

`DeviceCard` is deliberately not embedded here: it is an interactive
selection card (hand cursor, click-to-select signal), which is the wrong
affordance for a read-only details view.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from src.gui.components.warning_box import add_optional_warning_box
from src.gui.constants import SPACING_MD


class DeviceInfoDialog(QDialog):
    """Read-only dialog showing the connected device's details.

    Use the static ``show_info()`` method for standard usage.
    """

    def __init__(
        self,
        parent: QWidget | None,
        name: str,
        model: str,
        ip: str,
        warning_text: str = "",
    ) -> None:
        """Initialize the dialog.

        Args:
            parent: Parent widget (may be None).
            name: Friendly device display name.
            model: Device model string (row omitted when empty).
            ip: Device IP address.
            warning_text: Optional capability warning; shown in the shared
                warning-box treatment when non-empty.
        """
        super().__init__(parent)
        self.setWindowTitle("Connected Device")
        self.setMinimumWidth(360)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(SPACING_MD)

        form = QFormLayout()
        form.addRow("Device:", QLabel(name))
        if model:
            form.addRow("Model:", QLabel(model))
        form.addRow("IP address:", QLabel(ip))
        layout.addLayout(form)

        add_optional_warning_box(
            layout,
            ("Capabilities", warning_text) if warning_text else None,
            frame_object_name="device_info_warning_frame",
            body_object_name="device_info_warning_label",
        )

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        button_box.setObjectName("button_box")
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    @staticmethod
    def show_info(
        parent: QWidget | None,
        name: str,
        model: str,
        ip: str,
        warning_text: str = "",
    ) -> None:
        """Build and show the dialog modally (the mockable entry point --
        tests patch this static method, matching the codebase's custom-modal
        convention).

        Args:
            parent: Parent widget (may be None).
            name: Friendly device display name.
            model: Device model string (row omitted when empty).
            ip: Device IP address.
            warning_text: Optional capability warning.
        """
        DeviceInfoDialog(parent, name, model, ip, warning_text).exec()
