"""Integration tests for the profile recall flow.

Tests the full chain: MyPresetsView load_requested → SecondaryWorkflowManager.recall_profile
→ profile_recalled signal → MainWindow._on_profile_recalled → ReviewPage populated + navigation.

Requirements: 11.1-11.5
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.gui.app_settings import AppSettings
from src.gui.components.step_indicator import _StepState
from src.gui.main_window import PAGE_INDICES, MainWindow
from src.gui.wizard_controller import WizardStep
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
    from src.models.channel_mode import ChannelMode

    profile = MagicMock()
    if filters is not None:
        profile.filters = filters
    profile.name = name
    profile.channel_mode = ChannelMode.STEREO
    profile.filters_l = None
    profile.filters_r = None
    return profile


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
# mock_bridge is defined in conftest.py, shared across GUI integration test files.


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

        # Verify filters_origin set for the Filters step tooltip (#162d)
        assert state.filters_origin == "My Presets: Test Profile"

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
# Test 3b: L/R profile recall with one empty channel -> error, not a crash
# ---------------------------------------------------------------------------


class TestProfileRecallLrEmptyChannel:
    """An L/R profile whose combined filters (filters_l + filters_r) are
    non-empty because only one channel is empty must not crash
    _on_profile_recalled -- require_lr_filters() (ca14e26) raises for that
    case, and _on_profile_recalled must turn that ValueError into an error
    banner instead of letting it escape the Qt slot uncaught
    (branch-quality review, 2026-07-18)."""

    def test_recall_lr_profile_with_empty_channel_shows_error_not_crash(
        self, make_window, qtbot
    ) -> None:
        from src.models.channel_mode import ChannelMode

        window = make_window()
        # As _on_profile_load_requested does before calling recall_profile.
        window._wizard_controller.state.channel_mode = ChannelMode.LR

        profile = _make_profile(name="Broken LR Profile")
        profile.channel_mode = ChannelMode.LR
        profile.filters_l = []
        profile.filters_r = _make_filters(2)

        with patch.object(window._review_page, "set_lr_filters") as mock_set_lr:
            window._secondary_workflows.recall_profile(profile)

        mock_set_lr.assert_not_called()
        assert "Could not load preset" in window._status_banner._message_label.text()


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


# ---------------------------------------------------------------------------
# Test 5: Profile recall invalidates a stale PUSH completion (#238)
# ---------------------------------------------------------------------------


class TestProfileRecallInvalidatesStalePush:
    """Loading a different profile via the sidebar must not leave a later
    step (PUSH) checked while REVIEW -- which precedes it -- is freshly
    (re-)entered and unchecked. Same invariant-violation class as #238's
    onboarding "Get Started" bug, reached via ``_jump_to_review()`` instead.
    """

    def test_recall_clears_stale_push_completion(self, make_window, qtbot) -> None:
        """Simulate a completed push from a prior, unrelated flow, then
        recall a different profile via the sidebar. PUSH must be dropped
        from completed_steps and its StepIndicator pill un-checked.
        """
        window = make_window()

        # Simulate a previously completed push (as _on_write_complete would
        # leave behind after a successful push earlier in the session).
        window._wizard_controller.set_step_summary(WizardStep.PUSH, "Pushed to Device X")
        push_index = window._wizard_controller.get_steps().index(WizardStep.PUSH)
        window.step_indicator.set_completed(push_index, "Pushed to Device X")
        assert window.step_indicator._steps[push_index].state == _StepState.COMPLETED

        filters = _make_filters(2)
        profile = _make_profile(filters=filters, name="Different Profile")
        window._secondary_workflows.recall_profile(profile)

        assert WizardStep.PUSH not in window._wizard_controller.completed_steps
        assert window.step_indicator._steps[push_index].state != _StepState.COMPLETED
        assert window.stacked_widget.currentIndex() == PAGE_INDICES["review"]
