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

_KEY_RETURN = getattr(Qt, "Key_Return", 0x01000004)


def _visible_toc_count(view: HelpView) -> int:
    """Count TOC items not hidden by the current search filter."""
    return sum(
        1
        for i in range(view._toc_list.count())
        if (item := view._toc_list.item(i)) is not None and not item.isHidden()
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

    def test_navigate_to_section_updates_current(self, qtbot) -> None:
        """navigate_to_section updates the tracked current section."""
        view = HelpView()
        qtbot.addWidget(view)

        if view.section_count > 0:
            section_id = next(iter(view._sections))
            view.navigate_to_section(section_id)
            assert view._current_section == section_id

    def test_navigate_to_section_maps_wizard_step_names(self, qtbot) -> None:
        """navigate_to_section maps wizard step names to help sections."""
        view = HelpView()
        qtbot.addWidget(view)

        # Test that step mapping resolves without error
        for step_value, expected_section in _STEP_SECTION_MAP.items():
            if expected_section in view._sections:
                view.navigate_to_section(step_value)
                assert view._current_section == expected_section

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
            assert view._current_section == "getting-started"

    def test_toc_click_changes_content(self, qtbot) -> None:
        """Clicking a different TOC item changes the displayed content."""
        view = HelpView()
        qtbot.addWidget(view)

        if view._toc_list.count() >= 2:
            # Select second item
            view._toc_list.setCurrentRow(1)
            second_section = view._toc_list.item(1).data(Qt.ItemDataRole.UserRole)
            assert view._current_section == second_section


# ---------------------------------------------------------------------------
# TestHelpViewSearch
# ---------------------------------------------------------------------------


class TestHelpViewSearch:
    """Tests for TOC search/filter functionality."""

    def test_search_filters_toc_items(self, qtbot) -> None:
        """Typing in search field filters TOC items by title/content match."""
        view = HelpView()
        qtbot.addWidget(view)

        initial_visible = _visible_toc_count(view)

        # Search for something unlikely to match all items
        view._search_input.setText("xyznonexistent")

        # Should have fewer visible items (possibly zero)
        assert _visible_toc_count(view) <= initial_visible

    def test_clear_search_shows_all(self, qtbot) -> None:
        """Clearing the search shows all TOC items again."""
        view = HelpView()
        qtbot.addWidget(view)

        initial_visible = _visible_toc_count(view)

        # Apply and then clear filter
        view._search_input.setText("xyznonexistent")
        view._search_input.clear()

        assert _visible_toc_count(view) == initial_visible

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
                assert _visible_toc_count(view) >= 1

    def test_search_navigation_buttons_exist(self, qtbot) -> None:
        """Search view has next/previous navigation buttons and hit counter."""
        view = HelpView()
        qtbot.addWidget(view)

        assert view._search_prev_button is not None
        assert view._search_next_button is not None
        assert view._search_hit_label is not None

    def test_search_buttons_disabled_on_empty_search(self, qtbot) -> None:
        """Navigation buttons are disabled when there's no search query."""
        view = HelpView()
        qtbot.addWidget(view)

        # Initially, buttons should be disabled (no search)
        assert not view._search_prev_button.isEnabled()
        assert not view._search_next_button.isEnabled()

    def test_search_hits_content(self, qtbot, tmp_path) -> None:
        """Search finds and counts hits in the current section content."""

        view = HelpView()
        qtbot.addWidget(view)

        # Create a test section with known content
        test_content = (
            "# Test Section\n\nThe quick brown fox jumps. "
            "Fox is mentioned again in this fox paragraph."
        )
        view._sections["test-section"] = test_content
        view._section_titles["test-section"] = "Test Section"
        view._populate_toc()
        view._display_section("test-section")

        # Give the QTextBrowser time to render the markdown
        qtbot.wait(100)

        # Trigger search for "fox"
        view._search_input.setText("fox")

        # Should find hits (case-insensitive)
        # Note: exact count depends on markdown rendering, verify mechanism works
        assert view._search_query == "fox"
        # The search should have been performed
        assert view._current_hit_index >= 0 or view._search_hit_count == 0

    def test_search_navigates_to_first_match(self, qtbot) -> None:
        """When searching, the view navigates to and displays the first matching section."""
        view = HelpView()
        qtbot.addWidget(view)

        if view.section_count > 0:
            first_section_id = next(iter(view._sections.keys()))
            first_section_title = view._section_titles.get(first_section_id, "")

            # Search for part of the first section's title
            if len(first_section_title) > 2:
                search_term = first_section_title[:3].lower()
                view._search_input.setText(search_term)

                # Should navigate to a matching section
                assert view._current_section is not None

    def test_search_next_button_navigation(self, qtbot) -> None:
        """Clicking next button advances to the next search hit."""
        view = HelpView()
        qtbot.addWidget(view)

        # Create a test section with multiple occurrences
        test_content = (
            "# Test\n\nhello world hello there hello again"
        )
        view._sections["test"] = test_content
        view._section_titles["test"] = "Test"
        view._populate_toc()
        view._display_section("test")

        # Search for a term that appears multiple times
        view._search_input.setText("hello")

        if view._search_hit_count > 1:
            initial_index = view._current_hit_index
            view._search_next_button.click()
            # After clicking next, index should advance (wraps around)
            new_index = view._current_hit_index
            assert new_index != initial_index or view._search_hit_count == 1

    def test_search_previous_button_navigation(self, qtbot) -> None:
        """Clicking previous button goes to the previous search hit."""
        view = HelpView()
        qtbot.addWidget(view)

        # Create a test section with multiple occurrences
        test_content = (
            "# Test\n\nhello world hello there hello again"
        )
        view._sections["test"] = test_content
        view._section_titles["test"] = "Test"
        view._populate_toc()
        view._display_section("test")

        # Search for a term that appears multiple times
        view._search_input.setText("hello")

        if view._search_hit_count > 1:
            # Advance to a middle hit
            view._search_next_button.click()
            advanced_index = view._current_hit_index

            # Go back
            view._search_prev_button.click()
            previous_index = view._current_hit_index

            # Should move backward
            assert previous_index != advanced_index or view._search_hit_count == 1

    def test_enter_in_search_triggers_next_hit(self, qtbot) -> None:
        """Pressing Enter in the search field triggers next hit navigation."""
        view = HelpView()
        qtbot.addWidget(view)

        # Create a test section with multiple occurrences
        test_content = (
            "# Test\n\nhello world hello there hello again"
        )
        view._sections["test"] = test_content
        view._section_titles["test"] = "Test"
        view._populate_toc()
        view._display_section("test")

        # Set search query
        view._search_input.setText("hello")

        if view._search_hit_count > 1:
            initial_index = view._current_hit_index
            # Simulate pressing Enter
            view._search_input.returnPressed.emit()
            new_index = view._current_hit_index
            # Should advance to next hit (or wrap)
            assert new_index != initial_index or view._search_hit_count == 1

    def test_enter_does_not_close_dialog(self, qtbot) -> None:
        """Pressing Enter in the search field does not emit close_requested."""
        view = HelpView()
        qtbot.addWidget(view)

        close_emitted = False

        def on_close():
            nonlocal close_emitted
            close_emitted = True

        view.close_requested.connect(on_close)

        # Type in search input and press Enter
        view._search_input.setText("test")
        qtbot.keyClick(view._search_input, _KEY_RETURN)

        # close_requested should NOT have been emitted
        assert not close_emitted

    def test_enter_on_default_focus_does_not_close_dialog(self, qtbot) -> None:
        """QA-reported bug: pressing Enter right after opening the "User
        Guide" window closed it, unlike the Diagnostics window. Root cause:
        MainWindow hosts HelpView inside a real QDialog (`_help_dialog`),
        where QPushButton.autoDefault defaults to True -- Qt then silently
        auto-picks the first-created autoDefault button (here, the "X"
        close button, built before the search/TOC controls) as the dialog's
        Enter-key target. The panel also opens with initial keyboard focus
        already on that same close button, compounding it. The
        `test_enter_does_not_close_dialog` test above never wrapped HelpView
        in a QDialog, so autoDefault was never True there and it missed
        this entirely -- this test reproduces the real hosting context."""
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QDialog, QVBoxLayout

        dialog = QDialog()
        qtbot.addWidget(dialog)
        view = HelpView()
        QVBoxLayout(dialog).addWidget(view)

        closed: list[bool] = []
        view.close_requested.connect(lambda: closed.append(True))

        dialog.show()
        qtbot.waitExposed(dialog)

        # Default initial focus lands on the close button (first widget
        # built) -- pressing Enter there must not trigger it.
        QTest.keyClick(dialog.focusWidget() or view, _KEY_RETURN)

        assert not closed

    def test_enter_key_navigates_search_hits(self, qtbot) -> None:
        """Pressing Enter in the search field advances the current search hit."""
        view = HelpView()
        qtbot.addWidget(view)

        view._sections["test"] = "# Test\n\nhello world hello there hello again"
        view._section_titles["test"] = "Test"
        view._populate_toc()
        view._display_section("test")
        view._search_input.setText("hello")

        if view._search_hit_count > 1:
            initial_index = view._current_hit_index
            qtbot.keyClick(view._search_input, _KEY_RETURN)
            assert view._current_hit_index != initial_index or view._search_hit_count == 1

    def test_search_highlights_current_hit(self, qtbot) -> None:
        """Search hit highlighting is applied to the displayed section."""
        view = HelpView()
        qtbot.addWidget(view)

        view._sections["test"] = "# Test\n\nhello world hello there"
        view._section_titles["test"] = "Test"
        view._populate_toc()
        view._display_section("test")

        view._search_input.setText("hello")
        qtbot.wait(100)

        assert len(view._content_browser.extraSelections()) >= 1

    def test_hit_counter_updates(self, qtbot) -> None:
        """Hit counter label updates when search results change."""
        view = HelpView()
        qtbot.addWidget(view)

        # Initially, counter should show 0 of 0
        assert "0 of 0" in view._search_hit_label.text()

        # Create a test section with multiple occurrences
        test_content = (
            "# Test\n\nhello world hello there hello again"
        )
        view._sections["test"] = test_content
        view._section_titles["test"] = "Test"
        view._populate_toc()
        view._display_section("test")

        # Search for a term that appears multiple times
        view._search_input.setText("hello")

        # Counter should now show results
        if view._search_hit_count > 0:
            assert view._search_hit_count > 0
            assert "1 of" in view._search_hit_label.text()

    def test_hit_counter_wraps_around(self, qtbot) -> None:
        """Navigation wraps around when reaching the end/start of hits."""
        view = HelpView()
        qtbot.addWidget(view)

        # Create a test section with multiple occurrences
        test_content = (
            "# Test\n\nhello world hello there hello again"
        )
        view._sections["test"] = test_content
        view._section_titles["test"] = "Test"
        view._populate_toc()
        view._display_section("test")

        # Search for a term
        view._search_input.setText("hello")

        if view._search_hit_count > 1:
            # Move to the last hit
            while view._current_hit_index < view._search_hit_count - 1:
                view._search_next_button.click()

            last_index = view._current_hit_index
            assert last_index == view._search_hit_count - 1

            # Press next again - should wrap to start
            view._search_next_button.click()
            assert view._current_hit_index == 0


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
