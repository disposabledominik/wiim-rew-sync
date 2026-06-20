"""DeviceCard — clickable card showing device info and connection state.

Displays device name, model, IP address, firmware version, and multiroom
role badge. Supports four visual states: idle, connecting, connected, error.
Emits ``clicked`` when the card is selected and ``retry_clicked`` when the
retry button is pressed in the error state.

Requirements referenced: 2.3, 2.7, 2.9.
"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    Signal,
)
from PySide6.QtGui import QCursor, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.gui.constants import (
    ACCENT_COLOR,
    ANIMATION_NORMAL,
    CARD_RADIUS,
    ERROR_COLOR,
    FONT_SIZE_BODY,
    FONT_SIZE_CAPTION,
    FONT_SIZE_HEADING,
    FONT_WEIGHT_SEMIBOLD,
    SPACING_MD,
    SPACING_SM,
    SPACING_XS,
)


class DeviceCard(QFrame):
    """Clickable card representing a discovered WiiM device.

    The card displays the device name (heading), model, IP address, firmware
    version, and an optional multiroom role badge. Visual state is controlled
    via :meth:`set_state` and drives QSS styling through the ``state`` dynamic
    property.

    Signals:
        clicked: Emitted when the card body is clicked (device selection).
        retry_clicked: Emitted when the retry button is pressed in error state.
    """

    clicked = Signal()
    retry_clicked = Signal()

    # Valid state values
    _VALID_STATES = frozenset({"idle", "connecting", "connected", "error"})

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DeviceCard")
        self.setProperty("class", "card")
        self.setProperty("state", "idle")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFrameShape(QFrame.Shape.StyledPanel)

        # --- Stylesheet (inline for self-contained rendering) -----------------
        self._apply_base_style()

        # --- Main layout ------------------------------------------------------
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(SPACING_MD, SPACING_MD, SPACING_MD, SPACING_MD)
        self._main_layout.setSpacing(SPACING_SM)

        # Device name (heading)
        self._name_label = QLabel(self)
        self._name_label.setObjectName("DeviceCardName")
        self._name_label.setStyleSheet(
            f"font-size: {FONT_SIZE_HEADING}px; font-weight: {FONT_WEIGHT_SEMIBOLD};"
        )
        self._main_layout.addWidget(self._name_label)

        # Model (secondary text)
        self._model_label = QLabel(self)
        self._model_label.setObjectName("DeviceCardModel")
        self._model_label.setStyleSheet(f"font-size: {FONT_SIZE_BODY}px; color: #616161;")
        self._main_layout.addWidget(self._model_label)

        # Info row: IP + firmware
        info_row = QHBoxLayout()
        info_row.setSpacing(SPACING_MD)
        info_row.setContentsMargins(0, 0, 0, 0)

        self._ip_label = QLabel(self)
        self._ip_label.setObjectName("DeviceCardIP")
        self._ip_label.setStyleSheet(f"font-size: {FONT_SIZE_CAPTION}px; color: #9E9E9E;")
        info_row.addWidget(self._ip_label)

        self._firmware_label = QLabel(self)
        self._firmware_label.setObjectName("DeviceCardFirmware")
        self._firmware_label.setStyleSheet(f"font-size: {FONT_SIZE_CAPTION}px; color: #9E9E9E;")
        info_row.addWidget(self._firmware_label)

        info_row.addStretch()
        self._main_layout.addLayout(info_row)

        # Role badge (pill-shaped label, hidden by default)
        self._role_badge = QLabel(self)
        self._role_badge.setObjectName("DeviceCardRoleBadge")
        self._role_badge.setVisible(False)
        self._role_badge.setStyleSheet(
            f"font-size: {FONT_SIZE_CAPTION}px; "
            f"background-color: {ACCENT_COLOR}; "
            "color: #FFFFFF; "
            f"border-radius: {SPACING_SM}px; "
            f"padding: {SPACING_XS}px {SPACING_SM}px;"
        )
        self._role_badge.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._main_layout.addWidget(self._role_badge)

        # Error row (hidden by default): error message + retry button
        self._error_widget = QWidget(self)
        self._error_widget.setVisible(False)
        error_layout = QHBoxLayout(self._error_widget)
        error_layout.setContentsMargins(0, SPACING_XS, 0, 0)
        error_layout.setSpacing(SPACING_SM)

        self._error_label = QLabel(self._error_widget)
        self._error_label.setObjectName("DeviceCardError")
        self._error_label.setStyleSheet(
            f"font-size: {FONT_SIZE_CAPTION}px; color: {ERROR_COLOR};"
        )
        self._error_label.setWordWrap(True)
        self._error_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        error_layout.addWidget(self._error_label)

        self._retry_button = QPushButton("Retry", self._error_widget)
        self._retry_button.setObjectName("DeviceCardRetry")
        self._retry_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._retry_button.clicked.connect(self._on_retry_clicked)
        error_layout.addWidget(self._retry_button)

        self._main_layout.addWidget(self._error_widget)

        # --- Pulsing animation for connecting state ---------------------------
        self._pulse_animation: QPropertyAnimation | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_device_info(
        self,
        name: str,
        model: str,
        ip: str,
        firmware: str,
        role: str = "",
    ) -> None:
        """Populate the card with device information.

        Args:
            name: Device display name (e.g. "Living Room WiiM Pro").
            model: Device model (e.g. "WiiM Pro Plus").
            ip: IP address (e.g. "192.168.1.42").
            firmware: Firmware version string (e.g. "v4.8.1").
            role: Multiroom role ("Leader", "Follower", or empty for solo).
        """
        self._name_label.setText(name)
        self._model_label.setText(model)
        self._ip_label.setText(ip)
        self._firmware_label.setText(firmware)

        if role:
            self._role_badge.setText(role)
            self._role_badge.setVisible(True)
        else:
            self._role_badge.setVisible(False)

    def set_state(self, state: str) -> None:
        """Set the visual state of the card.

        Args:
            state: One of "idle", "connecting", "connected", "error".

        Raises:
            ValueError: If *state* is not a recognized value.
        """
        if state not in self._VALID_STATES:
            msg = f"Invalid state {state!r}; expected one of {sorted(self._VALID_STATES)}"
            raise ValueError(msg)

        self.setProperty("state", state)
        self._apply_base_style()

        # Stop any existing animation
        self._stop_pulse()

        # Hide error row unless in error state
        if state != "error":
            self._error_widget.setVisible(False)

        if state == "connecting":
            self._start_pulse()
        elif state == "error":
            self._error_widget.setVisible(True)

    def set_error(self, message: str) -> None:
        """Set the card to error state with the given message.

        Convenience method that calls :meth:`set_state` with ``"error"`` and
        populates the error label.

        Args:
            message: Human-readable error description.
        """
        self._error_label.setText(message)
        self.set_state("error")

    # ------------------------------------------------------------------
    # Event handling
    # ------------------------------------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Emit clicked signal on left-button press."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _apply_base_style(self) -> None:
        """Apply stylesheet based on current state property."""
        state = self.property("state") or "idle"

        # Base card style
        base = (
            f"QFrame#DeviceCard {{"
            f"  border-radius: {CARD_RADIUS}px;"
            f"  padding: {SPACING_MD}px;"
            f"  background-color: #FFFFFF;"
        )

        if state == "idle":
            style = base + "  border: 1px solid #E0E0E0;}"
        elif state == "connecting":
            style = base + f"  border: 2px solid {ACCENT_COLOR};}}"
            # Opacity handled by animation
            return self._set_card_style(style)
        elif state == "connected":
            style = base + f"  border: 1px solid #E0E0E0; border-left: 3px solid {ACCENT_COLOR};}}"
        elif state == "error":
            style = base + f"  border: 1px solid #E0E0E0; border-left: 3px solid {ERROR_COLOR};}}"
        else:
            style = base + "  border: 1px solid #E0E0E0;}"

        self._set_card_style(style)

    def _set_card_style(self, style: str) -> None:
        """Apply the given stylesheet to the frame."""
        self.setStyleSheet(style)

    def _start_pulse(self) -> None:
        """Start pulsing opacity animation for connecting state."""
        self._pulse_animation = QPropertyAnimation(self, b"windowOpacity")
        self._pulse_animation.setDuration(ANIMATION_NORMAL * 4)
        self._pulse_animation.setStartValue(1.0)
        self._pulse_animation.setKeyValueAt(0.5, 0.6)
        self._pulse_animation.setEndValue(1.0)
        self._pulse_animation.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._pulse_animation.setLoopCount(-1)  # Loop indefinitely
        self._pulse_animation.start()

    def _stop_pulse(self) -> None:
        """Stop pulsing animation and reset opacity."""
        if self._pulse_animation is not None:
            self._pulse_animation.stop()
            self._pulse_animation = None
        # Ensure full opacity
        self.setWindowOpacity(1.0)

    def _on_retry_clicked(self) -> None:
        """Handle retry button click without propagating as card click."""
        self.retry_clicked.emit()
