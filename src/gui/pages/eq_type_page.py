"""EQ Type selection page: Parametric EQ vs RoomFit.

Presents a binary choice as two large clickable cards. The WizardController
decides whether to show this page based on device capabilities (roomfit_level >= 2).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.gui.components.page_layout import (
    build_centered_content,
    center_column,
    make_page_title,
)
from src.gui.constants import (
    SPACING_LG,
    SPACING_MD,
)
from src.gui.style_utils import set_qss_property


class _EQCard(QFrame):
    """Clickable card representing one EQ type option."""

    clicked = Signal()

    def __init__(self, heading: str, description: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("class", "card")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._selected = False

        # Layout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SPACING_LG, SPACING_LG, SPACING_LG, SPACING_LG)
        layout.setSpacing(SPACING_MD)

        # Heading
        heading_label = QLabel(heading)
        heading_label.setObjectName("cardHeading")
        heading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        heading_label.setProperty("class", "sectionTitle")
        layout.addWidget(heading_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Description
        desc_label = QLabel(description)
        desc_label.setObjectName("cardDescription")
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_label.setWordWrap(True)
        desc_label.setProperty("class", "secondary")
        layout.addWidget(desc_label)

        center_column(layout)
        self._apply_style()

    @property
    def selected(self) -> bool:
        """Whether this card is currently selected."""
        return self._selected

    def set_selected(self, selected: bool) -> None:
        """Update the selected state and visual style."""
        self._selected = selected
        self._apply_style()

    def mousePressEvent(self, event: object) -> None:
        """Emit clicked signal on mouse press."""
        self.clicked.emit()

    def _apply_style(self) -> None:
        """Apply border emphasis based on selected state via the QSS ``selected`` property."""
        set_qss_property(self, "selected", self._selected)


class EQTypePage(QWidget):
    """PEQ vs RoomFit selection page.

    Displays two large selectable cards. Emits eq_type_selected with
    'peq' or 'roomfit' when the user makes a choice.
    """

    eq_type_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._selected_type: str | None = None

        container_layout, container = build_centered_content(self)

        # Title
        title = make_page_title("Select EQ Type", container, object_name="EQTypePageTitle")
        container_layout.addWidget(title)

        # Cards layout (side by side)
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(SPACING_LG)

        # PEQ card
        self._peq_card = _EQCard(
            heading="Parametric EQ",
            description="Per-input EQ filters. Each source gets its own settings.",
        )
        self._peq_card.clicked.connect(self._on_peq_selected)
        cards_layout.addWidget(self._peq_card)

        # RoomFit card
        self._roomfit_card = _EQCard(
            heading="RoomFit",
            description="Room correction applied to all audio inputs.",
        )
        self._roomfit_card.clicked.connect(self._on_roomfit_selected)
        cards_layout.addWidget(self._roomfit_card)

        container_layout.addLayout(cards_layout)

    def _on_peq_selected(self) -> None:
        """Handle PEQ card click."""
        self._selected_type = "peq"
        self._peq_card.set_selected(True)
        self._roomfit_card.set_selected(False)
        self.eq_type_selected.emit("peq")

    def _on_roomfit_selected(self) -> None:
        """Handle RoomFit card click."""
        self._selected_type = "roomfit"
        self._peq_card.set_selected(False)
        self._roomfit_card.set_selected(True)
        self.eq_type_selected.emit("roomfit")

    @property
    def selected_type(self) -> str | None:
        """Return the currently selected EQ type, or None if nothing selected."""
        return self._selected_type
