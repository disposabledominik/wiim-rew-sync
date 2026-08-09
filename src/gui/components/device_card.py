"""DeviceCard — clickable card showing device info and connection state.

Displays device name, model, and IP address in a single row. Supports three
visual states: idle, connecting, connected. Emits ``clicked`` when the card
is selected.

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
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.gui.constants import ANIMATION_NORMAL, SPACING_MD, SPACING_SM
from src.gui.style_utils import set_qss_property


class DeviceCard(QFrame):
    """Clickable card representing a discovered WiiM device.

    The card displays the device name, model, and IP address in a single
    row (name left-aligned and larger, model centered, IP right-aligned).
    Visual state is controlled via :meth:`set_state` and drives QSS styling
    through the ``state`` dynamic property.

    Signals:
        clicked: Emitted when the card body is clicked (device selection).
    """

    clicked = Signal()

    # Valid state values
    _VALID_STATES = frozenset({"idle", "connecting", "connected"})

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DeviceCard")
        self.setProperty("class", "card")
        self.setProperty("state", "idle")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFrameShape(QFrame.Shape.StyledPanel)

        # --- Main layout ------------------------------------------------------
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(SPACING_MD, SPACING_SM, SPACING_MD, SPACING_SM)
        self._main_layout.setSpacing(SPACING_SM)

        # Info row: name (left) / model (center) / IP (right), equal thirds
        info_row = QHBoxLayout()
        info_row.setSpacing(SPACING_MD)
        info_row.setContentsMargins(0, 0, 0, 0)

        self._name_label = QLabel(self)
        self._name_label.setObjectName("DeviceCardName")
        self._name_label.setProperty("class", "subheading")
        self._name_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        info_row.addWidget(self._name_label, 1)

        self._model_label = QLabel(self)
        self._model_label.setObjectName("DeviceCardModel")
        self._model_label.setProperty("class", "secondary")
        self._model_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._model_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        info_row.addWidget(self._model_label, 1)

        self._ip_label = QLabel(self)
        self._ip_label.setObjectName("DeviceCardIP")
        self._ip_label.setProperty("class", "secondary")
        self._ip_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._ip_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        info_row.addWidget(self._ip_label, 1)

        self._main_layout.addLayout(info_row)

        # --- Pulsing animation for connecting state ---------------------------
        self._pulse_animation: QPropertyAnimation | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_device_info(self, name: str, model: str, ip: str) -> None:
        """Populate the card with device information.

        Args:
            name: Device display name (e.g. "Living Room WiiM Pro").
            model: Device model (e.g. "WiiM Pro Plus").
            ip: IP address (e.g. "192.168.1.42").
        """
        self._name_label.setText(name)
        self._model_label.setText(model)
        self._ip_label.setText(ip)

    def set_state(self, state: str) -> None:
        """Set the visual state of the card.

        Args:
            state: One of "idle", "connecting", "connected".

        Raises:
            ValueError: If *state* is not a recognized value.
        """
        if state not in self._VALID_STATES:
            msg = f"Invalid state {state!r}; expected one of {sorted(self._VALID_STATES)}"
            raise ValueError(msg)

        set_qss_property(self, "state", state)

        # Stop any existing animation
        self._stop_pulse()

        if state == "connecting":
            self._start_pulse()

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
