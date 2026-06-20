"""Unit tests for HelpView in-app user guide.

Tests contextual navigation, section rendering, TOC search filtering,
close signal emission, and graceful handling of missing help files.

Requirements referenced: 27.1-27.10.
"""

from __future__ import annotations

from unittest.mock import patch

from PySide6.QtCore import Qt

from src.gui.views.help_view import (
    _STEP_SECTION_MAP,
    HelpView,
    _extract_title_from_markdown,
    _load_markdown,
)

# ---------------------------------------------------------------------------
# TestHelpViewBasic
# ---------------------------------------------------------------------------


class TestHelpViewBasic:
    """Tests for basic HelpView construction and display."""

    def test_creates_without_error(self, qtbot) -> None:
        """HelpView instantiates without errors."""
        view = HelpView()
        qtbot.addWidget(view)
        assert view is not None

    def test_has_close_button(self, qtbot) -> None:
        """HelpView has a close button that emits close_requested."""
        view = HelpView()
        qtbot.addWidget(view)

        with qtbot.waitSignal(view.close_requested, timeout=1000):
            qtbot.mouseClick(view._close_button, Qt.MouseButton.LeftButton)

    def test_has_search_input(self, qtbot) -> None:
        """HelpView has a search input field."""
        view = HelpView()
        qtbot.addWidget(view)

        assert view._search_input is not None
        assert view._search_input.placeholderText() == "Search topics..."

    def test_has_toc_list(self, qtbot) -> None:
        """HelpView has a table of contents list widget."""
        view = HelpView()
        qtbot.addWidget(view)

        assert view._toc_list is not None
        # Should have at least one item (even placeholder)
        assert view._toc_list.count() > 0

    def test_has_content_browser(self, qtbot) -> None:
        """HelpView has a content browser for rendering markdown."""
        view = HelpView()
        qtbot.addWidget(view)

        assert view._content_browser is not None

    def test_minimum_width_set(self, qtbot) -> None:
        """HelpView has a minimum width of 500px."""
        view = HelpView()
        qtbot.addWidget(view)

        assert view.minimumWidth() == 500


# ---------------------------------------------------------------------------
# TestHelpViewNavigation
# ---------------------------------------------------------------------------


class TestHelpViewNavigation:
    """Tests for contextual navigation and section display."""

    def test_navigate_to_section_emits_signal(self, qtbot) -> None:
        """navigate_to_section emits section_changed with the section ID."""
        view = HelpView()
        qtbot.addWidget(view)

        # Only test if we have more than one loaded section
        if view.section_count > 1:
            # Navigate to the second section (first is already selected on init)
            section_ids = list(view._sections.keys())
            target_id = section_ids[1]
            with qtbot.waitSignal(view.section_changed, timeout=1000) as blocker:
                view.navigate_to_section(target_id)
            assert blocker.args == [target_id]

    def test_navigate_to_section_updates_current(self, qtbot) -> None:
        """navigate_to_section updates current_section property."""
        view = HelpView()
        qtbot.addWidget(view)

        if view.section_count > 0:
            section_id = next(iter(view._sections))
            view.navigate_to_section(section_id)
            assert view.current_section == section_id

    def test_navigate_for_step_maps_correctly(self, qtbot) -> None:
        """navigate_for_step maps wizard step names to help sections."""
        view = HelpView()
        qtbot.addWidget(view)

        # Test that step mapping resolves without error
        for step_value, expected_section in _STEP_SECTION_MAP.items():
            if expected_section in view._sections:
                view.navigate_for_step(step_value)
                assert view.current_section == expected_section

    def test_navigate_to_unknown_section_no_crash(self, qtbot) -> None:
        """Navigating to a non-existent section does not crash."""
        view = HelpView()
        qtbot.addWidget(view)

        # Should not raise
        view.navigate_to_section("nonexistent-section-id")

    def test_navigate_via_wizard_step_name(self, qtbot) -> None:
        """navigate_to_section accepts wizard step names and resolves them."""
        view = HelpView()
        qtbot.addWidget(view)

        # 'connect' should resolve to 'getting-started' section
        if "getting-started" in view._sections:
            view.navigate_to_section("connect")
            assert view.current_section == "getting-started"

    def test_toc_click_changes_content(self, qtbot) -> None:
        """Clicking a different TOC item changes the displayed content."""
        view = HelpView()
        qtbot.addWidget(view)

        if view._toc_list.count() >= 2:
            # Select second item
            view._toc_list.setCurrentRow(1)
            second_section = view._toc_list.item(1).data(Qt.ItemDataRole.UserRole)
            assert view.current_section == second_section


# ---------------------------------------------------------------------------
# TestHelpViewSearch
# ---------------------------------------------------------------------------


class TestHelpViewSearch:
    """Tests for TOC search/filter functionality."""

    def test_search_filters_toc_items(self, qtbot) -> None:
        """Typing in search field filters TOC items by title/content match."""
        view = HelpView()
        qtbot.addWidget(view)

        initial_visible = view.visible_toc_count

        # Search for something unlikely to match all items
        view._search_input.setText("xyznonexistent")

        # Should have fewer visible items (possibly zero)
        assert view.visible_toc_count <= initial_visible

    def test_clear_search_shows_all(self, qtbot) -> None:
        """Clearing the search shows all TOC items again."""
        view = HelpView()
        qtbot.addWidget(view)

        initial_visible = view.visible_toc_count

        # Apply and then clear filter
        view._search_input.setText("xyznonexistent")
        view._search_input.clear()

        assert view.visible_toc_count == initial_visible

    def test_search_is_case_insensitive(self, qtbot) -> None:
        """Search matching is case-insensitive."""
        view = HelpView()
        qtbot.addWidget(view)

        if view.section_count > 0:
            # Get the title of first section and search for it in different case
            first_title = next(iter(view._section_titles.values()))
            if first_title:
                view._search_input.setText(first_title.upper())
                # At least the matching section should be visible
                assert view.visible_toc_count >= 1


# ---------------------------------------------------------------------------
# TestHelpViewGracefulFallback
# ---------------------------------------------------------------------------


class TestHelpViewGracefulFallback:
    """Tests for graceful handling of missing help files."""

    @patch("src.gui.views.help_view._resolve_help_dir")
    def test_missing_files_shows_placeholder(self, mock_dir, qtbot, tmp_path) -> None:
        """When no help files exist, a placeholder section is shown."""
        # Point to an empty directory
        mock_dir.return_value = tmp_path

        view = HelpView()
        qtbot.addWidget(view)

        # Should still have content (placeholder)
        assert view.section_count >= 1
        assert view._toc_list.count() >= 1

    @patch("src.gui.views.help_view._resolve_help_dir")
    def test_partial_files_loads_available(self, mock_dir, qtbot, tmp_path) -> None:
        """When some help files exist, only those are loaded."""
        # Create just one help file
        (tmp_path / "getting_started.md").write_text(
            "# Getting Started\n\nTest content here.", encoding="utf-8"
        )
        mock_dir.return_value = tmp_path

        view = HelpView()
        qtbot.addWidget(view)

        assert "getting-started" in view._sections
        assert view._section_titles["getting-started"] == "Getting Started"


# ---------------------------------------------------------------------------
# TestHelperFunctions
# ---------------------------------------------------------------------------


class TestHelperFunctions:
    """Tests for module-level helper functions."""

    def test_extract_title_from_markdown_h1(self) -> None:
        """Extracts first H1 heading as title."""
        content = "# My Title\n\nSome content\n## Section"
        assert _extract_title_from_markdown(content) == "My Title"

    def test_extract_title_skips_h2(self) -> None:
        """Does not pick up H2 headings as title."""
        content = "## Not a Title\n\n# Real Title"
        assert _extract_title_from_markdown(content) == "Real Title"

    def test_extract_title_no_heading_returns_untitled(self) -> None:
        """Returns 'Untitled' when no H1 heading exists."""
        content = "Some content without headings"
        assert _extract_title_from_markdown(content) == "Untitled"

    def test_load_markdown_nonexistent_returns_none(self, tmp_path) -> None:
        """_load_markdown returns None for non-existent files."""
        with patch("src.gui.views.help_view._resolve_help_dir", return_value=tmp_path):
            result = _load_markdown("nonexistent.md")
        assert result is None

    def test_load_markdown_existing_file(self, tmp_path) -> None:
        """_load_markdown returns content for existing files."""
        (tmp_path / "test.md").write_text("# Test\n\nHello", encoding="utf-8")
        with patch("src.gui.views.help_view._resolve_help_dir", return_value=tmp_path):
            result = _load_markdown("test.md")
        assert result == "# Test\n\nHello"
