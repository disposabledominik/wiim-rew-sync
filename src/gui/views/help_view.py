"""In-app user guide with contextual navigation.

Displays bundled Markdown help content from assets/help/ as a side panel
overlay. Features a searchable table of contents sidebar and contextual
navigation (auto-navigate to relevant section based on current wizard step).

Requirements: 27.1, 27.2, 27.3, 27.4, 27.5, 27.6, 27.7, 27.8, 27.9, 27.10.
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from src.gui.constants import (
    ACCENT_COLOR,
    FONT_SIZE_BODY,
    FONT_SIZE_CAPTION,
    FONT_SIZE_HEADING,
    SPACING_MD,
    SPACING_SM,
    SPACING_XS,
)

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

    Tries importlib.resources first (for installed packages), then falls
    back to file-system relative path (for development).
    """
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
        section_changed: Emitted with the section_id when navigation occurs.
    """

    close_requested = Signal()
    section_changed = Signal(str)

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
        header.setStyleSheet(
            f"QFrame#helpHeader {{"
            f"  border-bottom: 1px solid #E0E0E0;"
            f"  padding: {SPACING_SM}px;"
            f"}}"
        )
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(SPACING_MD, SPACING_SM, SPACING_SM, SPACING_SM)

        title_label = QLabel("User Guide")
        title_label.setStyleSheet(
            f"font-size: {FONT_SIZE_HEADING}px; font-weight: 600;"
        )
        header_layout.addWidget(title_label)
        header_layout.addStretch()

        self._close_button = QPushButton("\u2715")  # Unicode X
        self._close_button.setObjectName("helpCloseButton")
        self._close_button.setFixedSize(28, 28)
        self._close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_button.setStyleSheet(
            "QPushButton {"
            "  border: none;"
            "  border-radius: 4px;"
            "  font-size: 14px;"
            "  background: transparent;"
            "}"
            "QPushButton:hover {"
            "  background: #E0E0E0;"
            "}"
        )
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
        toc_panel.setStyleSheet(
            "QFrame#helpTocPanel {"
            "  border-right: 1px solid #E0E0E0;"
            "}"
        )
        toc_layout = QVBoxLayout(toc_panel)
        toc_layout.setContentsMargins(SPACING_SM, SPACING_SM, SPACING_SM, SPACING_SM)
        toc_layout.setSpacing(SPACING_XS)

        # Search input
        self._search_input = QLineEdit()
        self._search_input.setObjectName("helpSearchInput")
        self._search_input.setPlaceholderText("Search topics...")
        self._search_input.setClearButtonEnabled(True)
        self._search_input.setStyleSheet(
            f"QLineEdit {{"
            f"  padding: {SPACING_XS}px {SPACING_SM}px;"
            f"  border: 1px solid #E0E0E0;"
            f"  border-radius: 4px;"
            f"  font-size: {FONT_SIZE_CAPTION}px;"
            f"}}"
        )
        self._search_input.textChanged.connect(self._on_search_changed)
        toc_layout.addWidget(self._search_input)

        # TOC list
        self._toc_list = QListWidget()
        self._toc_list.setObjectName("helpTocList")
        self._toc_list.setStyleSheet(
            f"QListWidget {{"
            f"  border: none;"
            f"  font-size: {FONT_SIZE_BODY}px;"
            f"}}"
            f"QListWidget::item {{"
            f"  padding: {SPACING_XS}px {SPACING_SM}px;"
            f"  border-radius: 3px;"
            f"}}"
            f"QListWidget::item:selected {{"
            f"  background: {ACCENT_COLOR};"
            f"  color: white;"
            f"}}"
        )
        self._toc_list.currentItemChanged.connect(self._on_toc_item_changed)
        toc_layout.addWidget(self._toc_list)

        content_layout.addWidget(toc_panel)

        # Right content area: Markdown rendered as HTML
        self._content_browser = QTextBrowser()
        self._content_browser.setObjectName("helpContentBrowser")
        self._content_browser.setOpenExternalLinks(True)
        self._content_browser.setStyleSheet(
            f"QTextBrowser {{"
            f"  border: none;"
            f"  padding: {SPACING_MD}px;"
            f"  font-size: {FONT_SIZE_BODY}px;"
            f"}}"
        )
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
            self._toc_list.addItem(item)

        # Select the first item by default
        if self._toc_list.count() > 0:
            self._toc_list.setCurrentRow(0)

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
        self.section_changed.emit(section_id)

    def _on_search_changed(self, text: str) -> None:
        """Filter TOC items based on search text."""
        search_lower = text.lower().strip()

        for i in range(self._toc_list.count()):
            item = self._toc_list.item(i)
            if item is None:
                continue

            if not search_lower:
                item.setHidden(False)
            else:
                section_id = item.data(Qt.ItemDataRole.UserRole)
                title = self._section_titles.get(section_id, "")
                # Search in title and content
                content = self._sections.get(section_id, "")
                visible = (
                    search_lower in title.lower()
                    or search_lower in content.lower()
                )
                item.setHidden(not visible)

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

    def navigate_for_step(self, step_value: str) -> None:
        """Auto-navigate to the help section relevant to a wizard step.

        Args:
            step_value: The WizardStep enum value (e.g. 'connect', 'filters').
        """
        section_id = _STEP_SECTION_MAP.get(step_value)
        if section_id:
            self.navigate_to_section(section_id)

    @property
    def current_section(self) -> str | None:
        """Return the currently displayed section ID, or None."""
        return self._current_section

    @property
    def section_count(self) -> int:
        """Return the number of loaded help sections."""
        return len(self._sections)

    @property
    def visible_toc_count(self) -> int:
        """Return the number of currently visible (not hidden) TOC items."""
        count = 0
        for i in range(self._toc_list.count()):
            item = self._toc_list.item(i)
            if item is not None and not item.isHidden():
                count += 1
        return count
