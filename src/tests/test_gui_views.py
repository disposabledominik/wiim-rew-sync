"""Unit tests for secondary views: PresetsDeviceView, MyPresetsView, SettingsView.

HelpView tests already exist in test_help_view.py — not duplicated here.

Requirements referenced: 15.1-15.12, 8.3-8.6, 24.1-24.15.
"""

from __future__ import annotations

from unittest.mock import patch

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
        """Not specifying active_name (None default) styles nothing and
        shows no synthetic "Custom" row -- distinct from active_name=""."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)

        view.set_peq_presets(_make_peq_presets(3))

        assert view._peq_list.count() == 3
        for i in range(view._peq_list.count()):
            item = view._peq_list.item(i)
            assert "(active)" not in item.text()
            assert not item.font().bold()

    def test_empty_active_name_shows_custom_row(self, qtbot) -> None:
        """active_name="" (the device confirmed no saved preset matches the
        live config) prepends a synthetic "Custom" row, styled active and
        selectable like any other row (#165c)."""
        from PySide6.QtCore import Qt

        view = PresetsDeviceView()
        qtbot.addWidget(view)

        view.set_peq_presets(
            _make_peq_presets(2), active_name="", active_channel_mode="L/R"
        )

        assert view._peq_list.count() == 3
        custom_item = view._peq_list.item(0)
        assert custom_item.text().startswith("Custom")
        assert "[L/R]" in custom_item.text()
        assert "(active)" in custom_item.text()
        assert custom_item.font().bold()
        assert custom_item.flags() & Qt.ItemFlag.ItemIsSelectable
        assert custom_item.data(Qt.ItemDataRole.UserRole).is_custom

        # The real presets are unaffected -- neither is marked active or custom.
        for i in (1, 2):
            item = view._peq_list.item(i)
            assert "(active)" not in item.text()
            assert not item.data(Qt.ItemDataRole.UserRole).is_custom

    def test_custom_row_selectable_but_disables_delete(self, qtbot) -> None:
        """The synthetic "Custom" row is selectable -- Export/Save/Copy all
        work on it via a plain live read (#165c) -- but Delete is disabled
        whenever it's part of the selection, since there's no saved preset
        on the device to delete."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)
        view.show()

        view.set_peq_presets(_make_peq_presets(2), active_name="")
        custom_item = view._peq_list.item(0)
        assert custom_item.text().startswith("Custom")

        custom_item.setSelected(True)

        selected_items = view._get_all_selected_items()
        assert len(selected_items) == 1
        assert selected_items[0].is_custom
        assert view._export_btn.isEnabled()
        assert view._save_btn.isEnabled()
        assert view._copy_btn.isEnabled()
        assert not view._delete_btn.isEnabled()

        # Selecting everything (Custom + the 2 real presets) still disables
        # Delete -- a mixed batch delete can't operate on the custom item.
        view._peq_list.selectAll()
        assert len(view._get_all_selected_items()) == 3
        assert not view._delete_btn.isEnabled()

        # Deselecting Custom, leaving only real presets, re-enables Delete.
        custom_item.setSelected(False)
        assert all(not item.is_custom for item in view._get_all_selected_items())
        assert view._delete_btn.isEnabled()

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

    def test_active_peq_item_shows_eq_off_qualifier(self, qtbot) -> None:
        """active_enabled=False on the active PEQ preset's own source shows
        "(active, PEQ off)" instead of plain "(active)" -- the device
        reports a Name independent of whether PEQ is actually toggled on
        for that source."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)

        presets = _make_peq_presets(2)
        view.set_peq_presets(presets, active_name="PEQ Preset 2", active_enabled=False)

        item2 = view._peq_list.item(1)
        assert "(active, PEQ off)" in item2.text()
        assert "(active)" not in item2.text().replace("(active, PEQ off)", "")
        # Still styled as active (bold/accent) -- off just qualifies the text.
        assert item2.font().bold()

        # Non-active items are unaffected.
        item1 = view._peq_list.item(0)
        assert "(active" not in item1.text()

    def test_custom_row_shows_eq_off_qualifier(self, qtbot) -> None:
        """The synthetic "Custom" row also gets the "PEQ off" qualifier when
        the source it reflects has PEQ toggled off."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)

        view.set_peq_presets(
            _make_peq_presets(1), active_name="", active_enabled=False
        )

        custom_item = view._peq_list.item(0)
        assert custom_item.text().startswith("Custom")
        assert "(active, PEQ off)" in custom_item.text()

    def test_active_roomfit_item_shows_eq_off_qualifier(self, qtbot) -> None:
        """Same qualifier convention applies to the RoomFit list, reading
        "RoomFit off" instead of "PEQ off" (RoomFit's own toggle scope)."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)

        profiles = _make_roomfit_profiles(2)
        view.set_roomfit_profiles(
            profiles, active_name="RoomFit Profile 1", active_enabled=False
        )

        item1 = view._roomfit_list.item(0)
        assert "(active, RoomFit off)" in item1.text()
        item2 = view._roomfit_list.item(1)
        assert "(active" not in item2.text()

    def test_eq_off_qualifier_defaults_to_omitted(self, qtbot) -> None:
        """active_enabled defaults to True (the pre-existing behavior) --
        callers that don't know/care about EQStat get plain "(active)"."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)

        view.set_peq_presets(_make_peq_presets(2), active_name="PEQ Preset 1")
        item1 = view._peq_list.item(0)
        assert item1.text().endswith("(active)")
        assert "PEQ off" not in item1.text()


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


class TestPresetsDeviceViewContextMenu:
    """Tests for the PEQ/RoomFit lists' right-click context menu."""

    def test_context_menu_has_expected_actions(self, qtbot) -> None:
        """The menu mirrors the toolbar's action set and order: Export,
        Save, Copy, Delete."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)

        view.set_peq_presets(_make_peq_presets(2))
        item = view._peq_list.item(0)

        menu = view._build_context_menu(view._peq_list, item)
        labels = [a.text() for a in menu.actions() if not a.isSeparator()]

        assert labels == [
            "Export as REW File",
            "Save to My Presets",
            "Copy to Another Device",
            "Delete",
        ]

    def test_context_menu_delete_disabled_for_custom_row(self, qtbot) -> None:
        """Delete is disabled when the right-clicked/batched selection
        includes the synthetic "Custom" row (#165c) -- matching
        _update_action_buttons()'s toolbar-button logic."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)

        view.set_peq_presets(_make_peq_presets(1), active_name="")
        custom_item = view._peq_list.item(0)
        assert custom_item.text().startswith("Custom")

        menu = view._build_context_menu(view._peq_list, custom_item)
        actions = {a.text(): a for a in menu.actions() if not a.isSeparator()}

        assert not actions["Delete"].isEnabled()
        assert actions["Export as REW File"].isEnabled()

    def test_context_menu_single_item_when_not_in_selection(self, qtbot) -> None:
        """Right-clicking an item outside the current selection acts on
        just that item, not the stale selection (matches MyPresetsView's
        equivalent behavior)."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)
        view.show()

        view.set_peq_presets(_make_peq_presets(3))
        view._peq_list.item(0).setSelected(True)
        view._peq_list.item(1).setSelected(True)

        other_item = view._peq_list.item(2)
        menu = view._build_context_menu(view._peq_list, other_item)
        export_action = next(a for a in menu.actions() if a.text() == "Export as REW File")

        with qtbot.waitSignal(view.export_requested, timeout=1000) as blocker:
            export_action.trigger()

        assert blocker.args[0] == [other_item.data(Qt.ItemDataRole.UserRole)]

    def test_context_menu_batches_full_multiselection(self, qtbot) -> None:
        """Right-clicking an item that IS part of a multi-selection batches
        the action over every selected item, not just the one under the
        cursor -- Qt doesn't clear a selection on right-click."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)
        view.show()

        view.set_peq_presets(_make_peq_presets(3))
        view._peq_list.item(0).setSelected(True)
        view._peq_list.item(2).setSelected(True)

        clicked_item = view._peq_list.item(2)
        menu = view._build_context_menu(view._peq_list, clicked_item)
        copy_action = next(a for a in menu.actions() if a.text() == "Copy to Another Device")

        with qtbot.waitSignal(view.copy_to_device_requested, timeout=1000) as blocker:
            copy_action.trigger()

        assert len(blocker.args[0]) == 2

    def test_context_menu_works_on_roomfit_list(self, qtbot) -> None:
        """The same shared handler builds a working menu for the RoomFit
        list, not just PEQ."""
        view = PresetsDeviceView()
        qtbot.addWidget(view)
        view.show()

        view.set_roomfit_profiles(_make_roomfit_profiles(2))
        item = view._roomfit_list.item(0)

        menu = view._build_context_menu(view._roomfit_list, item)
        save_action = next(a for a in menu.actions() if a.text() == "Save to My Presets")

        with qtbot.waitSignal(view.save_to_my_presets, timeout=1000) as blocker:
            save_action.trigger()

        assert blocker.args[0] == [item.data(Qt.ItemDataRole.UserRole)]

    def test_show_context_menu_no_op_when_no_item_at_position(self, qtbot) -> None:
        """Right-clicking empty list space (no item under the cursor) is a
        no-op -- no menu, no exception."""
        from PySide6.QtCore import QPoint

        view = PresetsDeviceView()
        qtbot.addWidget(view)
        view.show()

        view.set_peq_presets(_make_peq_presets(1))
        # Nothing to assert beyond "doesn't raise" -- itemAt() at an empty
        # position returns None, which _show_context_menu must handle.
        view._show_context_menu(view._peq_list, QPoint(5000, 5000))


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

    def test_repopulate_during_active_rename_does_not_crash(self, qtbot) -> None:
        """A repopulate (e.g. search-field typing, or an external refresh)
        firing while a rename is still in progress must not crash --
        _populate_list() used to call QListWidget.clear() before
        _cancel_rename(), so _cancel_rename() touched a QListWidgetItem
        already destroyed by clear() (RuntimeError: Internal C++ object
        already deleted)."""
        view = MyPresetsView()
        qtbot.addWidget(view)
        view.show()

        view.set_presets([_make_profile("Original Name"), _make_profile("Other")])
        item = view._list_widget.item(0)
        view._list_widget.itemDoubleClicked.emit(item)
        assert view._rename_editor.isVisible()

        # Reproduces the risky sequence directly -- must not raise.
        view._populate_list()

        assert not view._rename_editor.isVisible()
        assert view._rename_item is None

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

    def test_delete_requested_signal(self, qtbot) -> None:
        """delete_requested signal emits with the correct preset name list."""
        view = MyPresetsView()
        qtbot.addWidget(view)

        view.set_presets([_make_profile("To Delete")])

        with qtbot.waitSignal(view.delete_requested, timeout=1000) as blocker:
            view.delete_requested.emit(["To Delete"])

        assert blocker.args == [["To Delete"]]

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

        assert [p.name for p in blocker.args[0]] == ["Copy Me"]

    def test_copy_to_device_disabled_without_selection(self, qtbot) -> None:
        """Copy to Another Device is disabled until a preset is selected."""
        view = MyPresetsView()
        qtbot.addWidget(view)

        view.set_presets([_make_profile("Some Preset")])

        assert not view._copy_btn.isEnabled()


class TestMyPresetsViewMultiSelect:
    """QA-reported gap: My Saved Presets had no multi-select, unlike Presets
    on Device / the Filters step's Device panel, which both use
    ExtendedSelection. Delete and Copy to Another Device both support a
    multi-select batch, matching that convention (and matching Presets on
    Device's own batch Copy) -- Rename/Duplicate stay single-item only,
    since they're inherently one-name/one-copy operations."""

    def test_selection_mode_is_extended(self, qtbot) -> None:
        view = MyPresetsView()
        qtbot.addWidget(view)

        from PySide6.QtWidgets import QListWidget

        assert view._list_widget.selectionMode() == QListWidget.SelectionMode.ExtendedSelection

    def test_multi_select_enables_delete_and_copy_but_not_single_item_actions(
        self, qtbot
    ) -> None:
        view = MyPresetsView()
        qtbot.addWidget(view)
        view.set_presets([_make_profile("A"), _make_profile("B"), _make_profile("C")])

        view._list_widget.item(0).setSelected(True)
        view._list_widget.item(1).setSelected(True)

        assert view._delete_btn.isEnabled()
        assert view._copy_btn.isEnabled()
        assert not view._rename_btn.isEnabled()
        assert not view._duplicate_btn.isEnabled()

    def test_copy_clicked_with_multi_select_emits_all_selected_profiles(
        self, qtbot
    ) -> None:
        view = MyPresetsView()
        qtbot.addWidget(view)
        view.set_presets([_make_profile("A"), _make_profile("B"), _make_profile("C")])

        view._list_widget.item(0).setSelected(True)
        view._list_widget.item(2).setSelected(True)

        with qtbot.waitSignal(view.copy_to_device_requested, timeout=1000) as blocker:
            view._on_copy_clicked()

        assert sorted(p.name for p in blocker.args[0]) == ["A", "C"]

    def test_context_menu_copy_batches_full_selection(self, qtbot) -> None:
        """Right-clicking a selected item within a multi-selection must batch
        Copy over the whole selection, same as Delete -- Qt's default
        right-click does not clear an existing selection.
        """
        view = MyPresetsView()
        qtbot.addWidget(view)
        view.set_presets([_make_profile("A"), _make_profile("B"), _make_profile("C")])

        view._list_widget.item(0).setSelected(True)
        view._list_widget.item(1).setSelected(True)

        menu = view._build_context_menu(view._list_widget.item(1))
        copy_action = next(a for a in menu.actions() if a.text() == "Copy to Another Device")
        assert copy_action.isEnabled()

        with qtbot.waitSignal(view.copy_to_device_requested, timeout=1000) as blocker:
            copy_action.trigger()

        assert sorted(p.name for p in blocker.args[0]) == ["A", "B"]

    def test_delete_clicked_with_multi_select_emits_all_selected_names(self, qtbot) -> None:
        view = MyPresetsView()
        qtbot.addWidget(view)
        view.set_presets(
            [_make_profile("A"), _make_profile("B"), _make_profile("C")]
        )

        view._list_widget.item(0).setSelected(True)
        view._list_widget.item(2).setSelected(True)

        with qtbot.waitSignal(view.delete_requested, timeout=1000) as blocker:
            view._on_delete_clicked()

        assert sorted(blocker.args[0]) == ["A", "C"]

    def test_context_menu_delete_batches_full_selection(self, qtbot) -> None:
        """Right-clicking a selected item within a multi-selection must batch
        Delete over the whole selection, not just the item under the cursor
        -- Qt's default right-click does not clear an existing selection, so
        the toolbar and context-menu Delete must agree on what gets removed.
        """
        view = MyPresetsView()
        qtbot.addWidget(view)
        view.set_presets([_make_profile("A"), _make_profile("B"), _make_profile("C")])

        view._list_widget.item(0).setSelected(True)
        view._list_widget.item(1).setSelected(True)

        menu = view._build_context_menu(view._list_widget.item(1))
        delete_action = next(a for a in menu.actions() if a.text() == "Delete")

        with qtbot.waitSignal(view.delete_requested, timeout=1000) as blocker:
            delete_action.trigger()

        assert sorted(blocker.args[0]) == ["A", "B"]

    def test_context_menu_delete_single_item_when_not_multi_selected(self, qtbot) -> None:
        """Right-clicking an item outside the current selection still deletes
        only that one item (no accidental batch over an unrelated selection).
        """
        view = MyPresetsView()
        qtbot.addWidget(view)
        view.set_presets([_make_profile("A"), _make_profile("B"), _make_profile("C")])

        view._list_widget.item(0).setSelected(True)

        menu = view._build_context_menu(view._list_widget.item(2))
        delete_action = next(a for a in menu.actions() if a.text() == "Delete")

        with qtbot.waitSignal(view.delete_requested, timeout=1000) as blocker:
            delete_action.trigger()

        assert blocker.args[0] == ["C"]

    def test_ctrl_click_deselect_leaves_current_item_stale(self, qtbot) -> None:
        """Regression: _get_selected_profile() must read selectedItems(), not
        currentItem() -- ctrl-clicking to deselect an item leaves Qt's
        currentItem() pointing at that now-unselected item, which previously
        made Rename/Duplicate/Copy silently act on the wrong preset.
        """
        view = MyPresetsView()
        qtbot.addWidget(view)
        view.set_presets([_make_profile("A"), _make_profile("B")])

        item_a = view._list_widget.item(0)
        item_b = view._list_widget.item(1)

        item_a.setSelected(True)
        view._list_widget.setCurrentItem(item_a)
        item_b.setSelected(True)
        view._list_widget.setCurrentItem(item_b)
        item_b.setSelected(False)

        # currentItem() is stale (still B, the last-clicked item), while the
        # actual selection is just A -- the two disagree.
        assert view._list_widget.currentItem() is item_b
        assert view._list_widget.selectedItems() == [item_a]

        profile = view._get_selected_profile()
        assert profile is not None
        assert profile.name == "A"


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

    def test_toolbar_stays_at_bottom_with_empty_list(self, qtbot) -> None:
        """The same bottom-anchoring must hold with no saved presets (list
        hidden, empty-state label shown in its place) -- previously only
        the list's own stretch factor claimed leftover vertical space, so
        with the list hidden and no other widget explicitly claiming it,
        Qt split the leftover space between the empty label and the
        toolbar instead, inflating both and pushing the toolbar down the
        page rather than pinning it to the bottom (smoke #267 follow-up:
        the effect was small enough to go unnoticed until the wizard's
        step-indicator row was reclaimed on this view, giving it enough
        extra height to make the drift obvious)."""
        view = MyPresetsView()
        qtbot.addWidget(view)
        view.resize(600, 500)
        view.show()
        view.set_presets([])
        qtbot.wait(20)
        y_at_500 = view._toolbar.y()
        height_at_500 = view._toolbar.height()

        view.resize(600, 900)
        qtbot.wait(20)

        assert view._toolbar.y() > y_at_500
        # The toolbar must stay pinned to its natural height regardless of
        # how much extra space the view is given -- only the empty label
        # should grow.
        assert view._toolbar.height() == height_at_500

    def test_toolbar_button_order(self, qtbot) -> None:
        """Toolbar buttons are ordered Copy to Another Device (the primary
        "send this preset somewhere" action -- loading now happens via the
        Filters step's Local Library option instead of a toolbar button
        here), Rename, Duplicate, with the destructive Delete last."""
        view = MyPresetsView()
        qtbot.addWidget(view)

        toolbar_layout = view._toolbar.layout()
        assert toolbar_layout is not None
        items = [toolbar_layout.itemAt(i) for i in range(toolbar_layout.count())]
        buttons = [item.widget() for item in items if item is not None]
        buttons = [w for w in buttons if w is not None]

        assert buttons == [
            view._copy_btn,
            view._rename_btn,
            view._duplicate_btn,
            view._delete_btn,
        ]

    def test_context_menu_action_order_matches_toolbar(self, qtbot) -> None:
        """Context menu action order matches the toolbar's: Copy to Another
        Device, Rename, Duplicate, Delete. Built via _build_context_menu()
        directly (not _show_context_menu()) since QMenu.exec()'s real modal
        popup isn't safely mockable headlessly."""
        view = MyPresetsView()
        qtbot.addWidget(view)

        view.set_presets([_make_profile("A Preset")])
        item = view._list_widget.item(0)

        menu = view._build_context_menu(item)

        action_texts = [a.text() for a in menu.actions() if not a.isSeparator()]
        assert action_texts == [
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


class TestSettingsViewBrowseWritabilityCheck:
    """_on_browse_clicked() (Req 24.9) delegates writability validation to
    src.utils.paths.is_writable_directory() rather than inlining os.access()
    itself (moved out of the GUI layer, branch-quality review 2026-08-02:
    the check has no Qt dependency and belongs in utils/). Previously
    untested -- neither branch here had any regression coverage before this
    change."""

    def test_writable_folder_accepted(self, qtbot) -> None:
        view = SettingsView()
        qtbot.addWidget(view)
        view.show()

        with (
            patch(
                "src.gui.views.settings_view.QFileDialog.getExistingDirectory",
                return_value="/some/folder",
            ),
            patch(
                "src.gui.views.settings_view.is_writable_directory",
                return_value=True,
            ),
        ):
            view._on_browse_clicked(view._rew_folder_edit, "REW Export Folder:")

        assert view._rew_folder_edit.text() != ""
        assert view._path_validation_label.isVisible() is False

    def test_unwritable_folder_rejected_shows_validation_label(self, qtbot) -> None:
        view = SettingsView()
        qtbot.addWidget(view)
        view.show()

        with (
            patch(
                "src.gui.views.settings_view.QFileDialog.getExistingDirectory",
                return_value="/some/readonly/folder",
            ),
            patch(
                "src.gui.views.settings_view.is_writable_directory",
                return_value=False,
            ),
        ):
            view._on_browse_clicked(view._rew_folder_edit, "REW Export Folder:")

        assert view._path_validation_label.isVisible() is True
        assert "not writable" in view._path_validation_label.text()

    def test_dialog_cancelled_leaves_field_and_label_unchanged(self, qtbot) -> None:
        """An empty return from the native picker (user cancelled) must not
        touch the line edit or validation label at all."""
        view = SettingsView()
        qtbot.addWidget(view)
        view.show()
        original_text = view._rew_folder_edit.text()

        with patch(
            "src.gui.views.settings_view.QFileDialog.getExistingDirectory",
            return_value="",
        ):
            view._on_browse_clicked(view._rew_folder_edit, "REW Export Folder:")

        assert view._rew_folder_edit.text() == original_text
        assert view._path_validation_label.isVisible() is False


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
        # Tall enough to fit 20 rows at the app's shared LIST_ITEM_HEIGHT
        # (44px) + inter-row spacing without a scrollbar.
        view.resize(400, 1300)
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

    def test_list_floor_height_shows_full_min_visible_rows_without_clipping(
        self, qtbot
    ) -> None:
        """_list_floor_height()'s promised "couple of rows" must actually
        render in full (not cut off mid-row) at exactly that floor height
        -- more rows exist below the floor (so the scrollbar itself stays
        nonzero; that's correct, not a bug), but the _MIN_VISIBLE_ROWS rows
        the floor claims to show must each be entirely inside the viewport.
        The floor used to omit the spacing style_selectable_list() applies
        around every row via setSpacing(), under-counting the floor height
        and clipping the last visible row by a few pixels (found via
        /code-review on the list-styling-consistency change that
        introduced the spacing)."""
        view = RewPullView()
        qtbot.addWidget(view)
        view.show()

        measurements = [_make_rew_measurement(f"Measurement {i}", i) for i in range(5)]
        view.set_measurements(measurements)
        qtbot.wait(20)

        floor_height = RewPullView._list_floor_height(view._list_widget)
        view._list_widget.resize(view._list_widget.width(), floor_height)
        qtbot.wait(20)

        last_visible_row = RewPullView._MIN_VISIBLE_ROWS - 1
        row_rect = view._list_widget.visualItemRect(
            view._list_widget.item(last_visible_row)
        )
        assert row_rect.bottom() < view._list_widget.viewport().height()

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
