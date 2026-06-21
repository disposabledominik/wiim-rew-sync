"""FiltersPage — filter loading wizard step.

Presents three options for loading filters: Import from REW File,
Pull from Device, and Pull from REW API. Supports stereo and L/R
file pickers, drag-and-drop of .txt files, RoomFit profile dropdown,
inline validation warnings, and error display with retry.

The page does NOT perform network I/O — it only emits signals.

Requirements referenced: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 4.10, 4.11, 4.12, 9.3.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.gui.constants import (
    ERROR_COLOR,
    FONT_SIZE_BODY,
    FONT_SIZE_CAPTION,
    FONT_SIZE_HEADING,
    FONT_WEIGHT_SEMIBOLD,
    MAX_CONTENT_WIDTH,
    SPACING_LG,
    SPACING_MD,
    WARNING_COLOR,
)


class _OptionCard(QWidget):
    """Clickable option card with title and description."""

    clicked = Signal()

    def __init__(
        self,
        title: str,
        description: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("FiltersOptionCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(64)
        self.setStyleSheet(
            "QWidget#FiltersOptionCard {"
            "  border: 1px solid #E0E0E0;"
            "  border-radius: 8px;"
            "  padding: 12px 16px;"
            "}"
            "QWidget#FiltersOptionCard:hover {"
            "  border-color: #00B4D8;"
            "  background: #F8FDFE;"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        self._title_label = QLabel(title, self)
        self._title_label.setStyleSheet(
            f"font-size: {FONT_SIZE_BODY}px; font-weight: {FONT_WEIGHT_SEMIBOLD};"
            " border: none; background: transparent;"
        )
        layout.addWidget(self._title_label)

        self._desc_label = QLabel(description, self)
        self._desc_label.setStyleSheet(
            f"font-size: {FONT_SIZE_CAPTION}px; color: #616161;"
            " border: none; background: transparent;"
        )
        self._desc_label.setWordWrap(True)
        layout.addWidget(self._desc_label)

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        """Emit clicked on mouse press."""
        self.clicked.emit()
        super().mousePressEvent(event)


class _DropZone(QWidget):
    """Drag-and-drop target for .txt files (Req 9.3)."""

    file_dropped = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FiltersDropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(80)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(
            "QWidget#FiltersDropZone {"
            "  border: 2px dashed #B0B0B0;"
            "  border-radius: 8px;"
            "  background: #FAFAFA;"
            "}"
        )

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label = QLabel("Drop REW .txt file here", self)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet(
            f"font-size: {FONT_SIZE_CAPTION}px; color: #9E9E9E;"
            " border: none; background: transparent;"
        )
        layout.addWidget(self._label)

    def dragEnterEvent(self, event) -> None:  # noqa: ANN001
        """Accept drag events containing file URLs."""
        mime = event.mimeData()
        if mime.hasUrls():
            for url in mime.urls():
                if url.toLocalFile().lower().endswith(".txt"):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event) -> None:  # noqa: ANN001
        """Handle dropped .txt file — emit file_dropped with path."""
        mime = event.mimeData()
        if mime.hasUrls():
            for url in mime.urls():
                path = url.toLocalFile()
                if path.lower().endswith(".txt"):
                    self.file_dropped.emit(path)
                    event.acceptProposedAction()
                    return
        event.ignore()


class FiltersPage(QWidget):
    """Filter loading step: Import file, Pull from device, Pull from REW API.

    Presents three option cards and supporting UI (drag-drop zone, file pickers,
    RoomFit profile dropdown). Displays validation warnings inline and parse
    errors with retry. The page emits signals only — no network I/O.

    Signals:
        file_import_requested: Path to a single REW .txt file (stereo mode).
        file_import_lr_requested: Paths to left and right channel files.
        device_pull_requested: User clicked Pull from Device.
        rew_api_pull_requested: User clicked Pull from REW API.
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
        self._left_path: str = ""
        self._right_path: str = ""
        self._setup_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_rew_api_available(self, available: bool) -> None:
        """Show or hide the REW API option card.

        Args:
            available: True to show the REW API option, False to hide it.
        """
        self._rew_api_card.setVisible(available)

    def set_roomfit_mode(self, enabled: bool) -> None:
        """Toggle RoomFit mode flag (no longer shows profile dropdown here).

        RoomFit profile pull is accessible via the "Presets on Device" sidebar.
        The Filters page always shows the file import flow regardless of EQ type.

        Args:
            enabled: True for RoomFit flow, False for PEQ flow.
        """
        self._roomfit_mode = enabled
        # RoomFit section hidden — pull from device is via sidebar only
        self._roomfit_section.setVisible(False)
        self._file_picker_section.setVisible(True)

    def set_roomfit_profiles(self, profiles: list[str]) -> None:
        """Populate the RoomFit profile dropdown.

        Args:
            profiles: List of profile names available on the device.
        """
        self._roomfit_combo.clear()
        self._roomfit_combo.addItem("Select a profile...")
        self._roomfit_combo.addItems(profiles)

    def set_channel_mode(self, mode: str) -> None:
        """Set stereo or L/R channel mode for file picking.

        Args:
            mode: Either "stereo" or "lr".
        """
        self._channel_mode = mode
        is_lr = mode == "lr"
        self._lr_section.setVisible(is_lr)
        self._drop_zone.setVisible(not self._roomfit_mode)

    def show_warnings(self, warnings: list[str]) -> None:
        """Display validation warnings inline with a continue button.

        Args:
            warnings: List of warning messages (gain/Q clamped, too many bands).
        """
        self._error_section.setVisible(False)
        if not warnings:
            self._warnings_section.setVisible(False)
            return

        text = "\n".join(f"\u2022 {w}" for w in warnings)
        self._warnings_label.setText(text)
        self._warnings_section.setVisible(True)

    def show_error(self, message: str) -> None:
        """Display a parse/network error with retry option.

        Args:
            message: Error description in plain language.
        """
        self._warnings_section.setVisible(False)
        self._error_label.setText(message)
        self._error_section.setVisible(True)

    def clear_results(self) -> None:
        """Reset to initial state — hide warnings and errors."""
        self._warnings_section.setVisible(False)
        self._error_section.setVisible(False)
        self._left_path = ""
        self._right_path = ""
        self._left_file_label.setText("No file selected")
        self._right_file_label.setText("No file selected")

    # ------------------------------------------------------------------
    # Private: UI setup
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Build the full page layout."""
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(0)
        page_layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        # Content wrapper with max width
        content_wrapper = QWidget(self)
        content_wrapper.setMaximumWidth(MAX_CONTENT_WIDTH)
        content_layout = QVBoxLayout(content_wrapper)
        content_layout.setContentsMargins(SPACING_LG, SPACING_LG, SPACING_LG, SPACING_LG)
        content_layout.setSpacing(SPACING_LG)

        # Page title
        title = QLabel("Get Filters", content_wrapper)
        title.setObjectName("FiltersPageTitle")
        title.setStyleSheet(
            f"font-size: {FONT_SIZE_HEADING}px; font-weight: {FONT_WEIGHT_SEMIBOLD};"
        )
        content_layout.addWidget(title)

        # Option cards (vertical stack)
        self._import_card = _OptionCard(
            "Import from REW File",
            "Load filters from a Room EQ Wizard text file",
            content_wrapper,
        )
        self._import_card.clicked.connect(self._on_import_clicked)
        content_layout.addWidget(self._import_card)

        self._pull_card = _OptionCard(
            "Pull from Device",
            "Read the current PEQ configuration from your connected device",
            content_wrapper,
        )
        self._pull_card.clicked.connect(self._on_pull_clicked)
        self._pull_card.setVisible(False)  # Available via "Presets on Device" sidebar
        content_layout.addWidget(self._pull_card)

        self._rew_api_card = _OptionCard(
            "Pull from REW API",
            "Fetch filters from a running REW instance on this computer",
            content_wrapper,
        )
        self._rew_api_card.clicked.connect(self._on_rew_api_clicked)
        self._rew_api_card.setVisible(False)  # Available via "Presets on Device" sidebar
        content_layout.addWidget(self._rew_api_card)

        # Drag-and-drop zone — hidden (stereo/L/R choice dialog handles import flow)
        self._drop_zone = _DropZone(content_wrapper)
        self._drop_zone.file_dropped.connect(self._on_file_dropped)
        self._drop_zone.setVisible(False)
        content_layout.addWidget(self._drop_zone)

        # L/R dual file picker section (hidden in stereo mode)
        self._lr_section = self._build_lr_section(content_wrapper)
        self._lr_section.setVisible(False)
        content_layout.addWidget(self._lr_section)

        # File picker section (hidden label for single file result)
        self._file_picker_section = QWidget(content_wrapper)
        self._file_picker_section.setVisible(False)
        content_layout.addWidget(self._file_picker_section)

        # RoomFit profile dropdown section (Req 4.8)
        self._roomfit_section = self._build_roomfit_section(content_wrapper)
        self._roomfit_section.setVisible(False)
        content_layout.addWidget(self._roomfit_section)

        # Warnings section (Req 4.5)
        self._warnings_section = self._build_warnings_section(content_wrapper)
        self._warnings_section.setVisible(False)
        content_layout.addWidget(self._warnings_section)

        # Error section (Req 4.6, 4.10)
        self._error_section = self._build_error_section(content_wrapper)
        self._error_section.setVisible(False)
        content_layout.addWidget(self._error_section)

        content_layout.addStretch()

        # Center the content wrapper
        wrapper_layout = QHBoxLayout()
        wrapper_layout.setContentsMargins(0, 0, 0, 0)
        wrapper_layout.addStretch()
        wrapper_layout.addWidget(content_wrapper)
        wrapper_layout.addStretch()
        page_layout.addLayout(wrapper_layout)

    def _build_lr_section(self, parent: QWidget) -> QWidget:
        """Build the dual file picker for L/R channel mode (Req 4.3)."""
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING_MD)

        # Left channel row
        left_row = QHBoxLayout()
        left_row.setSpacing(SPACING_MD)
        left_label = QLabel("Left channel:", widget)
        left_label.setStyleSheet(
            f"font-size: {FONT_SIZE_BODY}px; font-weight: {FONT_WEIGHT_SEMIBOLD};"
        )
        left_label.setFixedWidth(110)
        left_row.addWidget(left_label)

        self._left_file_label = QLabel("No file selected", widget)
        self._left_file_label.setStyleSheet(
            f"font-size: {FONT_SIZE_CAPTION}px; color: #616161;"
        )
        self._left_file_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        left_row.addWidget(self._left_file_label)

        left_btn = QPushButton("Browse...", widget)
        left_btn.setObjectName("FiltersLeftBrowseBtn")
        left_btn.setFixedWidth(90)
        left_btn.clicked.connect(self._on_left_browse)
        left_row.addWidget(left_btn)
        layout.addLayout(left_row)

        # Right channel row
        right_row = QHBoxLayout()
        right_row.setSpacing(SPACING_MD)
        right_label = QLabel("Right channel:", widget)
        right_label.setStyleSheet(
            f"font-size: {FONT_SIZE_BODY}px; font-weight: {FONT_WEIGHT_SEMIBOLD};"
        )
        right_label.setFixedWidth(110)
        right_row.addWidget(right_label)

        self._right_file_label = QLabel("No file selected", widget)
        self._right_file_label.setStyleSheet(
            f"font-size: {FONT_SIZE_CAPTION}px; color: #616161;"
        )
        self._right_file_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        right_row.addWidget(self._right_file_label)

        right_btn = QPushButton("Browse...", widget)
        right_btn.setObjectName("FiltersRightBrowseBtn")
        right_btn.setFixedWidth(90)
        right_btn.clicked.connect(self._on_right_browse)
        right_row.addWidget(right_btn)
        layout.addLayout(right_row)

        # Import L/R button (enabled when both files selected)
        self._import_lr_btn = QPushButton("Import L/R Files", widget)
        self._import_lr_btn.setObjectName("FiltersImportLRBtn")
        self._import_lr_btn.setEnabled(False)
        self._import_lr_btn.clicked.connect(self._on_import_lr_confirmed)
        layout.addWidget(self._import_lr_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        return widget

    def _build_roomfit_section(self, parent: QWidget) -> QWidget:
        """Build the RoomFit profile dropdown section (Req 4.8)."""
        widget = QWidget(parent)
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING_MD)

        label = QLabel("Select RoomFit profile to pull:", widget)
        label.setStyleSheet(f"font-size: {FONT_SIZE_BODY}px;")
        layout.addWidget(label)

        self._roomfit_combo = QComboBox(widget)
        self._roomfit_combo.setObjectName("FiltersRoomfitCombo")
        self._roomfit_combo.addItem("Select a profile...")
        self._roomfit_combo.currentIndexChanged.connect(self._on_roomfit_index_changed)
        layout.addWidget(self._roomfit_combo)

        return widget

    def _build_warnings_section(self, parent: QWidget) -> QWidget:
        """Build the inline warnings display area (Req 4.5)."""
        widget = QWidget(parent)
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

        heading = QLabel("Validation Warnings", widget)
        heading.setStyleSheet(
            f"font-size: {FONT_SIZE_BODY}px; font-weight: {FONT_WEIGHT_SEMIBOLD};"
            f" color: {WARNING_COLOR}; border: none; background: transparent;"
        )
        layout.addWidget(heading)

        self._warnings_label = QLabel("", widget)
        self._warnings_label.setObjectName("FiltersWarningsLabel")
        self._warnings_label.setStyleSheet(
            f"font-size: {FONT_SIZE_BODY}px; border: none; background: transparent;"
        )
        self._warnings_label.setWordWrap(True)
        layout.addWidget(self._warnings_label)

        continue_btn = QPushButton("Continue with adjustments", widget)
        continue_btn.setObjectName("FiltersContinueBtn")
        continue_btn.clicked.connect(self._on_continue_with_warnings)
        layout.addWidget(continue_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        return widget

    def _build_error_section(self, parent: QWidget) -> QWidget:
        """Build the error display area with retry (Req 4.6, 4.10)."""
        widget = QWidget(parent)
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

        heading = QLabel("Error", widget)
        heading.setStyleSheet(
            f"font-size: {FONT_SIZE_BODY}px; font-weight: {FONT_WEIGHT_SEMIBOLD};"
            f" color: {ERROR_COLOR}; border: none; background: transparent;"
        )
        layout.addWidget(heading)

        self._error_label = QLabel("", widget)
        self._error_label.setObjectName("FiltersErrorLabel")
        self._error_label.setStyleSheet(
            f"font-size: {FONT_SIZE_BODY}px; border: none; background: transparent;"
        )
        self._error_label.setWordWrap(True)
        layout.addWidget(self._error_label)

        retry_btn = QPushButton("Try Again", widget)
        retry_btn.setObjectName("FiltersRetryBtn")
        retry_btn.clicked.connect(self._on_retry)
        layout.addWidget(retry_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        return widget

    # ------------------------------------------------------------------
    # Private: Event handlers
    # ------------------------------------------------------------------

    @Slot()
    def _on_import_clicked(self) -> None:
        """Handle Import from REW File card click.

        Shows channel mode choice: Stereo (1 file) or L/R (2 files).
        For stereo, opens a single file picker.
        For L/R, shows the dual-file picker section.
        """
        if self._channel_mode == "lr":
            # Already in L/R mode (set by Source page) — show L/R picker
            self._lr_section.setVisible(True)
            return

        # Show a simple choice: Stereo or L/R import
        from PySide6.QtWidgets import QMessageBox

        msg = QMessageBox(self)
        msg.setWindowTitle("Import Mode")
        msg.setText("How would you like to import?")
        stereo_btn = msg.addButton("Stereo (1 file)", QMessageBox.ButtonRole.AcceptRole)
        lr_btn = msg.addButton("L/R (2 files)", QMessageBox.ButtonRole.ActionRole)
        msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked == lr_btn:
            self._channel_mode = "lr"
            self._lr_section.setVisible(True)
        elif clicked == stereo_btn:
            # Stereo: single file dialog (Req 4.2)
            path, _ = QFileDialog.getOpenFileName(
                self,
                "Select REW Filter File",
                "",
                "REW Text Files (*.txt);;All Files (*)",
            )
            if path:
                self.file_import_requested.emit(path)

    @Slot()
    def _on_pull_clicked(self) -> None:
        """Handle Pull from Device card click (Req 4.7)."""
        self.device_pull_requested.emit()

    @Slot()
    def _on_rew_api_clicked(self) -> None:
        """Handle Pull from REW API card click (Req 4.11)."""
        self.rew_api_pull_requested.emit()

    @Slot(str)
    def _on_file_dropped(self, path: str) -> None:
        """Handle drag-and-drop file (Req 9.3)."""
        if self._channel_mode == "lr":
            # In L/R mode, populate the first empty slot
            if not self._left_path:
                self._left_path = path
                self._left_file_label.setText(path.rsplit("/", 1)[-1])
                self._lr_section.setVisible(True)
            elif not self._right_path:
                self._right_path = path
                self._right_file_label.setText(path.rsplit("/", 1)[-1])
            self._update_lr_import_button()
        else:
            # Stereo: immediate import
            self.file_import_requested.emit(path)

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

    @Slot(int)
    def _on_roomfit_index_changed(self, index: int) -> None:
        """Handle RoomFit profile dropdown selection."""
        if index > 0:  # Skip placeholder item at index 0
            profile_name = self._roomfit_combo.currentText()
            self.roomfit_profile_selected.emit(profile_name)

    @Slot()
    def _on_continue_with_warnings(self) -> None:
        """User acknowledged warnings — emit filters_accepted."""
        self.filters_accepted.emit()

    @Slot()
    def _on_retry(self) -> None:
        """Retry after error — reset page to initial state so user can choose again."""
        self._error_section.setVisible(False)
        # Re-show option cards and drop zone so user can pick an import method again
        self._import_card.setVisible(True)
        self._import_card.setEnabled(True)
        self._drop_zone.setVisible(not self._roomfit_mode)

    # ------------------------------------------------------------------
    # Private: Helpers
    # ------------------------------------------------------------------

    def _update_lr_import_button(self) -> None:
        """Enable the Import L/R button when both files are selected."""
        self._import_lr_btn.setEnabled(bool(self._left_path and self._right_path))
