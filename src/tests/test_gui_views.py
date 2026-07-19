"""Unit tests for secondary views: PresetsDeviceView, MyPresetsView, SettingsView.

HelpView tests already exist in test_help_view.py — not duplicated here.

Requirements referenced: 15.1-15.12, 8.3-8.6, 24.1-24.15.
"""

from __future__ import annotations

from PySide6.QtCore import Qt

from src.adapters.rew_http_client import MeasurementSummary
from src.gui.components.page_layout import ICON_NO_CONNECTION
from src.gui.views.my_presets_view import MyPresetsView
from src.gui.views.presets_device_view import PresetItem, PresetsDeviceView
from src.gui.views.rew_pull_view import RewPullView
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

    def test_set_roomfit_profiles_reshows_hidden_section(self, qtbot) -> None:
        """set_roomfit_profiles() re-shows the section after set_roomfit_hidden()
        (#168) -- previously it stayed hidden for the rest of the session after
        connecting to a non-RoomFit device, even once a RoomFit-capable device
        connected afterward."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)
        view.show()

        view.set_roomfit_hidden()
        assert not view._roomfit_section.isVisible()

        view.set_roomfit_profiles(_make_roomfit_profiles())
        assert view._roomfit_section.isVisible()


class TestPresetsDeviceViewActiveHighlight:
    """Tests for the #165c active-preset/profile highlight."""

    def test_active_peq_item_has_label_and_styling(self, qtbot) -> None:
        """The active PEQ preset's item gets a "(active)" label, bold font,
        and accent foreground; other items get neither."""
        from PySide6.QtGui import QColor

        from src.gui.constants import ACCENT_COLOR

        view = PresetsDeviceView()
        qtbot.addWidget(view)

        presets = _make_peq_presets(2)
        view.set_peq_presets(presets, active_name="PEQ Preset 2")

        item1 = view._peq_list.item(0)
        item2 = view._peq_list.item(1)

        assert "(active)" not in item1.text()
        assert not item1.font().bold()

        assert item2.text().startswith("PEQ Preset 2")
        assert "(active)" in item2.text()
        assert item2.font().bold()
        assert item2.foreground().color() == QColor(ACCENT_COLOR)
        assert item2.toolTip() == "Currently active on this device"

    def test_active_roomfit_item_has_label_and_styling(self, qtbot) -> None:
        """Same active-item convention applies to the RoomFit list."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)

        profiles = _make_roomfit_profiles(2)
        view.set_roomfit_profiles(profiles, active_name="RoomFit Profile 1")

        item1 = view._roomfit_list.item(0)
        item2 = view._roomfit_list.item(1)

        assert "(active)" in item1.text()
        assert item1.font().bold()
        assert "(active)" not in item2.text()
        assert not item2.font().bold()

    def test_no_active_name_no_item_styled(self, qtbot) -> None:
        """An empty active_name (default) styles nothing."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)

        view.set_peq_presets(_make_peq_presets(3))

        for i in range(view._peq_list.count()):
            item = view._peq_list.item(i)
            assert "(active)" not in item.text()
            assert not item.font().bold()

    def test_active_name_matching_nothing_styles_nothing(self, qtbot) -> None:
        """An active_name that doesn't match any item styles nothing (e.g. the
        active preset was deleted from the device since the last refresh)."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)

        view.set_peq_presets(_make_peq_presets(2), active_name="Deleted Preset")

        for i in range(view._peq_list.count()):
            item = view._peq_list.item(i)
            assert "(active)" not in item.text()
            assert not item.font().bold()


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
        assert not view._delete_btn.isEnabled()

    def test_multi_select_enables_batch_buttons(self, qtbot) -> None:
        """Selecting multiple items enables Export, Save, Copy, Delete buttons."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)
        view.show()

        view.set_peq_presets(_make_peq_presets(3))
        view._peq_list.selectAll()

        assert view._export_btn.isEnabled()
        assert view._save_btn.isEnabled()
        assert view._copy_btn.isEnabled()
        assert view._delete_btn.isEnabled()
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

    def test_delete_requested_signal(self, qtbot) -> None:
        """Clicking Delete emits delete_requested with selected items."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)
        view.show()

        view.set_peq_presets(_make_peq_presets(2))
        view._peq_list.selectAll()

        with qtbot.waitSignal(view.delete_requested, timeout=1000) as blocker:
            view._delete_btn.click()

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

    def test_rename_sanitizes_disallowed_device_name_chars(self, qtbot) -> None:
        """Smoke #235: _on_rename_finished() must sanitize the entered text
        via sanitize_device_name() before emitting rename_requested -- a
        name containing device-rejected characters (e.g. parentheses)
        would otherwise reach a real device write unfiltered via "Copy to
        Another Device"."""
        view = MyPresetsView()
        qtbot.addWidget(view)
        view.show()

        view.set_presets([_make_profile("Old Name")])

        item = view._list_widget.item(0)
        view._list_widget.itemDoubleClicked.emit(item)
        view._rename_editor.setText("New (Name)!")

        with qtbot.waitSignal(view.rename_requested, timeout=1000) as blocker:
            view._rename_editor.editingFinished.emit()

        assert blocker.args == ["Old Name", "New Name"]


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

    def test_copy_to_device_button_emits_selected_profile(self, qtbot) -> None:
        """Clicking Copy to Another Device emits copy_to_device_requested with the Profile."""
        view = MyPresetsView()
        qtbot.addWidget(view)
        view.show()

        profile = _make_profile("Copy Me")
        view.set_presets([profile])
        view._list_widget.setCurrentRow(0)

        assert view._copy_btn.isEnabled()
        with qtbot.waitSignal(view.copy_to_device_requested, timeout=1000) as blocker:
            qtbot.mouseClick(view._copy_btn, Qt.MouseButton.LeftButton)

        assert blocker.args[0].name == "Copy Me"

    def test_copy_to_device_disabled_without_selection(self, qtbot) -> None:
        """Copy to Another Device is disabled until a preset is selected."""
        view = MyPresetsView()
        qtbot.addWidget(view)

        view.set_presets([_make_profile("Some Preset")])

        assert not view._copy_btn.isEnabled()


class TestMyPresetsViewToolbarLayout:
    """Tests for the toolbar's position and button order (smoke #227)."""

    def test_toolbar_bottom_anchored_below_list(self, qtbot) -> None:
        """The toolbar sits below the preset list, not above it -- matching
        every other view's bottom-anchored action row convention (this was
        previously the only view in the app where it wasn't)."""
        view = MyPresetsView()
        qtbot.addWidget(view)
        view.resize(600, 700)
        view.show()
        view.set_presets([_make_profile("A Preset")])
        qtbot.wait(20)

        assert view._toolbar.y() > view._list_widget.y()

    def test_toolbar_stays_at_bottom_when_view_grows(self, qtbot) -> None:
        """The toolbar's position tracks the bottom of the page as the view
        is given more height -- the list (not the toolbar) claims the
        page's spare vertical space."""
        view = MyPresetsView()
        qtbot.addWidget(view)
        view.resize(600, 500)
        view.show()
        view.set_presets([_make_profile("A Preset")])
        qtbot.wait(20)
        y_at_500 = view._toolbar.y()

        view.resize(600, 900)
        qtbot.wait(20)

        assert view._toolbar.y() > y_at_500

    def test_toolbar_button_order(self, qtbot) -> None:
        """Toolbar buttons are ordered Load, Copy to Another Device, Rename,
        Duplicate, Delete -- grouping the two "send this preset somewhere"
        actions (Load into Editor, Copy to Another Device) together right
        after each other, ahead of the local Rename/Duplicate edits, with
        the destructive Delete last."""
        view = MyPresetsView()
        qtbot.addWidget(view)

        toolbar_layout = view._toolbar.layout()
        assert toolbar_layout is not None
        items = [toolbar_layout.itemAt(i) for i in range(toolbar_layout.count())]
        buttons = [item.widget() for item in items if item is not None]
        buttons = [w for w in buttons if w is not None]

        assert buttons == [
            view._load_btn,
            view._copy_btn,
            view._rename_btn,
            view._duplicate_btn,
            view._delete_btn,
        ]

    def test_context_menu_action_order_matches_toolbar(self, qtbot) -> None:
        """Context menu action order matches the toolbar's: Load, Copy to
        Another Device, Rename, Duplicate, Delete. Built via
        _build_context_menu() directly (not _show_context_menu()) since
        QMenu.exec()'s real modal popup isn't safely mockable headlessly."""
        view = MyPresetsView()
        qtbot.addWidget(view)

        view.set_presets([_make_profile("A Preset")])
        item = view._list_widget.item(0)

        menu = view._build_context_menu(item)

        action_texts = [a.text() for a in menu.actions() if not a.isSeparator()]
        assert action_texts == [
            "Load",
            "Copy to Another Device",
            "Rename",
            "Duplicate",
            "Delete",
        ]


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
            "rew_folder": "/home/user/rew",
            "discovery_timeout": 10,
            "dry_run_default": True,
        })

        assert view._log_dir_edit.text() == "/var/log/wiim"
        assert view._presets_dir_edit.text() == "/home/user/presets"
        assert view._rew_folder_edit.text() == "/home/user/rew"

    def test_set_settings_populates_behavior(self, qtbot) -> None:
        """set_settings() populates timeout and dry run."""
        view = SettingsView()
        qtbot.addWidget(view)

        view.set_settings({
            "theme": "Light",
            "log_directory": "",
            "presets_directory": "",
            "rew_folder": "",
            "discovery_timeout": 15,
            "dry_run_default": True,
        })

        assert view._timeout_spin.value() == 15
        assert view._dry_run_check.isChecked()


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
            "rew_folder": "/tmp/rew",
            "discovery_timeout": 8,
            "dry_run_default": True,
        })

        settings = view.get_current_settings()
        assert settings["theme"] == "Dark"
        assert settings["log_directory"] == "/tmp/logs"
        assert settings["presets_directory"] == "/tmp/presets"
        assert settings["rew_folder"] == "/tmp/rew"
        assert settings["discovery_timeout"] == 8
        assert settings["dry_run_default"] is True

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


# ---------------------------------------------------------------------------
# TestRewPullView
# ---------------------------------------------------------------------------


def _make_rew_measurement(name: str, index: int) -> MeasurementSummary:
    """Create a MeasurementSummary for testing."""
    return MeasurementSummary(uuid=f"uuid-{index}", name=name, index=index)


class TestRewPullView:
    """Tests for the embedded RewPullView screen (sidebar 'Pull from REW')."""

    def test_starts_in_connecting_state(self, qtbot) -> None:
        """View starts showing the placeholder with a connecting message."""
        view = RewPullView()
        qtbot.addWidget(view)
        view.show()

        assert view._placeholder_widget.isVisible()
        assert not view._content_widget.isVisible()
        assert view._message_label.text() == "Connecting to REW..."

    def test_show_title_false_hides_title(self, qtbot) -> None:
        """show_title=False hides the "Pull from REW" title for embedded use."""
        view = RewPullView(show_title=False)
        qtbot.addWidget(view)
        view.show()

        assert not view._title.isVisible()

    def test_show_title_default_shows_title(self, qtbot) -> None:
        """Default construction shows the title (standalone sidebar page)."""
        view = RewPullView()
        qtbot.addWidget(view)
        view.show()

        assert view._title.isVisible()

    def test_show_header_false_hides_header(self, qtbot) -> None:
        """show_header=False hides the "Choose measurement(s)..." instruction
        line for embedded use (e.g. FiltersPage, which shows its own
        instruction text and would otherwise duplicate it)."""
        view = RewPullView(show_header=False)
        qtbot.addWidget(view)
        view.show()
        # isVisible() reflects the whole ancestor chain -- switch to the
        # content state (where _header actually lives) before asserting,
        # same as test_set_message_shows_placeholder does.
        view.set_measurements([_make_rew_measurement("Speaker", 0)])

        assert not view._header.isVisible()

    def test_show_header_default_shows_header(self, qtbot) -> None:
        """Default construction shows the header (standalone sidebar page)."""
        view = RewPullView()
        qtbot.addWidget(view)
        view.show()
        view.set_measurements([_make_rew_measurement("Speaker", 0)])

        assert view._header.isVisible()

    def test_embedded_true_uses_zero_outer_margins(self, qtbot) -> None:
        """embedded=True skips this view's own outer margins (from
        build_centered_content) since a host page like FiltersPage already
        provides its own -- otherwise the two stack, leaving unaccounted-for
        blank space around this view's content when embedded (smoke #220)."""
        view = RewPullView(embedded=True)
        qtbot.addWidget(view)

        layout = view.layout()
        assert layout is not None
        assert layout.contentsMargins().top() == 0
        assert layout.contentsMargins().left() == 0

    def test_embedded_false_keeps_own_margins(self, qtbot) -> None:
        """Default (standalone sidebar) construction keeps its own margins."""
        view = RewPullView()
        qtbot.addWidget(view)

        layout = view.layout()
        assert layout is not None
        assert layout.contentsMargins().top() > 0

    def test_set_message_shows_placeholder(self, qtbot) -> None:
        """set_message() switches back to the placeholder state with the given text."""
        view = RewPullView()
        qtbot.addWidget(view)
        view.show()

        view.set_measurements([_make_rew_measurement("Speaker", 0)])
        assert view._content_widget.isVisible()

        view.set_message("No measurements found in REW.")
        assert view._placeholder_widget.isVisible()
        assert not view._content_widget.isVisible()
        assert view._message_label.text() == "No measurements found in REW."

    def test_long_message_not_clipped_at_narrow_width(self, qtbot) -> None:
        """A long "REW not connected" style message isn't squeezed to
        near-zero height at a narrow window width (smoke #180 -- the
        placeholder layout previously called setAlignment(AlignCenter),
        which breaks word-wrap height-for-width sizing; see
        page_layout.center_column()'s docstring)."""
        view = RewPullView()
        qtbot.addWidget(view)
        view.resize(320, 400)
        view.show()

        long_message = (
            "REW is not connected. Please ensure REW is running and its "
            "HTTP API is enabled (localhost:4735)."
        )
        view.set_message(long_message, icon=ICON_NO_CONNECTION)

        single_line_height = view._message_label.fontMetrics().height()
        assert view._message_label.height() > single_line_height

    def test_set_measurements_shows_content_and_populates_lists(self, qtbot) -> None:
        """set_measurements() populates Stereo and L/R lists and shows content."""
        measurements = [
            _make_rew_measurement("Left Speaker", 0),
            _make_rew_measurement("Right Speaker", 1),
        ]
        view = RewPullView()
        qtbot.addWidget(view)
        view.show()

        view.set_measurements(measurements)

        assert view._content_widget.isVisible()
        assert not view._placeholder_widget.isVisible()
        assert view._list_widget.count() == 2
        assert view._list_left.count() == 2
        assert view._list_right.count() == 2
        assert not view.is_lr_mode

    def test_measurement_list_scrollable_when_window_too_short(self, qtbot) -> None:
        """Each measurement list keeps its own native scrollbar and scrolls
        independently -- so every measurement stays reachable -- while the
        header, Stereo/L-R toggle, and Back/Continue action bar stay fully
        visible and reachable without scrolling, because only the list
        (given a small floor minimumHeight) is compressed as the window
        shrinks, never the fixed items around it (smoke #232)."""
        view = RewPullView()
        qtbot.addWidget(view)
        view.resize(400, 900)
        view.show()
        measurements = [
            _make_rew_measurement(f"Measurement {i}", i) for i in range(20)
        ]
        view.set_measurements(measurements)
        qtbot.wait(20)

        assert view._list_widget.verticalScrollBarPolicy() == (
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        assert view._list_widget.verticalScrollBar().maximum() == 0

        view.resize(400, 250)
        qtbot.wait(20)

        assert view._list_widget.verticalScrollBar().maximum() > 0
        assert view._header.isVisible()
        assert view._stereo_radio.isVisible()
        assert view._continue_btn.isVisible()
        continue_btn_bottom = view._continue_btn.mapTo(
            view, view._continue_btn.rect().bottomLeft()
        ).y()
        assert continue_btn_bottom <= view.height()

    def test_lr_mode_continue_button_reachable_at_minimal_window_height(
        self, qtbot
    ) -> None:
        """L/R mode's extra "Left Channel"/"Right Channel" labels (absent
        in Stereo mode) make it the tallest content, most likely to force
        the lists to compress down to their floor -- when they do, the
        header/toggle/action-bar (fixed-size items in the same layout) must
        stay visible and reachable regardless (smoke #232).

        Replicates MainWindow's real compression mechanism (a parent with
        an explicit setMinimumSize() smaller than the view's natural
        content) rather than just resizing a bare top-level RewPullView --
        an isolated top-level widget's own layout silently overrides an
        undersized resize() back to its natural minimum, so it can't
        reproduce the clipping this guards against (same technique as
        test_labels_dont_elide_at_min_window_width_with_sidebar,
        test_gui_components.py)."""
        from PySide6.QtWidgets import QVBoxLayout, QWidget

        window = QWidget()
        qtbot.addWidget(window)
        window.setMinimumSize(300, 300)
        layout = QVBoxLayout(window)
        layout.setContentsMargins(0, 0, 0, 0)
        view = RewPullView()
        layout.addWidget(view)
        view.set_measurements([_make_rew_measurement("Speaker", 0)])
        view._lr_radio.setChecked(True)

        window.resize(300, 300)
        window.show()
        qtbot.wait(20)

        assert view._continue_btn.isVisible()
        assert view._header.isVisible()
        continue_btn_bottom = view._continue_btn.mapTo(
            window, view._continue_btn.rect().bottomLeft()
        ).y()
        assert continue_btn_bottom <= window.height()

    def test_lr_lists_scroll_independently_and_labels_stay_out_of_scroll(
        self, qtbot
    ) -> None:
        """Each L/R list has its own scrollbar, scrolling that list's rows
        only -- not the other list, and not the "Left Channel"/"Right
        Channel" heading label above it (smoke #232 follow-up: a shared
        outer QScrollArea previously scrolled both lists and their labels
        together as a single unit, which is wrong)."""
        view = RewPullView()
        qtbot.addWidget(view)
        view.resize(400, 150)
        view.show()
        measurements = [
            _make_rew_measurement(f"Measurement {i}", i) for i in range(20)
        ]
        view.set_measurements(measurements)
        view._lr_radio.setChecked(True)
        qtbot.wait(20)

        assert view._list_left.verticalScrollBarPolicy() == (
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        assert view._list_right.verticalScrollBarPolicy() == (
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        # The lists can scroll independently -- their scrollbars are
        # distinct objects, not one shared scroll region.
        assert (
            view._list_left.verticalScrollBar()
            is not view._list_right.verticalScrollBar()
        )

    def test_no_outer_scroll_area_wraps_the_lists(self, qtbot) -> None:
        """No outer QScrollArea wraps the measurement lists -- each list is
        the sole scrollable region for its own rows, so a heading label
        never gets dragged into a scroll along with its list (smoke #232,
        follow-up to #229's double-scrollbar bug and to the outer-scroll
        approach that scrolled labels together with list content)."""
        from PySide6.QtWidgets import QScrollArea

        view = RewPullView()
        qtbot.addWidget(view)
        view.set_measurements([_make_rew_measurement("Speaker", 0)])

        assert view._content_widget.findChildren(QScrollArea) == []
        for list_widget in (view._list_widget, view._list_left, view._list_right):
            assert (
                list_widget.verticalScrollBarPolicy()
                == Qt.ScrollBarPolicy.ScrollBarAsNeeded
            )

    def test_continue_emits_measurement_selected_in_stereo_mode(self, qtbot) -> None:
        """Continue emits the selected MeasurementSummary in Stereo mode."""
        measurements = [_make_rew_measurement("Speaker", 0)]
        view = RewPullView()
        qtbot.addWidget(view)
        view.set_measurements(measurements)

        view._list_widget.setCurrentRow(0)

        with qtbot.waitSignal(view.measurement_selected, timeout=1000) as blocker:
            view._on_continue_clicked()

        assert blocker.args[0].name == "Speaker"

    def test_continue_emits_tuple_in_lr_mode(self, qtbot) -> None:
        """Continue emits a (left, right) tuple in L/R mode."""
        measurements = [
            _make_rew_measurement("Left Speaker", 0),
            _make_rew_measurement("Right Speaker", 1),
        ]
        view = RewPullView()
        qtbot.addWidget(view)
        view.set_measurements(measurements)

        view._lr_radio.setChecked(True)
        view._list_left.setCurrentRow(0)
        view._list_right.setCurrentRow(1)

        with qtbot.waitSignal(view.measurement_selected, timeout=1000) as blocker:
            view._on_continue_clicked()

        left, right = blocker.args[0]
        assert left.name == "Left Speaker"
        assert right.name == "Right Speaker"

    def test_continue_disabled_until_valid_selection(self, qtbot) -> None:
        """Continue button is disabled until the active mode's selection is complete."""
        measurements = [
            _make_rew_measurement("Left Speaker", 0),
            _make_rew_measurement("Right Speaker", 1),
        ]
        view = RewPullView()
        qtbot.addWidget(view)
        view.set_measurements(measurements)

        assert not view._continue_btn.isEnabled()

        view._list_widget.setCurrentRow(0)
        assert view._continue_btn.isEnabled()

        view._lr_radio.setChecked(True)
        assert not view._continue_btn.isEnabled()  # switching modes resets requirement

        view._list_left.setCurrentRow(0)
        assert not view._continue_btn.isEnabled()  # only Left selected

        view._list_right.setCurrentRow(1)
        assert view._continue_btn.isEnabled()

    def test_back_button_emits_back_requested(self, qtbot) -> None:
        """Back button in the content state emits back_requested."""
        view = RewPullView()
        qtbot.addWidget(view)
        view.set_measurements([_make_rew_measurement("Speaker", 0)])

        back_btn = view.findChild(type(view._continue_btn), "btn_rew_pull_back")
        assert back_btn is not None
        with qtbot.waitSignal(view.back_requested, timeout=1000):
            back_btn.click()

    def test_placeholder_back_button_emits_back_requested(self, qtbot) -> None:
        """Back button in the placeholder state emits back_requested."""
        view = RewPullView()
        qtbot.addWidget(view)

        placeholder_back_btn = view.findChild(
            type(view._continue_btn), "btn_rew_pull_placeholder_back"
        )
        assert placeholder_back_btn is not None
        with qtbot.waitSignal(view.back_requested, timeout=1000):
            placeholder_back_btn.click()
