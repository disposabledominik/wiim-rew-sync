"""Unit tests for ImportDialog (REW EQ file preview and validation).

Tests preview-table population, over-limit warning gating, the
acknowledgement checkbox -> Accept button wiring, and the theme-aware
over-limit row highlight color. Bypasses QFileDialog by calling the
private ``_load_and_parse`` helper directly, matching the mocking
convention used in test_gui_filter_handlers.py.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import Qt

from src.gui.dialogs.import_dialog import ImportDialog, _warning_highlight_color
from src.models.canonical import CanonicalFilter
from src.models.errors import ParseError


def _make_filter(freq: float) -> CanonicalFilter:
    return CanonicalFilter(type="PEAK", frequency_hz=freq, gain_db=3.0, q=1.0)


# ---------------------------------------------------------------------------
# Successful parse
# ---------------------------------------------------------------------------


class TestImportDialogHappyPath:
    """Preview table population when parsing succeeds."""

    def test_populates_table_with_parsed_filters(self, qtbot) -> None:
        filters = [_make_filter(100.0), _make_filter(200.0)]
        dialog = ImportDialog(max_filters=10)
        qtbot.addWidget(dialog)

        with patch(
            "src.translator.rew_parser.REWParser.parse_file_with_warnings",
            return_value=(filters, []),
        ):
            dialog._load_and_parse(Path("/fake/path/eq.txt"))

        assert dialog._table.rowCount() == 2
        assert dialog._accept_button is not None
        assert dialog._accept_button.isEnabled()

    def test_no_filters_keeps_accept_disabled(self, qtbot) -> None:
        dialog = ImportDialog(max_filters=10)
        qtbot.addWidget(dialog)

        with patch(
            "src.translator.rew_parser.REWParser.parse_file_with_warnings",
            return_value=([], []),
        ):
            dialog._load_and_parse(Path("/fake/path/eq.txt"))

        assert dialog._accept_button is not None
        assert not dialog._accept_button.isEnabled()


# ---------------------------------------------------------------------------
# Parse errors
# ---------------------------------------------------------------------------


class TestImportDialogErrors:
    """Error label and disabled Accept on parse failure."""

    def test_parse_error_shows_error_label(self, qtbot) -> None:
        dialog = ImportDialog(max_filters=10)
        qtbot.addWidget(dialog)

        with patch(
            "src.translator.rew_parser.REWParser.parse_file_with_warnings",
            side_effect=ParseError("malformed file"),
        ):
            result = dialog._load_and_parse(Path("/fake/path/bad.txt"))

        assert result is False
        assert not dialog._error_label.isHidden()
        assert "malformed file" in dialog._error_label.text()
        assert dialog._accept_button is not None
        assert not dialog._accept_button.isEnabled()


# ---------------------------------------------------------------------------
# Over-limit warning + acknowledgement gating
# ---------------------------------------------------------------------------


class TestImportDialogOverLimit:
    """Over-limit banner and ack-checkbox -> Accept button wiring."""

    def test_over_limit_shows_warning_banner_and_blocks_accept(self, qtbot) -> None:
        filters = [_make_filter(100.0 + i) for i in range(12)]
        dialog = ImportDialog(max_filters=10)
        qtbot.addWidget(dialog)

        with patch(
            "src.translator.rew_parser.REWParser.parse_file_with_warnings",
            return_value=(filters, []),
        ):
            dialog._load_and_parse(Path("/fake/path/eq.txt"))

        assert not dialog._warning_banner.isHidden()
        assert "12" in dialog._warning_text.text()
        assert dialog._accept_button is not None
        assert not dialog._accept_button.isEnabled()

    def test_acknowledging_warning_enables_accept(self, qtbot) -> None:
        filters = [_make_filter(100.0 + i) for i in range(12)]
        dialog = ImportDialog(max_filters=10)
        qtbot.addWidget(dialog)

        with patch(
            "src.translator.rew_parser.REWParser.parse_file_with_warnings",
            return_value=(filters, []),
        ):
            dialog._load_and_parse(Path("/fake/path/eq.txt"))

        dialog._ack_checkbox.setCheckState(Qt.CheckState.Checked)

        assert dialog._accept_button is not None
        assert dialog._accept_button.isEnabled()

    def test_within_limit_hides_warning_banner(self, qtbot) -> None:
        filters = [_make_filter(100.0), _make_filter(200.0)]
        dialog = ImportDialog(max_filters=10)
        qtbot.addWidget(dialog)

        with patch(
            "src.translator.rew_parser.REWParser.parse_file_with_warnings",
            return_value=(filters, []),
        ):
            dialog._load_and_parse(Path("/fake/path/eq.txt"))

        assert dialog._warning_banner.isHidden()


# ---------------------------------------------------------------------------
# get_accepted_filters
# ---------------------------------------------------------------------------


class TestImportDialogAcceptedFilters:
    """get_accepted_filters() reflects the dialog's accept/reject result."""

    def test_returns_filters_when_accepted(self, qtbot) -> None:
        filters = [_make_filter(100.0)]
        dialog = ImportDialog(max_filters=10)
        qtbot.addWidget(dialog)

        with patch(
            "src.translator.rew_parser.REWParser.parse_file_with_warnings",
            return_value=(filters, []),
        ):
            dialog._load_and_parse(Path("/fake/path/eq.txt"))

        dialog.accept()

        assert dialog.get_accepted_filters() == filters

    def test_returns_none_when_rejected(self, qtbot) -> None:
        filters = [_make_filter(100.0)]
        dialog = ImportDialog(max_filters=10)
        qtbot.addWidget(dialog)

        with patch(
            "src.translator.rew_parser.REWParser.parse_file_with_warnings",
            return_value=(filters, []),
        ):
            dialog._load_and_parse(Path("/fake/path/eq.txt"))

        dialog.reject()

        assert dialog.get_accepted_filters() is None


# ---------------------------------------------------------------------------
# Theme-aware warning highlight color (regression: previously hardcoded
# orange regardless of active theme -- see _WARNING_ORANGE removal)
# ---------------------------------------------------------------------------


class TestWarningHighlightColor:
    """The over-limit row highlight must follow the active theme."""

    def test_uses_dark_warning_color_in_dark_theme(self) -> None:
        with patch(
            "src.gui.dialogs.import_dialog.get_active_theme", return_value="dark"
        ):
            color = _warning_highlight_color()

        assert color.name() == "#ffa726"

    def test_uses_light_warning_color_in_light_theme(self) -> None:
        with patch(
            "src.gui.dialogs.import_dialog.get_active_theme", return_value="light"
        ):
            color = _warning_highlight_color()

        assert color.name() == "#f57c00"

    def test_highlight_is_translucent(self) -> None:
        with patch(
            "src.gui.dialogs.import_dialog.get_active_theme", return_value="dark"
        ):
            color = _warning_highlight_color()

        assert color.alpha() == 80
