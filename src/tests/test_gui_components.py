"""Unit tests for shared GUI components.

Tests StatusBanner, StepIndicator, SidebarNav, FilterTable, and DeviceCard
using pytest-qt (qtbot fixture) for Qt widget lifecycle management.

Requirements referenced: 7.1-7.6, 1.3-1.4, 8.1-8.2, 5.1-5.5, 2.3.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QWidget

from src.gui.components.device_card import DeviceCard
from src.gui.components.filter_table import FilterTable
from src.gui.components.sidebar_nav import SidebarNav
from src.gui.components.status_banner import StatusBanner
from src.gui.components.step_indicator import StepIndicator
from src.gui.constants import SIDEBAR_COLLAPSED, SIDEBAR_EXPANDED
from src.gui.pages.push_page import PushPage
from src.models.canonical import CanonicalFilter
from src.translator._warnings import FilterRow, SkippedBand

# ---------------------------------------------------------------------------
# TestStatusBanner
# ---------------------------------------------------------------------------


class TestStatusBanner:
    """Tests for StatusBanner message display, auto-dismiss, and state colors."""

    def test_show_info_displays_message(self, qtbot) -> None:
        """show_info makes the banner visible with the given message text."""
        banner = StatusBanner()
        qtbot.addWidget(banner)

        banner.show_info("Device discovered")

        assert banner.isVisible()
        assert banner._message_label.text() == "Device discovered"
        assert banner.property("status") == "info"

    def test_show_success_auto_dismisses(self, qtbot) -> None:
        """show_success auto-dismisses after the specified timeout."""
        banner = StatusBanner()
        qtbot.addWidget(banner)

        # Use a very short auto-dismiss for testing
        banner.show_success("Pushed OK", auto_dismiss=50)

        assert banner.isVisible()
        assert banner.property("status") == "success"

        # Wait for the dismissed signal (triggered by auto-dismiss timer)
        with qtbot.waitSignal(banner.dismissed, timeout=2000):
            pass

        # Banner stays visible (reserves space) but enters idle state
        assert banner.property("status") == "idle"
        assert banner._message_label.text() == ""

    def test_show_error_persists(self, qtbot) -> None:
        """show_error keeps the banner visible (no auto-dismiss)."""
        banner = StatusBanner()
        qtbot.addWidget(banner)

        banner.show_error("Connection failed")

        assert banner.isVisible()
        assert banner.property("status") == "error"
        assert banner._message_label.text() == "Connection failed"
        # The auto-dismiss timer should not be active
        assert not banner._auto_dismiss_timer.isActive()

    def test_show_progress_shows_spinner(self, qtbot) -> None:
        """show_progress displays the progress bar and hides close button."""
        banner = StatusBanner()
        qtbot.addWidget(banner)

        banner.show_progress("Writing filters...")

        assert banner.isVisible()
        assert banner._progress_bar.isVisible()
        assert not banner._close_button.isVisible()
        assert banner._message_label.text() == "Writing filters..."

    def test_clear_hides_and_emits_dismissed(self, qtbot) -> None:
        """clear() resets the banner to idle and emits the dismissed signal."""
        banner = StatusBanner()
        qtbot.addWidget(banner)

        banner.show_info("Hello")
        assert banner.isVisible()

        with qtbot.waitSignal(banner.dismissed, timeout=1000):
            banner.clear()

        # Banner stays visible (reserves space) but enters idle state
        assert banner.property("status") == "idle"
        assert banner._message_label.text() == ""

    def test_close_button_dismisses(self, qtbot) -> None:
        """Clicking the close button resets banner to idle and emits dismissed."""
        banner = StatusBanner()
        qtbot.addWidget(banner)

        banner.show_error("Something went wrong")
        assert banner.isVisible()

        with qtbot.waitSignal(banner.dismissed, timeout=1000):
            qtbot.mouseClick(banner._close_button, Qt.MouseButton.LeftButton)

        # Banner stays visible (reserves space) but enters idle state
        assert banner.property("status") == "idle"
        assert banner._message_label.text() == ""

    def test_long_message_elides_with_full_text_in_tooltip(self, qtbot) -> None:
        """A message too wide for the banner is elided (not overflowed
        horizontally) and the full text -- with " | "-delimited segments on
        separate lines -- remains available via tooltip (smoke #181).
        Requires a real parent + constrained width: an unparented banner
        skips eliding entirely (see _update_display_text's docstring), since
        its top-level size is an arbitrary platform default, not meaningful.
        """
        container = QWidget()
        layout = QVBoxLayout(container)
        banner = StatusBanner()
        layout.addWidget(banner)
        qtbot.addWidget(container)
        container.resize(300, 100)
        container.show()

        long_message = (
            "Left: Band 3 clamped to device limits | Right: Band 5 truncated "
            "| Left: Band 7 clamped to device limits"
        )
        banner.show_info(long_message)

        displayed = banner._message_label.text()
        assert displayed != long_message
        assert displayed.endswith("…")  # ellipsis
        assert banner._message_label.toolTip() == (
            "Left: Band 3 clamped to device limits\n"
            "Right: Band 5 truncated\n"
            "Left: Band 7 clamped to device limits"
        )

    def test_short_message_not_elided_no_tooltip(self, qtbot) -> None:
        """A message that fits isn't elided and gets no tooltip clutter."""
        container = QWidget()
        layout = QVBoxLayout(container)
        banner = StatusBanner()
        layout.addWidget(banner)
        qtbot.addWidget(container)
        container.resize(600, 100)
        container.show()

        banner.show_info("Device discovered")

        assert banner._message_label.text() == "Device discovered"
        assert banner._message_label.toolTip() == ""


# ---------------------------------------------------------------------------
# TestStepIndicator
# ---------------------------------------------------------------------------


class TestStepIndicator:
    """Tests for StepIndicator step states, click signals, and label adaptation."""

    def test_set_steps_creates_widgets(self, qtbot) -> None:
        """set_steps creates the correct number of step widgets."""
        indicator = StepIndicator()
        qtbot.addWidget(indicator)

        indicator.set_steps(["Connect", "EQ Type", "Source", "Review"])

        assert len(indicator._steps) == 4
        assert len(indicator._connectors) == 3

    def test_set_current_highlights_active(self, qtbot) -> None:
        """set_current marks the specified step as active."""
        from src.gui.components.step_indicator import _StepState

        indicator = StepIndicator()
        qtbot.addWidget(indicator)

        indicator.set_steps(["Connect", "EQ Type", "Source"])
        indicator.set_current(1)

        assert indicator._steps[1].state == _StepState.ACTIVE
        # Step 0 should revert to UPCOMING since it wasn't completed
        assert indicator._steps[0].state == _StepState.UPCOMING

    def test_set_dimmed_mutes_active_pill(self, qtbot) -> None:
        """set_dimmed swaps the active step's classes to the muted variant."""
        indicator = StepIndicator()
        qtbot.addWidget(indicator)

        indicator.set_steps(["Connect", "EQ Type", "Source"])
        indicator.set_current(1)

        indicator.set_dimmed(True)
        active = indicator._steps[1]
        assert active.property("class") == "stepWidgetActiveDimmed"
        assert active._circle.property("class") == "stepCircleActiveDimmed"
        assert active._label.property("class") == "stepLabelActiveDimmed"

        indicator.set_dimmed(False)
        assert active.property("class") == "stepWidgetActive"
        assert active._circle.property("class") == "stepCircleActive"
        assert active._label.property("class") == "stepLabelActive"

    def test_set_current_preserves_dimmed_state(self, qtbot) -> None:
        """Navigating to a new active step keeps the indicator's dimmed flag."""
        indicator = StepIndicator()
        qtbot.addWidget(indicator)

        indicator.set_steps(["Connect", "EQ Type", "Source"])
        indicator.set_dimmed(True)
        indicator.set_current(2)

        assert indicator._steps[2].property("class") == "stepWidgetActiveDimmed"

    def test_set_completed_shows_checkmark(self, qtbot) -> None:
        """set_completed marks a step as completed with checkmark text."""
        from src.gui.components.step_indicator import _StepState

        indicator = StepIndicator()
        qtbot.addWidget(indicator)

        indicator.set_steps(["Connect", "EQ Type", "Source"])
        indicator.set_completed(0, "WiiM Pro")

        assert indicator._steps[0].state == _StepState.COMPLETED
        assert indicator._steps[0]._circle.text() == "\u2713"

    def test_completed_step_emits_click(self, qtbot) -> None:
        """Clicking a completed step emits step_clicked with the step index."""
        indicator = StepIndicator()
        qtbot.addWidget(indicator)

        indicator.set_steps(["Connect", "EQ Type", "Source"])
        indicator.set_completed(0)

        with qtbot.waitSignal(indicator.step_clicked, timeout=1000) as blocker:
            qtbot.mouseClick(indicator._steps[0], Qt.MouseButton.LeftButton)

        assert blocker.args == [0]

    def test_upcoming_step_not_clickable(self, qtbot) -> None:
        """Clicking an upcoming step does NOT emit step_clicked."""
        indicator = StepIndicator()
        qtbot.addWidget(indicator)

        indicator.set_steps(["Connect", "EQ Type", "Source"])

        signals_received = []
        indicator.step_clicked.connect(lambda idx: signals_received.append(idx))

        # Step 2 is upcoming - clicking should not emit
        qtbot.mouseClick(indicator._steps[2], Qt.MouseButton.LeftButton)

        assert signals_received == []

    def test_set_current_overrides_completed_state(self, qtbot) -> None:
        """set_current on a COMPLETED step forces it back to ACTIVE.

        Regression test for the breadcrumb bug: clicking back to a
        previously-completed step left a stale checkmark instead of
        showing the "you are here" active marker.
        """
        from src.gui.components.step_indicator import _StepState

        indicator = StepIndicator()
        qtbot.addWidget(indicator)

        indicator.set_steps(["Connect", "EQ Type", "Source"])
        indicator.set_completed(0, "WiiM Pro")
        indicator.set_current(2)

        # Navigate back to the now-completed step 0.
        indicator.set_current(0)

        assert indicator._steps[0].state == _StepState.ACTIVE
        assert indicator._steps[0]._circle.text() == ""

    def test_set_current_overrides_completed_clears_summary_and_connector(
        self, qtbot
    ) -> None:
        """Forcing a COMPLETED step back to ACTIVE also clears its summary
        text and trailing connector accent, matching clear_completed's
        existing behaviour for back-navigation invalidation."""
        indicator = StepIndicator()
        qtbot.addWidget(indicator)

        indicator.set_steps(["Connect", "EQ Type", "Source"])
        indicator.set_completed(0, "WiiM Pro")

        indicator.set_current(0)

        assert indicator._steps[0]._summary.text() == ""
        assert indicator._connectors[0].property("class") == "stepConnector"

    def test_active_step_has_pill_class(self, qtbot) -> None:
        """The active step widget gets the stepWidgetActive QSS class; the
        previously active widget loses it."""
        indicator = StepIndicator()
        qtbot.addWidget(indicator)

        indicator.set_steps(["Connect", "EQ Type", "Source"])
        assert indicator._steps[0].property("class") == "stepWidgetActive"

        indicator.set_current(1)

        assert indicator._steps[0].property("class") == ""
        assert indicator._steps[1].property("class") == "stepWidgetActive"

    def test_invalidate_from_resets_steps(self, qtbot) -> None:
        """invalidate_from resets steps from the given index onward to UPCOMING."""
        from src.gui.components.step_indicator import _StepState

        indicator = StepIndicator()
        qtbot.addWidget(indicator)

        indicator.set_steps(["Connect", "EQ Type", "Source", "Review"])
        indicator.set_completed(0)
        indicator.set_completed(1)
        indicator.set_completed(2)

        # Invalidate from step 1 onward
        indicator.invalidate_from(1)

        assert indicator._steps[0].state == _StepState.COMPLETED
        assert indicator._steps[1].state == _StepState.UPCOMING
        assert indicator._steps[2].state == _StepState.UPCOMING
        assert indicator._steps[3].state == _StepState.UPCOMING


# ---------------------------------------------------------------------------
# TestSidebarNav
# ---------------------------------------------------------------------------


class TestSidebarNav:
    """Tests for SidebarNav collapse/expand and navigation signals."""

    def test_initial_state_expanded(self, qtbot) -> None:
        """SidebarNav starts in expanded mode (200px width)."""
        nav = SidebarNav()
        qtbot.addWidget(nav)

        assert not nav.collapsed
        assert nav.width() == SIDEBAR_EXPANDED

    def test_collapse_sets_width(self, qtbot) -> None:
        """set_collapsed(True) sets width to SIDEBAR_COLLAPSED (48px)."""
        nav = SidebarNav()
        qtbot.addWidget(nav)

        nav.set_collapsed(True)

        assert nav.collapsed
        assert nav.maximumWidth() == SIDEBAR_COLLAPSED

    def test_expand_sets_width(self, qtbot) -> None:
        """set_collapsed(False) after collapse restores to SIDEBAR_EXPANDED."""
        nav = SidebarNav()
        qtbot.addWidget(nav)

        nav.set_collapsed(True)
        nav.set_collapsed(False)

        assert not nav.collapsed
        assert nav.maximumWidth() == SIDEBAR_EXPANDED

    def test_navigation_signal_emitted(self, qtbot) -> None:
        """Clicking a nav item emits navigation_requested with the view key."""
        nav = SidebarNav()
        qtbot.addWidget(nav)

        with qtbot.waitSignal(nav.navigation_requested, timeout=1000) as blocker:
            qtbot.mouseClick(nav._nav_buttons["settings"], Qt.MouseButton.LeftButton)

        assert blocker.args == ["settings"]

    def test_active_item_highlighted(self, qtbot) -> None:
        """Clicking a nav item sets it as active and deactivates previous."""
        nav = SidebarNav()
        qtbot.addWidget(nav)

        # Initially home is active
        assert nav._nav_buttons["home"]._active

        # Click settings
        qtbot.mouseClick(nav._nav_buttons["settings"], Qt.MouseButton.LeftButton)

        assert nav._nav_buttons["settings"]._active
        assert not nav._nav_buttons["home"]._active

    def test_help_click_does_not_change_active_item(self, qtbot) -> None:
        """Clicking "Help" leaves the previous highlight untouched.

        Help opens a separate window rather than replacing the current
        page, so highlighting it would misleadingly suggest it's the active
        view even after the Help window is closed.
        """
        nav = SidebarNav()
        qtbot.addWidget(nav)

        qtbot.mouseClick(nav._nav_buttons["settings"], Qt.MouseButton.LeftButton)
        assert nav._nav_buttons["settings"]._active

        with qtbot.waitSignal(nav.navigation_requested, timeout=1000) as blocker:
            qtbot.mouseClick(nav._nav_buttons["help"], Qt.MouseButton.LeftButton)

        assert blocker.args == ["help"]
        assert nav._nav_buttons["settings"]._active
        assert not nav._nav_buttons["help"]._active
        assert nav.active_key == "settings"

    def test_set_active_key_syncs_highlight(self, qtbot) -> None:
        """set_active_key lets MainWindow reconcile the highlight externally."""
        nav = SidebarNav()
        qtbot.addWidget(nav)

        qtbot.mouseClick(nav._nav_buttons["rew_api"], Qt.MouseButton.LeftButton)
        assert nav._nav_buttons["rew_api"]._active

        nav.set_active_key("home")

        assert nav._nav_buttons["home"]._active
        assert not nav._nav_buttons["rew_api"]._active
        assert nav.active_key == "home"

    def test_device_info_updates_header(self, qtbot) -> None:
        """set_device_info updates the header label text."""
        nav = SidebarNav()
        qtbot.addWidget(nav)

        nav.set_device_info("WiiM Pro Plus", connected=True)

        assert nav._device_label.text() == "WiiM Pro Plus"
        assert nav._device_label.isEnabled()

    def test_device_info_disconnected(self, qtbot) -> None:
        """set_device_info with connected=False shows 'No device'."""
        nav = SidebarNav()
        qtbot.addWidget(nav)

        nav.set_device_info("", connected=False)

        assert nav._device_label.text() == "No device"
        assert not nav._device_label.isEnabled()


# ---------------------------------------------------------------------------
# TestFilterTable
# ---------------------------------------------------------------------------


class TestFilterTable:
    """Tests for FilterTable column rendering, clamping, and L/R tabs."""

    def _make_filters(self) -> list[CanonicalFilter]:
        """Create a sample filter list for testing."""
        return [
            CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=3.5, q=1.41),
            CanonicalFilter(type="LS", frequency_hz=200.0, gain_db=-2.0, q=0.71),
            CanonicalFilter(type="OFF", frequency_hz=100.0, gain_db=0.0, q=1.0),
        ]

    def test_set_filters_populates_rows(self, qtbot) -> None:
        """set_filters creates the correct number of rows with data."""
        table = FilterTable()
        qtbot.addWidget(table)

        filters = self._make_filters()
        table.set_filters(filters)

        assert table._table is not None
        assert table._table.rowCount() == 3
        # Band column shows 1-based index
        item_0_0 = table._table.item(0, 0)
        assert item_0_0 is not None
        assert item_0_0.text() == "1"
        # Type column
        item_0_1 = table._table.item(0, 1)
        assert item_0_1 is not None
        assert item_0_1.text() == "PK"
        item_1_1 = table._table.item(1, 1)
        assert item_1_1 is not None
        assert item_1_1.text() == "LS"

    def test_clamping_indicator_shown(self, qtbot) -> None:
        """Clamped bands show an orange dot prefix in the gain column."""
        table = FilterTable()
        qtbot.addWidget(table)

        filters = self._make_filters()
        clamping_map = {0: ["gain exceeds +6 dB limit"]}
        table.set_filters(filters, clamping_map=clamping_map)

        assert table._table is not None
        gain_item = table._table.item(0, 3)
        assert gain_item is not None
        # Should start with the orange dot character
        assert gain_item.text().startswith("\u25cf")
        assert gain_item.toolTip() == "Original: +3.5 dB. Clamped: gain exceeds +6 dB limit"

    def test_conversion_note_shown_on_q_cell(self, qtbot) -> None:
        """A conversion note (e.g. default Q for bare LP/HP) shows a dot + tooltip on Q.

        Distinct from clamping: no orange warning color, just an accent-colored
        info indicator, since the value itself isn't out of range.
        """
        table = FilterTable()
        qtbot.addWidget(table)

        filters = self._make_filters()
        notes_map = {0: ["Q defaulted to 0.7071 (REW Butterworth default)"]}
        table.set_filters(filters, notes_map=notes_map)

        assert table._table is not None
        q_item = table._table.item(0, 4)
        assert q_item is not None
        assert q_item.text().startswith("\u25cf")
        assert q_item.toolTip() == "Note: Q defaulted to 0.7071 (REW Butterworth default)"

    def test_off_band_renders_like_normal_band(self, qtbot) -> None:
        """OFF bands are pushed to the device and render at full opacity with no strikethrough."""
        table = FilterTable()
        qtbot.addWidget(table)

        filters = self._make_filters()
        table.set_filters(filters)

        # Row 2 is OFF
        assert table._table is not None
        item = table._table.item(2, 1)
        assert item is not None
        assert item.foreground().color().alphaF() == pytest.approx(1.0, abs=1e-3)
        assert not item.font().strikeOut()

    def test_skipped_band_has_strikethrough_off_does_not(self, qtbot) -> None:
        """Skipped bands (excluded) carry strikethrough; OFF bands (still pushed) do not.

        Also guards the #157 fix: OFF bands must render fully opaque while
        skipped bands stay dimmed (_SKIPPED_OPACITY), so the two states don't
        regress back to looking visually identical.
        """
        table = FilterTable()
        qtbot.addWidget(table)

        off_filter = CanonicalFilter(type="OFF", frequency_hz=100.0, gain_db=0.0, q=1.0)
        rows: list[FilterRow] = [
            off_filter,
            SkippedBand(original_type="PEAK", reason="Exceeds device's 10-band limit"),
        ]
        table.set_filters([off_filter], rows=rows)

        assert table._table is not None
        off_item = table._table.item(0, 1)
        skipped_item = table._table.item(1, 1)
        assert off_item is not None
        assert skipped_item is not None
        assert not off_item.font().strikeOut()
        assert skipped_item.font().strikeOut()

        off_alpha = off_item.foreground().color().alphaF()
        skipped_alpha = skipped_item.foreground().color().alphaF()
        assert off_alpha == pytest.approx(1.0, abs=1e-3)
        assert skipped_alpha < off_alpha
        assert skipped_alpha == pytest.approx(0.45, abs=1e-3)

    def test_lr_filters_creates_tabs(self, qtbot) -> None:
        """set_lr_filters creates a QTabWidget with L and R tabs."""
        table = FilterTable()
        qtbot.addWidget(table)

        left = [CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=3.0, q=1.0)]
        right = [CanonicalFilter(type="PEAK", frequency_hz=2000.0, gain_db=-1.0, q=1.5)]

        table.set_lr_filters(left, right)

        assert table._tab_widget is not None
        assert table._tab_widget.count() == 2
        assert table._tab_widget.tabText(0) == "Left Channel"
        assert table._tab_widget.tabText(1) == "Right Channel"

    def test_comparison_highlights_changes(self, qtbot) -> None:
        """set_comparison highlights rows where filters differ."""
        table = FilterTable()
        qtbot.addWidget(table)

        before = [CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=3.0, q=1.0)]
        after = [CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=5.0, q=1.0)]

        table.set_comparison(before, after)

        assert table._table is not None
        # Changed row should have a background color set (accent highlight)
        item = table._table.item(0, 0)
        assert item is not None
        bg = item.background().color()
        assert bg.alpha() > 0  # Highlight applied

    def test_clear_removes_all(self, qtbot) -> None:
        """clear() removes the table widget."""
        table = FilterTable()
        qtbot.addWidget(table)

        filters = self._make_filters()
        table.set_filters(filters)
        assert table._table is not None

        table.clear()
        assert table._table is None

    def test_clamping_color_follows_active_theme(self, qtbot) -> None:
        """Clamped-band foreground color must follow the active theme.

        Regression guard for the old hardcoded WARNING_COLOR, which was
        correct for light mode but theme-blind in dark mode.
        """
        table = FilterTable()
        qtbot.addWidget(table)

        filters = self._make_filters()
        clamping_map = {0: ["gain exceeds +6 dB limit"]}

        with patch(
            "src.gui.components.filter_table.get_active_theme", return_value="dark"
        ):
            table.set_filters(filters, clamping_map=clamping_map)
            assert table._table is not None
            dark_item = table._table.item(0, 3)
            assert dark_item is not None
            dark_color = dark_item.foreground().color()

        with patch(
            "src.gui.components.filter_table.get_active_theme", return_value="light"
        ):
            table.set_filters(filters, clamping_map=clamping_map)
            assert table._table is not None
            light_item = table._table.item(0, 3)
            assert light_item is not None
            light_color = light_item.foreground().color()

        assert dark_color.name() == "#ffa726"
        assert light_color.name() == "#f57c00"

    def test_skipped_band_renders_as_na_crossed_out(self, qtbot) -> None:
        """A SkippedBand row shows 'N/A', strikethrough, and a reason tooltip."""
        table = FilterTable()
        qtbot.addWidget(table)

        filters = [CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=3.0, q=1.0)]
        rows: list[FilterRow] = [
            SkippedBand(original_type="Notch", reason="No WiiM equivalent for Notch"),
            filters[0],
        ]
        table.set_filters(filters, rows=rows)

        assert table._table is not None
        skipped_band_item = table._table.item(0, 0)
        assert skipped_band_item is not None
        assert skipped_band_item.text() == "N/A"
        skipped_type_item = table._table.item(0, 1)
        assert skipped_type_item is not None
        assert skipped_type_item.text() == "Notch"
        assert skipped_type_item.font().strikeOut()
        assert skipped_type_item.toolTip() == "No WiiM equivalent for Notch"
        assert skipped_type_item.foreground().color().alphaF() < 1.0

        # The valid filter after it still gets sequential band number 1
        valid_band_item = table._table.item(1, 0)
        assert valid_band_item is not None
        assert valid_band_item.text() == "1"

    def test_skipped_band_with_preserved_values_shows_them(self, qtbot) -> None:
        """A truncated SkippedBand (over the band cap) still shows its freq/gain/Q."""
        table = FilterTable()
        qtbot.addWidget(table)

        rows: list[FilterRow] = [
            SkippedBand(
                original_type="PEAK",
                reason="Exceeds device's 10-band limit",
                frequency_hz=500.0,
                gain_db=2.0,
                q=1.0,
            )
        ]
        table.set_filters([], rows=rows)

        assert table._table is not None
        assert table._table.item(0, 2) is not None
        assert table._table.item(0, 2).text() == "500 Hz"  # type: ignore[union-attr]
        assert table._table.item(0, 3).text() == "+2.0 dB"  # type: ignore[union-attr]
        assert table._table.item(0, 4).text() == "1.00"  # type: ignore[union-attr]

    def test_clamped_cell_shows_final_value_not_original(self, qtbot) -> None:
        """The gain/Q cell shows the value that will be written, not the raw import."""
        table = FilterTable()
        qtbot.addWidget(table)

        filters = [CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=15.0, q=1.0)]
        clamping_map = {0: ["gain +15.0 dB will be clamped to +12.0 dB"]}
        table.set_filters(filters, clamping_map=clamping_map)

        assert table._table is not None
        gain_item = table._table.item(0, 3)
        assert gain_item is not None
        assert gain_item.text() == "● +12.0 dB"
        assert "Original: +15.0 dB" in gain_item.toolTip()


# ---------------------------------------------------------------------------
# TestDeviceCard
# ---------------------------------------------------------------------------


class TestDeviceCard:
    """Tests for DeviceCard states (idle/connecting/connected/error)."""

    def test_set_device_info_populates_labels(self, qtbot) -> None:
        """set_device_info fills name, model, IP, firmware, and role labels."""
        card = DeviceCard()
        qtbot.addWidget(card)

        card.set_device_info(
            name="Living Room",
            model="WiiM Pro Plus",
            ip="192.168.1.42",
            firmware="v4.8.1",
            role="Leader",
        )

        assert card._name_label.text() == "Living Room"
        assert card._model_label.text() == "WiiM Pro Plus"
        assert card._ip_label.text() == "192.168.1.42"
        assert card._firmware_label.text() == "v4.8.1"
        assert card._role_badge.text() == "Leader"
        assert not card._role_badge.isHidden()

    def test_idle_state_neutral_border(self, qtbot) -> None:
        """idle state sets the 'idle' property value."""
        card = DeviceCard()
        qtbot.addWidget(card)

        card.set_state("idle")

        assert card.property("state") == "idle"

    def test_connected_state_accent_strip(self, qtbot) -> None:
        """connected state sets the 'connected' property value."""
        card = DeviceCard()
        qtbot.addWidget(card)

        card.set_state("connected")

        assert card.property("state") == "connected"

    def test_error_state_shows_retry(self, qtbot) -> None:
        """error state shows the error widget with retry button."""
        card = DeviceCard()
        qtbot.addWidget(card)

        card.set_error("Timeout")

        assert card.property("state") == "error"
        assert not card._error_widget.isHidden()
        assert card._error_label.text() == "Timeout"

    def test_clicked_signal_emitted(self, qtbot) -> None:
        """Left-clicking the card emits the clicked signal."""
        card = DeviceCard()
        qtbot.addWidget(card)

        with qtbot.waitSignal(card.clicked, timeout=1000):
            qtbot.mouseClick(card, Qt.MouseButton.LeftButton)

    def test_retry_signal_emitted(self, qtbot) -> None:
        """Clicking retry button emits retry_clicked signal."""
        card = DeviceCard()
        qtbot.addWidget(card)

        card.set_error("Connection lost")

        with qtbot.waitSignal(card.retry_clicked, timeout=1000):
            qtbot.mouseClick(card._retry_button, Qt.MouseButton.LeftButton)

    def test_invalid_state_raises(self, qtbot) -> None:
        """set_state with an invalid value raises ValueError."""
        card = DeviceCard()
        qtbot.addWidget(card)

        with pytest.raises(ValueError, match="Invalid state"):
            card.set_state("broken")


def test_pushpage_dry_run_badge_preserves_reserved_space(qtbot) -> None:
    """#109: toggling the dry-run badge must not shift the layout below it.

    sizeHint() alone can't catch this regression -- Qt widgets report a
    non-zero sizeHint whether or not they're visible, so a plain
    setVisible(False) with no retainSizeWhenHidden would still pass a
    sizeHint-only check while collapsing the badge's row and shifting
    everything below it up.

    Instead this asserts the actual on-screen y-position of the widget
    laid out directly after the badge (_progress_container) is identical
    whether the badge is hidden or shown -- i.e. the badge's row always
    occupies the same space in the layout. Toggling _progress_container's
    own visibility (as set_dry_run_result()/reset() do) is irrelevant to
    this -- Qt still reports a hidden widget's last-computed position, so
    the check has to happen while _progress_container itself stays
    visible; only the badge's visibility is toggled, exactly as it would
    be if retainSizeWhenHidden were flipped off and everything below the
    badge shifted up by the badge's row height.
    """
    page = PushPage()
    qtbot.addWidget(page)
    page.show()
    qtbot.wait(10)

    assert not page._dry_run_badge.isVisible()
    hidden_y = page._progress_container.pos().y()

    page._dry_run_badge.setVisible(True)
    qtbot.wait(10)
    shown_y = page._progress_container.pos().y()
    assert shown_y == hidden_y

    page._dry_run_badge.setVisible(False)
    qtbot.wait(10)
    hidden_again_y = page._progress_container.pos().y()
    assert hidden_again_y == hidden_y

    # Exercise the real public API too, to confirm set_dry_run_result/reset
    # still show/hide the badge as expected (behavioral smoke check).
    page.set_dry_run_result("Preview")
    qtbot.wait(10)
    assert page._dry_run_badge.isVisible()

    page.reset()
    qtbot.wait(10)
    assert not page._dry_run_badge.isVisible()
