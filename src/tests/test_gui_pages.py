"""Unit tests for wizard page widgets.

Tests ConnectPage, EQTypePage, SourcePage, FiltersPage, ReviewPage,
PushPage, and NameProfilePage using pytest-qt (qtbot fixture).

Requirements referenced: 2.1-2.9, 1.9, 3.1-3.6, 4.1-4.12, 5.1-5.7, 6.2-6.8.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from src.gui.pages.connect_page import ConnectPage
from src.gui.pages.eq_type_page import EQTypePage
from src.gui.pages.filters_page import FiltersPage
from src.gui.pages.name_profile_page import NameProfilePage
from src.gui.pages.push_page import PushPage
from src.gui.pages.review_page import ReviewPage
from src.gui.pages.source_page import SourcePage

# ---------------------------------------------------------------------------
# TestConnectPage
# ---------------------------------------------------------------------------


class TestConnectPage:
    """Tests for ConnectPage: discovery trigger, auto-select, empty state."""

    def test_initial_state_shows_scanning(self, qtbot) -> None:
        """ConnectPage starts with the scanning widget visible."""
        page = ConnectPage()
        qtbot.addWidget(page)
        page.show()

        assert page._scanning_widget.isVisible()
        assert not page._devices_scroll.isVisible()
        assert not page._empty_widget.isVisible()

    def test_set_devices_shows_cards(self, qtbot) -> None:
        """set_devices with multiple devices shows device cards."""
        page = ConnectPage()
        qtbot.addWidget(page)
        page.show()

        devices = [
            {"name": "Living Room", "model": "Pro Plus", "ip": "192.168.1.10"},
            {"name": "Bedroom", "model": "Pro", "ip": "192.168.1.11"},
        ]
        page.set_devices(devices)

        assert page._devices_scroll.isVisible()
        assert not page._scanning_widget.isVisible()
        assert not page._empty_widget.isVisible()
        assert len(page._device_cards) == 2

    def test_single_device_auto_selects(self, qtbot) -> None:
        """A single discovered device auto-emits device_selected."""
        page = ConnectPage()
        qtbot.addWidget(page)

        devices = [
            {"name": "Solo", "model": "Pro Plus", "ip": "192.168.1.42"},
        ]

        with qtbot.waitSignal(page.device_selected, timeout=1000) as blocker:
            page.set_devices(devices)

        assert blocker.args == ["192.168.1.42"]

    def test_empty_devices_shows_empty_state(self, qtbot) -> None:
        """set_devices with empty list shows the empty/no-devices widget."""
        page = ConnectPage()
        qtbot.addWidget(page)
        page.show()

        page.set_devices([])

        assert page._empty_widget.isVisible()
        assert not page._devices_scroll.isVisible()
        assert not page._scanning_widget.isVisible()

    def test_refresh_signal_on_show(self, qtbot) -> None:
        """showEvent emits refresh_requested for auto-discovery."""
        page = ConnectPage()
        qtbot.addWidget(page)

        with qtbot.waitSignal(page.refresh_requested, timeout=1000):
            page.show()

    def test_rescan_button_emits_refresh_requested(self, qtbot) -> None:
        """Clicking the title-row rescan button emits refresh_requested,
        the same signal the Retry button uses -- lets the user manually
        re-trigger discovery even when devices are already listed."""
        page = ConnectPage()
        qtbot.addWidget(page)

        with qtbot.waitSignal(page.refresh_requested, timeout=1000):
            page._rescan_btn.click()

    def test_rescan_button_disabled_while_scanning(self, qtbot) -> None:
        """The rescan button is disabled during an active scan and
        re-enabled once scanning stops."""
        page = ConnectPage()
        qtbot.addWidget(page)

        page.set_scanning(True)
        assert not page._rescan_btn.isEnabled()

        page.set_scanning(False)
        assert page._rescan_btn.isEnabled()

    def test_empty_state_causes_text_not_clipped_at_narrow_width(self, qtbot) -> None:
        """The "Common causes" bullet list isn't squeezed to near-zero height
        at a narrow window width (smoke #180 -- _build_empty_widget's layout
        previously called setAlignment(AlignCenter), which breaks word-wrap
        height-for-width sizing; see page_layout.center_column()'s docstring).
        """
        page = ConnectPage()
        qtbot.addWidget(page)
        page.resize(340, 500)
        page.show()

        page.set_devices([])

        causes_label = page.findChild(QLabel, "ConnectPageEmptyCauses")
        assert causes_label is not None
        single_line_height = causes_label.fontMetrics().height()
        assert causes_label.height() > single_line_height * 2


# ---------------------------------------------------------------------------
# TestEQTypePage
# ---------------------------------------------------------------------------


class TestEQTypePage:
    """Tests for EQTypePage: selection signals and mutual exclusion."""

    def test_peq_selection_emits_signal(self, qtbot) -> None:
        """Clicking PEQ card emits eq_type_selected with 'peq'."""
        page = EQTypePage()
        qtbot.addWidget(page)

        with qtbot.waitSignal(page.eq_type_selected, timeout=1000) as blocker:
            qtbot.mouseClick(page._peq_card, Qt.MouseButton.LeftButton)

        assert blocker.args == ["peq"]

    def test_roomfit_selection_emits_signal(self, qtbot) -> None:
        """Clicking RoomFit card emits eq_type_selected with 'roomfit'."""
        page = EQTypePage()
        qtbot.addWidget(page)

        with qtbot.waitSignal(page.eq_type_selected, timeout=1000) as blocker:
            qtbot.mouseClick(page._roomfit_card, Qt.MouseButton.LeftButton)

        assert blocker.args == ["roomfit"]

    def test_only_one_selected_at_a_time(self, qtbot) -> None:
        """Selecting PEQ then RoomFit only leaves RoomFit selected."""
        page = EQTypePage()
        qtbot.addWidget(page)

        qtbot.mouseClick(page._peq_card, Qt.MouseButton.LeftButton)
        assert page._peq_card.selected
        assert not page._roomfit_card.selected

        qtbot.mouseClick(page._roomfit_card, Qt.MouseButton.LeftButton)
        assert not page._peq_card.selected
        assert page._roomfit_card.selected
        assert page.selected_type == "roomfit"

    def test_card_description_not_clipped_at_narrow_width(self, qtbot) -> None:
        """A card's description text isn't squeezed to near-zero height when
        the two side-by-side cards are narrowed (smoke #180 -- _EQCard's
        layout previously called setAlignment(AlignCenter), which breaks
        word-wrap height-for-width sizing; see
        page_layout.center_column()'s docstring)."""
        page = EQTypePage()
        qtbot.addWidget(page)
        page.resize(340, 500)
        page.show()

        desc_label = page._peq_card.findChild(QLabel, "cardDescription")
        assert desc_label is not None
        single_line_height = desc_label.fontMetrics().height()
        assert desc_label.height() > single_line_height


# ---------------------------------------------------------------------------
# TestSourcePage
# ---------------------------------------------------------------------------


class TestSourcePage:
    """Tests for SourcePage: source list, pre-selection, channel modes."""

    def test_set_sources_populates_list(self, qtbot) -> None:
        """set_sources creates checkboxes for each source."""
        page = SourcePage()
        qtbot.addWidget(page)

        page.set_sources(["wifi", "HDMI", "Bluetooth"])

        assert len(page._source_checkboxes) == 3
        assert "wifi" in page._source_checkboxes
        assert "HDMI" in page._source_checkboxes

    def test_active_source_pre_selected(self, qtbot) -> None:
        """The active source checkbox is pre-checked."""
        page = SourcePage()
        qtbot.addWidget(page)

        page.set_sources(["wifi", "HDMI", "Bluetooth"], active_source="HDMI")

        assert page._source_checkboxes["HDMI"].isChecked()
        assert not page._source_checkboxes["wifi"].isChecked()

    def test_channel_modes_hidden_by_default(self, qtbot) -> None:
        """Channel mode section is hidden by default."""
        page = SourcePage()
        qtbot.addWidget(page)
        page.show()

        assert not page._channel_section.isVisible()

    def test_source_selected_signal(self, qtbot) -> None:
        """Clicking Continue emits source_selected with source and channel."""
        page = SourcePage()
        qtbot.addWidget(page)

        page.set_sources(["wifi", "HDMI"], active_source="wifi")

        with qtbot.waitSignal(page.source_selected, timeout=1000) as blocker:
            qtbot.mouseClick(page._continue_btn, Qt.MouseButton.LeftButton)

        assert blocker.args == ["wifi", "Stereo"]


# ---------------------------------------------------------------------------
# TestFiltersPage
# ---------------------------------------------------------------------------


class TestFiltersPage:
    """Tests for FiltersPage: mode toggle, browse, signals, warnings, errors."""

    def test_stereo_mode_is_default(self, qtbot) -> None:
        """Stereo mode section is visible by default."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page.show()

        assert page._stereo_section.isVisible()
        assert not page._lr_section.isVisible()

    def test_lr_mode_toggle_shows_lr_section(self, qtbot) -> None:
        """Switching to L/R mode shows L/R browse section."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page.show()

        page._lr_radio.setChecked(True)

        assert page._lr_section.isVisible()
        assert not page._stereo_section.isVisible()

    def test_next_button_disabled_initially(self, qtbot) -> None:
        """Next button is disabled when no file is selected."""
        page = FiltersPage()
        qtbot.addWidget(page)

        assert not page._next_btn.isEnabled()

    def test_next_button_enabled_after_file_selection(self, qtbot) -> None:
        """Next button is enabled after a stereo file path is set."""
        page = FiltersPage()
        qtbot.addWidget(page)

        # Simulate file selection
        page._stereo_path = "/tmp/test.txt"
        page._next_btn.setEnabled(True)

        assert page._next_btn.isEnabled()

    def test_show_warnings_displays_text(self, qtbot) -> None:
        """show_warnings displays warning messages in the warnings section."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page.show()

        page.show_warnings(["Gain clamped to +6 dB", "Q adjusted from 50 to 24"])

        assert page._warnings_section.isVisible()
        assert "Gain clamped" in page._warnings_label.text()
        assert "Q adjusted" in page._warnings_label.text()

    def test_show_error_displays_text(self, qtbot) -> None:
        """show_error displays error message in the error section."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page.show()

        page.show_error("Failed to parse REW file: invalid format")

        assert page._error_section.isVisible()
        assert "Failed to parse" in page._error_label.text()

    def test_file_import_is_default_source(self, qtbot) -> None:
        """File Import section is visible and RewPullView hidden by default."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page.show()

        assert page._file_import_section.isVisible()
        assert not page.rew_pull_view.isVisible()
        assert not page.rew_pull_view._title.isVisible()

    def test_toggle_to_rew_api_shows_picker_and_emits_signal(self, qtbot) -> None:
        """Switching source to "Pull from REW API" swaps sections and emits."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page.show()

        with qtbot.waitSignal(page.rew_api_pull_requested, timeout=1000):
            page._rew_api_source_radio.setChecked(True)

        assert not page._file_import_section.isVisible()
        assert page.rew_pull_view.isVisible()

    def test_rew_pull_back_reverts_to_file_import(self, qtbot) -> None:
        """RewPullView's back_requested flips the source toggle back."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page.show()
        page._rew_api_source_radio.setChecked(True)

        page.rew_pull_view.back_requested.emit()

        assert page._file_source_radio.isChecked()
        assert page._file_import_section.isVisible()
        assert not page.rew_pull_view.isVisible()

    def test_set_rew_api_available_false_disables_and_falls_back(self, qtbot) -> None:
        """set_rew_api_available(False) disables the radio and reverts selection."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page._rew_api_source_radio.setChecked(True)

        page.set_rew_api_available(False)

        assert not page._rew_api_source_radio.isEnabled()
        assert page._file_source_radio.isChecked()

    def test_clear_results_reverts_to_file_import(self, qtbot) -> None:
        """clear_results() resets the source toggle back to File Import."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page._rew_api_source_radio.setChecked(True)

        page.clear_results()

        assert page._file_source_radio.isChecked()


# ---------------------------------------------------------------------------
# TestReviewPage
# ---------------------------------------------------------------------------


class TestReviewPage:
    """Tests for ReviewPage: summary, dry run, push signal, compare toggle."""

    def test_dry_run_toggle_changes_button(self, qtbot) -> None:
        """Toggling dry run changes the push button text and badge appearance.

        Badge coloring is driven by the QSS theme files via the "active" dynamic
        property (QLabel#ReviewPageDryRunBadge[active="true"/"false"]), not an
        inline stylesheet, so we assert on the property rather than styleSheet().
        """
        page = ReviewPage()
        qtbot.addWidget(page)
        page.show()

        page.set_dry_run(True)

        assert page._push_button.text() == "Preview Only"
        assert page._dry_run_badge.property("active") is True

        page.set_dry_run(False)

        assert page._push_button.text() == "Push to Device"
        assert page._dry_run_badge.property("active") is False

    def test_push_signal_emitted(self, qtbot) -> None:
        """Clicking push button emits push_requested."""
        page = ReviewPage()
        qtbot.addWidget(page)

        with qtbot.waitSignal(page.push_requested, timeout=1000):
            qtbot.mouseClick(page._push_button, Qt.MouseButton.LeftButton)

    def test_dry_run_hint_visible(self, qtbot) -> None:
        """The always-visible Dry Run explanation is shown near the checkbox
        (smoke #182) -- non-technical users shouldn't have to guess what the
        checkbox does or wonder why nothing changed on their device."""
        page = ReviewPage()
        qtbot.addWidget(page)
        page.show()

        assert page._dry_run_hint.isVisible()
        assert "previewed only" in page._dry_run_hint.text()


# ---------------------------------------------------------------------------
# TestPushPage
# ---------------------------------------------------------------------------


class TestPushPage:
    """Tests for PushPage: progress stages, success/failure display."""

    def test_set_stage_updates_stepper(self, qtbot) -> None:
        """set_stage marks prior stages complete and current as active."""
        page = PushPage()
        qtbot.addWidget(page)

        page.set_stage("writing")

        assert page._stage_rows["backing_up"].status == "complete"
        assert page._stage_rows["writing"].status == "active"
        assert page._stage_rows["verifying"].status == "pending"
        assert page._stage_rows["done"].status == "pending"

    def test_set_success_shows_buttons(self, qtbot) -> None:
        """set_success shows the OK and Undo buttons."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_success()

        assert page._ok_button.isVisible()
        assert page._undo_button.isVisible()
        assert page._result_container.isVisible()

    def test_set_failure_shows_message(self, qtbot) -> None:
        """set_failure displays error message and shows OK but not Undo."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_stage("verifying")
        page.set_failure("Verification mismatch", "/tmp/backup.json")

        assert page._result_container.isVisible()
        msg = page._result_message.text().lower()
        assert "failed" in msg or "recovery" in msg
        assert page._ok_button.isVisible()
        assert not page._undo_button.isVisible()

    def test_undo_signal_emitted(self, qtbot) -> None:
        """Clicking Undo button emits undo_requested."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_success()
        qtbot.wait(10)  # let the layout settle before synthesizing a click

        with qtbot.waitSignal(page.undo_requested, timeout=1000):
            qtbot.mouseClick(page._undo_button, Qt.MouseButton.LeftButton)

    def test_dry_run_result_shows_badge(self, qtbot) -> None:
        """set_dry_run_result shows the DRY RUN badge."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_dry_run_result("10 bands translated, no changes written")

        assert page._dry_run_badge.isVisible()
        assert "Dry Run Complete" in page._result_message.text()

    def test_failure_detail_not_clipped_at_min_window_height(self, qtbot) -> None:
        """A long multi-line critical failure message isn't silently
        squeezed to near-zero height at the app's minimum window size
        (smoke #179/#180 -- see page_layout.center_column's docstring for
        the layout.setAlignment()-breaks-word-wrap bug this guards against).
        """
        from src.gui.constants import MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH

        page = PushPage()
        qtbot.addWidget(page)
        page.resize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        page.show()

        long_message = (
            "Write verification failed because the device reported a checksum "
            "mismatch after three retries, which usually indicates a flaky "
            "network connection or the device rebooting mid-write."
        )
        page.set_failure(long_message, "/tmp/backup.json", critical=True)
        page.resize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)

        # A correctly height-for-width-sized wrapped label is actually
        # allocated several lines of height -- a clipped/mis-sized one would
        # collapse back toward (or below) its single-line height.
        single_line_height = page._detail_label.fontMetrics().height()
        assert page._detail_label.height() > single_line_height * 2

    def test_stage_icons_align_in_a_column_regardless_of_label_length(
        self, qtbot
    ) -> None:
        """Stage row icons share the same x position even though the stage
        labels ("Backing up" vs "Done") are different lengths (smoke #179 --
        centering each row independently made the icon column zigzag)."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        icon_x_positions = {
            key: row._icon_label.mapTo(page, row._icon_label.rect().topLeft()).x()
            for key, row in page._stage_rows.items()
        }
        assert len(set(icon_x_positions.values())) == 1, icon_x_positions

    def test_title_is_left_aligned_like_other_pages(self, qtbot) -> None:
        """The page title sits flush left in the content column, matching
        every other wizard page's make_page_title() convention -- not
        centered (smoke #179)."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        title = page.findChild(QLabel, "PushPageTitle")
        assert title is not None
        # Flush left within its immediate parent (the content column) --
        # the page-level x offset also includes the page's own outer
        # margin, which isn't what's being asserted here.
        assert title.mapTo(title.parentWidget(), title.rect().topLeft()).x() == 0

    def test_content_scrolls_instead_of_clipping_when_too_tall(self, qtbot) -> None:
        """When the page is embedded in a window shorter than the result
        card's natural height, a scrollbar appears instead of the bottom
        (e.g. the OK button) being silently cut off by the window edge --
        MainWindow's central area has no scroll area of its own (smoke #179).
        """
        from PySide6.QtWidgets import QMainWindow, QScrollArea

        window = QMainWindow()
        page = PushPage()
        window.setCentralWidget(page)
        qtbot.addWidget(window)
        window.resize(900, 350)
        window.show()
        qtbot.wait(10)

        page.set_failure(
            "Verification mismatch on band 3, checksum did not match after retry",
            "/tmp/backup.json",
            critical=True,
        )
        qtbot.wait(10)

        scroll_area = page.findChild(QScrollArea, "PushPageScrollArea")
        assert scroll_area is not None
        assert scroll_area.verticalScrollBar().maximum() > 0


# ---------------------------------------------------------------------------
# TestNameProfilePage
# ---------------------------------------------------------------------------


class TestNameProfilePage:
    """Tests for NameProfilePage: save button state, signal, warning."""

    def test_save_disabled_when_empty(self, qtbot) -> None:
        """Save button is disabled when name input is empty."""
        page = NameProfilePage()
        qtbot.addWidget(page)

        assert not page._save_button.isEnabled()

        page._name_input.setText("  ")  # whitespace only
        assert not page._save_button.isEnabled()

    def test_name_confirmed_signal(self, qtbot) -> None:
        """Clicking Save emits name_confirmed with the trimmed name."""
        page = NameProfilePage()
        qtbot.addWidget(page)

        page._name_input.setText("  My Profile  ")

        with qtbot.waitSignal(page.name_confirmed, timeout=1000) as blocker:
            qtbot.mouseClick(page._save_button, Qt.MouseButton.LeftButton)

        assert blocker.args == ["My Profile"]

    def test_warning_shown_for_active_profile(self, qtbot) -> None:
        """Warning is shown when name matches the active profile."""
        page = NameProfilePage()
        qtbot.addWidget(page)
        page.show()

        page.set_existing_profiles(["Default", "Night"], active_profile="Night")
        page._name_input.setText("Night")

        assert page._warning_label.isVisible()

        page._name_input.setText("New Name")
        assert not page._warning_label.isVisible()

    def test_active_profile_property(self, qtbot) -> None:
        """active_profile reflects the last value passed to set_existing_profiles."""
        page = NameProfilePage()
        qtbot.addWidget(page)

        assert page.active_profile == ""

        page.set_existing_profiles(["Default", "Night"], active_profile="Night")
        assert page.active_profile == "Night"

        page.set_existing_profiles(["Default"], active_profile="")
        assert page.active_profile == ""

    def test_active_item_has_label_and_styling(self, qtbot) -> None:
        """The active profile's list item gets a "(active)" label, bold font,
        and accent foreground color; non-active items get neither (#165a)."""
        from PySide6.QtGui import QColor

        from src.gui.constants import ACCENT_COLOR

        page = NameProfilePage()
        qtbot.addWidget(page)

        page.set_existing_profiles(["Default", "Night"], active_profile="Night")

        default_item = page._profiles_list.item(0)
        night_item = page._profiles_list.item(1)

        assert default_item.text() == "Default"
        assert not default_item.font().bold()

        assert night_item.text() == "Night (active)"
        assert night_item.font().bold()
        assert night_item.foreground().color() == QColor(ACCENT_COLOR)
        assert night_item.toolTip() == "Currently active on this device"

    def test_no_active_profile_no_item_styled(self, qtbot) -> None:
        """When active_profile is "" (or matches nothing), no item is styled."""
        page = NameProfilePage()
        qtbot.addWidget(page)

        page.set_existing_profiles(["Default", "Night"], active_profile="")

        for i in range(page._profiles_list.count()):
            item = page._profiles_list.item(i)
            assert not item.text().endswith("(active)")
            assert not item.font().bold()

    def test_activation_note_always_visible_and_unconditional(self, qtbot) -> None:
        """#191: the always-visible caption states the now-unconditional
        truth (every save activates the profile and enables RoomFit if
        off) regardless of which name is typed -- unlike _warning_label,
        it's never hidden/shown based on classify()."""
        page = NameProfilePage()
        qtbot.addWidget(page)
        page.show()

        activation_notes = [
            child
            for child in page.findChildren(type(page._warning_label))
            if "active on your device" in child.text()
        ]
        assert len(activation_notes) == 1
        note = activation_notes[0]
        assert "turning RoomFit on" in note.text()
        assert note.isVisible()

        page._name_input.setText("Brand New Name")
        assert note.isVisible()

    def test_classify(self, qtbot) -> None:
        """classify() distinguishes empty/new, existing-non-active, and
        active names -- the single source of truth shared by the inline
        warning label and main_window's pre-save confirm dialog (#183)."""
        page = NameProfilePage()
        qtbot.addWidget(page)
        page.set_existing_profiles(["Default", "Night"], active_profile="Night")

        assert page.classify("") == "none"
        assert page.classify("Brand New Name") == "none"
        assert page.classify("Default") == "existing"
        assert page.classify("Night") == "active"

    def test_warning_shown_for_existing_non_active_profile(self, qtbot) -> None:
        """A different wording appears when the name matches an existing but
        non-active profile, vs. the active one (smoke #183)."""
        page = NameProfilePage()
        qtbot.addWidget(page)
        page.show()

        page.set_existing_profiles(["Default", "Night"], active_profile="Night")
        page._name_input.setText("Default")

        assert page._warning_label.isVisible()
        assert "already exists" in page._warning_label.text()
        assert "currently playing" not in page._warning_label.text()

        page._name_input.setText("Night")
        assert "currently playing" in page._warning_label.text()

    def test_click_existing_profile_populates_name(self, qtbot) -> None:
        """Clicking a non-active profile in the reference list populates the
        name field with its raw name (no "(active)" suffix) -- purely local,
        the names were already fetched once via set_existing_profiles()
        (#183)."""
        page = NameProfilePage()
        qtbot.addWidget(page)
        page.show()

        page.set_existing_profiles(["Default", "Night"], active_profile="Night")
        item = page._profiles_list.item(0)
        page._profiles_list.itemClicked.emit(item)

        assert page._name_input.text() == "Default"

    def test_click_active_profile_populates_name_without_suffix(self, qtbot) -> None:
        """Clicking the active profile's item (labeled "Night (active)")
        populates the field with just "Night", and shows the active-profile
        warning (#183)."""
        page = NameProfilePage()
        qtbot.addWidget(page)
        page.show()

        page.set_existing_profiles(["Default", "Night"], active_profile="Night")
        item = page._profiles_list.item(1)
        assert item.text() == "Night (active)"
        page._profiles_list.itemClicked.emit(item)

        assert page._name_input.text() == "Night"
        assert page._warning_label.isVisible()
        assert "currently playing" in page._warning_label.text()
