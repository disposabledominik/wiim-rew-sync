"""Developer diagnostics panel.

Provides raw command input, response display, capability dump, and log tail
for debugging. Intended for use inside a QDockWidget. This panel does NOT
execute commands itself - it emits signals for the controller layer to handle.
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.models.capabilities import DeviceCapabilities

_LOG_TAIL_LINES = 100


def _monospace_font() -> QFont:
    """Create a monospace font for code/log displays.

    Returns:
        A QFont configured as monospace, size 9.
    """
    font = QFont("Courier New", 9)
    font.setStyleHint(QFont.StyleHint.Monospace)
    return font


class DiagnosticsPanel(QWidget):
    """Developer diagnostics panel for raw device interaction and log viewing.

    Signals:
        raw_command_requested: Emitted with the command text when Send is clicked.
    """

    raw_command_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the diagnostics panel.

        Args:
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        """Build the panel layout with header, command input, and displays."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # --- Warning header ---
        header_label = QLabel(
            "\u26a0 Developer Diagnostics - Not for production use"
        )
        header_label.setStyleSheet("font-weight: bold; color: #e67e22;")
        layout.addWidget(header_label)

        # --- Raw command input ---
        cmd_group = QGroupBox("Raw Command")
        cmd_layout = QHBoxLayout(cmd_group)
        self._command_input = QLineEdit()
        self._command_input.setPlaceholderText("Enter httpapi command...")
        cmd_layout.addWidget(self._command_input)
        self._send_btn = QPushButton("Send")
        self._send_btn.setFixedWidth(80)
        cmd_layout.addWidget(self._send_btn)
        layout.addWidget(cmd_group)

        # --- Response display ---
        resp_group = QGroupBox("Raw Response")
        resp_layout = QVBoxLayout(resp_group)
        self._response_display = QTextEdit()
        self._response_display.setReadOnly(True)
        self._response_display.setFont(_monospace_font())
        self._response_display.setMaximumHeight(150)
        resp_layout.addWidget(self._response_display)
        layout.addWidget(resp_group)

        # --- Capability dump ---
        caps_group = QGroupBox("Device Capabilities")
        caps_layout = QVBoxLayout(caps_group)
        self._capabilities_display = QTextEdit()
        self._capabilities_display.setReadOnly(True)
        self._capabilities_display.setFont(_monospace_font())
        self._capabilities_display.setMaximumHeight(200)
        caps_layout.addWidget(self._capabilities_display)
        layout.addWidget(caps_group)

        # --- Log tail ---
        log_group = QGroupBox("Log Tail (wiim_api.log)")
        log_layout = QVBoxLayout(log_group)
        self._log_display = QTextEdit()
        self._log_display.setReadOnly(True)
        self._log_display.setFont(_monospace_font())
        log_layout.addWidget(self._log_display)
        layout.addWidget(log_group)

    def _connect_signals(self) -> None:
        """Wire internal widget signals."""
        self._send_btn.clicked.connect(self._on_send_clicked)
        self._command_input.returnPressed.connect(self._on_send_clicked)

    def _on_send_clicked(self) -> None:
        """Handle Send button click or Enter key in command input."""
        command = self._command_input.text().strip()
        if command:
            self.raw_command_requested.emit(command)

    # --- Public slots ---

    def on_raw_response(self, response: str) -> None:
        """Display raw response text from a command.

        Args:
            response: The raw response string to display.
        """
        self._response_display.setPlainText(response)

    def on_capabilities_ready(self, capabilities: DeviceCapabilities) -> None:
        """Update the capability dump display with formatted JSON.

        Args:
            capabilities: The probed device capabilities.
        """
        caps_dict = capabilities.model_dump()
        formatted = json.dumps(caps_dict, indent=2, default=str)
        self._capabilities_display.setPlainText(formatted)

    def refresh_log_tail(self, log_path: Path) -> None:
        """Read and display the last 100 lines of the specified log file.

        Performs synchronous file I/O (acceptable for a local ~100-line read).

        Args:
            log_path: Path to the log file to tail.
        """
        try:
            if not log_path.exists():
                self._log_display.setPlainText(f"Log file not found: {log_path}")
                return
            lines = log_path.read_text(encoding="utf-8").splitlines()
            tail = lines[-_LOG_TAIL_LINES:]
            self._log_display.setPlainText("\n".join(tail))
        except OSError as e:
            self._log_display.setPlainText(f"Error reading log: {e}")
