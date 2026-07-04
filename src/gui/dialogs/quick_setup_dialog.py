"""QuickSetupDialog — completes missing wizard state before loading filters.

When a user loads a preset/profile from the sidebar before completing
all wizard steps, this dialog asks only for the missing information
(EQ type, source selection) so the filters can be applied correctly.

Always renders both the EQ Type and Source sections in a single fixed
layout. Sections (or individual controls) whose value is already fixed by
prior wizard context, or unsupported by the connected device, are disabled
rather than hidden -- so the dialog's size and layout never change between
PEQ and RoomFit selections (issue: layout reflow between the three previous
need_eq_type/need_source variants).

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
    SPACING_LG,
    SPACING_MD,
    SPACING_SM,
)


class QuickSetupDialog(QDialog):
    """Modal dialog that collects missing wizard state before loading filters.

    Both the EQ Type and Source sections are always shown; a section (or a
    single control within it) is disabled instead of hidden when its value
    is already fixed by prior wizard context or unsupported by the device,
    so the dialog layout stays stable regardless of context or selection.
    """

    def __init__(
        self,
        parent: QWidget | None,
        need_eq_type: bool = False,
        need_source: bool = False,
        available_sources: list[str] | None = None,
        current_eq_type: str = "peq",
        current_sources: list[str] | None = None,
        supports_roomfit: bool = True,
    ) -> None:
        """Initialize the dialog.

        Args:
            parent: Parent widget.
            need_eq_type: Whether EQ type still needs to be chosen. When
                False, the EQ Type section is shown pre-set to
                `current_eq_type` but disabled.
            need_source: Whether source selection still needs to be made.
                When False, the Source section is shown pre-set to
                `current_sources` but disabled.
            available_sources: Source names to offer, from the connected
                device's (capability-file-merged) capabilities -- resolved
                and guaranteed non-empty by merge_into() (#167b). Callers
                should never need to pass a generic fallback list here.
            current_eq_type: The already-fixed EQ type ('peq'/'roomfit'),
                used to pre-select the section when `need_eq_type` is False.
            current_sources: The already-fixed source selection, used to
                pre-select the section when `need_source` is False.
            supports_roomfit: Whether the connected device supports RoomFit
                at all. When False, the RoomFit option is disabled with an
                explanatory tooltip regardless of `need_eq_type`.
        """
        super().__init__(parent)
        self.setWindowTitle("Complete Setup")
        self.setMinimumWidth(360)
        self.setModal(True)

        self._need_eq_type = need_eq_type
        self._need_source = need_source
        self._available_sources = available_sources or []
        self._supports_roomfit = supports_roomfit

        self._eq_type: str = current_eq_type if current_eq_type == "roomfit" else "peq"
        self._selected_sources: list[str] = list(current_sources or [])

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
        current_eq_type: str = "peq",
        current_sources: list[str] | None = None,
        supports_roomfit: bool = True,
    ) -> tuple[str, list[str]] | None:
        """Show dialog and return (eq_type, sources) or None if cancelled.

        Args:
            parent: Parent widget.
            need_eq_type: Whether EQ type selection is needed.
            need_source: Whether source selection is needed.
            available_sources: Available sources for selection.
            current_eq_type: Already-fixed EQ type, shown disabled when
                `need_eq_type` is False.
            current_sources: Already-fixed sources, shown disabled when
                `need_source` is False.
            supports_roomfit: Whether the connected device supports RoomFit.

        Returns:
            Tuple of (eq_type, selected_sources) or None if cancelled.
        """
        dialog = QuickSetupDialog(
            parent,
            need_eq_type,
            need_source,
            available_sources,
            current_eq_type,
            current_sources,
            supports_roomfit,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.eq_type, dialog.selected_sources
        return None

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Build the dialog layout — both sections always present."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_LG, SPACING_LG, SPACING_LG, SPACING_LG)
        layout.setSpacing(SPACING_LG)

        instruction = QLabel("Before loading, please confirm the following:")
        instruction.setWordWrap(True)
        layout.addWidget(instruction)

        # --- EQ Type section (always present) ---
        self._eq_section = eq_section = QWidget()
        eq_layout = QVBoxLayout(eq_section)
        eq_layout.setContentsMargins(0, 0, 0, 0)
        eq_layout.setSpacing(SPACING_SM)

        eq_label = QLabel("EQ Type:")
        eq_label.setProperty("class", "fieldLabel")
        eq_layout.addWidget(eq_label)

        eq_buttons = QHBoxLayout()
        eq_buttons.setSpacing(SPACING_MD)
        self._eq_group = QButtonGroup(self)

        self._peq_radio = QRadioButton("PEQ")
        self._roomfit_radio = QRadioButton("RoomFit")
        self._eq_group.addButton(self._peq_radio)
        self._eq_group.addButton(self._roomfit_radio)
        (self._roomfit_radio if self._eq_type == "roomfit" else self._peq_radio).setChecked(True)

        eq_buttons.addWidget(self._peq_radio)
        eq_buttons.addWidget(self._roomfit_radio)
        eq_buttons.addStretch()
        eq_layout.addLayout(eq_buttons)
        layout.addWidget(eq_section)

        # Locked by prior wizard context — show the fixed value, disabled.
        eq_section.setEnabled(self._need_eq_type)

        # Unsupported by the connected device — disabled regardless of context.
        if not self._supports_roomfit:
            self._roomfit_radio.setEnabled(False)
            self._roomfit_radio.setToolTip("This device does not support RoomFit.")

        self._roomfit_radio.toggled.connect(self._on_eq_type_toggled)

        # --- Source section (always present) ---
        self._source_section = QWidget()
        source_layout = QVBoxLayout(self._source_section)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(SPACING_SM)

        source_label = QLabel("Target source(s):")
        source_label.setProperty("class", "fieldLabel")
        source_layout.addWidget(source_label)

        self._source_checkboxes: dict[str, QCheckBox] = {}
        preset_sources = set(self._selected_sources)
        for source in self._available_sources:
            cb = QCheckBox(source)
            if (preset_sources and source in preset_sources) or (
                not preset_sources and source == "wifi"
            ):
                cb.setChecked(True)
                cb.setProperty("class", "accent")
            cb.toggled.connect(self._on_source_toggled)
            source_layout.addWidget(cb)
            self._source_checkboxes[source] = cb

        layout.addWidget(self._source_section)

        # Locked by prior wizard context, or greyed while RoomFit is selected
        # (RoomFit is device-global -- Rule: RoomFit filters are not per-input).
        self._update_source_section_enabled()

        # Buttons
        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._button_box.accepted.connect(self._on_accept)
        self._button_box.rejected.connect(self.reject)
        layout.addWidget(self._button_box)

        self._update_ok_enabled()

    def _on_eq_type_toggled(self, _checked: bool) -> None:
        """Grey out the source section (not hide) when RoomFit is selected."""
        self._update_source_section_enabled()
        self._update_ok_enabled()

    def _update_source_section_enabled(self) -> None:
        """Source section is greyed when RoomFit is selected or context-locked."""
        is_roomfit = self._roomfit_radio.isChecked()
        self._source_section.setEnabled(self._need_source and not is_roomfit)

    def _on_source_toggled(self, _checked: bool) -> None:
        """Update OK button state when source selection changes."""
        self._update_ok_enabled()

    def _update_ok_enabled(self) -> None:
        """Enable OK only when required fields are filled."""
        ok_btn = self._button_box.button(QDialogButtonBox.StandardButton.Ok)
        if not ok_btn:
            return

        is_roomfit = self._roomfit_radio.isChecked()
        if self._need_source and not is_roomfit:
            has_source = any(cb.isChecked() for cb in self._source_checkboxes.values())
            ok_btn.setEnabled(has_source)
            return

        ok_btn.setEnabled(True)

    def _on_accept(self) -> None:
        """Gather selections and accept."""
        self._eq_type = "roomfit" if self._roomfit_radio.isChecked() else "peq"

        if self._need_source and self._eq_type != "roomfit":
            self._selected_sources = [
                name for name, cb in self._source_checkboxes.items() if cb.isChecked()
            ]
        elif not self._selected_sources:
            self._selected_sources = ["wifi"]

        self.accept()
