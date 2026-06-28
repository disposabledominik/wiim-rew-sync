"""Unit tests for shared GUI components.

Tests StatusBanner, StepIndicator, SidebarNav, FilterTable, and DeviceCard
using pytest-qt (qtbot fixture) for Qt widget lifecycle management.

Requirements referenced: 7.1-7.6, 1.3-1.4, 8.1-8.2, 5.1-5.5, 2.3.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from PySide6.QtCore import Qt

from src.gui.components.device_card import DeviceCard
from src.gui.components.filter_table import FilterTable
from src.gui.components.sidebar_nav import SidebarNav
from src.gui.components.status_banner import StatusBanner
from src.gui.components.step_indicator import StepIndicator
from src.gui.constants import SIDEBAR_COLLAPSED, SIDEBAR_EXPANDED
from src.gui.pages.push_page import PushPage
from src.models.canonical import CanonicalFilter

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
        assert gain_item.toolTip() == "Clamped: gain exceeds +6 dB limit"

    def test_disabled_band_opacity(self, qtbot) -> None:
        """OFF bands have reduced opacity applied to their items."""
        table = FilterTable()
        qtbot.addWidget(table)

        filters = self._make_filters()
        table.set_filters(filters)

        # Row 2 is OFF - check that alpha is reduced
        assert table._table is not None
        item = table._table.item(2, 1)
        assert item is not None
        color = item.foreground().color()
        assert color.alphaF() < 1.0

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
    """#109: Dry-run badge keeps a stable size hint when toggled."""
    page = PushPage()
    qtbot.addWidget(page)
    page.show()
    qtbot.wait(10)

    initial_badge_hint = page._dry_run_badge.sizeHint().height()
    initial_page_hint = page.sizeHint().height()

    page.set_dry_run_result("Preview")
    qtbot.wait(10)

    visible_badge_hint = page._dry_run_badge.sizeHint().height()
    visible_page_hint = page.sizeHint().height()

    page.reset()
    qtbot.wait(10)

    reset_badge_hint = page._dry_run_badge.sizeHint().height()
    reset_page_hint = page.sizeHint().height()

    assert initial_badge_hint > 0
    assert visible_badge_hint == initial_badge_hint
    assert reset_badge_hint == initial_badge_hint
    assert visible_page_hint >= initial_page_hint
    assert reset_page_hint >= initial_page_hint
