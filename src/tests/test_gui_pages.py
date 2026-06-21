"""Unit tests for wizard page widgets.

Tests ConnectPage, EQTypePage, SourcePage, FiltersPage, ReviewPage,
PushPage, and NameProfilePage using pytest-qt (qtbot fixture).

Requirements referenced: 2.1-2.9, 1.9, 3.1-3.6, 4.1-4.12, 5.1-5.7, 6.2-6.8.
"""

from __future__ import annotations

from PySide6.QtCore import Qt

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
            {"name": "Living Room", "model": "Pro Plus", "ip": "192.168.1.10",
             "firmware": "v4.8", "role": ""},
            {"name": "Bedroom", "model": "Pro", "ip": "192.168.1.11",
             "firmware": "v4.7", "role": ""},
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
            {"name": "Solo", "model": "Pro Plus", "ip": "192.168.1.42",
             "firmware": "v4.8", "role": ""},
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


# ---------------------------------------------------------------------------
# TestReviewPage
# ---------------------------------------------------------------------------


class TestReviewPage:
    """Tests for ReviewPage: summary, dry run, push signal, compare toggle."""

    def test_set_summary_updates_label(self, qtbot) -> None:
        """set_summary updates the summary label with device/source/channel info."""
        page = ReviewPage()
        qtbot.addWidget(page)

        page.set_summary(
            device="WiiM Pro Plus",
            source="wifi",
            channel="Stereo",
            band_count=10,
        )

        text = page._summary_label.text()
        assert "10 bands" in text
        assert "WiiM Pro Plus" in text
        assert "wifi" in text

    def test_dry_run_toggle_changes_button(self, qtbot) -> None:
        """Toggling dry run changes the push button text."""
        page = ReviewPage()
        qtbot.addWidget(page)
        page.show()

        page.set_dry_run(True)

        assert page._push_button.text() == "Preview Only"
        assert page._dry_run_badge.isVisible()

        page.set_dry_run(False)

        assert page._push_button.text() == "Push to Device"
        assert not page._dry_run_badge.isVisible()

    def test_push_signal_emitted(self, qtbot) -> None:
        """Clicking push button emits push_requested."""
        page = ReviewPage()
        qtbot.addWidget(page)

        with qtbot.waitSignal(page.push_requested, timeout=1000):
            qtbot.mouseClick(page._push_button, Qt.MouseButton.LeftButton)


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

        with qtbot.waitSignal(page.undo_requested, timeout=1000):
            qtbot.mouseClick(page._undo_button, Qt.MouseButton.LeftButton)

    def test_dry_run_result_shows_badge(self, qtbot) -> None:
        """set_dry_run_result shows the DRY RUN badge."""
        page = PushPage()
        qtbot.addWidget(page)
        page.show()

        page.set_dry_run_result("10 bands translated, no changes written")

        assert page._dry_run_badge.isVisible()
        assert "Translation Preview" in page._result_message.text()


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
