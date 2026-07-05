"""Onboarding Overlay - first-run welcome screen.

Displays a semi-transparent overlay with 3 capability cards explaining
what the app does and a "Get Started" button to begin the wizard.
Shown only on first launch (when first_run_complete is False).

The overlay itself does NOT check settings - the parent widget is
responsible for showing/hiding it based on the first_run_complete flag.

Requirements referenced: 23.1, 23.2, 23.3, 23.5, 23.7.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from src.gui.constants import (
    FONT_SIZE_BODY,
    FONT_SIZE_TITLE,
    SPACING_LG,
    SPACING_MD,
    SPACING_SM,
    SPACING_XL,
)

# ---------------------------------------------------------------------------
# Capability card data
# ---------------------------------------------------------------------------

_CAPABILITY_CARDS: list[tuple[str, str, str]] = [
    (
        "\U0001F4E5",  # 📥
        "Import Filters",
        "Import parametric EQ from REW files or the REW API",
    ),
    (
        "\U0001F6E1\uFE0F",  # 🛡️
        "Push Safely",
        "Write EQ to your WiiM with automatic backup and verification",
    ),
    (
        "\U0001F4BE",  # 💾
        "Save Presets",
        "Build a local library of EQ presets for quick recall",
    ),
]


class OnboardingOverlay(QWidget):
    """First-run welcome overlay (Req 23).

    Displays a semi-transparent backdrop with a centered card containing:
    - Welcome title
    - Brief app description
    - 3 capability cards (Import, Push, Save)
    - "Get Started" primary button

    Signals:
        get_started_clicked: Emitted when user clicks "Get Started".
        skip_clicked: Emitted for backward compatibility (not used).

    The overlay rebuilds its UI on each show to pick up the active theme.
    """

    get_started_clicked = Signal()
    skip_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the onboarding overlay.

        Args:
            parent: Parent widget. The overlay will fill the parent's geometry.
        """
        super().__init__(parent)
        self.setObjectName("onboarding_overlay")
        # Fill entire parent area
        if parent is not None:
            self.setGeometry(parent.rect())
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._setup_ui()

    def showEvent(self, event: object) -> None:
        """Ensure the overlay fills the parent's geometry when shown."""
        super().showEvent(event)  # type: ignore[arg-type]
        if self.parent() is not None:
            self.setGeometry(self.parent().rect())  # type: ignore[union-attr]

    def _setup_ui(self) -> None:
        """Build the overlay layout."""
        # Root layout: centers the card
        root_layout = QVBoxLayout(self)
        root_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root_layout.setContentsMargins(SPACING_XL, SPACING_XL, SPACING_XL, SPACING_XL)

        # --- Central card ---
        card = QWidget()
        card.setObjectName("onboarding_card")
        card.setMaximumWidth(600)
        # Drop shadow for depth
        shadow = QGraphicsDropShadowEffect(card)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 8)
        shadow.setColor(Qt.GlobalColor.black)
        card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(SPACING_LG)
        card_layout.setContentsMargins(SPACING_XL, SPACING_XL, SPACING_XL, SPACING_XL)

        # --- Title ---
        title = QLabel("Welcome to WiiM PEQ Sync")
        title.setObjectName("onboarding_title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setMinimumHeight(FONT_SIZE_TITLE + SPACING_LG)
        card_layout.addWidget(title)

        # --- Subtitle ---
        subtitle = QLabel(
            "Transfer room correction filters between REW and your WiiM device."
        )
        subtitle.setObjectName("onboarding_subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setMinimumHeight(FONT_SIZE_BODY * 2 + SPACING_MD)
        card_layout.addWidget(subtitle)

        # --- Capability cards row ---
        cards_row = QWidget()
        cards_row.setObjectName("capability_cards_row")
        cards_layout = QHBoxLayout(cards_row)
        cards_layout.setSpacing(SPACING_MD)
        cards_layout.setContentsMargins(0, SPACING_MD, 0, SPACING_MD)

        for emoji, cap_title, cap_desc in _CAPABILITY_CARDS:
            cap_card = self._build_capability_card(emoji, cap_title, cap_desc)
            cards_layout.addWidget(cap_card)

        card_layout.addWidget(cards_row)

        # --- Buttons area ---
        buttons_area = QWidget()
        buttons_area.setObjectName("onboarding_buttons_area")
        buttons_layout = QVBoxLayout(buttons_area)
        buttons_layout.setSpacing(SPACING_SM)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Get Started button (primary accent)
        get_started_btn = QLabel("Get Started")
        get_started_btn.setObjectName("get_started_button")
        get_started_btn.setAlignment(Qt.AlignmentFlag.AlignCenter)
        get_started_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        get_started_btn.setFixedHeight(40)
        get_started_btn.setFixedWidth(200)
        get_started_btn.mousePressEvent = lambda _event: self._on_get_started()  # type: ignore[method-assign]
        buttons_layout.addWidget(get_started_btn, 0, Qt.AlignmentFlag.AlignCenter)

        card_layout.addWidget(buttons_area)

        root_layout.addWidget(card)

    def _build_capability_card(self, emoji: str, cap_title: str, cap_desc: str) -> QWidget:
        """Build a single capability card widget.

        Args:
            emoji: Emoji icon string.
            cap_title: Card title text.
            cap_desc: Card description text.

        Returns:
            QWidget containing the formatted card.
        """
        card = QWidget()
        card.setProperty("class", "onboardingCapCard")
        layout = QVBoxLayout(card)
        layout.setSpacing(SPACING_SM)
        layout.setContentsMargins(SPACING_SM, SPACING_MD, SPACING_SM, SPACING_MD)

        # Emoji icon
        icon_label = QLabel(emoji)
        icon_label.setObjectName("onboarding_cap_icon")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon_label, alignment=Qt.AlignmentFlag.AlignHCenter)

        # Title
        title_label = QLabel(cap_title)
        title_label.setProperty("class", "onboardingCapTitle")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        # Description
        desc_label = QLabel(cap_desc)
        desc_label.setProperty("class", "onboardingCapDesc")
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        # Anchors content to the top of the card (matches the previous
        # AlignTop intent) without an item/layout alignment flag, which
        # would otherwise break height-for-width sizing on the wrapped
        # title/desc labels above (smoke #180).
        layout.addStretch()
        return card

    def _on_get_started(self) -> None:
        """Handle 'Get Started' click - dismiss overlay and signal."""
        self.get_started_clicked.emit()
        self.hide()

    def _on_skip(self) -> None:
        """Handle 'Skip' click - dismiss overlay and signal."""
        self.skip_clicked.emit()
        self.hide()

    def resizeEvent(self, event: object) -> None:
        """Resize overlay to match parent when parent is resized."""
        super().resizeEvent(event)  # type: ignore[arg-type]
        if self.parent() is not None:
            self.setGeometry(self.parent().rect())  # type: ignore[union-attr]
