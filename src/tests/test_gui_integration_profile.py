"""Integration tests for the profile recall flow.

Tests the full chain: MyPresetsView load_requested → SecondaryWorkflowManager.recall_profile
→ profile_recalled signal → MainWindow._on_profile_recalled → ReviewPage populated + navigation.

Requirements: 11.1-11.5
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.gui.app_settings import AppSettings
from src.gui.main_window import PAGE_INDICES, MainWindow
from src.models.canonical import CanonicalFilter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_filters(count: int = 3) -> list[CanonicalFilter]:
    """Create a minimal valid filter list for test purposes."""
    base_filters = [
        CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-3.0, q=1.4),
        CanonicalFilter(type="HS", frequency_hz=8000.0, gain_db=2.0, q=0.7),
        CanonicalFilter(type="LS", frequency_hz=200.0, gain_db=1.5, q=1.0),
    ]
    return base_filters[:count]


def _make_profile(*, filters: list[CanonicalFilter] | None = None, name: str = "Test Profile"):
    """Create a mock profile object with filters and name attributes."""
    profile = MagicMock()
    if filters is not None:
        profile.filters = filters
    profile.name = name
    return profile


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_bridge() -> MagicMock:
    """Create a MagicMock async bridge with expected signal attributes."""
    bridge = MagicMock()
    bridge.start = MagicMock()
    bridge.shutdown = MagicMock()
    return bridge


@pytest.fixture()
def make_window(qtbot, mock_bridge):
    """Factory fixture to create MainWindow with mocked AsyncBridge."""
    windows: list[MainWindow] = []

    def _factory() -> MainWindow:
        settings = AppSettings()
        with (
            patch("src.gui.app_settings.AppSettings.load", return_value=settings),
            patch("src.gui.app_settings.AppSettings.save"),
        ):
            window = MainWindow(async_bridge=mock_bridge)
            qtbot.addWidget(window)
            windows.append(window)
            return window

    yield _factory

    for w in windows:
        w._wizard_controller.state.current_filters = []
        w.close()


# ---------------------------------------------------------------------------
# Test 1: Profile recall with valid filters → navigates to Review
# ---------------------------------------------------------------------------


class TestProfileRecallWithFilters:
    """Test profile with filters triggers recall and navigates to Review.

    Requirements: 11.1, 11.2, 11.3
    """

    def test_profile_recall_with_filters(self, make_window, qtbot) -> None:
        """Create a profile with valid filters, trigger recall_profile,
        verify profile_recalled signal emits, and _on_profile_recalled
        stores filters and navigates to Review page.
        """
        window = make_window()
        filters = _make_filters(3)
        profile = _make_profile(filters=filters, name="Test Profile")

        # Capture profile_recalled signal
        recalled_filters: list = []
        window._secondary_workflows.profile_recalled.connect(
            lambda f: recalled_filters.append(f)
        )

        # Trigger the recall flow (as MyPresetsView would)
        window._secondary_workflows.recall_profile(profile)

        # Verify profile_recalled emitted with filters
        assert len(recalled_filters) == 1
        assert recalled_filters[0] == filters

        # Verify wizard state has filters
        state = window._wizard_controller.state
        assert state.current_filters == filters

        # Verify navigated to Review page
        assert window.stacked_widget.currentIndex() == PAGE_INDICES["review"]

        # Verify StatusBanner shows success
        assert "3 bands ready for review" in window._status_banner._message_label.text()


# ---------------------------------------------------------------------------
# Test 2: Profile recall with empty filters → error shown
# ---------------------------------------------------------------------------


class TestProfileRecallEmptyFilters:
    """Test profile with empty filters shows error in StatusBanner.

    Requirements: 11.4
    """

    def test_profile_recall_empty_filters(self, make_window, qtbot) -> None:
        """Create profile with filters=[]. Call recall_profile.
        Verify profile_recalled emitted with empty list.
        Verify StatusBanner shows error 'Profile contains no filters'.
        """
        window = make_window()
        profile = _make_profile(filters=[], name="Empty Profile")

        # Capture profile_recalled signal
        recalled_filters: list = []
        window._secondary_workflows.profile_recalled.connect(
            lambda f: recalled_filters.append(f)
        )

        # Start on connect page
        window._stacked_widget.setCurrentIndex(PAGE_INDICES["connect"])

        # Trigger the recall flow
        window._secondary_workflows.recall_profile(profile)

        # Verify profile_recalled emitted with empty list
        assert len(recalled_filters) == 1
        assert recalled_filters[0] == []

        # Verify StatusBanner shows error
        assert "Profile contains no filters" in window._status_banner._message_label.text()

        # Verify we did NOT navigate away from current page
        assert window.stacked_widget.currentIndex() == PAGE_INDICES["connect"]


# ---------------------------------------------------------------------------
# Test 3: Profile recall with no filters attribute → error handling
# ---------------------------------------------------------------------------


class TestProfileRecallNoFiltersAttr:
    """Test profile with no 'filters' attribute emits empty list and shows error.

    Requirements: 11.5
    """

    def test_profile_recall_no_filters_attr(self, make_window, qtbot) -> None:
        """Create profile object without a 'filters' attribute.
        Call recall_profile. Verify profile_recalled emitted with empty list.
        Verify error handling shows appropriate message.
        """
        window = make_window()

        # Create a profile mock without the 'filters' attribute
        profile = MagicMock(spec=[])  # Empty spec = no attributes
        profile.name = "Corrupted Profile"
        # Ensure getattr(profile, 'filters', []) returns []
        del profile.filters  # Remove if auto-created by MagicMock

        # Capture profile_recalled signal
        recalled_filters: list = []
        window._secondary_workflows.profile_recalled.connect(
            lambda f: recalled_filters.append(f)
        )

        # Start on my_presets page
        window._stacked_widget.setCurrentIndex(PAGE_INDICES["my_presets"])

        # Trigger the recall flow
        window._secondary_workflows.recall_profile(profile)

        # Verify profile_recalled emitted with empty list
        assert len(recalled_filters) == 1
        assert recalled_filters[0] == []

        # Verify StatusBanner shows error (handled by _on_profile_recalled)
        assert "Profile contains no filters" in window._status_banner._message_label.text()

        # Verify we stayed on the same page
        assert window.stacked_widget.currentIndex() == PAGE_INDICES["my_presets"]


# ---------------------------------------------------------------------------
# Test 4: Profile recall updates ReviewPage via set_filters
# ---------------------------------------------------------------------------


class TestProfileRecallUpdatesReviewPage:
    """Test that profile recall calls review_page.set_filters with the filters.

    Requirements: 11.3
    """

    def test_profile_recall_updates_review_page(self, make_window, qtbot) -> None:
        """Create a profile with valid filters, trigger recall flow,
        verify review_page.set_filters was called with the filters.
        """
        window = make_window()
        filters = _make_filters(2)
        profile = _make_profile(filters=filters, name="Review Test Profile")

        # Patch set_filters on the review page to track calls
        with patch.object(window._review_page, "set_filters") as mock_set_filters:
            # Trigger the recall flow
            window._secondary_workflows.recall_profile(profile)

            # Verify set_filters was called with our filters
            mock_set_filters.assert_called_once_with(filters)
