"""QuickSetupDialog — completes missing wizard state before loading filters.

When a user loads a preset/profile from the sidebar before completing
all wizard steps, this dialog asks only for the missing information
(EQ type, source selection) so the filters can be applied correctly.

Smoke test issue #87: adaptive pop-up for missing state.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from src.gui.constants import (
    ACCENT_COLOR,
    FONT_SIZE_BODY,
    FONT_WEIGHT_SEMIBOLD,
    SPACING_LG,
    SPACING_MD,
    SPACING_SM,
)


class QuickSetupDialog(QDialog):
    """Modal dialog that collects missing wizard state before loading filters.

    Only shows sections for information that is actually missing. If everything
    is already set, this dialog should not be shown at all.
    """

    def __init__(
        self,
        parent: QWidget | None,
        need_eq_type: bool = False,
        need_source: bool = False,
        available_sources: list[str] | None = None,
    ) -> None:
        """Initialize the dialog.

        Args:
            parent: Parent widget.
            need_eq_type: Whether to show EQ type selection (PEQ/RoomFit).
            need_source: Whether to show source selection checkboxes.
            available_sources: List of source names for source selection.
        """
        super().__init__(parent)
        self.setWindowTitle("Complete Setup")
        self.setMinimumWidth(360)
        self.setModal(True)

        self._need_eq_type = need_eq_type
        self._need_source = need_source
        self._available_sources = available_sources or [
            "wifi", "bluetooth", "line-in", "optical", "HDMI", "auxIn"
        ]

        self._eq_type: str = "peq"
        self._selected_sources: list[str] = []

        self._setup_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def eq_type(self) -> str:
        """Return selected EQ type: 'peq' or 'roomfit'."""
        return self._eq_type

    @property
    def selected_sources(self) -> list[str]:
        """Return list of selected source names."""
        return self._selected_sources

    # ------------------------------------------------------------------
    # Static helper
    # ------------------------------------------------------------------

    @staticmethod
    def get_setup(
        parent: QWidget | None,
        need_eq_type: bool = False,
        need_source: bool = False,
        available_sources: list[str] | None = None,
    ) -> tuple[str, list[str]] | None:
        """Show dialog and return (eq_type, sources) or None if cancelled.

        Args:
            parent: Parent widget.
            need_eq_type: Whether EQ type selection is needed.
            need_source: Whether source selection is needed.
            available_sources: Available sources for selection.

        Returns:
            Tuple of (eq_type, selected_sources) or None if cancelled.
        """
        dialog = QuickSetupDialog(
            parent, need_eq_type, need_source, available_sources
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.eq_type, dialog.selected_sources
        return None

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Build the dialog layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_LG, SPACING_LG, SPACING_LG, SPACING_LG)
        layout.setSpacing(SPACING_LG)

        # Instruction
        instruction = QLabel(
            "Before loading, please confirm the following:"
        )
        instruction.setWordWrap(True)
        instruction.setStyleSheet(f"font-size: {FONT_SIZE_BODY}px;")
        layout.addWidget(instruction)

        # EQ Type section
        if self._need_eq_type:
            eq_section = QWidget()
            eq_layout = QVBoxLayout(eq_section)
            eq_layout.setContentsMargins(0, 0, 0, 0)
            eq_layout.setSpacing(SPACING_SM)

            eq_label = QLabel("EQ Type:")
            eq_label.setStyleSheet(
                f"font-size: {FONT_SIZE_BODY}px; font-weight: {FONT_WEIGHT_SEMIBOLD};"
            )
            eq_layout.addWidget(eq_label)

            eq_buttons = QHBoxLayout()
            eq_buttons.setSpacing(SPACING_MD)
            self._eq_group = QButtonGroup(self)

            self._peq_radio = QRadioButton("PEQ")
            self._peq_radio.setChecked(True)
            self._roomfit_radio = QRadioButton("RoomFit")
            self._eq_group.addButton(self._peq_radio)
            self._eq_group.addButton(self._roomfit_radio)

            eq_buttons.addWidget(self._peq_radio)
            eq_buttons.addWidget(self._roomfit_radio)
            eq_buttons.addStretch()
            eq_layout.addLayout(eq_buttons)

            layout.addWidget(eq_section)

        # Source section (only for PEQ — RoomFit is device-global)
        if self._need_source:
            self._source_section = QWidget()
            source_layout = QVBoxLayout(self._source_section)
            source_layout.setContentsMargins(0, 0, 0, 0)
            source_layout.setSpacing(SPACING_SM)

            source_label = QLabel("Target source(s):")
            source_label.setStyleSheet(
                f"font-size: {FONT_SIZE_BODY}px; font-weight: {FONT_WEIGHT_SEMIBOLD};"
            )
            source_layout.addWidget(source_label)

            self._source_checkboxes: dict[str, QCheckBox] = {}
            for source in self._available_sources:
                cb = QCheckBox(source)
                if source == "wifi":
                    cb.setChecked(True)
                    cb.setStyleSheet(f"QCheckBox {{ color: {ACCENT_COLOR}; }}")
                cb.toggled.connect(self._on_source_toggled)
                source_layout.addWidget(cb)
                self._source_checkboxes[source] = cb

            layout.addWidget(self._source_section)

            # If we also have eq_type, hide source when RoomFit is chosen
            if self._need_eq_type:
                self._roomfit_radio.toggled.connect(self._on_eq_type_toggled)

        # Buttons
        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._button_box.accepted.connect(self._on_accept)
        self._button_box.rejected.connect(self.reject)
        layout.addWidget(self._button_box)

        self._update_ok_enabled()

    def _on_eq_type_toggled(self, checked: bool) -> None:
        """Hide source section when RoomFit is selected (it's device-global)."""
        if hasattr(self, "_source_section"):
            self._source_section.setVisible(not checked)
        self._update_ok_enabled()

    def _on_source_toggled(self, _checked: bool) -> None:
        """Update OK button state when source selection changes."""
        self._update_ok_enabled()

    def _update_ok_enabled(self) -> None:
        """Enable OK only when required fields are filled."""
        ok_btn = self._button_box.button(QDialogButtonBox.StandardButton.Ok)
        if not ok_btn:
            return

        # If source is needed and EQ type is PEQ, at least one source required
        if self._need_source:
            is_roomfit = (
                hasattr(self, "_roomfit_radio") and self._roomfit_radio.isChecked()
            )
            if not is_roomfit:
                has_source = any(
                    cb.isChecked() for cb in self._source_checkboxes.values()
                )
                ok_btn.setEnabled(has_source)
                return

        ok_btn.setEnabled(True)

    def _on_accept(self) -> None:
        """Gather selections and accept."""
        # EQ type
        if self._need_eq_type and hasattr(self, "_roomfit_radio"):
            self._eq_type = "roomfit" if self._roomfit_radio.isChecked() else "peq"
        else:
            self._eq_type = "peq"

        # Sources
        if self._need_source and hasattr(self, "_source_checkboxes"):
            self._selected_sources = [
                name for name, cb in self._source_checkboxes.items()
                if cb.isChecked()
            ]
        else:
            self._selected_sources = ["wifi"]

        self.accept()
