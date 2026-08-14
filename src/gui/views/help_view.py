"""In-app user guide with contextual navigation.

Displays bundled Markdown help content from assets/help/ as a side panel
overlay. Features a searchable table of contents sidebar and contextual
navigation (auto-navigate to relevant section based on current wizard step).

Requirements: 27.1, 27.2, 27.3, 27.4, 27.5, 27.6, 27.7, 27.8, 27.9, 27.10.
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QColor, QKeyEvent, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.gui.components.action_button import make_action_button
from src.gui.components.list_item_style import size_list_item, style_selectable_list
from src.gui.constants import (
    ACCENT_COLOR,
    SPACING_MD,
    SPACING_SM,
    SPACING_XS,
)

_KEY_RETURN = getattr(Qt, "Key_Return", 0x01000004)
_KEY_ENTER = getattr(Qt, "Key_Enter", 0x01000005)

# Extra block spacing (px) applied after rendering, since QTextDocument's
# Markdown importer (setMarkdown()) builds block formats directly rather
# than through a CSS stylesheet -- setDefaultStyleSheet() has no effect on
# heading/paragraph/list spacing here, only on inline HTML embedded in the
# Markdown. Margins must be set per-block after the fact instead.
_HEADING_TOP_MARGIN = {1: 24, 2: 18, 3: 14}
_HEADING_BOTTOM_MARGIN = 8
_LIST_ITEM_BOTTOM_MARGIN = 6
_PARAGRAPH_TOP_MARGIN = 4
_PARAGRAPH_BOTTOM_MARGIN = 12


def _apply_block_spacing(document: QTextDocument) -> None:
    """Widen the gaps between headings, paragraphs, and list items.

    Qt's default Markdown rendering packs blocks tightly together. This
    walks every block in the already-rendered document and sets a more
    comfortable top/bottom margin based on what kind of block it is.
    """
    cursor = QTextCursor(document)
    block = document.begin()
    while block.isValid():
        block_format = block.blockFormat()
        heading_level = block_format.headingLevel()
        if heading_level > 0:
            block_format.setTopMargin(_HEADING_TOP_MARGIN.get(heading_level, 12))
            block_format.setBottomMargin(_HEADING_BOTTOM_MARGIN)
        elif block.textList() is not None:
            block_format.setTopMargin(0)
            block_format.setBottomMargin(_LIST_ITEM_BOTTOM_MARGIN)
        elif block.text().strip():
            block_format.setTopMargin(_PARAGRAPH_TOP_MARGIN)
            block_format.setBottomMargin(_PARAGRAPH_BOTTOM_MARGIN)
        cursor.setPosition(block.position())
        cursor.setBlockFormat(block_format)
        block = block.next()

# ---------------------------------------------------------------------------
# Section-to-file mapping and wizard step context mapping
# ---------------------------------------------------------------------------

# Each help file defines one or more logical sections. The key is the
# section_id used by navigate_to_section(); the value is the filename
# (without path) in assets/help/.
_SECTION_FILE_MAP: dict[str, str] = {
    "getting-started": "getting_started.md",
    "import-and-push": "import_and_push.md",
    "pull-and-export": "pull_and_export.md",
    "managing-presets": "managing_presets.md",
    "using-roomfit": "using_roomfit.md",
    "troubleshooting": "troubleshooting.md",
}

# Maps wizard step names (from WizardStep enum value) to relevant help section.
_STEP_SECTION_MAP: dict[str, str] = {
    "connect": "getting-started",
    "eq_type": "getting-started",
    "source": "import-and-push",
    "filters": "import-and-push",
    "review": "import-and-push",
    "name_profile": "using-roomfit",
    "push": "import-and-push",
}

# Placeholder content shown when no help files are found.
_PLACEHOLDER_CONTENT = (
    "# Help\n\n"
    "Help content is not yet available.\n\n"
    "The user guide will be bundled with the application and will cover "
    "all workflows and features."
)


def _resolve_help_dir() -> Path:
    """Resolve the assets/help/ directory path.

    Tries PyInstaller _MEIPASS first (for packaged builds), then
    importlib.resources (for installed packages), then falls back to
    file-system relative path (for development).
    """
    # PyInstaller onefile: files are extracted to sys._MEIPASS
    import sys

    if hasattr(sys, "_MEIPASS"):
        meipass_path = Path(sys._MEIPASS) / "src" / "gui" / "assets" / "help"
        if meipass_path.is_dir():
            return meipass_path

    try:
        # Python 3.12+ files() API
        ref = importlib.resources.files("src.gui.assets.help")
        # Convert Traversable to Path if possible
        help_path = Path(str(ref))
        if help_path.is_dir():
            return help_path
    except (ModuleNotFoundError, TypeError, AttributeError):
        pass

    # Fallback: resolve relative to this file
    return Path(__file__).resolve().parent.parent / "assets" / "help"


def _load_markdown(filename: str) -> str | None:
    """Load a markdown file from the help directory.

    Returns None if the file doesn't exist or can't be read.
    """
    help_dir = _resolve_help_dir()
    filepath = help_dir / filename
    if filepath.is_file():
        try:
            return filepath.read_text(encoding="utf-8")
        except OSError:
            return None
    return None


def _extract_title_from_markdown(content: str) -> str:
    """Extract the first H1 heading from markdown content as title."""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not stripped.startswith("##"):
            return stripped[2:].strip()
    return "Untitled"


class HelpView(QFrame):
    """In-app user guide with contextual navigation.

    Displayed as a side panel overlay that does not replace the current view.
    Features a searchable table of contents and content browser.

    Signals:
        close_requested: Emitted when the user clicks the close button.
    """

    close_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("helpView")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setProperty("class", "help-panel")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        self.setMinimumWidth(500)

        self._current_section: str | None = None
        self._sections: dict[str, str] = {}  # section_id -> markdown content
        self._section_titles: dict[str, str] = {}  # section_id -> display title

        # Search state tracking
        self._search_query: str = ""
        self._search_matches: list[tuple[str, int]] = []
        self._current_hit_index: int = -1
        self._search_hit_count: int = 0

        self._build_ui()
        self._load_all_sections()
        self._populate_toc()

    def _build_ui(self) -> None:
        """Construct the widget layout."""
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Header bar with title and close button
        header = QFrame()
        header.setObjectName("helpHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(SPACING_MD, SPACING_SM, SPACING_SM, SPACING_SM)

        title_label = QLabel("User Guide")
        title_label.setProperty("class", "heading")
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        self._close_button = make_action_button(
            "\u2715", object_name="helpCloseButton", style_class="ghost"
        )  # Unicode X
        self._close_button.setFixedSize(28, 28)
        self._close_button.clicked.connect(self.close_requested.emit)
        header_layout.addWidget(self._close_button)
        root_layout.addWidget(header)

        # Main content area: TOC sidebar + content browser
        content_area = QWidget()
        content_layout = QHBoxLayout(content_area)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Left sidebar: search + TOC list
        toc_panel = QFrame()
        toc_panel.setObjectName("helpTocPanel")
        toc_panel.setFixedWidth(180)
        toc_layout = QVBoxLayout(toc_panel)
        toc_layout.setContentsMargins(SPACING_SM, SPACING_SM, SPACING_SM, SPACING_SM)
        toc_layout.setSpacing(SPACING_XS)

        # Search input with navigation controls below
        search_container = QWidget()
        search_layout = QVBoxLayout(search_container)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(SPACING_XS)

        self._search_input = QLineEdit()
        self._search_input.setObjectName("helpSearchInput")
        self._search_input.setPlaceholderText("Search topics...")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.textChanged.connect(self._on_search_changed)
        self._search_input.returnPressed.connect(self._on_search_next)
        self._search_input.installEventFilter(self)
        search_layout.addWidget(self._search_input)

        navigation_container = QWidget()
        navigation_layout = QHBoxLayout(navigation_container)
        navigation_layout.setContentsMargins(0, 0, 0, 0)
        navigation_layout.setSpacing(SPACING_XS)

        self._search_prev_button = make_action_button(
            "◀", object_name="helpSearchPrevButton", style_class="ghost",
            tooltip="Previous match",
        )
        self._search_prev_button.setFixedSize(24, 24)
        self._search_prev_button.clicked.connect(self._on_search_previous)
        self._search_prev_button.setEnabled(False)
        navigation_layout.addWidget(self._search_prev_button)

        self._search_next_button = make_action_button(
            "▶", object_name="helpSearchNextButton", style_class="ghost",
            tooltip="Next match",
        )
        self._search_next_button.setFixedSize(24, 24)
        self._search_next_button.clicked.connect(self._on_search_next)
        self._search_next_button.setEnabled(False)
        navigation_layout.addWidget(self._search_next_button)

        navigation_layout.addStretch()

        self._search_hit_label = QLabel("0 of 0")
        self._search_hit_label.setObjectName("helpSearchHitLabel")
        navigation_layout.addWidget(self._search_hit_label)

        search_layout.addWidget(navigation_container)
        toc_layout.addWidget(search_container)

        # TOC list
        self._toc_list = QListWidget()
        self._toc_list.setObjectName("helpTocList")
        style_selectable_list(self._toc_list)
        self._toc_list.currentItemChanged.connect(self._on_toc_item_changed)
        toc_layout.addWidget(self._toc_list)

        content_layout.addWidget(toc_panel)

        # Right content area: Markdown rendered as HTML
        self._content_browser = QTextBrowser()
        self._content_browser.setObjectName("helpContentBrowser")
        self._content_browser.setOpenExternalLinks(True)
        content_layout.addWidget(self._content_browser)

        root_layout.addWidget(content_area)

    def _load_all_sections(self) -> None:
        """Load all help markdown files into memory."""
        for section_id, filename in _SECTION_FILE_MAP.items():
            content = _load_markdown(filename)
            if content is not None:
                self._sections[section_id] = content
                self._section_titles[section_id] = _extract_title_from_markdown(content)
            else:
                # Section file doesn't exist yet - skip it
                pass

        # If no sections loaded at all, add a placeholder
        if not self._sections:
            self._sections["placeholder"] = _PLACEHOLDER_CONTENT
            self._section_titles["placeholder"] = "Help"

    def _populate_toc(self) -> None:
        """Populate the table of contents list widget."""
        self._toc_list.clear()
        for section_id, title in self._section_titles.items():
            item = QListWidgetItem(title)
            item.setData(Qt.ItemDataRole.UserRole, section_id)
            size_list_item(item)
            self._toc_list.addItem(item)

        # Select the first item by default
        if self._toc_list.count() > 0:
            self._toc_list.setCurrentRow(0)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Intercept Enter/Return in the search field so the dialog does not accept."""
        if obj is self._search_input and event.type() == QEvent.Type.KeyPress:
            if isinstance(event, QKeyEvent) and event.key() in (_KEY_RETURN, _KEY_ENTER):
                self._on_search_next()
                return True
        return super().eventFilter(obj, event)

    def _on_toc_item_changed(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ) -> None:
        """Handle TOC selection change — display the selected section."""
        if current is None:
            return
        section_id = current.data(Qt.ItemDataRole.UserRole)
        self._display_section(section_id)

    def _display_section(self, section_id: str) -> None:
        """Render the given section's markdown content in the browser."""
        self._current_section = section_id
        content = self._sections.get(section_id, _PLACEHOLDER_CONTENT)

        # Use QTextBrowser's built-in markdown support (Qt 5.14+)
        self._content_browser.setMarkdown(content)
        _apply_block_spacing(self._content_browser.document())
        self._content_browser.setExtraSelections([])

    def _on_search_changed(self, text: str) -> None:
        """Perform search and filter TOC items based on search text."""
        self._search_query = text.lower().strip()
        self._current_hit_index = -1
        self._search_matches = []
        self._search_hit_count = 0

        # Update button and label states
        self._search_prev_button.setEnabled(False)
        self._search_next_button.setEnabled(False)
        self._search_hit_label.setText("0 of 0")

        if not self._search_query:
            # No search: show all TOC items
            for i in range(self._toc_list.count()):
                item = self._toc_list.item(i)
                if item is not None:
                    item.setHidden(False)
            self._content_browser.setExtraSelections([])
            return

        # Search mode: filter TOC and build hit list across sections
        for i in range(self._toc_list.count()):
            item = self._toc_list.item(i)
            if item is None:
                continue

            section_id = item.data(Qt.ItemDataRole.UserRole)
            title = self._section_titles.get(section_id, "")
            content = self._sections.get(section_id, "")
            content_lower = content.lower()

            is_match = (
                self._search_query in title.lower()
                or self._search_query in content_lower
            )
            item.setHidden(not is_match)

            if is_match:
                start = 0
                occurrence = 0
                while True:
                    found = content_lower.find(self._search_query, start)
                    if found == -1:
                        break
                    self._search_matches.append((section_id, occurrence))
                    occurrence += 1
                    start = found + len(self._search_query)

        self._search_hit_count = len(self._search_matches)
        if self._search_hit_count == 0:
            self._content_browser.setExtraSelections([])

        if self._search_hit_count > 0:
            self._goto_search_hit(0)

    def _goto_search_hit(self, hit_index: int) -> None:
        """Jump to and highlight a specific hit across sections."""
        if hit_index < 0 or hit_index >= self._search_hit_count:
            return

        self._current_hit_index = hit_index
        section_id, _ = self._search_matches[hit_index]

        # Select and display the target section
        for i in range(self._toc_list.count()):
            item = self._toc_list.item(i)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == section_id:
                self._toc_list.setCurrentItem(item)
                break

        self._display_section(section_id)
        self._highlight_current_hit()

    def _highlight_current_hit(self) -> None:
        """Highlight the current hit in the displayed section."""
        if self._current_hit_index < 0 or self._current_hit_index >= self._search_hit_count:
            return

        section_id, local_occurrence = self._search_matches[self._current_hit_index]
        if section_id != self._current_section:
            self._display_section(section_id)

        # Reset the browser cursor and search for the current hit in rendered text.
        browser_cursor = self._content_browser.textCursor()
        browser_cursor.movePosition(QTextCursor.MoveOperation.Start)
        self._content_browser.setTextCursor(browser_cursor)

        found = False
        for _ in range(local_occurrence + 1):
            found = self._content_browser.find(self._search_query)
            if not found:
                break

        if not found:
            self._content_browser.setExtraSelections([])
            return

        selection_cursor = self._content_browser.textCursor()
        highlight_color = QColor(ACCENT_COLOR)
        highlight_color.setAlpha(60)
        selection = QTextEdit.ExtraSelection()
        selection.cursor = selection_cursor
        selection.format.setBackground(highlight_color)

        self._content_browser.setExtraSelections([selection])

        # Collapse the actual cursor and ensure the found hit is visible.
        visible_cursor = QTextCursor(self._content_browser.document())
        visible_cursor.setPosition(selection_cursor.selectionEnd())
        self._content_browser.setTextCursor(visible_cursor)
        self._content_browser.ensureCursorVisible()

        self._search_hit_label.setText(f"{self._current_hit_index + 1} of {self._search_hit_count}")
        self._search_prev_button.setEnabled(self._search_hit_count > 1)
        self._search_next_button.setEnabled(self._search_hit_count > 1)

    def _on_search_next(self) -> None:
        """Navigate to the next search hit."""
        if self._search_hit_count <= 0:
            return

        next_index = (self._current_hit_index + 1) % self._search_hit_count
        self._goto_search_hit(next_index)

    def _on_search_previous(self) -> None:
        """Navigate to the previous search hit."""
        if self._search_hit_count <= 0:
            return

        prev_index = (self._current_hit_index - 1) % self._search_hit_count
        self._goto_search_hit(prev_index)

    def navigate_to_section(self, section_id: str) -> None:
        """Navigate to a specific help section by its ID.

        This is the main entry point for contextual help navigation.
        Called when the user clicks a '?' help icon or when help is opened
        from a specific wizard step context.

        Args:
            section_id: The section identifier (e.g. 'getting-started',
                'import-and-push', 'troubleshooting').
        """
        # If the section_id is a wizard step name, map it to a help section
        resolved_id = _STEP_SECTION_MAP.get(section_id, section_id)

        # Find and select the TOC item
        for i in range(self._toc_list.count()):
            item = self._toc_list.item(i)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == resolved_id:
                self._toc_list.setCurrentItem(item)
                return

        # If section not found in TOC, try to display directly
        if resolved_id in self._sections:
            self._display_section(resolved_id)

    @property
    def section_count(self) -> int:
        """Return the number of loaded help sections."""
        return len(self._sections)
