"""Unit tests for secondary views: PresetsDeviceView, MyPresetsView, SettingsView.

HelpView tests already exist in test_help_view.py — not duplicated here.

Requirements referenced: 15.1-15.12, 8.3-8.6, 24.1-24.15.
"""

from __future__ import annotations

from PySide6.QtCore import Qt

from src.gui.views.my_presets_view import MyPresetsView
from src.gui.views.presets_device_view import PresetItem, PresetsDeviceView
from src.gui.views.settings_view import SettingsView
from src.models.canonical import CanonicalFilter
from src.models.profile import Profile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_peq_presets(count: int = 3) -> list[PresetItem]:
    """Create a list of PEQ PresetItem objects for testing."""
    return [
        PresetItem(name=f"PEQ Preset {i}", channel_mode="Stereo", preset_type="PEQ")
        for i in range(1, count + 1)
    ]


def _make_roomfit_profiles(count: int = 2) -> list[PresetItem]:
    """Create a list of RoomFit PresetItem objects for testing."""
    return [
        PresetItem(name=f"RoomFit Profile {i}", channel_mode="Stereo", preset_type="RoomFit")
        for i in range(1, count + 1)
    ]


def _make_profile(name: str = "Test Preset", gain: float = 2.5) -> Profile:
    """Create a stereo Profile with a few canonical filters."""
    filters = [
        CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=gain, q=1.0),
        CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=0.0, q=1.5),
        CanonicalFilter(type="HS", frequency_hz=8000.0, gain_db=-3.0, q=0.7),
    ]
    return Profile(name=name, channel_mode="stereo", filters=filters)


# ---------------------------------------------------------------------------
# TestPresetsDeviceView
# ---------------------------------------------------------------------------


class TestPresetsDeviceViewEmptyState:
    """Tests for PresetsDeviceView empty/no-device state."""

    def test_starts_in_empty_state(self, qtbot) -> None:
        """PresetsDeviceView starts showing the empty (no device) state."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)
        view.show()

        assert view._empty_widget.isVisible()
        assert not view._content_widget.isVisible()

    def test_set_no_device_shows_empty(self, qtbot) -> None:
        """set_no_device() switches back to empty state after content was loaded."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)
        view.show()

        view.set_peq_presets(_make_peq_presets())
        assert view._content_widget.isVisible()

        view.set_no_device()
        assert view._empty_widget.isVisible()
        assert not view._content_widget.isVisible()


class TestPresetsDeviceViewSections:
    """Tests for PEQ and RoomFit section display."""

    def test_set_peq_presets_populates_list(self, qtbot) -> None:
        """set_peq_presets() populates the PEQ list with correct item count."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)
        view.show()

        presets = _make_peq_presets(5)
        view.set_peq_presets(presets)

        assert view._peq_list.count() == 5
        assert view._content_widget.isVisible()

    def test_set_roomfit_profiles_populates_list(self, qtbot) -> None:
        """set_roomfit_profiles() populates the RoomFit list with correct count."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)
        view.show()

        profiles = _make_roomfit_profiles(4)
        view.set_roomfit_profiles(profiles)

        assert view._roomfit_list.count() == 4
        assert view._content_widget.isVisible()

    def test_set_peq_unavailable_shows_message(self, qtbot) -> None:
        """set_peq_unavailable() shows unavailable label and hides PEQ list."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)
        view.show()

        view.set_peq_presets(_make_peq_presets())
        view.set_peq_unavailable()

        assert view._peq_unavailable_label.isVisible()
        assert not view._peq_list.isVisible()

    def test_set_roomfit_hidden_hides_section(self, qtbot) -> None:
        """set_roomfit_hidden() hides the entire RoomFit section."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)
        view.show()

        view.set_peq_presets(_make_peq_presets())
        view.set_roomfit_hidden()

        assert not view._roomfit_section.isVisible()


class TestPresetsDeviceViewSearch:
    """Tests for search field visibility and filtering."""

    def test_search_hidden_when_few_items(self, qtbot) -> None:
        """Search field hidden when 10 or fewer items."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)
        view.show()

        view.set_peq_presets(_make_peq_presets(5))
        assert not view._peq_search.isVisible()

    def test_search_visible_when_many_items(self, qtbot) -> None:
        """Search field visible when more than 10 items."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)
        view.show()

        view.set_peq_presets(_make_peq_presets(15))
        assert view._peq_search.isVisible()

    def test_search_filters_peq_items(self, qtbot) -> None:
        """Typing in the PEQ search field filters the displayed items."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)
        view.show()

        presets = [
            PresetItem(name="Living Room", channel_mode="Stereo", preset_type="PEQ"),
            PresetItem(name="Bedroom", channel_mode="Stereo", preset_type="PEQ"),
            PresetItem(name="Kitchen", channel_mode="Stereo", preset_type="PEQ"),
        ]
        # Need > 10 items for search to be visible, so pad with extras
        presets += _make_peq_presets(10)
        view.set_peq_presets(presets)

        view._peq_search.setText("Living")
        assert view._peq_list.count() == 1


class TestPresetsDeviceViewSelection:
    """Tests for multi-select and button enable/disable states."""

    def test_no_selection_disables_buttons(self, qtbot) -> None:
        """All action buttons disabled when nothing is selected."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)
        view.show()

        view.set_peq_presets(_make_peq_presets(3))

        # Ensure nothing selected
        view._peq_list.clearSelection()
        assert not view._export_btn.isEnabled()
        assert not view._save_btn.isEnabled()
        assert not view._load_btn.isEnabled()
        assert not view._copy_btn.isEnabled()

    def test_multi_select_enables_batch_buttons(self, qtbot) -> None:
        """Selecting multiple items enables Export, Save, Copy buttons."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)
        view.show()

        view.set_peq_presets(_make_peq_presets(3))
        view._peq_list.selectAll()

        assert view._export_btn.isEnabled()
        assert view._save_btn.isEnabled()
        assert view._copy_btn.isEnabled()
        # Load into Editor requires single selection
        assert not view._load_btn.isEnabled()

    def test_single_select_enables_load_button(self, qtbot) -> None:
        """Selecting a single item enables the Load into Editor button."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)
        view.show()

        view.set_peq_presets(_make_peq_presets(3))
        view._peq_list.setCurrentRow(0)

        assert view._load_btn.isEnabled()


class TestPresetsDeviceViewSignals:
    """Tests for signal emission on button clicks."""

    def test_export_requested_signal(self, qtbot) -> None:
        """Clicking Export emits export_requested with selected items."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)
        view.show()

        view.set_peq_presets(_make_peq_presets(2))
        view._peq_list.selectAll()

        with qtbot.waitSignal(view.export_requested, timeout=1000) as blocker:
            view._export_btn.click()

        assert len(blocker.args[0]) == 2

    def test_save_to_my_presets_signal(self, qtbot) -> None:
        """Clicking Save emits save_to_my_presets with selected items."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)
        view.show()

        view.set_peq_presets(_make_peq_presets(2))
        view._peq_list.setCurrentRow(0)

        with qtbot.waitSignal(view.save_to_my_presets, timeout=1000) as blocker:
            view._save_btn.click()

        assert len(blocker.args[0]) == 1

    def test_load_into_editor_signal(self, qtbot) -> None:
        """Clicking Load emits load_into_editor with the single selected item."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)
        view.show()

        presets = _make_peq_presets(3)
        view.set_peq_presets(presets)
        view._peq_list.setCurrentRow(1)

        with qtbot.waitSignal(view.load_into_editor, timeout=1000) as blocker:
            view._load_btn.click()

        assert blocker.args[0].name == "PEQ Preset 2"

    def test_copy_to_device_requested_signal(self, qtbot) -> None:
        """Clicking Copy emits copy_to_device_requested with selected items."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)
        view.show()

        view.set_peq_presets(_make_peq_presets(2))
        view._peq_list.selectAll()

        with qtbot.waitSignal(view.copy_to_device_requested, timeout=1000) as blocker:
            view._copy_btn.click()

        assert len(blocker.args[0]) == 2


# ---------------------------------------------------------------------------
# TestMyPresetsView
# ---------------------------------------------------------------------------


class TestMyPresetsViewPopulation:
    """Tests for preset list population and empty state."""

    def test_set_presets_populates_list(self, qtbot) -> None:
        """set_presets() fills the list widget with profiles."""
        view = MyPresetsView()
        qtbot.addWidget(view)
        view.show()

        profiles = [_make_profile(f"Preset {i}") for i in range(3)]
        view.set_presets(profiles)

        assert view._list_widget.count() == 3
        assert view._list_widget.isVisible()
        assert not view._empty_label.isVisible()

    def test_empty_presets_shows_empty_label(self, qtbot) -> None:
        """set_presets([]) shows the empty-state label."""
        view = MyPresetsView()
        qtbot.addWidget(view)
        view.show()

        view.set_presets([])

        assert view._empty_label.isVisible()
        assert not view._list_widget.isVisible()

    def test_preset_count_property(self, qtbot) -> None:
        """preset_count() returns the number of presets held."""
        view = MyPresetsView()
        qtbot.addWidget(view)

        view.set_presets([_make_profile("A"), _make_profile("B")])
        assert view.preset_count() == 2


class TestMyPresetsViewSearch:
    """Tests for search field visibility and filtering."""

    def test_search_hidden_below_threshold(self, qtbot) -> None:
        """Search field hidden when 10 or fewer presets."""
        view = MyPresetsView()
        qtbot.addWidget(view)
        view.show()

        view.set_presets([_make_profile(f"P{i}") for i in range(5)])
        assert not view._search_field.isVisible()

    def test_search_visible_above_threshold(self, qtbot) -> None:
        """Search field visible when more than 10 presets."""
        view = MyPresetsView()
        qtbot.addWidget(view)
        view.show()

        view.set_presets([_make_profile(f"Preset {i}") for i in range(12)])
        assert view._search_field.isVisible()

    def test_search_filters_by_name(self, qtbot) -> None:
        """Typing in search field filters presets by name."""
        view = MyPresetsView()
        qtbot.addWidget(view)
        view.show()

        profiles = [
            _make_profile("Living Room EQ"),
            _make_profile("Bedroom EQ"),
            _make_profile("Kitchen EQ"),
        ]
        view.set_presets(profiles)
        view._search_field.setText("Living")

        assert view._list_widget.count() == 1


class TestMyPresetsViewRename:
    """Tests for inline rename via double-click."""

    def test_double_click_shows_rename_editor(self, qtbot) -> None:
        """Double-clicking an item shows the rename editor."""
        view = MyPresetsView()
        qtbot.addWidget(view)
        view.show()

        view.set_presets([_make_profile("Original Name")])

        item = view._list_widget.item(0)
        view._list_widget.itemDoubleClicked.emit(item)

        assert view._rename_editor.isVisible()
        assert view._rename_editor.text() == "Original Name"

    def test_rename_editor_emits_rename_requested(self, qtbot) -> None:
        """Completing a rename emits rename_requested(old_name, new_name)."""
        view = MyPresetsView()
        qtbot.addWidget(view)
        view.show()

        view.set_presets([_make_profile("Old Name")])

        item = view._list_widget.item(0)
        view._list_widget.itemDoubleClicked.emit(item)

        view._rename_editor.setText("New Name")

        with qtbot.waitSignal(view.rename_requested, timeout=1000) as blocker:
            view._rename_editor.editingFinished.emit()

        assert blocker.args == ["Old Name", "New Name"]

    def test_rename_same_name_does_not_emit(self, qtbot) -> None:
        """Renaming to the same name does not emit rename_requested."""
        view = MyPresetsView()
        qtbot.addWidget(view)
        view.show()

        view.set_presets([_make_profile("Same Name")])

        item = view._list_widget.item(0)
        view._list_widget.itemDoubleClicked.emit(item)
        view._rename_editor.setText("Same Name")

        # Should NOT emit
        emitted = []
        view.rename_requested.connect(lambda old, new: emitted.append((old, new)))
        view._rename_editor.editingFinished.emit()

        assert len(emitted) == 0


class TestMyPresetsViewContextMenu:
    """Tests for context menu actions and signal emission."""

    def test_load_requested_signal(self, qtbot) -> None:
        """load_requested signal emits with the Profile object."""
        view = MyPresetsView()
        qtbot.addWidget(view)
        view.show()

        profile = _make_profile("My EQ")
        view.set_presets([profile])

        view._list_widget.setCurrentRow(0)
        item = view._list_widget.item(0)
        stored_profile = item.data(Qt.ItemDataRole.UserRole)

        with qtbot.waitSignal(view.load_requested, timeout=1000) as blocker:
            view.load_requested.emit(stored_profile)

        assert blocker.args[0].name == "My EQ"

    def test_delete_requested_signal(self, qtbot) -> None:
        """delete_requested signal emits with the correct preset name."""
        view = MyPresetsView()
        qtbot.addWidget(view)

        view.set_presets([_make_profile("To Delete")])

        with qtbot.waitSignal(view.delete_requested, timeout=1000) as blocker:
            view.delete_requested.emit("To Delete")

        assert blocker.args == ["To Delete"]

    def test_duplicate_requested_signal(self, qtbot) -> None:
        """duplicate_requested signal emits with the correct preset name."""
        view = MyPresetsView()
        qtbot.addWidget(view)

        view.set_presets([_make_profile("Original")])

        with qtbot.waitSignal(view.duplicate_requested, timeout=1000) as blocker:
            view.duplicate_requested.emit("Original")

        assert blocker.args == ["Original"]


# ---------------------------------------------------------------------------
# TestSettingsView
# ---------------------------------------------------------------------------


class TestSettingsViewPopulation:
    """Tests for set_settings() populating controls."""

    def test_set_settings_populates_theme(self, qtbot) -> None:
        """set_settings() sets the theme combo to the correct value."""
        view = SettingsView()
        qtbot.addWidget(view)

        view.set_settings({"theme": "Dark"})
        assert view._theme_combo.currentText() == "Dark"

    def test_set_settings_populates_paths(self, qtbot) -> None:
        """set_settings() populates log/presets/rew path fields."""
        view = SettingsView()
        qtbot.addWidget(view)

        view.set_settings({
            "theme": "System",
            "log_directory": "/var/log/wiim",
            "presets_directory": "/home/user/presets",
            "rew_export_folder": "/home/user/rew",
            "discovery_timeout": 10,
            "dry_run_default": True,
            "last_device": "Living Room Pro",
        })

        assert view._log_dir_edit.text() == "/var/log/wiim"
        assert view._presets_dir_edit.text() == "/home/user/presets"
        assert view._rew_export_edit.text() == "/home/user/rew"

    def test_set_settings_populates_behavior(self, qtbot) -> None:
        """set_settings() populates timeout, dry run, and last device."""
        view = SettingsView()
        qtbot.addWidget(view)

        view.set_settings({
            "theme": "Light",
            "log_directory": "",
            "presets_directory": "",
            "rew_export_folder": "",
            "discovery_timeout": 15,
            "dry_run_default": True,
            "last_device": "Bedroom",
        })

        assert view._timeout_spin.value() == 15
        assert view._dry_run_check.isChecked()
        assert view._last_device_label.text() == "Bedroom"


class TestSettingsViewSignals:
    """Tests for signal emission on user interactions."""

    def test_theme_changed_signal_on_combo_change(self, qtbot) -> None:
        """Changing the theme combo emits theme_changed with new value."""
        view = SettingsView()
        qtbot.addWidget(view)

        with qtbot.waitSignal(view.theme_changed, timeout=1000) as blocker:
            view._theme_combo.setCurrentText("Dark")

        assert blocker.args == ["Dark"]

    def test_settings_changed_on_theme_change(self, qtbot) -> None:
        """Changing the theme combo also emits settings_changed."""
        view = SettingsView()
        qtbot.addWidget(view)

        with qtbot.waitSignal(view.settings_changed, timeout=1000) as blocker:
            view._theme_combo.setCurrentText("Light")

        settings = blocker.args[0]
        assert settings["theme"] == "Light"

    def test_settings_changed_on_timeout_change(self, qtbot) -> None:
        """Changing the timeout spinner emits settings_changed."""
        view = SettingsView()
        qtbot.addWidget(view)

        with qtbot.waitSignal(view.settings_changed, timeout=1000) as blocker:
            view._timeout_spin.setValue(12)

        settings = blocker.args[0]
        assert settings["discovery_timeout"] == 12

    def test_settings_changed_on_dry_run_toggle(self, qtbot) -> None:
        """Toggling dry run checkbox emits settings_changed."""
        view = SettingsView()
        qtbot.addWidget(view)

        with qtbot.waitSignal(view.settings_changed, timeout=1000) as blocker:
            view._dry_run_check.setChecked(True)

        settings = blocker.args[0]
        assert settings["dry_run_default"] is True

    def test_support_bundle_requested_signal(self, qtbot) -> None:
        """support_bundle_requested signal is emittable."""
        view = SettingsView()
        qtbot.addWidget(view)

        with qtbot.waitSignal(view.support_bundle_requested, timeout=1000):
            view.support_bundle_requested.emit()

    def test_show_onboarding_requested_signal(self, qtbot) -> None:
        """show_onboarding_requested signal is emittable."""
        view = SettingsView()
        qtbot.addWidget(view)

        with qtbot.waitSignal(view.show_onboarding_requested, timeout=1000):
            view.show_onboarding_requested.emit()


class TestSettingsViewGetCurrentSettings:
    """Tests for get_current_settings() returning correct dict."""

    def test_get_current_settings_defaults(self, qtbot) -> None:
        """get_current_settings() returns sensible defaults before set_settings."""
        view = SettingsView()
        qtbot.addWidget(view)

        settings = view.get_current_settings()

        assert "theme" in settings
        assert settings["theme"] == "System"  # default
        assert "discovery_timeout" in settings
        assert settings["discovery_timeout"] == 5  # default
        assert "dry_run_default" in settings
        assert settings["dry_run_default"] is False  # default

    def test_get_current_settings_after_set(self, qtbot) -> None:
        """get_current_settings() reflects values from set_settings()."""
        view = SettingsView()
        qtbot.addWidget(view)

        view.set_settings({
            "theme": "Dark",
            "log_directory": "/tmp/logs",
            "presets_directory": "/tmp/presets",
            "rew_export_folder": "/tmp/rew",
            "discovery_timeout": 8,
            "dry_run_default": True,
            "last_device": "Kitchen",
        })

        settings = view.get_current_settings()
        assert settings["theme"] == "Dark"
        assert settings["log_directory"] == "/tmp/logs"
        assert settings["presets_directory"] == "/tmp/presets"
        assert settings["rew_export_folder"] == "/tmp/rew"
        assert settings["discovery_timeout"] == 8
        assert settings["dry_run_default"] is True
        assert settings["last_device"] == "Kitchen"

    def test_get_current_settings_after_manual_change(self, qtbot) -> None:
        """get_current_settings() reflects user-driven changes."""
        view = SettingsView()
        qtbot.addWidget(view)

        view._theme_combo.setCurrentText("Light")
        view._timeout_spin.setValue(20)
        view._dry_run_check.setChecked(True)

        settings = view.get_current_settings()
        assert settings["theme"] == "Light"
        assert settings["discovery_timeout"] == 20
        assert settings["dry_run_default"] is True
