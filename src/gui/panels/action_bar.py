"""Action bar panel with Import/Export/Pull/Push buttons and Dry Run toggle.

Provides the main action controls for the application. Emits signals for each
operation — does NOT perform any network I/O or business logic directly.
Button states are managed through public slots that reflect application state.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QWidget,
)

from src.models.capabilities import DeviceCapabilities


class ActionBar(QWidget):
    """Action bar with Import/Export/Pull/Push buttons and Dry Run toggle.

    Signals:
        import_requested: Emitted when user clicks Import REW.
        export_requested: Emitted when user clicks Export REW.
        pull_requested: Emitted when user clicks Pull.
        push_requested: Emitted when user clicks Push.
        dry_run_toggled: Emitted when dry run state changes. Payload: bool (active).
    """

    import_requested = Signal()
    export_requested = Signal()
    pull_requested = Signal()
    push_requested = Signal()
    dry_run_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        """Initialize the action bar.

        Args:
            parent: Optional Qt parent widget.
        """
        super().__init__(parent)
        self._device_selected = False
        self._source_selected = False
        self._filters_loaded = False
        self._supports_peq = False
        self._dry_run = False

        self._setup_ui()
        self._connect_signals()
        self._update_button_states()

    def _setup_ui(self) -> None:
        """Build the action bar layout."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Import REW button
        self._import_btn = QPushButton("Import REW")
        self._import_btn.setToolTip("Import filters from a REW EQ text file")
        layout.addWidget(self._import_btn)

        # Export REW button
        self._export_btn = QPushButton("Export REW")
        self._export_btn.setToolTip("Export current filters to a REW EQ text file")
        layout.addWidget(self._export_btn)

        layout.addSpacing(16)

        # Pull button
        self._pull_btn = QPushButton("Pull")
        self._pull_btn.setToolTip("Read PEQ filters from device")
        layout.addWidget(self._pull_btn)

        # Push button
        self._push_btn = QPushButton("Push")
        self._push_btn.setToolTip("Write PEQ filters to device")
        layout.addWidget(self._push_btn)

        layout.addSpacing(16)

        # Save as preset controls
        self._preset_checkbox = QCheckBox("Save as preset:")
        self._preset_checkbox.setEnabled(False)
        self._preset_checkbox.setToolTip("Save as device preset after successful push")
        layout.addWidget(self._preset_checkbox)

        self._preset_name_edit = QLineEdit()
        self._preset_name_edit.setPlaceholderText("Preset name...")
        self._preset_name_edit.setMaximumWidth(150)
        self._preset_name_edit.setEnabled(False)
        layout.addWidget(self._preset_name_edit)

        layout.addStretch()

        # Dry Run toggle
        self._dry_run_toggle = QPushButton("Dry Run")
        self._dry_run_toggle.setCheckable(True)
        self._dry_run_toggle.setToolTip("Preview write operations without sending to device")
        layout.addWidget(self._dry_run_toggle)

        # Dry Run label (hidden by default)
        self._dry_run_label = QLabel("DRY RUN")
        self._dry_run_label.setStyleSheet(
            "background-color: #DC3545; color: white; font-weight: bold; "
            "padding: 4px 8px; border-radius: 4px;"
        )
        self._dry_run_label.hide()
        layout.addWidget(self._dry_run_label)

    def _connect_signals(self) -> None:
        """Wire internal widget signals to handlers."""
        self._import_btn.clicked.connect(self.import_requested.emit)
        self._export_btn.clicked.connect(self.export_requested.emit)
        self._pull_btn.clicked.connect(self.pull_requested.emit)
        self._push_btn.clicked.connect(self.push_requested.emit)
        self._dry_run_toggle.toggled.connect(self._on_dry_run_toggled)
        self._preset_checkbox.toggled.connect(self._preset_name_edit.setEnabled)

    def _on_dry_run_toggled(self, checked: bool) -> None:
        """Handle dry run toggle state change.

        Args:
            checked: Whether dry run is now active.
        """
        self._dry_run = checked
        self._dry_run_label.setVisible(checked)
        self._update_button_states()
        self.dry_run_toggled.emit(checked)

    # ------------------------------------------------------------------
    # Public Slots
    # ------------------------------------------------------------------

    def set_device_selected(self, selected: bool) -> None:
        """Update button states based on device selection.

        Args:
            selected: Whether a device is currently selected.
        """
        self._device_selected = selected
        self._update_button_states()

    def set_source_selected(self, selected: bool) -> None:
        """Update button states based on source availability.

        Args:
            selected: Whether a source is currently selected.
        """
        self._source_selected = selected
        self._update_button_states()

    def set_filters_loaded(self, loaded: bool) -> None:
        """Update button states for filter availability.

        Args:
            loaded: Whether filters are currently loaded in the EQ panel.
        """
        self._filters_loaded = loaded
        self._update_button_states()

    def set_capabilities(self, capabilities: DeviceCapabilities) -> None:
        """Gate pull/push by PEQ support from device capabilities.

        Args:
            capabilities: Probed device capabilities.
        """
        self._supports_peq = capabilities.supports_peq
        self._update_button_states()

    def enable_preset_save(self, enabled: bool) -> None:
        """Enable or disable the 'Save as preset' controls after push.

        Args:
            enabled: Whether preset saving should be enabled.
        """
        self._preset_checkbox.setEnabled(enabled)
        if not enabled:
            self._preset_checkbox.setChecked(False)
            self._preset_name_edit.setEnabled(False)

    @property
    def preset_save_requested(self) -> bool:
        """Return True if user wants to save as device preset."""
        return self._preset_checkbox.isChecked()

    @property
    def preset_name(self) -> str:
        """Return the preset name entered by the user."""
        return self._preset_name_edit.text().strip()

    @property
    def dry_run(self) -> bool:
        """Return current dry run state."""
        return self._dry_run

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _update_button_states(self) -> None:
        """Recalculate enabled/disabled state for all action buttons."""
        # Import REW: always enabled when a device is selected (works offline)
        self._import_btn.setEnabled(self._device_selected)

        # Export REW: enabled when filters are loaded
        self._export_btn.setEnabled(self._device_selected and self._filters_loaded)

        # Pull: enabled when device + source selected and device supports PEQ
        self._pull_btn.setEnabled(
            self._device_selected and self._source_selected and self._supports_peq
        )

        # Push: enabled when device + source + filters available and NOT dry run
        self._push_btn.setEnabled(
            self._device_selected
            and self._source_selected
            and self._filters_loaded
            and self._supports_peq
            and not self._dry_run
        )
