"""SettingsView — application configuration panel.

Provides sections for Appearance, Paths, Behavior, Logs, and Support.
All settings changes are emitted via signals; the view does NOT persist
settings itself — the parent (MainWindow / controller) handles persistence.

Requirements referenced: 24.1, 24.2, 24.5, 24.9, 24.10, 24.11, 24.12, 24.14, 24.15, 25.4.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
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
from src.utils.app_dirs import to_display_path
from src.utils.paths import is_writable_directory


class SettingsView(QWidget):
    """App configuration view with Appearance, Paths, Behavior, Logs, Support sections.

    The view emits signals when settings change. It does NOT write to disk —
    the owning controller handles persistence via settings.json.

    Signals:
        theme_changed: Emitted with the new theme mode string ("Light", "Dark", "System").
        settings_changed: Emitted with a dict of all current settings values.
        support_bundle_requested: Emitted when the user clicks "Generate Support Bundle".
        show_onboarding_requested: Emitted when the user clicks "Show onboarding again".
    """

    theme_changed = Signal(str)
    settings_changed = Signal(dict)
    support_bundle_requested = Signal()
    show_onboarding_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SettingsView")
        self._setup_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def action_buttons(self) -> list[QWidget]:
        """Return buttons that should be disabled while an operation is in progress."""
        return [self._bundle_btn]

    def set_settings(self, settings: dict[str, Any]) -> None:
        """Populate all controls from a settings dict.

        Expected keys:
            theme: str ("Light", "Dark", "System")
            log_directory: str
            presets_directory: str
            rew_folder: str
            discovery_timeout: int (seconds)
            dry_run_default: bool
        """
        # Block signals while populating to avoid feedback loops
        self._theme_combo.blockSignals(True)
        theme = settings.get("theme", "System")
        idx = self._theme_combo.findText(theme)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)
        self._theme_combo.blockSignals(False)

        self._log_dir_edit.setText(to_display_path(settings.get("log_directory", "")))
        self._presets_dir_edit.setText(
            to_display_path(settings.get("presets_directory", ""))
        )
        self._rew_folder_edit.setText(to_display_path(settings.get("rew_folder", "")))

        self._timeout_spin.blockSignals(True)
        self._timeout_spin.setValue(settings.get("discovery_timeout", 5))
        self._timeout_spin.blockSignals(False)

        self._dry_run_check.blockSignals(True)
        self._dry_run_check.setChecked(settings.get("dry_run_default", False))
        self._dry_run_check.blockSignals(False)

    def set_log_files(self, log_files: list[dict[str, str]]) -> None:
        """Populate the log file list.

        Each dict should have: name, size, modified.

        Args:
            log_files: List of dicts with log file info.
        """
        # Clear existing items
        while self._log_list_layout.count():
            item = self._log_list_layout.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.deleteLater()

        for log_info in log_files:
            row = QWidget(self._log_list_widget)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 2, 0, 2)
            row_layout.setSpacing(SPACING_SM)

            name_label = QLabel(log_info.get("name", ""), row)
            row_layout.addWidget(name_label)

            size_label = QLabel(log_info.get("size", ""), row)
            size_label.setProperty("class", "caption")
            row_layout.addWidget(size_label)

            row_layout.addStretch()
            self._log_list_layout.addWidget(row)

    def get_current_settings(self) -> dict[str, Any]:
        """Return a dict of all current control values."""
        return {
            "theme": self._theme_combo.currentText(),
            "log_directory": self._log_dir_edit.text(),
            "presets_directory": self._presets_dir_edit.text(),
            "rew_folder": self._rew_folder_edit.text(),
            "discovery_timeout": self._timeout_spin.value(),
            "dry_run_default": self._dry_run_check.isChecked(),
        }

    # ------------------------------------------------------------------
    # Private: UI construction
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        """Build the settings page layout.

        Uses the shared `build_centered_content` column (matching every
        other page/view) instead of hand-rolling an equivalent
        QHBoxLayout+AlignHCenter+maximumWidth centering block -- this view
        used to be the only one with its own duplicate of that pattern.
        """
        content_layout, content_wrapper = build_centered_content(self)

        title = make_page_title(
            "Settings", content_wrapper, object_name="SettingsViewTitle"
        )
        content_layout.addWidget(title)

        # Scrollable area for the sections below the title
        scroll = QScrollArea(content_wrapper)
        scroll.setObjectName("SettingsViewScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(SPACING_LG)

        # Build sections
        body_layout.addWidget(self._build_appearance_section(body))
        body_layout.addWidget(self._build_paths_section(body))
        body_layout.addWidget(self._build_behavior_section(body))
        body_layout.addWidget(self._build_logs_section(body))
        body_layout.addWidget(self._build_support_section(body))

        body_layout.addStretch()

        scroll.setWidget(body)
        content_layout.addWidget(scroll, 1)

    def _build_appearance_section(self, parent: QWidget) -> QGroupBox:
        """Build the Appearance section with theme toggle (Req 25.4)."""
        group = QGroupBox("Appearance", parent)
        group.setObjectName("SettingsAppearanceGroup")
        layout = QVBoxLayout(group)
        layout.setSpacing(SPACING_MD)

        # Theme selector row
        theme_row = QWidget(group)
        theme_layout = QHBoxLayout(theme_row)
        theme_layout.setContentsMargins(0, 0, 0, 0)
        theme_layout.setSpacing(SPACING_MD)

        theme_label = QLabel("Theme:", theme_row)
        theme_layout.addWidget(theme_label)

        self._theme_combo = QComboBox(theme_row)
        self._theme_combo.setObjectName("SettingsThemeCombo")
        self._theme_combo.addItems(["Light", "Dark", "System"])
        self._theme_combo.setCurrentText("System")
        self._theme_combo.setMinimumWidth(120)
        self._theme_combo.currentTextChanged.connect(self._on_theme_changed)
        theme_layout.addWidget(self._theme_combo)

        theme_layout.addStretch()
        layout.addWidget(theme_row)

        description = QLabel(
            "Choose Light, Dark, or System (follows your OS preference).",
            group,
        )
        description.setProperty("class", "caption")
        description.setWordWrap(True)
        layout.addWidget(description)

        return group

    def _build_paths_section(self, parent: QWidget) -> QGroupBox:
        """Build the Paths section (Req 24.9, 24.10, 24.11)."""
        group = QGroupBox("Paths", parent)
        group.setObjectName("SettingsPathsGroup")
        layout = QVBoxLayout(group)
        layout.setSpacing(SPACING_MD)

        # Log directory (Req 24.9)
        self._log_dir_edit, log_row = self._build_path_row(
            group, "Log directory:", "log_dir"
        )
        layout.addWidget(log_row)

        # Presets directory (Req 24.10)
        self._presets_dir_edit, presets_row = self._build_path_row(
            group, "Presets directory:", "presets_dir"
        )
        layout.addWidget(presets_row)

        # Default REW import/export folder (Req 24.11)
        self._rew_folder_edit, rew_row = self._build_path_row(
            group, "Default REW import/export folder:", "rew_folder"
        )
        layout.addWidget(rew_row)

        # Validation message label
        self._path_validation_label = QLabel("", group)
        self._path_validation_label.setObjectName("SettingsPathValidation")
        self._path_validation_label.setProperty("class", "pathError")
        self._path_validation_label.setWordWrap(True)
        self._path_validation_label.setVisible(False)
        layout.addWidget(self._path_validation_label)

        # Restart note
        restart_note = QLabel(
            "Path changes take effect after restarting the app.", group
        )
        restart_note.setObjectName("SettingsPathRestartNote")
        restart_note.setProperty("class", "caption")
        layout.addWidget(restart_note)

        return group

    def _build_path_row(
        self, parent: QWidget, label_text: str, object_prefix: str
    ) -> tuple[QLineEdit, QWidget]:
        """Build a path row with label, line edit, and browse button."""
        row = QWidget(parent)
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(SPACING_SM)

        label = QLabel(label_text, row)
        row_layout.addWidget(label)

        input_row = QWidget(row)
        input_layout = QHBoxLayout(input_row)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(SPACING_SM)

        line_edit = QLineEdit(input_row)
        line_edit.setObjectName(f"Settings_{object_prefix}_edit")
        line_edit.setReadOnly(True)
        line_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        input_layout.addWidget(line_edit)

        browse_btn = make_action_button(
            "Browse...",
            object_name=f"Settings_{object_prefix}_browse",
            style_class="secondary",
            parent=input_row,
        )
        browse_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        browse_btn.clicked.connect(
            lambda: self._on_browse_clicked(line_edit, label_text)
        )
        input_layout.addWidget(browse_btn)

        row_layout.addWidget(input_row)
        return line_edit, row

    def _build_behavior_section(self, parent: QWidget) -> QGroupBox:
        """Build the Behavior section (Req 24.15)."""
        group = QGroupBox("Behavior", parent)
        group.setObjectName("SettingsBehaviorGroup")
        layout = QVBoxLayout(group)
        layout.setSpacing(SPACING_MD)

        # Discovery timeout (Req 24.15)
        timeout_row = QWidget(group)
        timeout_layout = QHBoxLayout(timeout_row)
        timeout_layout.setContentsMargins(0, 0, 0, 0)
        timeout_layout.setSpacing(SPACING_MD)

        timeout_label = QLabel("Discovery timeout (seconds):", timeout_row)
        timeout_layout.addWidget(timeout_label)

        self._timeout_spin = QSpinBox(timeout_row)
        self._timeout_spin.setObjectName("SettingsTimeoutSpin")
        self._timeout_spin.setMinimum(1)
        self._timeout_spin.setMaximum(30)
        self._timeout_spin.setValue(5)
        self._timeout_spin.setSuffix(" s")
        self._timeout_spin.valueChanged.connect(self._on_setting_changed)
        timeout_layout.addWidget(self._timeout_spin)

        timeout_layout.addStretch()
        layout.addWidget(timeout_row)

        # Dry Run default (Req 24.15)
        self._dry_run_check = QCheckBox("Enable Dry Run by default for new sessions", group)
        self._dry_run_check.setObjectName("SettingsDryRunCheck")
        self._dry_run_check.stateChanged.connect(self._on_setting_changed)
        layout.addWidget(self._dry_run_check)

        return group

    def _build_logs_section(self, parent: QWidget) -> QGroupBox:
        """Build the Logs section (Req 24.1, 24.2, 24.5)."""
        group = QGroupBox("Logs", parent)
        group.setObjectName("SettingsLogsGroup")
        layout = QVBoxLayout(group)
        layout.setSpacing(SPACING_MD)

        # Log file list container
        self._log_list_widget = QWidget(group)
        self._log_list_layout = QVBoxLayout(self._log_list_widget)
        self._log_list_layout.setContentsMargins(0, 0, 0, 0)
        self._log_list_layout.setSpacing(SPACING_SM)
        layout.addWidget(self._log_list_widget)

        # Action buttons row
        btn_row = QWidget(group)
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(SPACING_MD)

        # Open Log Folder button (Req 24.1)
        open_folder_btn = make_action_button(
            "Open Log Folder", object_name="SettingsOpenLogFolderBtn",
            style_class="secondary", parent=btn_row,
        )
        open_folder_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        open_folder_btn.clicked.connect(self._on_open_log_folder)
        btn_layout.addWidget(open_folder_btn)

        # Copy Log Path button (Req 24.5)
        copy_path_btn = make_action_button(
            "Copy Log Path", object_name="SettingsCopyLogPathBtn",
            style_class="secondary", parent=btn_row,
        )
        copy_path_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        copy_path_btn.clicked.connect(self._on_copy_log_path)
        btn_layout.addWidget(copy_path_btn)

        btn_layout.addStretch()
        layout.addWidget(btn_row)

        return group

    def _build_support_section(self, parent: QWidget) -> QGroupBox:
        """Build the Support section (Req 24.12, 24.14)."""
        group = QGroupBox("Support", parent)
        group.setObjectName("SettingsSupportGroup")
        layout = QVBoxLayout(group)
        layout.setSpacing(SPACING_MD)

        # Generate Support Bundle button (Req 24.12)
        self._bundle_btn = make_action_button(
            "Generate Support Bundle", object_name="SettingsSupportBundleBtn",
            style_class="secondary", parent=group,
        )
        self._bundle_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._bundle_btn.clicked.connect(self._on_support_bundle_clicked)
        layout.addWidget(self._bundle_btn)

        bundle_desc = QLabel(
            "Creates a ZIP with logs and config for sharing with support. "
            "No user filter data or profiles are included.",
            group,
        )
        bundle_desc.setProperty("class", "caption")
        bundle_desc.setWordWrap(True)
        layout.addWidget(bundle_desc)

        # Show onboarding again button
        onboarding_btn = make_action_button(
            "Show onboarding again", object_name="SettingsShowOnboardingBtn",
            style_class="secondary", parent=group,
        )
        onboarding_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        onboarding_btn.clicked.connect(self._on_show_onboarding_clicked)
        layout.addWidget(onboarding_btn)

        return group

    # ------------------------------------------------------------------
    # Private: Event handlers
    # ------------------------------------------------------------------

    @Slot(str)
    def _on_theme_changed(self, theme: str) -> None:
        """Handle theme combo change."""
        self.theme_changed.emit(theme)
        self._emit_settings_changed()

    @Slot()
    def _on_setting_changed(self) -> None:
        """Handle any non-theme setting change."""
        self._emit_settings_changed()

    @Slot()
    def _on_browse_clicked(self, line_edit: QLineEdit, label: str) -> None:
        """Open a folder picker and validate the selection."""
        current_path = line_edit.text()
        start_dir = current_path if current_path and Path(current_path).exists() else ""

        folder = QFileDialog.getExistingDirectory(
            self,
            f"Select {label.rstrip(':')}",
            start_dir,
            QFileDialog.Option.ShowDirsOnly,
        )

        if folder:
            # Validate directory exists and is writable (Req 24.9)
            if is_writable_directory(folder):
                line_edit.setText(to_display_path(folder))
                self._path_validation_label.setVisible(False)
                self._emit_settings_changed()
            else:
                self._path_validation_label.setText(
                    f"Directory is not writable: {folder}"
                )
                self._path_validation_label.setVisible(True)

    @Slot()
    def _on_open_log_folder(self) -> None:
        """Open the log directory in the system file explorer (Req 24.1)."""
        log_dir = self._log_dir_edit.text()
        if log_dir and Path(log_dir).is_dir():
            self._open_folder(log_dir)

    @Slot()
    def _on_copy_log_path(self) -> None:
        """Copy the log directory path to clipboard (Req 24.5)."""
        log_dir = self._log_dir_edit.text()
        if log_dir:
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(log_dir)

    @Slot()
    def _on_support_bundle_clicked(self) -> None:
        """Emit signal to request support bundle generation (Req 24.12)."""
        self.support_bundle_requested.emit()

    @Slot()
    def _on_show_onboarding_clicked(self) -> None:
        """Emit signal to show onboarding again."""
        self.show_onboarding_requested.emit()

    # ------------------------------------------------------------------
    # Private: Helpers
    # ------------------------------------------------------------------

    def _emit_settings_changed(self) -> None:
        """Collect all control values and emit settings_changed."""
        self.settings_changed.emit(self.get_current_settings())

    @staticmethod
    def _open_folder(path: str) -> None:
        """Open a folder in the OS file explorer."""
        system = sys.platform
        if system == "win32":
            os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
        elif system == "darwin":
            subprocess.Popen(["/usr/bin/open", path])  # noqa: S603
        else:
            subprocess.Popen(["/usr/bin/xdg-open", path])  # noqa: S603
