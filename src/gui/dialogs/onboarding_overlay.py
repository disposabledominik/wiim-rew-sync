"""Onboarding Overlay - first-run welcome screen.

Displays a semi-transparent overlay with 3 capability cards explaining
what the app does and a "Get Started" button to begin the wizard.
Shown only on first launch (when first_run_complete is False).

The overlay itself does NOT check settings - the parent widget is
responsible for showing/hiding it based on the first_run_complete flag.

Requirements referenced: 23.1, 23.2, 23.3, 23.4, 23.5, 23.7.
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
    ACCENT_COLOR,
    BUTTON_RADIUS,
    CARD_RADIUS,
    COLORS_DARK,
    COLORS_LIGHT,
    FONT_FAMILY,
    FONT_SIZE_BODY,
    FONT_SIZE_CAPTION,
    FONT_SIZE_HEADING,
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
        self.setStyleSheet(
            "QWidget#onboarding_overlay {"
            "  background-color: rgba(0, 0, 0, 0.55);"
            "}"
        )
        self._setup_ui()

    def showEvent(self, event: object) -> None:
        """Rebuild UI on show to pick up current theme colors."""
        super().showEvent(event)  # type: ignore[arg-type]
        # Remove old layout and rebuild with current theme
        old_layout = self.layout()
        if old_layout is not None:
            # Delete all child widgets
            while old_layout.count():
                item = old_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            QWidget().setLayout(old_layout)  # Detach layout
        self._setup_ui()

    def _get_colors(self) -> tuple[str, str, str, str, str, str]:
        """Return theme-appropriate colors.

        Returns a tuple of (surface, text_primary, text_secondary,
        text_on_accent, background, border_subtle).
        """
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        # Detect if dark theme is active by checking the app stylesheet
        is_dark = False
        if app is not None:
            stylesheet = app.styleSheet()  # type: ignore[union-attr]
            if stylesheet and "background-color: #1E1E1E" in stylesheet:
                is_dark = True

        colors = COLORS_DARK if is_dark else COLORS_LIGHT
        return (
            colors.surface,
            colors.text_primary,
            colors.text_secondary,
            colors.text_on_accent,
            colors.background,
            colors.border_subtle,
        )

    def _setup_ui(self) -> None:
        """Build the overlay layout."""
        surface, text_primary, text_secondary, text_on_accent, background, border_subtle = (
            self._get_colors()
        )

        # Root layout: centers the card
        root_layout = QVBoxLayout(self)
        root_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root_layout.setContentsMargins(SPACING_XL, SPACING_XL, SPACING_XL, SPACING_XL)

        # --- Central card ---
        card = QWidget()
        card.setObjectName("onboarding_card")
        card.setMaximumWidth(600)
        card.setStyleSheet(
            f"QWidget#onboarding_card {{"
            f"  background-color: {surface};"
            f"  border-radius: {CARD_RADIUS + 4}px;"
            f"  padding: {SPACING_XL}px;"
            f"}}"
        )
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
        title.setStyleSheet(
            f"font-family: {FONT_FAMILY};"
            f"font-size: {FONT_SIZE_TITLE}px;"
            "font-weight: 700;"
            f"color: {text_primary};"
            "background: transparent;"
        )
        title.setMinimumHeight(FONT_SIZE_TITLE + SPACING_LG)
        card_layout.addWidget(title)

        # --- Subtitle ---
        subtitle = QLabel(
            "Transfer room correction filters between REW and your WiiM device."
        )
        subtitle.setObjectName("onboarding_subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            f"font-family: {FONT_FAMILY};"
            f"font-size: {FONT_SIZE_BODY}px;"
            f"color: {text_secondary};"
            "background: transparent;"
        )
        subtitle.setMinimumHeight(FONT_SIZE_BODY * 2 + SPACING_MD)
        card_layout.addWidget(subtitle)

        # --- Capability cards row ---
        cards_row = QWidget()
        cards_row.setObjectName("capability_cards_row")
        cards_row.setStyleSheet("background: transparent;")
        cards_layout = QHBoxLayout(cards_row)
        cards_layout.setSpacing(SPACING_MD)
        cards_layout.setContentsMargins(0, SPACING_MD, 0, SPACING_MD)

        for emoji, cap_title, cap_desc in _CAPABILITY_CARDS:
            cap_card = self._build_capability_card(
                emoji, cap_title, cap_desc,
                background, text_primary, text_secondary, border_subtle,
            )
            cards_layout.addWidget(cap_card)

        card_layout.addWidget(cards_row)

        # --- Buttons area ---
        buttons_area = QWidget()
        buttons_area.setStyleSheet("background: transparent;")
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
        get_started_btn.setStyleSheet(
            f"background-color: {ACCENT_COLOR};"
            f"color: {text_on_accent};"
            f"border-radius: {BUTTON_RADIUS}px;"
            f"font-family: {FONT_FAMILY};"
            f"font-size: {FONT_SIZE_BODY}px;"
            "font-weight: 600;"
            "padding: 8px 24px;"
        )
        get_started_btn.mousePressEvent = lambda _event: self._on_get_started()  # type: ignore[method-assign]
        buttons_layout.addWidget(get_started_btn, 0, Qt.AlignmentFlag.AlignCenter)

        card_layout.addWidget(buttons_area)

        root_layout.addWidget(card)

    def _build_capability_card(
        self,
        emoji: str,
        cap_title: str,
        cap_desc: str,
        background: str,
        text_primary: str,
        text_secondary: str,
        border_subtle: str,
    ) -> QWidget:
        """Build a single capability card widget.

        Args:
            emoji: Emoji icon string.
            cap_title: Card title text.
            cap_desc: Card description text.
            background: Background color for the card.
            text_primary: Primary text color.
            text_secondary: Secondary text color.
            border_subtle: Subtle border color.

        Returns:
            QWidget containing the formatted card.
        """
        card = QWidget()
        card.setObjectName(f"cap_card_{cap_title.lower().replace(' ', '_')}")
        card.setStyleSheet(
            f"QWidget#{card.objectName()} {{"
            f"  background-color: {background};"
            f"  border-radius: {CARD_RADIUS}px;"
            f"  border: 1px solid {border_subtle};"
            f"  padding: {SPACING_MD}px;"
            f"}}"
        )
        layout = QVBoxLayout(card)
        layout.setSpacing(SPACING_SM)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        layout.setContentsMargins(SPACING_SM, SPACING_MD, SPACING_SM, SPACING_MD)

        # Emoji icon
        icon_label = QLabel(emoji)
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet(
            "font-size: 32px; background: transparent;"
        )
        layout.addWidget(icon_label)

        # Title
        title_label = QLabel(cap_title)
        title_label.setObjectName(f"cap_title_{cap_title.lower().replace(' ', '_')}")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setWordWrap(True)
        title_label.setMinimumHeight(FONT_SIZE_HEADING + SPACING_SM)
        title_label.setStyleSheet(
            f"font-family: {FONT_FAMILY};"
            f"font-size: {FONT_SIZE_HEADING - 4}px;"
            "font-weight: 600;"
            f"color: {text_primary};"
            "background: transparent;"
        )
        layout.addWidget(title_label)

        # Description
        desc_label = QLabel(cap_desc)
        desc_label.setObjectName(f"cap_desc_{cap_title.lower().replace(' ', '_')}")
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_label.setWordWrap(True)
        desc_label.setMinimumHeight(FONT_SIZE_CAPTION * 3 + SPACING_SM)
        desc_label.setStyleSheet(
            f"font-family: {FONT_FAMILY};"
            f"font-size: {FONT_SIZE_CAPTION}px;"
            f"color: {text_secondary};"
            "background: transparent;"
        )
        layout.addWidget(desc_label)

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
