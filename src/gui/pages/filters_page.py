"""FiltersPage — filter loading wizard step.

Presents a Stereo/L/R toggle and file browse buttons for loading REW EQ files.
Supports inline validation warnings and error display with retry.

The page does NOT perform network I/O — it only emits signals.

Requirements referenced: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 9.3.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
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
    ERROR_COLOR,
    FONT_SIZE_BODY,
    FONT_SIZE_HEADING,
    FONT_WEIGHT_SEMIBOLD,
    SPACING_LG,
    SPACING_MD,
    SPACING_SM,
    WARNING_COLOR,
)


class FiltersPage(QWidget):
    """Filter loading step with Stereo/L/R toggle and file browse buttons.

    The page always shows:
    - A Stereo vs L/R radio toggle
    - File browse button(s) depending on mode
    - Inline warnings/errors after import

    Signals:
        file_import_requested: Path to a single REW .txt file (stereo mode).
        file_import_lr_requested: Paths to left and right channel files.
        device_pull_requested: (unused — kept for interface compatibility).
        rew_api_pull_requested: (unused — kept for interface compatibility).
        roomfit_profile_selected: User selected a RoomFit profile name.
        filters_accepted: User clicked "Continue with adjustments" after warnings.
    """

    file_import_requested = Signal(str)
    file_import_lr_requested = Signal(str, str)
    device_pull_requested = Signal()
    rew_api_pull_requested = Signal()
    roomfit_profile_selected = Signal(str)
    filters_accepted = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FiltersPage")
        self._channel_mode: str = "stereo"
        self._roomfit_mode: bool = False
        self._stereo_path: str = ""
        self._left_path: str = ""
        self._right_path: str = ""
        self._setup_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_rew_api_available(self, available: bool) -> None:
        """No-op (kept for interface compatibility)."""

    def set_roomfit_mode(self, enabled: bool) -> None:
        """Toggle RoomFit mode flag.

        RoomFit profile pull is accessible via the "Presets on Device" sidebar.
        The Filters page always shows the file import flow regardless of EQ type.
        """
        self._roomfit_mode = enabled

    def set_roomfit_profiles(self, profiles: list[str]) -> None:
        """Populate the RoomFit profile dropdown (kept for interface compat).

        Args:
            profiles: List of profile names available on the device.
        """
        self._roomfit_combo.clear()
        self._roomfit_combo.addItem("Select a profile...")
        self._roomfit_combo.addItems(profiles)

    def set_channel_mode(self, mode: str) -> None:
        """Set stereo or L/R channel mode.

        Args:
            mode: Either "stereo" or "lr".
        """
        self._channel_mode = mode
        if mode == "lr":
            self._lr_radio.setChecked(True)
        else:
            self._stereo_radio.setChecked(True)
        self._update_mode_ui()

    def show_warnings(self, warnings: list[str]) -> None:
        """Display validation warnings inline with a continue button."""
        self._error_section.setVisible(False)
        if not warnings:
            self._warnings_section.setVisible(False)
            return
        text = "\n".join(f"\u2022 {w}" for w in warnings)
        self._warnings_label.setText(text)
        self._warnings_section.setVisible(True)

    def show_error(self, message: str) -> None:
        """Display a parse/network error with retry option."""
        self._warnings_section.setVisible(False)
        self._error_label.setText(message)
        self._error_section.setVisible(True)

    def clear_results(self) -> None:
        """Reset to initial state — hide warnings and errors."""
        self._warnings_section.setVisible(False)
        self._error_section.setVisible(False)
        self._stereo_path = ""
        self._left_path = ""
        self._right_path = ""
        self._left_file_label.setText("No file selected")
        self._right_file_label.setText("No file selected")
        self._stereo_file_label.setText("No file selected")
        self._next_btn.setEnabled(False)
        self._import_lr_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # Private: UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Build the page layout — toggle + browse buttons, no cards/dialogs."""
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(SPACING_LG, SPACING_LG, SPACING_LG, SPACING_LG)
        page_layout.setSpacing(SPACING_LG)

        # Page title
        title = QLabel("Import REW Filters")
        title.setObjectName("FiltersPageTitle")
        title.setStyleSheet(
            f"font-size: {FONT_SIZE_HEADING}px;"
            f" font-weight: {FONT_WEIGHT_SEMIBOLD};"
        )
        page_layout.addWidget(title)

        # Subtitle
        subtitle = QLabel(
            "Select channel mode and browse for your REW EQ text file(s)."
        )
        subtitle.setWordWrap(True)
        subtitle.setProperty("class", "secondary")
        page_layout.addWidget(subtitle)

        # --- Channel mode toggle ---
        mode_section = QWidget()
        mode_layout = QHBoxLayout(mode_section)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(SPACING_MD)

        mode_label = QLabel("Channel mode:")
        mode_label.setStyleSheet(
            f"font-size: {FONT_SIZE_BODY}px;"
            f" font-weight: {FONT_WEIGHT_SEMIBOLD};"
        )
        mode_layout.addWidget(mode_label)

        self._mode_group = QButtonGroup(self)
        self._stereo_radio = QRadioButton("Stereo (1 file)")
        self._stereo_radio.setChecked(True)
        self._lr_radio = QRadioButton("L/R (2 files)")
        self._mode_group.addButton(self._stereo_radio)
        self._mode_group.addButton(self._lr_radio)
        self._stereo_radio.toggled.connect(self._on_mode_toggled)

        mode_layout.addWidget(self._stereo_radio)
        mode_layout.addWidget(self._lr_radio)
        mode_layout.addStretch()

        page_layout.addWidget(mode_section)

        # --- Stereo file section ---
        self._stereo_section = QWidget()
        stereo_layout = QHBoxLayout(self._stereo_section)
        stereo_layout.setContentsMargins(0, 0, 0, 0)
        stereo_layout.setSpacing(SPACING_MD)

        self._stereo_file_label = QLabel("No file selected")
        self._stereo_file_label.setProperty("class", "secondary")
        self._stereo_file_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        stereo_layout.addWidget(self._stereo_file_label)

        stereo_btn = QPushButton("Browse...")
        stereo_btn.setMinimumWidth(100)
        stereo_btn.clicked.connect(self._on_stereo_browse)
        stereo_layout.addWidget(stereo_btn)

        page_layout.addWidget(self._stereo_section)

        # "Next" button for stereo mode (enabled once a file is selected)
        self._next_btn = QPushButton("Next")
        self._next_btn.setMinimumWidth(140)
        self._next_btn.setEnabled(False)
        self._next_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {ACCENT_COLOR}; color: white;"
            f"  border: none; border-radius: 6px;"
            f"  padding: 8px 16px; font-size: 13px;"
            f"}}"
            f"QPushButton:disabled {{"
            f"  background-color: #CCCCCC; color: #888888;"
            f"}}"
        )
        self._next_btn.clicked.connect(self._on_stereo_next)
        page_layout.addWidget(self._next_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # --- L/R file section ---
        self._lr_section = QWidget()
        lr_layout = QVBoxLayout(self._lr_section)
        lr_layout.setContentsMargins(0, 0, 0, 0)
        lr_layout.setSpacing(SPACING_SM)

        # Left channel row
        left_row = QHBoxLayout()
        left_row.setSpacing(SPACING_MD)
        left_label = QLabel("Left channel:")
        left_label.setStyleSheet(
            f"font-size: {FONT_SIZE_BODY}px;"
            f" font-weight: {FONT_WEIGHT_SEMIBOLD};"
        )
        left_label.setMinimumWidth(100)
        left_row.addWidget(left_label)

        self._left_file_label = QLabel("No file selected")
        self._left_file_label.setProperty("class", "secondary")
        self._left_file_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        left_row.addWidget(self._left_file_label)

        left_btn = QPushButton("Browse...")
        left_btn.setMinimumWidth(100)
        left_btn.clicked.connect(self._on_left_browse)
        left_row.addWidget(left_btn)
        lr_layout.addLayout(left_row)

        # Right channel row
        right_row = QHBoxLayout()
        right_row.setSpacing(SPACING_MD)
        right_label = QLabel("Right channel:")
        right_label.setStyleSheet(
            f"font-size: {FONT_SIZE_BODY}px;"
            f" font-weight: {FONT_WEIGHT_SEMIBOLD};"
        )
        right_label.setMinimumWidth(100)
        right_row.addWidget(right_label)

        self._right_file_label = QLabel("No file selected")
        self._right_file_label.setProperty("class", "secondary")
        self._right_file_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        right_row.addWidget(self._right_file_label)

        right_btn = QPushButton("Browse...")
        right_btn.setMinimumWidth(100)
        right_btn.clicked.connect(self._on_right_browse)
        right_row.addWidget(right_btn)
        lr_layout.addLayout(right_row)

        # Next button for L/R mode (enabled when both files are selected)
        self._import_lr_btn = QPushButton("Next")
        self._import_lr_btn.setMinimumWidth(140)
        self._import_lr_btn.setEnabled(False)
        self._import_lr_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {ACCENT_COLOR}; color: white;"
            f"  border: none; border-radius: 6px;"
            f"  padding: 8px 16px; font-size: 13px;"
            f"}}"
            f"QPushButton:disabled {{"
            f"  background-color: #CCCCCC; color: #888888;"
            f"}}"
        )
        self._import_lr_btn.clicked.connect(self._on_import_lr_confirmed)
        lr_layout.addWidget(
            self._import_lr_btn, alignment=Qt.AlignmentFlag.AlignLeft
        )

        self._lr_section.setVisible(False)
        page_layout.addWidget(self._lr_section)

        # --- RoomFit profile dropdown (hidden — used only from sidebar) ---
        self._roomfit_section = QWidget()
        rf_layout = QVBoxLayout(self._roomfit_section)
        rf_layout.setContentsMargins(0, 0, 0, 0)
        self._roomfit_combo = QComboBox()
        self._roomfit_combo.addItem("Select a profile...")
        self._roomfit_combo.currentIndexChanged.connect(
            self._on_roomfit_index_changed
        )
        rf_layout.addWidget(self._roomfit_combo)
        self._roomfit_section.setVisible(False)
        page_layout.addWidget(self._roomfit_section)

        # --- Warnings section ---
        self._warnings_section = self._build_warnings_section()
        self._warnings_section.setVisible(False)
        page_layout.addWidget(self._warnings_section)

        # --- Error section ---
        self._error_section = self._build_error_section()
        self._error_section.setVisible(False)
        page_layout.addWidget(self._error_section)

        page_layout.addStretch()

        # Set initial mode visibility
        self._update_mode_ui()

    def _build_warnings_section(self) -> QWidget:
        """Build the inline warnings display area."""
        widget = QWidget()
        widget.setObjectName("FiltersWarningsSection")
        widget.setStyleSheet(
            f"QWidget#FiltersWarningsSection {{"
            f"  border: 1px solid {WARNING_COLOR};"
            f"  border-radius: 6px;"
            f"  padding: 12px;"
            f"  background: #FFF8E1;"
            f"}}"
        )
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(SPACING_MD)

        heading = QLabel("Validation Warnings")
        heading.setStyleSheet(
            f"font-size: {FONT_SIZE_BODY}px;"
            f" font-weight: {FONT_WEIGHT_SEMIBOLD};"
            f" color: {WARNING_COLOR};"
            " border: none; background: transparent;"
        )
        layout.addWidget(heading)

        self._warnings_label = QLabel("")
        self._warnings_label.setStyleSheet(
            f"font-size: {FONT_SIZE_BODY}px;"
            " border: none; background: transparent;"
        )
        self._warnings_label.setWordWrap(True)
        layout.addWidget(self._warnings_label)

        continue_btn = QPushButton("Continue with adjustments")
        continue_btn.clicked.connect(self._on_continue_with_warnings)
        layout.addWidget(continue_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        return widget

    def _build_error_section(self) -> QWidget:
        """Build the error display area with retry."""
        widget = QWidget()
        widget.setObjectName("FiltersErrorSection")
        widget.setStyleSheet(
            f"QWidget#FiltersErrorSection {{"
            f"  border: 1px solid {ERROR_COLOR};"
            f"  border-radius: 6px;"
            f"  padding: 12px;"
            f"  background: #FFEBEE;"
            f"}}"
        )
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(SPACING_MD)

        heading = QLabel("Error")
        heading.setStyleSheet(
            f"font-size: {FONT_SIZE_BODY}px;"
            f" font-weight: {FONT_WEIGHT_SEMIBOLD};"
            f" color: {ERROR_COLOR};"
            " border: none; background: transparent;"
        )
        layout.addWidget(heading)

        self._error_label = QLabel("")
        self._error_label.setStyleSheet(
            f"font-size: {FONT_SIZE_BODY}px;"
            " border: none; background: transparent;"
        )
        self._error_label.setWordWrap(True)
        layout.addWidget(self._error_label)

        retry_btn = QPushButton("Try Again")
        retry_btn.clicked.connect(self._on_retry)
        layout.addWidget(retry_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        return widget

    # ------------------------------------------------------------------
    # Private: Event handlers
    # ------------------------------------------------------------------

    @Slot(bool)
    def _on_mode_toggled(self, _checked: bool) -> None:
        """Handle Stereo/L/R radio toggle."""
        if self._stereo_radio.isChecked():
            self._channel_mode = "stereo"
        else:
            self._channel_mode = "lr"
        self._update_mode_ui()

    def _update_mode_ui(self) -> None:
        """Show/hide stereo vs L/R sections based on current mode."""
        is_lr = self._channel_mode == "lr"
        self._stereo_section.setVisible(not is_lr)
        self._next_btn.setVisible(not is_lr)
        self._lr_section.setVisible(is_lr)

    @Slot()
    def _on_stereo_browse(self) -> None:
        """Open file dialog for stereo file selection (does not trigger import)."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select REW Filter File",
            "",
            "REW Text Files (*.txt);;All Files (*)",
        )
        if path:
            self._stereo_path = path
            self._stereo_file_label.setText(path.rsplit("/", 1)[-1])
            self._next_btn.setEnabled(True)

    @Slot()
    def _on_left_browse(self) -> None:
        """Open file dialog for left channel file."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Left Channel REW File",
            "",
            "REW Text Files (*.txt);;All Files (*)",
        )
        if path:
            self._left_path = path
            self._left_file_label.setText(path.rsplit("/", 1)[-1])
            self._update_lr_import_button()

    @Slot()
    def _on_right_browse(self) -> None:
        """Open file dialog for right channel file."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Right Channel REW File",
            "",
            "REW Text Files (*.txt);;All Files (*)",
        )
        if path:
            self._right_path = path
            self._right_file_label.setText(path.rsplit("/", 1)[-1])
            self._update_lr_import_button()

    @Slot()
    def _on_import_lr_confirmed(self) -> None:
        """Emit file_import_lr_requested with both L/R paths."""
        if self._left_path and self._right_path:
            self.file_import_lr_requested.emit(self._left_path, self._right_path)

    @Slot()
    def _on_stereo_next(self) -> None:
        """Emit file_import_requested with the selected stereo file path."""
        if self._stereo_path:
            self.file_import_requested.emit(self._stereo_path)

    @Slot(int)
    def _on_roomfit_index_changed(self, index: int) -> None:
        """Handle RoomFit profile dropdown selection."""
        if index > 0:
            profile_name = self._roomfit_combo.currentText()
            self.roomfit_profile_selected.emit(profile_name)

    @Slot()
    def _on_continue_with_warnings(self) -> None:
        """User acknowledged warnings — emit filters_accepted."""
        self.filters_accepted.emit()

    @Slot()
    def _on_retry(self) -> None:
        """Retry after error — reset page to initial state."""
        self._error_section.setVisible(False)
        self._warnings_section.setVisible(False)

    # ------------------------------------------------------------------
    # Private: Helpers
    # ------------------------------------------------------------------

    def _update_lr_import_button(self) -> None:
        """Enable the Import L/R button when both files are selected."""
        self._import_lr_btn.setEnabled(
            bool(self._left_path and self._right_path)
        )
