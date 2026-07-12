"""FiltersPage — filter loading wizard step.

Presents an Import source toggle (File Import vs Pull from REW API). File
Import shows a Stereo/L/R toggle and file browse buttons for loading REW EQ
files; Pull from REW API embeds RewPullView (the same picker used by the
sidebar "Pull from REW" entry, see src/gui/views/rew_pull_view.py) so REW
measurement selection behaves identically in both places. Supports inline
validation warnings and error display with retry.

The page does NOT perform network I/O — it only emits signals. RewPullView
is driven from the outside (MainWindow) exactly like the sidebar's instance.

Requirements referenced: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 9.3, 5.2, 5.7.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from src.gui.components.action_button import make_action_button
from src.gui.components.page_layout import build_centered_content, make_page_title
from src.gui.constants import (
    SPACING_LG,
    SPACING_MD,
    SPACING_SM,
)
from src.gui.views.rew_pull_view import RewPullView


class FiltersPage(QWidget):
    """Filter loading step with an Import source toggle.

    The page always shows:
    - A File Import / Pull from REW API source toggle
    - File Import: a Stereo vs L/R radio toggle + file browse button(s)
    - Pull from REW API: the embedded RewPullView picker
    - Inline warnings/errors after import

    Signals:
        file_import_requested: Path to a single REW .txt file (stereo mode).
        file_import_lr_requested: Paths to left and right channel files.
        device_pull_requested: (unused — kept for interface compatibility).
        rew_api_pull_requested: User switched the source toggle to "Pull from
            REW API" — caller should connect to REW and list measurements,
            then drive rew_pull_view via its set_connecting/set_measurements/
            set_message methods.
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
        # Default REW folder from Settings; a directory the user browses to
        # during this session overrides it for the rest of the session.
        self._default_import_dir: str = ""
        self._session_import_dir: str = ""
        self.rew_pull_view = RewPullView(show_title=False, show_header=False)
        self._setup_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_default_import_folder(self, path: str) -> None:
        """Set the Settings-configured default folder for the REW import dialogs.

        Called on startup and whenever Settings changes. Does not override a
        directory the user has already browsed to during this session — see
        `_browse_start_dir`.

        Args:
            path: The user's configured default REW folder, or "" for none.
        """
        self._default_import_dir = path

    def set_rew_api_available(self, available: bool) -> None:
        """Enable/disable the "Pull from REW API" source option.

        Falls back to File Import if it was selected when disabled.

        Args:
            available: Whether REW API pull should be offered on this page.
        """
        self._rew_api_source_radio.setEnabled(available)
        if not available and self._rew_api_source_radio.isChecked():
            self._file_source_radio.setChecked(True)

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

    def set_lr_enabled(self, enabled: bool) -> None:
        """Enable or disable the L/R channel mode option.

        Disabled (not hidden) when the connected device's capabilities
        report no L/R filter support, so the control's presence stays
        consistent while remaining unselectable. Forces Stereo mode if L/R
        was selected at the moment it becomes disabled.

        Args:
            enabled: Whether L/R mode should be selectable.
        """
        self._lr_radio.setEnabled(enabled)
        if not enabled:
            self._lr_radio.setToolTip(
                "This device does not support independent Left/Right channel filters."
            )
            if self._lr_radio.isChecked():
                self._stereo_radio.setChecked(True)
        else:
            self._lr_radio.setToolTip("")

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
        """Reset to initial state — hide warnings/errors, revert to File Import."""
        self._warnings_section.setVisible(False)
        self._error_section.setVisible(False)
        self._file_source_radio.setChecked(True)
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
        page_layout, content_wrapper = build_centered_content(self)

        # Page title
        title = make_page_title(
            "Import REW Filters", content_wrapper, object_name="FiltersPageTitle"
        )
        page_layout.addWidget(title)

        # --- Import source toggle (above the instruction text, so the
        # instruction line always sits directly below it -- same position
        # and font in both File Import and Pull from REW API modes) ---
        source_section = QWidget()
        source_layout = QHBoxLayout(source_section)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(SPACING_MD)

        source_label = QLabel("Import source:")
        source_label.setProperty("class", "subheading")
        source_layout.addWidget(source_label)

        self._source_group = QButtonGroup(self)
        self._file_source_radio = QRadioButton("File Import")
        self._file_source_radio.setChecked(True)
        self._rew_api_source_radio = QRadioButton("Pull from REW API")
        self._source_group.addButton(self._file_source_radio)
        self._source_group.addButton(self._rew_api_source_radio)
        self._rew_api_source_radio.toggled.connect(self._on_source_toggled)

        source_layout.addWidget(self._file_source_radio)
        source_layout.addWidget(self._rew_api_source_radio)
        source_layout.addStretch()

        page_layout.addWidget(source_section)

        # Instruction line (updated by _on_source_toggled to match the
        # active source) -- stays in this exact layout position and keeps
        # this styling in both modes, so switching source doesn't move or
        # restyle it, only its text changes.
        self._subtitle = QLabel(
            "Select channel mode and browse for your REW EQ text file(s)."
        )
        self._subtitle.setWordWrap(True)
        self._subtitle.setProperty("class", "secondary")
        page_layout.addWidget(self._subtitle)

        # --- File Import section (channel toggle + browse buttons) ---
        self._file_import_section = QWidget()
        file_layout = QVBoxLayout(self._file_import_section)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(SPACING_LG)
        page_layout.addWidget(self._file_import_section)

        # --- Channel mode toggle ---
        mode_section = QWidget()
        mode_layout = QHBoxLayout(mode_section)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(SPACING_MD)

        mode_label = QLabel("Channel mode:")
        mode_label.setProperty("class", "subheading")
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

        file_layout.addWidget(mode_section)

        # --- Stereo file section ---
        self._stereo_section = QWidget()
        stereo_layout = QHBoxLayout(self._stereo_section)
        stereo_layout.setContentsMargins(0, 0, 0, 0)
        stereo_layout.setSpacing(SPACING_MD)

        stereo_btn = make_action_button(
            "Browse...", object_name="filters_browse_stereo", style_class="secondary"
        )
        stereo_btn.setMinimumWidth(100)
        stereo_btn.clicked.connect(self._on_stereo_browse)
        stereo_layout.addWidget(stereo_btn)

        self._stereo_file_label = QLabel("No file selected")
        self._stereo_file_label.setProperty("class", "secondary")
        self._stereo_file_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        stereo_layout.addWidget(self._stereo_file_label)

        file_layout.addWidget(self._stereo_section)

        # --- L/R file section ---
        self._lr_section = QWidget()
        lr_layout = QVBoxLayout(self._lr_section)
        lr_layout.setContentsMargins(0, 0, 0, 0)
        lr_layout.setSpacing(SPACING_SM)

        # Left channel row
        left_row = QHBoxLayout()
        left_row.setSpacing(SPACING_MD)
        left_label = QLabel("Left channel:")
        left_label.setProperty("class", "subheading")
        left_label.setMinimumWidth(100)
        left_row.addWidget(left_label)

        left_btn = make_action_button(
            "Browse...", object_name="filters_browse_left", style_class="secondary"
        )
        left_btn.setMinimumWidth(100)
        left_btn.clicked.connect(self._on_left_browse)
        left_row.addWidget(left_btn)

        self._left_file_label = QLabel("No file selected")
        self._left_file_label.setProperty("class", "secondary")
        self._left_file_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        left_row.addWidget(self._left_file_label)
        lr_layout.addLayout(left_row)

        # Right channel row
        right_row = QHBoxLayout()
        right_row.setSpacing(SPACING_MD)
        right_label = QLabel("Right channel:")
        right_label.setProperty("class", "subheading")
        right_label.setMinimumWidth(100)
        right_row.addWidget(right_label)

        right_btn = make_action_button(
            "Browse...", object_name="filters_browse_right", style_class="secondary"
        )
        right_btn.setMinimumWidth(100)
        right_btn.clicked.connect(self._on_right_browse)
        right_row.addWidget(right_btn)

        self._right_file_label = QLabel("No file selected")
        self._right_file_label.setProperty("class", "secondary")
        self._right_file_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        right_row.addWidget(self._right_file_label)
        lr_layout.addLayout(right_row)

        self._lr_section.setVisible(False)
        file_layout.addWidget(self._lr_section)

        # --- Pull from REW API section (embedded picker) ---
        # measurement_selected is consumed directly by MainWindow (same
        # signal the sidebar's RewPullView instance uses); back_requested
        # is also handled locally to flip the source toggle back. Given a
        # stretch factor so it claims the page's spare vertical space
        # directly, rather than that space collecting below it at the
        # trailing addStretch() -- RewPullView's own internal measurement
        # list already has a stretch factor of 1 inside itself, so the
        # extra height flows through to the actual list.
        self.rew_pull_view.setVisible(False)
        self.rew_pull_view.back_requested.connect(self._on_rew_pull_back_requested)
        page_layout.addWidget(self.rew_pull_view, 1)

        # --- Continue action row (shared position for both modes, so
        # switching between Stereo/L/R doesn't shift the button vertically
        # the way it would if each mode kept its own button inline after
        # its own (differently-sized) file rows). Lives in its own
        # page_layout-level container (not file_layout) with a leading
        # stretch so it's bottom-anchored like every other wizard step's
        # primary button, regardless of how tall the file rows above it
        # are; visibility is tied to the File Import section's own toggle
        # in _on_source_toggled so it doesn't show while Pull from REW API
        # (which has its own action bar) is active. ---
        self._file_import_actions = QWidget()
        actions_row = QHBoxLayout(self._file_import_actions)
        actions_row.setContentsMargins(0, 0, 0, 0)
        actions_row.addStretch()

        self._next_btn = make_action_button(
            "Continue", object_name="filters_next_stereo", style_class="primary"
        )
        self._next_btn.setEnabled(False)
        self._next_btn.clicked.connect(self._on_stereo_next)
        actions_row.addWidget(self._next_btn)

        self._import_lr_btn = make_action_button(
            "Continue", object_name="filters_next_lr", style_class="primary"
        )
        self._import_lr_btn.setEnabled(False)
        self._import_lr_btn.setVisible(False)
        self._import_lr_btn.clicked.connect(self._on_import_lr_confirmed)
        actions_row.addWidget(self._import_lr_btn)

        page_layout.addStretch()
        page_layout.addWidget(self._file_import_actions)

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

        # Set initial mode visibility
        self._update_mode_ui()

    def _build_warnings_section(self) -> QWidget:
        """Build the inline warnings display area."""
        widget = QWidget()
        widget.setObjectName("FiltersWarningsSection")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(SPACING_MD)

        heading = QLabel("Validation Warnings")
        heading.setProperty("class", "warning")
        layout.addWidget(heading)

        self._warnings_label = QLabel("")
        self._warnings_label.setWordWrap(True)
        layout.addWidget(self._warnings_label)

        continue_btn = make_action_button(
            "Continue with adjustments",
            object_name="filters_continue_with_warnings",
            style_class="warning",
        )
        continue_btn.clicked.connect(self._on_continue_with_warnings)
        layout.addWidget(continue_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        return widget

    def _build_error_section(self) -> QWidget:
        """Build the error display area with retry."""
        widget = QWidget()
        widget.setObjectName("FiltersErrorSection")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(SPACING_MD)

        heading = QLabel("Error")
        heading.setProperty("class", "error")
        layout.addWidget(heading)

        self._error_label = QLabel("")
        self._error_label.setWordWrap(True)
        layout.addWidget(self._error_label)

        retry_btn = make_action_button(
            "Try Again", object_name="filters_retry_btn", style_class="secondary"
        )
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
        self._import_lr_btn.setVisible(is_lr)

    @Slot(bool)
    def _on_source_toggled(self, rew_api_checked: bool) -> None:
        """Handle File Import / Pull from REW API source toggle.

        Args:
            rew_api_checked: Whether the "Pull from REW API" radio is now
                checked (passed by the toggled(bool) signal of that radio).
        """
        self._file_import_section.setVisible(not rew_api_checked)
        self._file_import_actions.setVisible(not rew_api_checked)
        self.rew_pull_view.setVisible(rew_api_checked)
        if rew_api_checked:
            self._subtitle.setText("Select a REW measurement to import filters from.")
            self.rew_pull_view.set_connecting()
            self.rew_api_pull_requested.emit()
        else:
            self._subtitle.setText(
                "Select channel mode and browse for your REW EQ text file(s)."
            )

    @Slot()
    def _on_rew_pull_back_requested(self) -> None:
        """Handle Back from the embedded RewPullView — revert to File Import."""
        self._file_source_radio.setChecked(True)

    def _browse_start_dir(self) -> str:
        """Return the starting directory for the REW import file dialogs.

        A directory the user has already browsed to this session takes
        precedence over the Settings-configured default.
        """
        return self._session_import_dir or self._default_import_dir

    @Slot()
    def _on_stereo_browse(self) -> None:
        """Open file dialog for stereo file selection (does not trigger import)."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select REW Filter File",
            self._browse_start_dir(),
            "REW Text Files (*.txt);;All Files (*)",
        )
        if path:
            self._stereo_path = path
            self._stereo_file_label.setText(path.rsplit("/", 1)[-1])
            self._session_import_dir = str(Path(path).parent)
            self._next_btn.setEnabled(True)

    @Slot()
    def _on_left_browse(self) -> None:
        """Open file dialog for left channel file."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Left Channel REW File",
            self._browse_start_dir(),
            "REW Text Files (*.txt);;All Files (*)",
        )
        if path:
            self._left_path = path
            self._left_file_label.setText(path.rsplit("/", 1)[-1])
            self._session_import_dir = str(Path(path).parent)
            self._update_lr_import_button()

    @Slot()
    def _on_right_browse(self) -> None:
        """Open file dialog for right channel file."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Right Channel REW File",
            self._browse_start_dir(),
            "REW Text Files (*.txt);;All Files (*)",
        )
        if path:
            self._right_path = path
            self._right_file_label.setText(path.rsplit("/", 1)[-1])
            self._session_import_dir = str(Path(path).parent)
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
