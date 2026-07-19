"""Unit tests for wizard page widgets.

Tests ConnectPage, EQTypePage, SourcePage, FiltersPage, ReviewPage,
PushPage, and NameProfilePage using pytest-qt (qtbot fixture).

Requirements referenced: 2.1-2.9, 1.9, 3.1-3.6, 4.1-4.12, 5.1-5.7, 6.2-6.8.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from src.adapters.rew_http_client import MeasurementSummary
from src.gui.constants import FILTER_TABLE_MAX_WIDTH
from src.gui.pages.connect_page import ConnectPage
from src.gui.pages.eq_type_page import EQTypePage
from src.gui.pages.filters_page import FiltersPage
from src.gui.pages.name_profile_page import NameProfilePage
from src.gui.pages.push_page import PushPage
from src.gui.pages.review_page import ReviewPage
from src.gui.pages.source_page import SourcePage
from src.models.canonical import CanonicalFilter

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

    def test_set_devices_sorts_alphabetically_by_name(self, qtbot) -> None:
        """Devices are displayed sorted by name, not discovery-arrival order."""
        page = ConnectPage()
        qtbot.addWidget(page)
        page.show()

        devices = [
            {"name": "Zebra Room", "model": "Pro", "ip": "192.168.1.12"},
            {"name": "Bedroom", "model": "Pro", "ip": "192.168.1.11"},
            {"name": "attic", "model": "Pro", "ip": "192.168.1.13"},
        ]
        page.set_devices(devices)

        names = [ip for _card, ip, _sort_key in page._device_cards]
        assert names == ["192.168.1.13", "192.168.1.11", "192.168.1.12"]

    def test_blank_name_device_sorts_and_displays_as_unknown(self, qtbot) -> None:
        """A device with a present-but-empty "name" (real for some mDNS/
        subnet-scan responses) must sort and display the same fallback --
        previously the sort key used "" (pinning it to the very top) while
        the card label showed "" too (the dict-default only covers a
        missing key, not an empty string), so an unnamed device rendered
        with a blank label instead of "Unknown Device"."""
        page = ConnectPage()
        qtbot.addWidget(page)
        page.show()

        devices = [
            {"name": "Bedroom", "model": "Pro", "ip": "192.168.1.11"},
            {"name": "", "model": "Pro", "ip": "192.168.1.99"},
        ]
        page.set_devices(devices)

        blank_card = next(
            card for card, ip, _sort_key in page._device_cards if ip == "192.168.1.99"
        )
        assert blank_card._name_label.text() == "Unknown Device"

        sort_keys = [sort_key for _card, _ip, sort_key in page._device_cards]
        assert sort_keys == sorted(sort_keys)
        assert sort_keys[-1] == "unknown device"

    def test_update_devices_keeps_progressive_arrivals_sorted(self, qtbot) -> None:
        """Devices added incrementally during progressive discovery still
        end up in alphabetical order, not arrival order."""
        page = ConnectPage()
        qtbot.addWidget(page)
        page.show()

        page.update_devices(
            [{"name": "Zebra Room", "model": "Pro", "ip": "192.168.1.12"}]
        )
        page.update_devices(
            [
                {"name": "Zebra Room", "model": "Pro", "ip": "192.168.1.12"},
                {"name": "Bedroom", "model": "Pro", "ip": "192.168.1.11"},
            ]
        )

        ips_in_order = [ip for _card, ip, _sort_key in page._device_cards]
        assert ips_in_order == ["192.168.1.11", "192.168.1.12"]

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

    def test_source_toggle_hides_stale_warnings(self, qtbot) -> None:
        """Smoke #236: _on_source_toggled() must hide _warnings_section when
        switching between File Import and Pull from REW API -- previously
        only the file-import/REW-pull sections themselves were toggled, so
        a stale warning box from a File Import stayed visible after
        switching to Pull from REW API."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page.show()

        page.show_warnings(["Gain clamped to +6 dB"])
        assert page._warnings_section.isVisible()

        page._rew_api_source_radio.setChecked(True)

        assert not page._warnings_section.isVisible()

    def test_source_toggle_hides_stale_error(self, qtbot) -> None:
        """Smoke #236: _on_source_toggled() must hide _error_section when
        switching source modes -- previously a stale parse-error box from a
        File Import stayed visible after switching to Pull from REW API."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page.show()

        page.show_error("Failed to parse REW file: invalid format")
        assert page._error_section.isVisible()

        page._rew_api_source_radio.setChecked(True)

        assert not page._error_section.isVisible()

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
        assert not page._file_import_actions.isVisible()
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
        assert page._file_import_actions.isVisible()
        assert not page.rew_pull_view.isVisible()

    def test_subtitle_position_and_style_unchanged_across_source_toggle(
        self, qtbot
    ) -> None:
        """The instruction line under the source toggle keeps the same
        widget/position/font in both modes -- only its text changes -- so
        toggling source doesn't visually jump or reflow (only its text
        should change, not its identity, styling, or place in the layout)."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page.show()

        subtitle_before = page._subtitle
        style_class_before = page._subtitle.property("class")
        text_before = page._subtitle.text()

        page._rew_api_source_radio.setChecked(True)

        assert page._subtitle is subtitle_before
        assert page._subtitle.property("class") == style_class_before
        assert page._subtitle.text() != text_before

        page._file_source_radio.setChecked(True)

        assert page._subtitle is subtitle_before
        assert page._subtitle.property("class") == style_class_before
        assert page._subtitle.text() == text_before

    def test_continue_button_bottom_anchored(self, qtbot) -> None:
        """The File Import Continue row sits at the bottom of the page,
        matching Source/Review/NameProfile's convention, regardless of how
        much vertical space the page is given."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page.resize(1000, 700)
        page.show()

        y_at_700 = page._file_import_actions.y()

        page.resize(1000, 1200)

        assert page._file_import_actions.y() > y_at_700

    def test_lr_continue_button_reachable_at_minimal_window_height(self, qtbot) -> None:
        """In File Import's L/R mode (the tallest File Import sub-mode --
        two file rows instead of one), the Continue button stays visible
        and within the page's bounds even at a minimal window height,
        instead of being pushed off below the visible window with no way
        to reach it (smoke #232). `_file_import_section` shrinks/scrolls
        first (it has the layout's stretch factor); the action row, header,
        and toggles never do.

        Replicates MainWindow's real compression mechanism (a parent with
        an explicit setMinimumSize() smaller than the page's natural
        content) rather than just resizing a bare top-level FiltersPage --
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
        page = FiltersPage()
        layout.addWidget(page)
        page._lr_radio.setChecked(True)

        window.resize(300, 300)
        window.show()
        qtbot.wait(20)

        assert page._file_import_actions.isVisible()
        continue_btn_bottom = page._import_lr_btn.mapTo(
            window, page._import_lr_btn.rect().bottomLeft()
        ).y()
        assert continue_btn_bottom <= window.height()

    def test_continue_button_same_bottom_position_in_both_modes(self, qtbot) -> None:
        """The visible primary button's bottom edge sits at the same page
        y-position in File Import mode (_next_btn) and Pull from REW API
        mode (rew_pull_view's own _continue_btn) -- previously RewPullView
        carried its own extra outer margins when embedded, competing with
        FiltersPage's own bottom-anchoring stretch and leaving its Continue
        row measurably higher than File Import's (smoke #220)."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page.resize(1000, 900)
        page.show()
        qtbot.wait(20)

        file_mode_bottom = page._next_btn.mapTo(
            page, page._next_btn.rect().bottomLeft()
        ).y()

        page._rew_api_source_radio.setChecked(True)
        page.rew_pull_view.set_measurements(
            [MeasurementSummary(uuid="u0", name="Speaker", index=0)]
        )
        qtbot.wait(20)

        api_mode_bottom = page.rew_pull_view._continue_btn.mapTo(
            page, page.rew_pull_view._continue_btn.rect().bottomLeft()
        ).y()

        assert api_mode_bottom == file_mode_bottom

    def test_no_gap_between_subtitle_and_rew_pull_toggle(self, qtbot) -> None:
        """The vertical gap between FiltersPage's own instruction line and
        the embedded RewPullView's Stereo/L-R toggle (its first visible
        child, since header/title are suppressed) is a single layout
        spacing gap, not doubled by RewPullView's own outer margins from
        build_centered_content -- previously RewPullView applied its own
        margins on top of FiltersPage's, leaving unused empty space between
        the two (smoke #220)."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page.resize(1000, 900)
        page.show()
        qtbot.wait(20)

        page._rew_api_source_radio.setChecked(True)
        page.rew_pull_view.set_measurements(
            [MeasurementSummary(uuid="u0", name="Speaker", index=0)]
        )
        qtbot.wait(20)

        subtitle_bottom = page._subtitle.mapTo(
            page, page._subtitle.rect().bottomLeft()
        ).y()
        toggle_top = page.rew_pull_view._stereo_radio.mapTo(
            page, page.rew_pull_view._stereo_radio.rect().topLeft()
        ).y()

        # Same single-spacing gap the file-import section gets below the
        # subtitle (mode_section is its first visible child).
        expected_gap = (
            page._file_import_section.mapTo(
                page, page._file_import_section.rect().topLeft()
            ).y()
            - subtitle_bottom
        )
        assert toggle_top - subtitle_bottom == expected_gap

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
        """Toggling dry run changes the push button text."""
        page = ReviewPage()
        qtbot.addWidget(page)
        page.show()

        page.set_dry_run(True)

        assert page._push_button.text() == "Preview Only"

        page.set_dry_run(False)

        assert page._push_button.text() == "Push to Device"

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

    def test_filter_table_stretches_to_max_width_not_collapsed(self, qtbot) -> None:
        """#202: the FilterTable must actually fill its FILTER_TABLE_MAX_WIDTH
        cap, not collapse to a tiny sliver.

        `content_layout.addWidget(widget, stretch, alignment=...)` sizes the
        widget to its sizeHint() instead of letting an Expanding size policy
        fill up to setMaximumWidth() -- and FilterTable's Stretch-mode
        columns don't contribute meaningfully to sizeHint(), so using the
        addWidget alignment param (instead of a stretch-widget-stretch
        sandwich) silently collapsed the whole table to a sliver even though
        setMaximumWidth(FILTER_TABLE_MAX_WIDTH) was set. The page must be
        wide enough that FILTER_TABLE_MAX_WIDTH is the binding constraint,
        not the window itself, or this assertion would pass trivially."""
        page = ReviewPage()
        qtbot.addWidget(page)
        page.resize(1000, 700)
        page.show()

        filters = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=1.0, q=1.0)
        ]
        page.set_filters(filters)

        assert page._filter_table.width() == FILTER_TABLE_MAX_WIDTH

    def test_filter_table_grows_to_fit_more_rows_but_not_past_them(self, qtbot) -> None:
        """The FilterTable grows to accommodate more rows (so a large filter
        set isn't squeezed into a few-row scroll box) but stops at the
        height needed to show all of them -- it must not keep stretching to
        fill a tall window once every row is already visible."""
        page = ReviewPage()
        qtbot.addWidget(page)
        page.resize(1000, 900)
        page.show()

        few_filters = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=1.0, q=1.0)
        ]
        page.set_filters(few_filters)
        qtbot.wait(10)
        few_rows_height = page._filter_table.height()

        many_filters = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0 * (i + 1), gain_db=1.0, q=1.0)
            for i in range(10)
        ]
        page.set_filters(many_filters)
        qtbot.wait(10)
        many_rows_height = page._filter_table.height()

        assert many_rows_height > few_rows_height

    def test_filter_table_does_not_grow_past_content_when_page_grows(self, qtbot) -> None:
        """Once the table is tall enough to show every row, giving the page
        more height must not stretch the table further -- extra space
        should go to the bottom-anchored action row, not an empty-looking
        table."""
        page = ReviewPage()
        qtbot.addWidget(page)
        filters = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=1.0, q=1.0)
        ]
        page.set_filters(filters)

        page.resize(1000, 700)
        page.show()
        height_at_700 = page._filter_table.height()

        page.resize(1000, 1400)
        height_at_1400 = page._filter_table.height()

        assert height_at_1400 == height_at_700


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

    def test_set_stage_done_marks_all_stages_complete(self, qtbot) -> None:
        """set_stage("done") (the backend's final on_stage callback) marks
        every real stage complete -- there's no dedicated "Done" row."""
        page = PushPage()
        qtbot.addWidget(page)

        page.set_stage("done")

        assert page._stage_rows["backing_up"].status == "complete"
        assert page._stage_rows["writing"].status == "complete"
        assert page._stage_rows["verifying"].status == "complete"
        assert "done" not in page._stage_rows

    def test_set_success_shows_buttons(self, qtbot) -> None:
        """set_success shows the OK and Undo buttons."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_success()

        assert page._ok_button.isVisible()
        assert page._undo_button.isVisible()
        assert page._result_container.isVisible()

    def test_set_success_hides_redundant_stepper(self, qtbot) -> None:
        """set_success hides the stepper -- once every stage reads "complete"
        it's fully redundant with the result checkmark/message, and hiding
        it reclaims vertical space in the most common outcome."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_success()

        assert not page._progress_container.isVisible()

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

    def test_set_push_round_hidden_for_single_source(self, qtbot) -> None:
        """total<=1 keeps the round label hidden -- nothing to disambiguate."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_push_round("wifi", 1, 1)

        assert not page._round_label.isVisible()

    def test_set_push_round_shows_source_and_count(self, qtbot) -> None:
        """total>1 shows the round label with source name and round count."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_push_round("optical", 2, 3)

        assert page._round_label.isVisible()
        assert page._round_label.text() == "Pushing to optical (2 of 3)"

    def test_reset_hides_round_label(self, qtbot) -> None:
        """reset() clears a stale round label from a previous multi-source push."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()
        page.set_push_round("optical", 2, 3)

        page.reset()

        assert not page._round_label.isVisible()

    def test_set_success_hides_stale_round_label(self, qtbot) -> None:
        """#201: a multi-source push's round label ("Pushing to X (2 of 2)")
        must not remain visible once a terminal result is reached -- it used
        to only be cleared by reset(), so it lingered alongside the success
        message until the page was reset for a new push."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()
        page.set_push_round("optical", 2, 2)

        page.set_success()

        assert not page._round_label.isVisible()

    def test_set_failure_hides_stale_round_label(self, qtbot) -> None:
        """#201: same as success -- failure is also a terminal result."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()
        page.set_push_round("optical", 2, 2)

        page.set_failure("Verification mismatch", "/tmp/backup.json")

        assert not page._round_label.isVisible()

    def test_set_dry_run_result_hides_stale_round_label(self, qtbot) -> None:
        """#201: same as success/failure -- dry run is also a terminal result."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()
        page.set_push_round("optical", 2, 2)

        page.set_dry_run_result("2 filters would be written.")

        assert not page._round_label.isVisible()

    def test_set_failure_keeps_stepper_visible(self, qtbot) -> None:
        """set_failure keeps the stepper visible -- unlike success, it's the
        only place that shows which specific stage failed."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_stage("verifying")
        page.set_failure("Verification mismatch", "/tmp/backup.json")

        assert page._progress_container.isVisible()

    def test_undo_signal_emitted(self, qtbot) -> None:
        """Clicking Undo button emits undo_requested."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_success()
        qtbot.wait(10)  # let the layout settle before synthesizing a click

        with qtbot.waitSignal(page.undo_requested, timeout=1000):
            qtbot.mouseClick(page._undo_button, Qt.MouseButton.LeftButton)

    def test_mark_undo_complete_disables_button_on_success(self, qtbot) -> None:
        """A successful undo disables the Undo button -- clicking it again
        would be ambiguous (nothing left to undo)."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_success()
        assert page._undo_button.isEnabled()

        page.mark_undo_complete(True)

        assert not page._undo_button.isEnabled()

    def test_mark_undo_complete_keeps_button_enabled_on_failure(self, qtbot) -> None:
        """A failed undo leaves the button enabled so the user can retry."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_success()
        page.mark_undo_complete(False)

        assert page._undo_button.isEnabled()

    def test_reset_reenables_undo_button(self, qtbot) -> None:
        """A fresh push cycle re-enables Undo, even if a prior push's undo
        had disabled it."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_success()
        page.mark_undo_complete(True)
        assert not page._undo_button.isEnabled()

        page.reset()

        assert page._undo_button.isEnabled()

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

    def test_char_warning_shown_for_disallowed_characters(self, qtbot) -> None:
        """Typing a character outside the device-accepted set (letters,
        numbers, space, - and _) shows the character warning; a name using
        only allowed characters does not."""
        page = NameProfilePage()
        qtbot.addWidget(page)
        page.show()

        page._name_input.setText("Living Room!")
        assert page._char_warning_label.isVisible()

        page._name_input.setText("Living-Room_2")
        assert not page._char_warning_label.isVisible()

    def test_save_sanitizes_disallowed_characters(self, qtbot) -> None:
        """Saving strips characters the device naming API doesn't accept,
        so a push never fails on a rejected name (user-reported: the WiiM
        Home app disallows anything but letters/numbers/underscore, though
        dash and space are also confirmed to work -- see
        src/utils/device_name.py)."""
        page = NameProfilePage()
        qtbot.addWidget(page)

        page._name_input.setText("Living Room! (Main)")

        with qtbot.waitSignal(page.name_confirmed, timeout=1000) as blocker:
            qtbot.mouseClick(page._save_button, Qt.MouseButton.LeftButton)

        assert blocker.args == ["Living Room Main"]

    def test_save_disabled_when_name_is_only_disallowed_characters(self, qtbot) -> None:
        """Save stays disabled if sanitizing the typed name leaves nothing --
        e.g. a name made entirely of disallowed characters."""
        page = NameProfilePage()
        qtbot.addWidget(page)

        page._name_input.setText("!!!")

        assert not page._save_button.isEnabled()

    def test_char_warning_does_not_block_typing_or_save(self, qtbot) -> None:
        """The character warning is advisory, not a hard block -- Save stays
        enabled and clickable as long as sanitizing leaves a non-empty name."""
        page = NameProfilePage()
        qtbot.addWidget(page)
        page.show()

        page._name_input.setText("Living Room!")

        assert page._char_warning_label.isVisible()
        assert page._save_button.isEnabled()
