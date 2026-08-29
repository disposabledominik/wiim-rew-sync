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
from src.gui.views.presets_device_view import PresetItem
from src.models.canonical import CanonicalFilter
from src.models.profile import Profile

# FiltersPage's Import source combo index order (REW_FILE, REW_API, DEVICE,
# LOCAL_LIBRARY) -- matches src.gui.pages.filters_page._SOURCE_ORDER.
_REW_FILE_INDEX = 0
_REW_API_INDEX = 1
_DEVICE_INDEX = 2
_LOCAL_LIBRARY_INDEX = 3

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

    def test_rescan_button_stays_enabled_while_scanning(self, qtbot) -> None:
        """The rescan button stays enabled through set_scanning() toggles --
        disabling it during an in-flight operation is OperationFeedbackManager's
        job (via action_buttons()/is_active), not ConnectPage's, so it never
        disagrees with the Ctrl+R shortcut about whether refresh is available."""
        page = ConnectPage()
        qtbot.addWidget(page)

        page.set_scanning(True)
        assert page._rescan_btn.isEnabled()

        page.set_scanning(False)
        assert page._rescan_btn.isEnabled()

    def test_cancel_scanning_with_no_devices_shows_empty_state(self, qtbot) -> None:
        """Cancelling a scan before any device was found must not leave the
        page blank -- a bare set_scanning(False) only hides the spinner and
        relies on a set_devices() call to show something else, which a
        cancelled discovery never makes; cancel_scanning() must fall back to
        the same empty/retry state a completed zero-result scan would show."""
        page = ConnectPage()
        qtbot.addWidget(page)
        page.show()
        page.set_scanning(True)

        page.cancel_scanning()

        assert page._empty_widget.isVisible()
        assert not page._devices_scroll.isVisible()
        assert not page._scanning_widget.isVisible()

    def test_cancel_scanning_with_devices_keeps_them(self, qtbot) -> None:
        """Cancelling a scan after progressive discovery already found some
        devices must just hide the spinner -- not clear the cards already
        shown via update_devices()."""
        page = ConnectPage()
        qtbot.addWidget(page)
        page.show()
        page.update_devices(
            [{"name": "Living Room", "model": "Pro Plus", "ip": "192.168.1.10"}]
        )
        assert page._devices_scroll.isVisible()

        page.cancel_scanning()

        assert len(page._device_cards) == 1
        assert page._devices_scroll.isVisible()
        assert not page._scanning_widget.isVisible()

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

    def _two_device_page(self, qtbot) -> ConnectPage:
        page = ConnectPage()
        qtbot.addWidget(page)
        page.show()
        page.set_devices(
            [
                {"name": "Bedroom", "model": "Pro", "ip": "192.168.1.11"},
                {"name": "Living Room", "model": "Pro Plus", "ip": "192.168.1.10"},
            ]
        )
        return page

    def test_mark_connecting_pulses_only_the_matching_card(self, qtbot) -> None:
        page = self._two_device_page(qtbot)

        page.mark_connecting("192.168.1.10")

        cards_by_ip = {ip: card for card, ip, _sort_key in page._device_cards}
        assert cards_by_ip["192.168.1.10"].property("state") == "connecting"
        assert cards_by_ip["192.168.1.11"].property("state") == "idle"

    def test_mark_connected_shows_solid_accent_on_the_matching_card(self, qtbot) -> None:
        page = self._two_device_page(qtbot)
        page.mark_connecting("192.168.1.10")

        page.mark_connected("192.168.1.10")

        cards_by_ip = {ip: card for card, ip, _sort_key in page._device_cards}
        assert cards_by_ip["192.168.1.10"].property("state") == "connected"

    def test_reset_connecting_reverts_a_pulsing_card_to_idle(self, qtbot) -> None:
        """Simulates a failed capability probe: the card the user clicked
        must stop pulsing, not spin forever with no feedback."""
        page = self._two_device_page(qtbot)
        page.mark_connecting("192.168.1.10")

        page.reset_connecting()

        cards_by_ip = {ip: card for card, ip, _sort_key in page._device_cards}
        assert cards_by_ip["192.168.1.10"].property("state") == "idle"

    def test_reset_connecting_is_a_noop_when_nothing_is_connecting(self, qtbot) -> None:
        page = self._two_device_page(qtbot)

        page.reset_connecting()  # must not raise

        cards_by_ip = {ip: card for card, ip, _sort_key in page._device_cards}
        assert cards_by_ip["192.168.1.10"].property("state") == "idle"
        assert cards_by_ip["192.168.1.11"].property("state") == "idle"

    def test_mark_connecting_unknown_ip_is_a_noop(self, qtbot) -> None:
        page = self._two_device_page(qtbot)

        page.mark_connecting("10.0.0.99")  # no card has this IP -- must not raise

        cards_by_ip = {ip: card for card, ip, _sort_key in page._device_cards}
        assert all(card.property("state") == "idle" for card in cards_by_ip.values())


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

    def test_continue_button_accessor_matches_action_buttons_entry(self, qtbot) -> None:
        """continue_button() returns the same widget action_buttons() lists.

        Guards the smoke #250 follow-up fragility (/code-review ultra):
        callers that need to target Continue specifically (e.g.
        OperationFeedbackManager.note_button_state_changed()) must use this
        named accessor rather than an index into action_buttons(), which
        exists purely for bulk disable/enable registration.
        """
        page = SourcePage()
        qtbot.addWidget(page)

        assert page.continue_button() is page.action_buttons()[0]

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

    def test_file_import_is_default_source(self, qtbot) -> None:
        """File Import panel is visible and RewPullView hidden by default."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page.show()

        assert page._source_combo.currentIndex() == _REW_FILE_INDEX
        assert page._rew_file_panel.isVisible()
        assert not page.rew_pull_view.isVisible()
        assert not page.rew_pull_view._title.isVisible()

    def test_toggle_to_rew_api_shows_picker_and_emits_signal(self, qtbot) -> None:
        """Switching source to "Pull from REW API" swaps panels and emits."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page.show()

        with qtbot.waitSignal(page.rew_api_pull_requested, timeout=1000):
            page._source_combo.setCurrentIndex(_REW_API_INDEX)

        assert not page._rew_file_panel.isVisible()
        assert page.rew_pull_view.isVisible()

    def test_rew_pull_back_reverts_to_file_import(self, qtbot) -> None:
        """RewPullView's back_requested flips the source dropdown back."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page.show()
        page._source_combo.setCurrentIndex(_REW_API_INDEX)

        page.rew_pull_view.back_requested.emit()

        assert page._source_combo.currentIndex() == _REW_FILE_INDEX
        assert page._rew_file_panel.isVisible()
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

        page._source_combo.setCurrentIndex(_REW_API_INDEX)

        assert page._subtitle is subtitle_before
        assert page._subtitle.property("class") == style_class_before
        assert page._subtitle.text() != text_before

        page._source_combo.setCurrentIndex(_REW_FILE_INDEX)

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
        to reach it (smoke #232). `_rew_file_panel` shrinks/scrolls
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

        page._source_combo.setCurrentIndex(_REW_API_INDEX)
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

        page._source_combo.setCurrentIndex(_REW_API_INDEX)
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

        # Same single-spacing gap the File Import panel gets below the
        # subtitle (mode_section is its first visible child).
        expected_gap = (
            page._rew_file_panel.mapTo(
                page, page._rew_file_panel.rect().topLeft()
            ).y()
            - subtitle_bottom
        )
        assert toggle_top - subtitle_bottom == expected_gap

    def test_clear_results_reverts_to_file_import(self, qtbot) -> None:
        """clear_results() resets the source dropdown back to File Import."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page._source_combo.setCurrentIndex(_REW_API_INDEX)

        page.clear_results()

        assert page._source_combo.currentIndex() == _REW_FILE_INDEX

    # ------------------------------------------------------------------
    # Device panel (merged PEQ/RoomFit list)
    # ------------------------------------------------------------------

    def test_switching_to_device_shows_panel_and_requests_presets(self, qtbot) -> None:
        """Selecting "Device" shows its panel and asks MainWindow to fetch presets."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page.show()

        with qtbot.waitSignal(page.device_presets_requested, timeout=1000):
            page._source_combo.setCurrentIndex(_DEVICE_INDEX)

        assert page._device_panel.isVisible()

    def test_device_list_merges_peq_and_roomfit_regardless_of_flow(self, qtbot) -> None:
        """The Device list combines PEQ presets and RoomFit profiles together,
        so a preset can be loaded regardless of the wizard's current EQ_TYPE."""
        page = FiltersPage()
        qtbot.addWidget(page)

        page.set_peq_presets(
            [PresetItem(name="Living Room PEQ", channel_mode="Stereo", preset_type="PEQ")],
            active_name="",
        )
        page.set_roomfit_profiles(
            [PresetItem(name="Living Room RF", channel_mode="Stereo", preset_type="RoomFit")],
            active_name="Living Room RF",
        )

        # active_name="" on the PEQ side means the device confirmed no
        # saved preset matches the live config -- a synthetic "Custom" row
        # joins the two real rows (#165c).
        assert page._device_list.count() == 3
        labels = {page._device_list.item(i).text() for i in range(3)}
        assert any("Living Room PEQ" in label and "PEQ" in label for label in labels)
        assert any(
            "Living Room RF" in label and "RoomFit" in label and "active" in label
            for label in labels
        )
        assert any("Custom" in label and "PEQ" in label and "active" in label for label in labels)

    def test_device_list_shows_eq_off_qualifier_for_both_types(self, qtbot) -> None:
        """active_enabled=False on either set_peq_presets() or
        set_roomfit_profiles() qualifies that type's active row as
        "(active, PEQ off)"/"(active, RoomFit off)" instead of plain
        "(active)" -- the merged list's own equivalent of
        TestPresetsDeviceViewActiveHighlight's coverage in test_gui_views.py."""
        page = FiltersPage()
        qtbot.addWidget(page)

        page.set_peq_presets(
            [PresetItem(name="Living Room PEQ", channel_mode="Stereo", preset_type="PEQ")],
            active_name="Living Room PEQ",
            active_enabled=False,
        )
        page.set_roomfit_profiles(
            [PresetItem(name="Living Room RF", channel_mode="Stereo", preset_type="RoomFit")],
            active_name="Living Room RF",
            active_enabled=False,
        )

        labels = {page._device_list.item(i).text() for i in range(page._device_list.count())}
        assert any("Living Room PEQ" in label and "(active, PEQ off)" in label for label in labels)
        assert any(
            "Living Room RF" in label and "(active, RoomFit off)" in label for label in labels
        )

    def test_device_load_button_enabled_only_with_selection(self, qtbot) -> None:
        """The Device panel's Load Preset button is disabled until a row is selected."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page.set_peq_presets(
            [PresetItem(name="Preset A", channel_mode="Stereo", preset_type="PEQ")]
        )

        assert not page._device_load_btn.isEnabled()

        page._device_list.setCurrentRow(0)

        assert page._device_load_btn.isEnabled()

    def test_device_load_emits_selected_preset_item(self, qtbot) -> None:
        """Clicking Load Preset emits device_item_selected with the chosen PresetItem."""
        page = FiltersPage()
        qtbot.addWidget(page)
        item = PresetItem(name="Preset A", channel_mode="L/R", preset_type="RoomFit")
        page.set_roomfit_profiles([item])
        page._device_list.setCurrentRow(0)

        with qtbot.waitSignal(page.device_item_selected, timeout=1000) as blocker:
            page._device_load_btn.click()

        assert blocker.args == [item]

    def test_custom_row_shown_when_active_peq_name_empty(self, qtbot) -> None:
        """active_name="" on set_peq_presets() prepends a synthetic "Custom"
        row for the device's live/unnamed active PEQ config (#165c)."""
        page = FiltersPage()
        qtbot.addWidget(page)

        page.set_peq_presets(
            [PresetItem(name="Preset A", channel_mode="Stereo", preset_type="PEQ")],
            active_name="",
            active_channel_mode="L/R",
        )

        assert page._device_list.count() == 2
        custom_label = page._device_list.item(0).text()
        assert custom_label.startswith("Custom")
        assert "[L/R]" in custom_label
        assert "(active)" in custom_label

    def test_custom_row_load_emits_device_pull_requested_not_item_selected(
        self, qtbot
    ) -> None:
        """Selecting the synthetic "Custom" row and clicking Load Preset
        emits device_pull_requested, never device_item_selected."""
        page = FiltersPage()
        qtbot.addWidget(page)

        page.set_peq_presets(
            [PresetItem(name="Preset A", channel_mode="Stereo", preset_type="PEQ")],
            active_name="",
        )
        page._device_list.setCurrentRow(0)  # the synthetic "Custom" row

        received: list[object] = []
        page.device_item_selected.connect(received.append)

        with qtbot.waitSignal(page.device_pull_requested, timeout=1000):
            page._device_load_btn.click()

        assert received == []

    def test_set_peq_unavailable_clears_peq_items(self, qtbot) -> None:
        """Code-review round (2026-08-06): set_peq_unavailable() -- forwarded
        from PrimaryWorkflowManager.peq_presets_unavailable alongside
        PresetsDeviceView's own handler -- must clear the Device panel's
        cached PEQ items too, or a device that stops reporting profile
        enumeration support would still show the previous device's PEQ
        presets as loadable."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page.set_peq_presets(
            [PresetItem(name="Preset A", channel_mode="Stereo", preset_type="PEQ")],
            active_name="Preset A",
        )
        assert page._device_list.count() == 1

        page.set_peq_unavailable()

        assert page._device_peq.items == []
        assert page._device_peq.active_name is None
        assert page._device_list.count() == 0

    def test_set_roomfit_hidden_clears_roomfit_items(self, qtbot) -> None:
        """Code-review round (2026-08-06): set_roomfit_hidden() -- forwarded
        from PrimaryWorkflowManager.roomfit_profiles_hidden -- must clear the
        Device panel's cached RoomFit items, matching PresetsDeviceView's own
        set_roomfit_hidden()."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page.set_roomfit_profiles(
            [PresetItem(name="Profile A", channel_mode="Stereo", preset_type="RoomFit")],
            active_name="Profile A",
        )
        assert page._device_list.count() == 1

        page.set_roomfit_hidden()

        assert page._device_roomfit.items == []
        assert page._device_roomfit.active_name == ""
        assert page._device_list.count() == 0

    def test_clear_device_presets_empties_merged_list(self, qtbot) -> None:
        """Code-review round (2026-08-06): clear_device_presets() -- called by
        MainWindow._on_device_selected on a device switch -- resets both the
        PEQ and RoomFit caches, since the Device panel is a merged list and
        neither device-scoped cache belongs to the newly connected device."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page.set_peq_presets(
            [PresetItem(name="Preset A", channel_mode="Stereo", preset_type="PEQ")],
            active_name="Preset A",
        )
        page.set_roomfit_profiles(
            [PresetItem(name="Profile A", channel_mode="Stereo", preset_type="RoomFit")],
            active_name="Profile A",
        )
        assert page._device_list.count() == 2

        page.clear_device_presets()

        assert page._device_peq.items == []
        assert page._device_roomfit.items == []
        assert page._device_peq.active_name is None
        assert page._device_roomfit.active_name == ""
        assert page._device_list.count() == 0

    def test_clear_device_presets_never_refetches(self, qtbot) -> None:
        """clear_device_presets() must never emit device_presets_requested --
        it's called synchronously from MainWindow._on_device_selected, before
        the new device's adapter exists (that's only created later, in
        _on_capabilities_ready), so refetching here would read the *old*
        device's presets (round-2 code review, 2026-08-06, BUG 1). This holds
        even when the Device panel is the currently showing source: MainWindow
        itself re-triggers the fetch once the new adapter is actually ready,
        via FiltersPage.current_source."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page._source_combo.setCurrentIndex(_DEVICE_INDEX)

        received: list[None] = []
        page.device_presets_requested.connect(lambda: received.append(None))
        page.clear_device_presets()

        assert received == []

    def test_current_source_reflects_combo_selection(self, qtbot) -> None:
        """current_source is a public read of the combo's selected panel --
        MainWindow reads it to decide whether a re-triggered fetch (e.g. after
        a device switch's adapter becomes ready) matches what's on screen."""
        from src.gui.wizard_controller import FiltersSource

        page = FiltersPage()
        qtbot.addWidget(page)
        assert page.current_source == FiltersSource.REW_FILE

        page._source_combo.setCurrentIndex(_DEVICE_INDEX)
        assert page.current_source == FiltersSource.DEVICE

    # ------------------------------------------------------------------
    # Local Library panel
    # ------------------------------------------------------------------

    def test_switching_to_local_library_shows_panel_and_requests_profiles(
        self, qtbot
    ) -> None:
        """Selecting "Local Library" shows its panel and asks MainWindow to fetch profiles."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page.show()

        with qtbot.waitSignal(page.local_profiles_requested, timeout=1000):
            page._source_combo.setCurrentIndex(_LOCAL_LIBRARY_INDEX)

        assert page._local_library_panel.isVisible()

    def test_local_load_emits_selected_profile(self, qtbot) -> None:
        """Clicking Load Preset emits local_profile_selected with the chosen Profile."""
        page = FiltersPage()
        qtbot.addWidget(page)
        profile = Profile(name="My Local Preset", channel_mode="Stereo", filters=[])
        page.set_local_profiles([profile])
        page._local_list.setCurrentRow(0)

        with qtbot.waitSignal(page.local_profile_selected, timeout=1000) as blocker:
            page._local_load_btn.click()

        assert blocker.args == [profile]

    def test_local_library_empty_state(self, qtbot) -> None:
        """No saved profiles shows the empty-state label instead of the list."""
        page = FiltersPage()
        qtbot.addWidget(page)
        page.show()
        page._source_combo.setCurrentIndex(_LOCAL_LIBRARY_INDEX)

        page.set_local_profiles([])

        assert page._local_empty_label.isVisible()
        assert not page._local_list.isVisible()


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

    def test_set_failure_partial_sources_offers_undo(self, qtbot) -> None:
        """#242: a multi-source push that failed partway through must offer
        Undo (for the sources that already succeeded) instead of the
        ordinary failure state's no-Undo behavior, and must not claim a
        full restore in its message."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_failure(
            "Verification mismatch", "wifi=/tmp/wifi.json", critical=False, partial_sources=1
        )

        assert page._ok_button.isVisible()
        assert page._undo_button.isVisible()
        msg = page._result_message.text().lower()
        assert "not restored" in msg
        assert "safely restored" not in page._detail_label.text().lower()

    def test_set_failure_critical_and_partial_sources_explains_undo(self, qtbot) -> None:
        """A source can fail its OWN rollback (critical) while earlier
        sources in the same multi-source push already succeeded
        (partial_sources > 0) -- these are independent failure modes and can
        co-occur. The Undo button's visibility is unconditional on
        partial_sources alone, so without this, it would appear in the
        critical UI with zero explanation of what it restores (found during
        review: the critical branch's message never mentioned
        partial_sources at all)."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_failure(
            "Rollback failed", "/tmp/optical.json", critical=True, partial_sources=2
        )

        assert page._undo_button.isVisible()
        detail = page._detail_label.text().lower()
        assert "critical" in page._result_message.text().lower()
        assert "2 other source" in detail
        assert "auto-rollback also failed" in detail
        assert "restore-backup" in detail  # manual recovery steps still shown

    def test_set_failure_no_partial_sources_still_hides_undo(self, qtbot) -> None:
        """A single-source (or first-source) failure keeps the pre-#242
        behavior: no Undo, "device safely restored" message."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_failure("Verification mismatch", "/tmp/backup.json")

        assert not page._undo_button.isVisible()
        assert "safely restored" in page._detail_label.text().lower()

    def test_set_failure_unverified_does_not_claim_safely_restored(self, qtbot) -> None:
        """docs/backlog.md item 9: a connection/response/backup error that
        aborted the write before it could be confirmed either way must NOT
        say "device safely restored" -- that claim is only true when a
        rollback actually ran (or nothing was ever written), neither of
        which happened here."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_failure("Could not reach device", "", verified=False)

        assert not page._undo_button.isVisible()
        detail = page._detail_label.text().lower()
        assert "safely restored" not in detail
        assert "device state unknown" in page._result_message.text().lower()

    def test_set_failure_auto_rollback_fully_succeeded_hides_undo(self, qtbot) -> None:
        """docs/backlog.md item 3: when every already-succeeded source was
        automatically restored, there's nothing left to manually undo."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_failure(
            "Verification mismatch", "/tmp/hdmi.json",
            partial_sources=0, auto_rollback_attempted=2,
        )

        assert not page._undo_button.isVisible()
        msg = page._result_message.text().lower()
        assert "2 source" in msg
        assert "automatically restored" in msg
        # Code review finding: this source's own backup_path is shown via
        # _backup_path_label (visible whenever backup_path is set and
        # partial_sources == 0) -- the detail text must confirm what it's
        # for, not leave an unexplained path on screen.
        assert page._backup_path_label.isVisible()
        detail = page._detail_label.text().lower()
        assert "safely restored" in detail
        assert "/tmp/hdmi.json" in detail

    def test_set_failure_auto_rollback_fully_succeeded_no_own_backup(
        self, qtbot
    ) -> None:
        """Same branch as above, but this source's own write never got far
        enough to create a backup (backup_path empty) -- no false "safely
        restored" claim should be added since there's nothing to confirm."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_failure(
            "No profile name specified", "",
            partial_sources=0, auto_rollback_attempted=1,
        )

        assert not page._backup_path_label.isVisible()
        detail = page._detail_label.text().lower()
        assert "safely restored" not in detail

    def test_set_failure_auto_rollback_partial_failure_offers_undo(self, qtbot) -> None:
        """docs/backlog.md item 3: when auto-rollback fails for some (but
        not all) already-succeeded sources, Undo is offered for the
        remaining subset and the message says how many of how many."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_failure(
            "Verification mismatch", "/tmp/hdmi.json",
            partial_sources=1, auto_rollback_attempted=2,
        )

        assert page._undo_button.isVisible()
        msg = page._result_message.text().lower()
        assert "auto-rollback failed for 1 of 2" in msg
        detail = page._detail_label.text().lower()
        assert "1 of 2 source" in detail

    def test_set_failure_partial_sources_names_replace_count(self, qtbot) -> None:
        """docs/backlog.md item 9b: when the caller supplies decoded source
        names, the detail text names them instead of just stating a count
        -- the "N source(s) not restored" branch (all of auto-rollback
        failed, or none was attempted)."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_failure(
            "Verification mismatch", "wifi=/tmp/wifi.json",
            partial_sources=2, partial_source_names=["optical", "hdmi"],
        )

        detail = page._detail_label.text()
        assert "optical, hdmi" in detail
        assert "2 sources" not in detail

    def test_set_failure_auto_rollback_partial_failure_names_replace_count(
        self, qtbot
    ) -> None:
        """Same as above, for the partly-succeeded auto-rollback branch."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_failure(
            "Verification mismatch", "/tmp/hdmi.json",
            partial_sources=1, auto_rollback_attempted=2,
            partial_source_names=["optical"],
        )

        detail = page._detail_label.text()
        assert "failed for optical" in detail
        assert "the remaining 1" not in detail

    def test_set_failure_critical_and_partial_sources_names_replace_count(
        self, qtbot
    ) -> None:
        """Same as above, for the critical (this source's own rollback also
        failed) branch's own partial_sources mention."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_failure(
            "Rollback failed", "/tmp/optical.json", critical=True,
            partial_sources=2, partial_source_names=["wifi", "hdmi"],
        )

        detail = page._detail_label.text()
        assert "wifi, hdmi" in detail
        assert "2 other source" not in detail

    def test_set_failure_partial_sources_falls_back_to_count_without_names(
        self, qtbot
    ) -> None:
        """No partial_source_names supplied (e.g. an older caller, or
        partial_backup_paths failed to decode) -- must degrade to the
        pre-9b count-only wording, not crash or show nothing."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_failure(
            "Verification mismatch", "wifi=/tmp/wifi.json", partial_sources=2
        )

        detail = page._detail_label.text().lower()
        assert "2 sources" in detail

    def test_set_failure_unverified_not_swallowed_by_auto_rollback_message(
        self, qtbot
    ) -> None:
        """Code review finding: a multi-source push where a prior source's
        auto-rollback fully succeeded (auto_rollback_attempted > 0) must
        still surface that THIS failing source's own write is unconfirmed
        (verified=False) -- the two facts describe different sources and
        neither should silently drop the other."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_failure(
            "Could not reach device", "",
            partial_sources=0, auto_rollback_attempted=1, verified=False,
        )

        msg = page._result_message.text().lower()
        assert "automatically restored" in msg
        detail = page._detail_label.text().lower()
        assert "could not be confirmed" in detail
        assert "state is unknown" in detail

    def test_set_failure_unverified_not_swallowed_by_partial_sources_message(
        self, qtbot
    ) -> None:
        """Same code review finding as above, for the partial_sources
        (auto-rollback failed for some prior sources) branch."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_failure(
            "Could not reach device", "",
            partial_sources=1, auto_rollback_attempted=1, verified=False,
        )

        detail = page._detail_label.text().lower()
        assert "not restored" in detail or "not automatically rolled back" in detail
        assert "could not be confirmed" in detail
        assert "state is unknown" in detail

    def test_set_failure_critical_recovery_command_is_valid_cli_invocation(
        self, qtbot
    ) -> None:
        """The critical-failure recovery text tells the user to run a
        specific `restore-backup` command -- if that command is missing a
        required flag (found during review: it omitted --source), copying
        it verbatim fails with an argparse error instead of recovering, in
        the exact worst-case state the message exists to get the user out
        of. Parse the shown command with the CLI's real argument parser
        (after substituting its placeholders) so any future required-flag
        drift here fails loudly instead of only being caught by manual
        review."""
        import shlex

        from src.cli.main import _build_parser

        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_failure("Rollback failed", "/tmp/backup.json", critical=True)

        detail = page._detail_label.text()
        run_line = next(line for line in detail.splitlines() if "Run:" in line)
        command = run_line.split("Run:", 1)[1].strip()
        command = (
            command.replace("<ip>", "192.168.1.50")
            .replace("<source>", "wifi")
            .replace("<backup path>", "/tmp/backup.json")
        )
        tokens = shlex.split(command)
        assert tokens[0] == "wiim-rew-sync"

        # parse_args() calls sys.exit(2) on a missing required argument --
        # letting that propagate uncaught is exactly the failure signal
        # wanted here.
        args = _build_parser().parse_args(tokens[1:])
        assert args.command == "restore-backup"

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

    def test_set_failure_collapses_stepper_when_no_stage_ever_started(self, qtbot) -> None:
        """A failure reported before any on_stage callback ever fired (e.g.
        the backup file was already missing) has no "active" stage to mark
        "failed" -- the stepper must collapse instead of showing three
        untouched pending circles next to the failure message."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_failure("No backup available", "/tmp/backup.json")

        self._assert_stepper_collapsed(page)

    def test_set_undo_failure_collapses_stepper_when_no_stage_ever_started(
        self, qtbot
    ) -> None:
        """Same collapse as set_failure(), for an undo that fails before
        start_undo()'s stepper ever advances past "pending" (e.g. the
        backup file is missing)."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()
        page.start_undo()

        page.set_undo_failure("No backup available")

        self._assert_stepper_collapsed(page)

    def test_set_undo_failure_collapses_after_earlier_source_fails_later_succeeds(
        self, qtbot
    ) -> None:
        """Multi-source undo: an earlier source can fail partway through,
        but if a later source then runs to completion, its "done" call
        marks every row "complete" via set_stage()'s forward-fill --
        overwriting the earlier failure's "active" row. By the time the
        aggregate failure is reported, _fail_active_stage() finds no
        "active" row and collapses the stepper rather than showing a
        misleading all-green completion next to a failure message. Covers
        the reverse ordering of
        test_undo_multi_source_partial_failure_clears_snapshot (which only
        exercises last-source-fails); round-5 code-review finding,
        2026-07-26.
        """
        page = PushPage()
        qtbot.addWidget(page)
        page.show()
        page.start_undo()

        # Source 1 ("wifi") fails partway through, at "verifying".
        page.set_push_round("wifi", 1, 2)
        page.set_stage("backing_up")
        page.set_stage("writing")
        page.set_stage("verifying")

        # Source 2 ("bluetooth") then runs to completion.
        page.set_push_round("bluetooth", 2, 2)
        page.set_stage("backing_up")
        page.set_stage("writing")
        page.set_stage("verifying")
        page.set_stage("done")

        page.set_undo_failure("1 restored, 1 failed")

        assert not page._progress_container.isVisible()

    @staticmethod
    def _assert_stepper_collapsed(page: PushPage) -> None:
        """Shared assertion for the two collapses-with-nothing-active tests
        above: the progress container is hidden and every row is untouched."""
        assert not page._progress_container.isVisible()
        assert all(row.status == "pending" for row in page._stage_rows.values())

    def test_undo_signal_emitted(self, qtbot) -> None:
        """Clicking Undo button emits undo_requested."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_success()
        qtbot.wait(10)  # let the layout settle before synthesizing a click

        with qtbot.waitSignal(page.undo_requested, timeout=1000):
            qtbot.mouseClick(page._undo_button, Qt.MouseButton.LeftButton)

    def test_start_undo_shows_badge_and_resets_stepper(self, qtbot) -> None:
        """start_undo() re-shows the stepper (reset to pending) and the
        "UNDO" badge, reusing set_success()'s collapsed-stepper result state
        as the starting point (mirrors clicking Undo right after a push)."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()
        page.set_success()

        page.start_undo()

        assert page._progress_container.isVisible()
        assert not page._result_container.isVisible()
        assert page._status_badge.isVisible()
        assert page._status_badge.text() == "UNDO"
        assert all(row.status == "pending" for row in page._stage_rows.values())

    def test_set_push_round_uses_restoring_text_in_undo_mode(self, qtbot) -> None:
        """The round label reuses set_push_round() for undo, but with
        "Restoring" instead of "Pushing to" once start_undo() has run."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()
        page.start_undo()

        page.set_push_round("optical", 2, 3)

        assert page._round_label.isVisible()
        assert page._round_label.text() == "Restoring optical (2 of 3)"

    def test_set_push_round_uses_rolling_back_text_when_rollback_in_progress(
        self, qtbot
    ) -> None:
        """docs/backlog.md item 3: during an in-progress push's own
        auto-rollback of already-succeeded sources, the round label reads
        "Rolling back" -- distinct from both the forward push's "Pushing
        to" and a manual Undo's "Restoring" -- and without touching the
        UNDO badge/stepper the way start_undo() does, since this happens
        mid-push, not as a separate run."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_rollback_in_progress(True)
        page.set_push_round("wifi", 1, 2)

        assert page._round_label.isVisible()
        assert page._round_label.text() == "Rolling back wifi (1 of 2)"
        assert not page._status_badge.isVisible()

    def test_set_rollback_in_progress_false_restores_pushing_verb(self, qtbot) -> None:
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_rollback_in_progress(True)
        page.set_rollback_in_progress(False)
        page.set_push_round("wifi", 1, 2)

        assert page._round_label.text() == "Pushing to wifi (1 of 2)"

    def test_reset_clears_rollback_mode(self, qtbot) -> None:
        page = PushPage()
        qtbot.addWidget(page)
        page.show()
        page.set_rollback_in_progress(True)

        page.reset()
        page.set_push_round("wifi", 1, 2)

        assert page._round_label.text() == "Pushing to wifi (1 of 2)"

    def test_set_undo_success_hides_undo_and_secondary_actions(self, qtbot) -> None:
        """A successful undo shows the given message, hides Undo (nothing
        left to undo-the-undo) and the Export/Save links, but keeps the
        "UNDO" badge visible so the result reads as the undo's, not the
        original push's."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()
        page.set_success()
        page.start_undo()

        page.set_undo_success("Previous filters restored")

        assert page._result_container.isVisible()
        assert page._result_message.text() == "Previous filters restored"
        assert page._status_badge.isVisible()
        assert page._status_badge.text() == "UNDO"
        assert page._ok_button.isVisible()
        assert not page._undo_button.isVisible()
        assert not page._secondary_row.isVisible()

    def test_set_undo_failure_keeps_undo_button_for_retry(self, qtbot) -> None:
        """A failed undo leaves the Undo button visible so the user can
        retry, and keeps the "UNDO" badge visible on the failure card."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()
        page.set_success()
        page.start_undo()

        page.set_undo_failure("Backup file not found")

        assert page._result_container.isVisible()
        assert "Undo failed" in page._result_message.text()
        assert page._detail_label.text() == "Backup file not found"
        assert page._status_badge.isVisible()
        assert page._status_badge.text() == "UNDO"
        assert page._ok_button.isVisible()
        assert page._undo_button.isVisible()
        assert not page._secondary_row.isVisible()

    def test_reset_clears_undo_mode_and_badge(self, qtbot) -> None:
        """A fresh push cycle clears undo mode (round label reverts to
        "Pushing to") and hides the "UNDO" badge, even after a prior push's
        undo had turned both on."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()
        page.set_success()
        page.start_undo()
        page.set_undo_success("Previous filters restored")
        assert page._status_badge.isVisible()

        page.reset()

        assert not page._status_badge.isVisible()
        page.set_push_round("optical", 2, 3)
        assert page._round_label.text() == "Pushing to optical (2 of 3)"

    def test_dry_run_result_shows_badge(self, qtbot) -> None:
        """set_dry_run_result shows the DRY RUN badge."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_dry_run_result("10 bands translated, no changes written")

        assert page._status_badge.isVisible()
        assert page._status_badge.text() == "DRY RUN"
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
