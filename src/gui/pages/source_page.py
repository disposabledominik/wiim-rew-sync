"""Source selection wizard page.

Displays audio sources available on the connected WiiM device and allows
the user to select which input(s) to apply PEQ to. Supports multi-selection
so the same filters can be pushed to multiple sources in a single action.

Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5, 3.6
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.gui.constants import (
    ACCENT_COLOR,
    LIST_ITEM_HEIGHT,
    MAX_CONTENT_WIDTH,
    SPACING_LG,
    SPACING_MD,
)


class SourcePage(QWidget):
    """Audio source/input selection page with multi-select support.

    Shows a list of device audio sources as selectable checkboxes.
    The currently active source is pre-selected with a "(currently active)"
    badge. Multiple sources can be selected — on push, filters are applied
    to all of them.

    An optional channel mode selector allows choosing between Stereo,
    Left, and Right when the device supports L/R mode.

    Signals:
        source_selected(str, str): Emitted when the user clicks Continue.
            Arguments are (comma-separated source names, channel_mode).
    """

    source_selected = Signal(str, str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._active_source: str = ""
        self._source_checkboxes: dict[str, QCheckBox] = {}

        self._setup_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_sources(self, sources: list[str], active_source: str = "") -> None:
        """Populate the source list with selectable items.

        Args:
            sources: List of available audio source names (e.g. "wifi", "HDMI").
            active_source: The currently active source on the device (if known).
                If empty, defaults to "wifi" as the recommended pre-selection.
        """
        self._active_source = active_source

        # Default to "wifi" if no active source detected (most common use case)
        default_source = active_source if active_source else "wifi"

        # Clear existing source checkboxes
        self._source_checkboxes.clear()
        while self._source_list_layout.count():
            item = self._source_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Create a checkbox for each source
        for source in sources:
            label = source
            if source == active_source and active_source:
                label = f"{source}  \u2014  currently active"
            elif source == default_source and not active_source:
                label = f"{source}  \u2014  recommended default"

            checkbox = QCheckBox(label)
            checkbox.setObjectName(f"source_checkbox_{source}")
            checkbox.setMinimumHeight(LIST_ITEM_HEIGHT)
            checkbox.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

            if source == default_source:
                checkbox.setStyleSheet(f"QCheckBox {{ color: {ACCENT_COLOR}; }}")
                checkbox.setChecked(True)

            checkbox.toggled.connect(self._on_source_toggled)
            self._source_list_layout.addWidget(checkbox)
            self._source_checkboxes[source] = checkbox

        self._update_continue_enabled()

    def set_channel_modes_visible(self, visible: bool) -> None:
        """Show or hide the channel mode selector section.

        Args:
            visible: True to show channel mode options, False to hide.
                When hidden, Stereo mode is used implicitly.
        """
        self._channel_section.setVisible(visible)

    # ------------------------------------------------------------------
    # Private setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Build the page layout."""
        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(SPACING_LG, SPACING_LG, SPACING_LG, SPACING_LG)

        # Content container with max width
        content = QWidget()
        content.setMaximumWidth(MAX_CONTENT_WIDTH)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(SPACING_LG, SPACING_LG, SPACING_LG, SPACING_LG)
        content_layout.setSpacing(SPACING_MD)

        # Title
        title = QLabel("Select Audio Source(s)")
        title.setObjectName("source_page_title")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        content_layout.addWidget(title)

        # Explanatory note (Req 3.4)
        note = QLabel(
            "PEQ settings are stored per-source. Select one or more inputs "
            "to apply EQ to.\n"
            "Tip: 'wifi' covers Wi-Fi, Ethernet, and USB playback. "
            "Sound/Lite models use 'auxIn' instead of 'line-in'."
        )
        note.setObjectName("source_page_note")
        note.setWordWrap(True)
        note.setStyleSheet("color: #616161; font-size: 13px;")
        content_layout.addWidget(note)

        # Source list area
        source_list_widget = QWidget()
        source_list_widget.setObjectName("source_list_container")
        self._source_list_layout = QVBoxLayout(source_list_widget)
        self._source_list_layout.setContentsMargins(0, 0, 0, 0)
        self._source_list_layout.setSpacing(0)
        content_layout.addWidget(source_list_widget)

        # Channel mode section (hidden by default, Req 3.5 / 3.6)
        self._channel_section = QWidget()
        self._channel_section.setObjectName("channel_mode_section")
        channel_layout = QVBoxLayout(self._channel_section)
        channel_layout.setContentsMargins(0, SPACING_MD, 0, 0)
        channel_layout.setSpacing(SPACING_MD)

        channel_label = QLabel("Channel Mode")
        channel_label.setObjectName("channel_mode_label")
        channel_label.setStyleSheet("font-size: 14px; font-weight: 600;")
        channel_layout.addWidget(channel_label)

        channel_buttons_widget = QWidget()
        channel_buttons_layout = QHBoxLayout(channel_buttons_widget)
        channel_buttons_layout.setContentsMargins(0, 0, 0, 0)
        channel_buttons_layout.setSpacing(SPACING_MD)

        self._channel_group = QButtonGroup(self)
        self._channel_group.setExclusive(True)

        self._radio_stereo = QRadioButton("Stereo")
        self._radio_stereo.setObjectName("channel_stereo")
        self._radio_stereo.setChecked(True)

        self._radio_left = QRadioButton("Left")
        self._radio_left.setObjectName("channel_left")

        self._radio_right = QRadioButton("Right")
        self._radio_right.setObjectName("channel_right")

        self._channel_group.addButton(self._radio_stereo)
        self._channel_group.addButton(self._radio_left)
        self._channel_group.addButton(self._radio_right)

        channel_buttons_layout.addWidget(self._radio_stereo)
        channel_buttons_layout.addWidget(self._radio_left)
        channel_buttons_layout.addWidget(self._radio_right)
        channel_buttons_layout.addStretch()

        channel_layout.addWidget(channel_buttons_widget)

        self._channel_section.setVisible(False)
        content_layout.addWidget(self._channel_section)

        # Spacer to push button to bottom
        content_layout.addStretch()

        # Continue button
        self._continue_btn = QPushButton("Continue")
        self._continue_btn.setObjectName("source_continue_btn")
        self._continue_btn.setEnabled(False)
        self._continue_btn.setMinimumHeight(LIST_ITEM_HEIGHT)
        self._continue_btn.setStyleSheet(
            f"QPushButton {{ background-color: {ACCENT_COLOR}; color: white;"
            f" border-radius: 6px; font-size: 14px; font-weight: 600; }}"
            f" QPushButton:disabled {{ background-color: #CCCCCC; color: #888888; }}"
        )
        self._continue_btn.clicked.connect(self._on_continue_clicked)
        content_layout.addWidget(self._continue_btn)

        outer_layout.addWidget(content)

    # ------------------------------------------------------------------
    # Private slots
    # ------------------------------------------------------------------

    def _on_source_toggled(self, checked: bool) -> None:
        """Handle source checkbox toggle."""
        self._update_continue_enabled()

    def _on_continue_clicked(self) -> None:
        """Emit source_selected with the chosen source(s) and channel mode."""
        sources = self._get_selected_sources()
        channel_mode = self._get_selected_channel_mode()
        if sources:
            # Emit comma-separated source names
            self.source_selected.emit(",".join(sources), channel_mode)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _update_continue_enabled(self) -> None:
        """Enable Continue button when at least one source is selected."""
        self._continue_btn.setEnabled(len(self._get_selected_sources()) > 0)

    def _get_selected_sources(self) -> list[str]:
        """Return the source names of all currently checked checkboxes."""
        selected = []
        for source_name, checkbox in self._source_checkboxes.items():
            if checkbox.isChecked():
                selected.append(source_name)
        return selected

    def _get_selected_channel_mode(self) -> str:
        """Return the selected channel mode string."""
        if self._radio_left.isChecked():
            return "Left"
        if self._radio_right.isChecked():
            return "Right"
        return "Stereo"
