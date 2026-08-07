"""FiltersPage - filter loading wizard step.

Presents an Import source dropdown with four options: File Import, Pull from
REW API, Device, and Local Library. Each option shows its own panel in a
QStackedWidget:
    - File Import: a Stereo/L/R toggle and file browse buttons for loading
      REW EQ files.
    - Pull from REW API: embeds RewPullView (the same picker used by the
      sidebar before it was consolidated here, see
      src/gui/views/rew_pull_view.py) so REW measurement selection behaves
      identically wherever it's reached from.
    - Device: a "Current configuration on device" action plus a merged list
      of PEQ presets and RoomFit profiles saved on the connected device
      (regardless of the wizard's current EQ_TYPE -- a saved preset's origin
      doesn't have to match the flow pushing it).
    - Local Library: a list of presets saved locally on this computer.

Supports inline validation warnings and error display with retry.

The page does NOT perform network I/O or filesystem reads - it only emits
signals; all four panels are populated from the outside (MainWindow).

Requirements referenced: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 9.3, 5.2, 5.7.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal, Slot
from PySide6.QtGui import QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QRadioButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from src.gui.components.action_button import make_action_button
from src.gui.components.list_item_style import build_preset_list_item
from src.gui.components.page_layout import build_centered_content, make_page_title
from src.gui.constants import (
    LIST_ITEM_HEIGHT,
    SPACING_LG,
    SPACING_MD,
    SPACING_SM,
)
from src.gui.views.my_presets_view import _PresetItemWidget
from src.gui.views.presets_device_view import PresetItem, build_peq_rows
from src.gui.views.rew_pull_view import RewPullView
from src.gui.wizard_controller import FiltersSource
from src.models.profile import Profile

# Sentinel stored as a Device-list row's UserRole data for the synthetic
# "Custom" row (see build_custom_peq_item) -- identity-checked at dispatch
# time rather than matching on item.name, so a real saved preset that
# happens to also be named "Custom" is never misrouted to device_pull_requested.
_CUSTOM_ROW_MARKER = object()

# Dropdown/stack index order -- shared by the combo's model construction and
# every index<->FiltersSource lookup in this file.
_SOURCE_ORDER: list[FiltersSource] = [
    FiltersSource.REW_FILE,
    FiltersSource.REW_API,
    FiltersSource.DEVICE,
    FiltersSource.LOCAL_LIBRARY,
]

_SOURCE_LABELS: dict[FiltersSource, str] = {
    FiltersSource.REW_FILE: "File Import",
    FiltersSource.REW_API: "Pull from REW API",
    FiltersSource.DEVICE: "Device",
    FiltersSource.LOCAL_LIBRARY: "Local Library",
}

_SOURCE_SUBTITLES: dict[FiltersSource, str] = {
    FiltersSource.REW_FILE: "Select channel mode and browse for your REW EQ text file(s).",
    FiltersSource.REW_API: "Select a REW measurement to import filters from.",
    FiltersSource.DEVICE: "Read the device's current configuration, or load a saved preset.",
    FiltersSource.LOCAL_LIBRARY: "Load a preset saved locally on this computer.",
}


class FiltersPage(QWidget):
    """Filter loading step with a four-option Import source dropdown.

    The page always shows:
    - A File Import / Pull from REW API / Device / Local Library source dropdown
    - File Import: a Stereo vs L/R radio toggle + file browse button(s)
    - Pull from REW API: the embedded RewPullView picker
    - Device: a "Current configuration on device" action + merged PEQ/
      RoomFit preset list. When the live PEQ config on the selected source
      doesn't match any saved preset, the list also shows a synthetic
      "Custom" row for it (WiiM Home's own term for this state) --
      selecting it and clicking Load Preset does the same thing as the
      button above. The button stays the only way to pull the live config
      on devices that don't support listing saved presets at all (no
      profile-enumeration capability), or before the list has loaded.
    - Local Library: a list of locally-saved presets
    - Inline warnings/errors after import

    Signals:
        file_import_requested: Path to a single REW .txt file (stereo mode).
        file_import_lr_requested: Paths to left and right channel files.
        device_pull_requested: User wants the device's current live PEQ
            configuration (no named preset involved) -- emitted by the
            "Current configuration on device" button, or equivalently by
            selecting the merged list's synthetic "Custom" row.
        rew_api_pull_requested: User switched to "Pull from REW API" -
            caller should connect to REW and list measurements, then drive
            rew_pull_view via its set_connecting/set_measurements/set_message
            methods.
        device_presets_requested: User switched to "Device" - caller should
            (re)fetch PEQ presets and RoomFit profiles and populate via
            set_peq_presets()/set_roomfit_profiles().
        local_profiles_requested: User switched to "Local Library" - caller
            should (re)fetch saved profiles and populate via set_local_profiles().
        device_item_selected: User picked a named preset/profile from the
            merged Device list (PresetItem payload; caller branches on
            preset_type). Never emitted for the synthetic "Custom" row --
            that emits device_pull_requested instead (see above).
        local_profile_selected: User picked a preset from the Local Library
            list (Profile payload).
        filters_accepted: User clicked "Continue with adjustments" after warnings.
    """

    file_import_requested = Signal(str)
    file_import_lr_requested = Signal(str, str)
    device_pull_requested = Signal()
    rew_api_pull_requested = Signal()
    device_presets_requested = Signal()
    local_profiles_requested = Signal()
    device_item_selected = Signal(object)
    local_profile_selected = Signal(object)
    filters_accepted = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("FiltersPage")
        self._channel_mode: str = "stereo"
        self._current_source: FiltersSource = FiltersSource.REW_FILE
        self._stereo_path: str = ""
        self._left_path: str = ""
        self._right_path: str = ""
        # Default REW folder from Settings; a directory the user browses to
        # during this session overrides it for the rest of the session.
        self._default_import_dir: str = ""
        self._session_import_dir: str = ""
        self._device_peq_items: list[PresetItem] = []
        # None = PEQ fetch hasn't resolved yet (distinct from "" = it
        # resolved and found no active preset name). The RoomFit fetch runs
        # concurrently and can populate the list on its own first, so "not
        # yet known" has to stay distinguishable from "confirmed empty" --
        # only the latter shows the synthetic "Custom" row.
        self._device_active_peq_name: str | None = None
        self._device_active_peq_channel_mode: str = "Stereo"
        self._device_roomfit_items: list[PresetItem] = []
        self._device_active_roomfit_name: str = ""
        self._local_profiles: list[Profile] = []
        self.rew_pull_view = RewPullView(
            show_title=False, show_header=False, embedded=True
        )
        self._setup_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def action_buttons(self) -> list[QWidget]:
        """Return buttons that should be disabled while an operation is in progress."""
        return [
            self._next_btn,
            self._import_lr_btn,
            self._continue_with_warnings_btn,
            self._retry_btn,
            self._device_current_btn,
            self._device_load_btn,
            self._local_load_btn,
        ]

    def set_default_import_folder(self, path: str) -> None:
        """Set the Settings-configured default folder for the REW import dialogs.

        Called on startup and whenever Settings changes. Does not override a
        directory the user has already browsed to during this session - see
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
        self._source_items[FiltersSource.REW_API].setEnabled(available)
        if not available and self._current_source == FiltersSource.REW_API:
            self._source_combo.setCurrentIndex(_SOURCE_ORDER.index(FiltersSource.REW_FILE))

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

    def set_peq_presets(
        self,
        presets: list[PresetItem],
        active_name: str | None = None,
        active_channel_mode: str = "Stereo",
    ) -> None:
        """Populate the Device panel's PEQ presets.

        Args:
            presets: List of PresetItem objects for PEQ presets.
            active_name: Name of the preset currently active on this source,
                if known -- highlighted distinctly in the merged list. ""
                means the device confirmed the live config doesn't match any
                saved preset -- shown as a synthetic "Custom" row instead
                (see presets_device_view.build_custom_peq_item). None (the
                default) means this isn't known yet -- no highlight, no
                Custom row.
            active_channel_mode: Channel mode of the live active config,
                used only to label the synthetic "Custom" row when
                active_name is "".
        """
        self._device_peq_items = list(presets)
        self._device_active_peq_name = active_name
        self._device_active_peq_channel_mode = active_channel_mode
        self._populate_device_list()

    def set_roomfit_profiles(self, profiles: list[PresetItem], active_name: str = "") -> None:
        """Populate the Device panel's RoomFit profiles.

        Args:
            profiles: List of PresetItem objects for RoomFit profiles.
            active_name: Name of the profile currently active on the device,
                if any -- highlighted distinctly in the merged list.
        """
        self._device_roomfit_items = list(profiles)
        self._device_active_roomfit_name = active_name
        self._populate_device_list()

    def set_local_profiles(self, profiles: list[Profile]) -> None:
        """Populate the Local Library panel's saved-preset list.

        Args:
            profiles: List of locally-saved Profile objects.
        """
        self._local_profiles = list(profiles)
        self._populate_local_list()

    @property
    def current_source(self) -> FiltersSource:
        """The "Import source" dropdown's currently selected panel.

        Public so MainWindow can decide whether a re-triggered fetch (e.g.
        after a device switch's adapter becomes ready) is actually relevant
        to what's currently on screen.
        """
        return self._current_source

    def set_peq_unavailable(self) -> None:
        """Clear the Device panel's PEQ presets when the device doesn't
        support profile enumeration -- mirrors PresetsDeviceView's
        set_peq_unavailable() so both consumers of
        PrimaryWorkflowManager.peq_presets_unavailable stay in sync."""
        self._device_peq_items = []
        self._device_active_peq_name = None
        self._populate_device_list()

    def set_roomfit_hidden(self) -> None:
        """Clear the Device panel's RoomFit profiles when the device has no
        RoomFit support -- mirrors PresetsDeviceView's set_roomfit_hidden()
        so both consumers of PrimaryWorkflowManager.roomfit_profiles_hidden
        stay in sync."""
        self._device_roomfit_items = []
        self._device_active_roomfit_name = ""
        self._populate_device_list()

    def clear_device_presets(self) -> None:
        """Clear the Device panel's cached PEQ/RoomFit lists after a device
        switch.

        Without this, browsing back to the Filters step's Device panel after
        switching devices on the Connect step would keep showing the
        previous device's presets/profiles -- the combo's currentIndexChanged
        (which normally triggers a refetch, see _on_source_index_changed)
        never fires just from revisiting an already-selected wizard step, so
        the stale list would otherwise persist until the user manually
        flips the "Import source" dropdown away and back.

        Deliberately does NOT refetch here even if the Device panel is
        currently showing: the new device's adapter isn't ready yet at this
        call site (MainWindow._on_device_selected calls this synchronously,
        before the async capability probe completes) -- refetching here
        would read presets from the *old* device. MainWindow re-triggers the
        fetch itself once the new adapter is live (_on_capabilities_ready).
        """
        self._device_peq_items = []
        self._device_active_peq_name = None
        self._device_roomfit_items = []
        self._device_active_roomfit_name = ""
        self._populate_device_list()

    def show_warnings(self, warnings: list[str]) -> None:
        """Display validation warnings inline with a continue button."""
        self._error_section.setVisible(False)
        if not warnings:
            self._warnings_section.setVisible(False)
            return
        text = "\n".join(f"• {w}" for w in warnings)
        self._warnings_label.setText(text)
        self._warnings_section.setVisible(True)

    def show_error(self, message: str) -> None:
        """Display a parse/network error with retry option."""
        self._warnings_section.setVisible(False)
        self._error_label.setText(message)
        self._error_section.setVisible(True)

    def clear_results(self) -> None:
        """Reset to initial state - hide warnings/errors, revert to File Import."""
        self._warnings_section.setVisible(False)
        self._error_section.setVisible(False)
        self._source_combo.setCurrentIndex(_SOURCE_ORDER.index(FiltersSource.REW_FILE))
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
        """Build the page layout - dropdown + stacked source panels."""
        page_layout, content_wrapper = build_centered_content(self)

        # Page title
        title = make_page_title(
            "Import REW Filters", content_wrapper, object_name="FiltersPageTitle"
        )
        page_layout.addWidget(title)

        # --- Import source dropdown (above the instruction text, so the
        # instruction line always sits directly below it -- same position
        # and font regardless of which source panel is active) ---
        source_section = QWidget()
        source_layout = QHBoxLayout(source_section)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(SPACING_MD)

        source_label = QLabel("Import source:")
        source_label.setProperty("class", "subheading")
        source_layout.addWidget(source_label)

        self._source_combo = QComboBox()
        self._source_combo.setObjectName("FiltersSourceCombo")
        source_model = QStandardItemModel(self._source_combo)
        self._source_items: dict[FiltersSource, QStandardItem] = {}
        for source in _SOURCE_ORDER:
            item = QStandardItem(_SOURCE_LABELS[source])
            source_model.appendRow(item)
            self._source_items[source] = item
        self._source_combo.setModel(source_model)
        self._source_combo.currentIndexChanged.connect(self._on_source_index_changed)
        source_layout.addWidget(self._source_combo)
        source_layout.addStretch()

        page_layout.addWidget(source_section)

        # Instruction line (updated by _on_source_index_changed to match the
        # active source) -- stays in this exact layout position and keeps
        # this styling for every source, so switching source doesn't move or
        # restyle it, only its text changes.
        self._subtitle = QLabel(_SOURCE_SUBTITLES[FiltersSource.REW_FILE])
        self._subtitle.setWordWrap(True)
        self._subtitle.setProperty("class", "secondary")
        page_layout.addWidget(self._subtitle)

        # --- Stacked source panels -- given a stretch factor so it claims
        # the page's spare vertical space directly (matching how
        # rew_pull_view carried a stretch factor of 1 on its own before),
        # each panel bottom-anchors its own action button internally via its
        # own trailing addStretch(), the same layout trick this page always
        # used, just scoped per-panel instead of shared across all of them.
        self._source_panels = QStackedWidget()
        self._rew_file_panel = self._build_rew_file_panel()
        self._device_panel = self._build_device_panel()
        self._local_library_panel = self._build_local_library_panel()
        self._source_panels.addWidget(self._rew_file_panel)
        self._source_panels.addWidget(self.rew_pull_view)
        self._source_panels.addWidget(self._device_panel)
        self._source_panels.addWidget(self._local_library_panel)
        page_layout.addWidget(self._source_panels, 1)

        self.rew_pull_view.back_requested.connect(self._on_rew_pull_back_requested)

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

    def _build_rew_file_panel(self) -> QWidget:
        """Build the File Import panel - channel toggle + browse buttons."""
        panel = QWidget()
        file_layout = QVBoxLayout(panel)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(SPACING_LG)

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

        file_layout.addStretch()

        # --- Continue action row (bottom-anchored by the addStretch() above) ---
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

        file_layout.addWidget(self._file_import_actions)

        return panel

    def _build_device_panel(self) -> QWidget:
        """Build the Device panel - current-config action + merged preset list."""
        panel = QWidget()
        device_layout = QVBoxLayout(panel)
        device_layout.setContentsMargins(0, 0, 0, 0)
        device_layout.setSpacing(SPACING_MD)

        current_row = QHBoxLayout()
        self._device_current_btn = make_action_button(
            "Current configuration on device",
            object_name="filters_device_current",
            style_class="secondary",
        )
        self._device_current_btn.clicked.connect(self.device_pull_requested.emit)
        current_row.addWidget(self._device_current_btn)
        current_row.addStretch()
        device_layout.addLayout(current_row)

        list_label = QLabel("Or load a saved preset:")
        list_label.setProperty("class", "subheading")
        device_layout.addWidget(list_label)

        self._device_list = QListWidget()
        self._device_list.setObjectName("FiltersDeviceList")
        self._device_list.currentItemChanged.connect(self._on_device_selection_changed)
        device_layout.addWidget(self._device_list, 1)

        self._device_empty_label = QLabel("No presets found on this device.")
        self._device_empty_label.setProperty("class", "secondary")
        self._device_empty_label.setVisible(False)
        device_layout.addWidget(self._device_empty_label)

        device_actions_row = QHBoxLayout()
        device_actions_row.addStretch()
        self._device_load_btn = make_action_button(
            "Load Preset", object_name="filters_device_load", style_class="primary"
        )
        self._device_load_btn.setEnabled(False)
        self._device_load_btn.clicked.connect(self._on_device_load_clicked)
        device_actions_row.addWidget(self._device_load_btn)
        device_layout.addLayout(device_actions_row)

        return panel

    def _build_local_library_panel(self) -> QWidget:
        """Build the Local Library panel - list of saved presets."""
        panel = QWidget()
        local_layout = QVBoxLayout(panel)
        local_layout.setContentsMargins(0, 0, 0, 0)
        local_layout.setSpacing(SPACING_MD)

        self._local_list = QListWidget()
        self._local_list.setObjectName("FiltersLocalLibraryList")
        self._local_list.currentItemChanged.connect(self._on_local_selection_changed)
        local_layout.addWidget(self._local_list, 1)

        self._local_empty_label = QLabel("No saved presets yet.")
        self._local_empty_label.setProperty("class", "secondary")
        self._local_empty_label.setVisible(False)
        local_layout.addWidget(self._local_empty_label)

        local_actions_row = QHBoxLayout()
        local_actions_row.addStretch()
        self._local_load_btn = make_action_button(
            "Load Preset", object_name="filters_local_load", style_class="primary"
        )
        self._local_load_btn.setEnabled(False)
        self._local_load_btn.clicked.connect(self._on_local_load_clicked)
        local_actions_row.addWidget(self._local_load_btn)
        local_layout.addLayout(local_actions_row)

        return panel

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

        self._continue_with_warnings_btn = make_action_button(
            "Continue with adjustments",
            object_name="filters_continue_with_warnings",
            style_class="warning",
        )
        self._continue_with_warnings_btn.clicked.connect(self._on_continue_with_warnings)
        layout.addWidget(
            self._continue_with_warnings_btn, alignment=Qt.AlignmentFlag.AlignLeft
        )

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

        self._retry_btn = make_action_button(
            "Try Again", object_name="filters_retry_btn", style_class="secondary"
        )
        self._retry_btn.clicked.connect(self._on_retry)
        layout.addWidget(self._retry_btn, alignment=Qt.AlignmentFlag.AlignLeft)

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

    @Slot(int)
    def _on_source_index_changed(self, index: int) -> None:
        """Handle Import source dropdown selection.

        Args:
            index: New combo index, mapped to a FiltersSource via _SOURCE_ORDER.
        """
        self._current_source = _SOURCE_ORDER[index]
        self._source_panels.setCurrentIndex(index)
        self._warnings_section.setVisible(False)
        self._error_section.setVisible(False)
        self._subtitle.setText(_SOURCE_SUBTITLES[self._current_source])

        if self._current_source == FiltersSource.REW_API:
            self.rew_pull_view.set_connecting()
            self.rew_api_pull_requested.emit()
        elif self._current_source == FiltersSource.DEVICE:
            self.device_presets_requested.emit()
        elif self._current_source == FiltersSource.LOCAL_LIBRARY:
            self.local_profiles_requested.emit()

    @Slot()
    def _on_rew_pull_back_requested(self) -> None:
        """Handle Back from the embedded RewPullView - revert to File Import."""
        self._source_combo.setCurrentIndex(_SOURCE_ORDER.index(FiltersSource.REW_FILE))

    def _browse_start_dir(self) -> str:
        """Return the starting directory for the REW import file dialogs.

        A directory the user has already browsed to this session takes
        precedence over the Settings-configured default.
        """
        return self._session_import_dir or self._default_import_dir

    def _browse_rew_file(self, dialog_title: str) -> str | None:
        """Open a REW-file picker dialog and record the chosen directory.

        Returns:
            The selected path, or None if the dialog was cancelled.
        """
        path, _ = QFileDialog.getOpenFileName(
            self,
            dialog_title,
            self._browse_start_dir(),
            "REW Text Files (*.txt);;All Files (*)",
        )
        if not path:
            return None
        self._session_import_dir = str(Path(path).parent)
        return path

    @Slot()
    def _on_stereo_browse(self) -> None:
        """Open file dialog for stereo file selection (does not trigger import)."""
        path = self._browse_rew_file("Select REW Filter File")
        if path:
            self._stereo_path = path
            self._stereo_file_label.setText(Path(path).name)
            self._next_btn.setEnabled(True)

    @Slot()
    def _on_left_browse(self) -> None:
        """Open file dialog for left channel file."""
        path = self._browse_rew_file("Select Left Channel REW File")
        if path:
            self._left_path = path
            self._left_file_label.setText(Path(path).name)
            self._update_lr_import_button()

    @Slot()
    def _on_right_browse(self) -> None:
        """Open file dialog for right channel file."""
        path = self._browse_rew_file("Select Right Channel REW File")
        if path:
            self._right_path = path
            self._right_file_label.setText(Path(path).name)
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

    def _populate_device_list(self) -> None:
        """Rebuild the merged Device list from the stored PEQ + RoomFit items.

        Prepends a synthetic "Custom" row (see
        presets_device_view.build_custom_peq_item) when the PEQ fetch has
        resolved and found no active preset name -- selecting it and
        clicking Load Preset emits device_pull_requested (via
        _CUSTOM_ROW_MARKER), the same signal the "Current configuration on
        device" button emits, rather than device_item_selected.
        """
        self._device_list.clear()
        peq_rows = build_peq_rows(
            self._device_peq_items,
            self._device_active_peq_name,
            self._device_active_peq_channel_mode,
        )
        combined: list[tuple[PresetItem, bool, object]] = [
            (item, is_active, _CUSTOM_ROW_MARKER if item.is_custom else item)
            for item, is_active in peq_rows
        ]
        combined += [
            (item, item.name == self._device_active_roomfit_name, item)
            for item in self._device_roomfit_items
        ]
        self._device_empty_label.setVisible(not combined)
        self._device_list.setVisible(bool(combined))
        for display_item, is_active, user_data in combined:
            list_item = build_preset_list_item(display_item, is_active)
            list_item.setData(Qt.ItemDataRole.UserRole, user_data)
            self._device_list.addItem(list_item)
        self._device_load_btn.setEnabled(False)

    @Slot(QListWidgetItem, QListWidgetItem)
    def _on_device_selection_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        """Enable the Load Preset button once a Device-list row is selected."""
        self._device_load_btn.setEnabled(current is not None)

    @Slot()
    def _on_device_load_clicked(self) -> None:
        """Emit device_item_selected with the selected list row's PresetItem.

        The synthetic "Custom" row is the one exception: it carries
        _CUSTOM_ROW_MARKER instead of a PresetItem, and emits
        device_pull_requested -- same as the "Current configuration on
        device" button -- rather than device_item_selected.
        """
        current = self._device_list.currentItem()
        if current is None:
            return
        user_data = current.data(Qt.ItemDataRole.UserRole)
        if user_data is _CUSTOM_ROW_MARKER:
            self.device_pull_requested.emit()
            return
        self.device_item_selected.emit(user_data)

    def _populate_local_list(self) -> None:
        """Rebuild the Local Library list from the stored Profile list."""
        self._local_list.clear()
        self._local_empty_label.setVisible(not self._local_profiles)
        self._local_list.setVisible(bool(self._local_profiles))
        for profile in self._local_profiles:
            active_bands, total_bands = profile.band_counts()
            item_widget = _PresetItemWidget(
                name=profile.name,
                channel_mode=profile.channel_mode,
                active_bands=active_bands,
                total_bands=total_bands,
            )
            item = QListWidgetItem(self._local_list)
            item.setSizeHint(QSize(0, LIST_ITEM_HEIGHT))
            item.setData(Qt.ItemDataRole.UserRole, profile)
            self._local_list.setItemWidget(item, item_widget)
        self._local_load_btn.setEnabled(False)

    @Slot(QListWidgetItem, QListWidgetItem)
    def _on_local_selection_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        """Enable the Load Preset button once a Local Library row is selected."""
        self._local_load_btn.setEnabled(current is not None)

    @Slot()
    def _on_local_load_clicked(self) -> None:
        """Emit local_profile_selected with the selected list row's Profile."""
        current = self._local_list.currentItem()
        if current is None:
            return
        profile = current.data(Qt.ItemDataRole.UserRole)
        self.local_profile_selected.emit(profile)

    @Slot()
    def _on_continue_with_warnings(self) -> None:
        """User acknowledged warnings - emit filters_accepted."""
        self.filters_accepted.emit()

    @Slot()
    def _on_retry(self) -> None:
        """Retry after error - reset page to initial state."""
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
