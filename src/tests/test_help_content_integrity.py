"""Content-integrity tests for the in-app user guide (src/gui/assets/help/).

These check help text against the same source of truth the UI itself uses --
button labels, numeric limits, keyboard shortcuts, Settings section names --
rather than full prose correctness. The point is to catch the exact failure
mode found during a documentation-accuracy audit (smoke #241/#242): help
text hardcodes a string that already exists as a named constant or literal
elsewhere in the code, and the two independently drift apart. Nothing here
proves the guide is *well written*, only that specific, checkable claims
still match reality.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.gui.views.my_presets_view import _SEARCH_THRESHOLD
from src.models.constants import DEFAULT_MAX_BANDS
from src.utils.device_name import DEVICE_NAME_RULE_TEXT

_GUI_ROOT = Path(__file__).resolve().parents[1] / "gui"
_HELP_DIR = _GUI_ROOT / "assets" / "help"
_MAIN_WINDOW_PY = _GUI_ROOT / "main_window.py"
_SETTINGS_VIEW_PY = _GUI_ROOT / "views" / "settings_view.py"

_HELP_FILES = sorted(_HELP_DIR.glob("*.md"))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


_WHITESPACE_RE = re.compile(r"\s+")


def _unwrapped(text: str) -> str:
    """Collapse whitespace runs (including the newlines from this project's
    hard-wrapped markdown) to single spaces, so a substring/regex check
    isn't fooled by a phrase that happens to cross a line-wrap boundary --
    markdown renders that as one continuous phrase either way."""
    return _WHITESPACE_RE.sub(" ", text)


def _help_text(filename: str) -> str:
    """Unwrapped text of one help file -- for substring/regex checks against
    prose. Use _read() directly instead when line structure matters (e.g.
    heading detection)."""
    return _unwrapped(_read(_HELP_DIR / filename))


def _all_help_text() -> str:
    return " ".join(_help_text(p.name) for p in _HELP_FILES)


# ---------------------------------------------------------------------------
# 1. Button/action labels -- help text must quote the CURRENT label of the
#    button it's describing, not whatever it was called when the guide was
#    written. Extracted by a balanced-paren scan of every
#    make_action_button(...) call site rather than hardcoding the labels a
#    second time here, so a future rename is caught automatically.
# ---------------------------------------------------------------------------


def _find_balanced_call(text: str, open_paren_index: int) -> str:
    """Return the text between the '(' at open_paren_index and its match.

    A simple depth counter, not a regex -- make_action_button(...) calls
    span multiple lines with keyword args in varying order, which a
    single-line regex can't reliably bound.
    """
    depth = 1
    i = open_paren_index + 1
    while depth > 0:
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
        i += 1
    return text[open_paren_index + 1 : i - 1]


def _scan_action_button_labels() -> dict[str, str]:
    """Map object_name -> label text for every make_action_button(...) call
    under src/gui/ (label is always the first positional string argument;
    object_name is a keyword argument in the same call)."""
    label_re = re.compile(r'^\s*f?"((?:[^"\\]|\\.)*)"')
    object_name_re = re.compile(r'object_name=f?"((?:[^"\\]|\\.)*)"')
    labels: dict[str, str] = {}
    for path in _GUI_ROOT.rglob("*.py"):
        text = _read(path)
        for m in re.finditer(r"make_action_button\(", text):
            args = _find_balanced_call(text, m.end() - 1)
            label_m = label_re.match(args)
            name_m = object_name_re.search(args)
            if label_m and name_m:
                labels[name_m.group(1)] = label_m.group(1)
    return labels


_ACTION_BUTTON_LABELS = _scan_action_button_labels()

# (help markdown filename, make_action_button object_name it describes).
# Not exhaustive -- just the button references this guide currently makes.
_BUTTON_LABEL_REFERENCES = [
    ("managing_presets.md", "btn_load_into_editor"),
    ("managing_presets.md", "btn_copy_device_local"),
    ("managing_presets.md", "btn_duplicate_preset"),
    ("managing_presets.md", "btn_rename_preset"),
    ("managing_presets.md", "btn_delete_preset_local"),
    ("import_and_push.md", "PushPageShowFiltersButton"),
    ("import_and_push.md", "PushPageUndoButton"),
    ("import_and_push.md", "PushPageExportLink"),
    ("import_and_push.md", "PushPageSavePresetLink"),
    ("import_and_push.md", "ReviewPagePushButton"),
    ("using_roomfit.md", "btn_copy_device"),
]


def test_action_button_scan_found_buttons() -> None:
    """Sanity check on the scanner itself -- if this drops to 0, the regex
    broke (e.g. make_action_button's call shape changed), and every
    parametrized case below would misleadingly report "label not found"."""
    assert len(_ACTION_BUTTON_LABELS) > 40


@pytest.mark.parametrize("help_filename,object_name", _BUTTON_LABEL_REFERENCES)
def test_help_button_label_matches_source(help_filename: str, object_name: str) -> None:
    label = _ACTION_BUTTON_LABELS.get(object_name)
    assert label is not None, (
        f"{object_name!r} not found by the make_action_button() scan -- "
        f"either it was renamed/removed, or the scan regex needs updating"
    )
    text = _help_text(help_filename)
    assert f'"{label}"' in text or f"**{label}**" in text, (
        f"{help_filename} does not quote the current button label {label!r} "
        f"for {object_name!r} (as \"{label}\" or **{label}**)"
    )


# ---------------------------------------------------------------------------
# 2. Numeric limits -- guide prose must agree with the actual constants.
# ---------------------------------------------------------------------------


def test_help_max_bands_matches_constant() -> None:
    text = _help_text("troubleshooting.md")
    assert f"up to {DEFAULT_MAX_BANDS} PEQ bands" in text, (
        f"troubleshooting.md's band-limit text doesn't match "
        f"DEFAULT_MAX_BANDS={DEFAULT_MAX_BANDS}"
    )


def test_help_search_threshold_matches_constant() -> None:
    text = _help_text("managing_presets.md")
    assert f"more than {_SEARCH_THRESHOLD} presets" in text, (
        f"managing_presets.md's search-box threshold text doesn't match "
        f"MyPresetsView._SEARCH_THRESHOLD={_SEARCH_THRESHOLD}"
    )


# ---------------------------------------------------------------------------
# 3. Device naming rule -- must agree with DEVICE_NAME_RULE_TEXT, the single
#    source of truth sanitize_device_name()/has_invalid_device_name_chars()
#    are built from.
# ---------------------------------------------------------------------------

_NAME_RULE_TOKENS = [t.strip() for t in DEVICE_NAME_RULE_TEXT.replace(" and ", ", ").split(", ")]


@pytest.mark.parametrize("help_filename", ["managing_presets.md", "using_roomfit.md"])
def test_help_device_name_rule_matches_constant(help_filename: str) -> None:
    text = _help_text(help_filename)
    missing = [tok for tok in _NAME_RULE_TOKENS if tok not in text]
    assert not missing, (
        f"{help_filename} is missing {missing!r} from the device naming rule "
        f"(DEVICE_NAME_RULE_TEXT={DEVICE_NAME_RULE_TEXT!r})"
    )


# ---------------------------------------------------------------------------
# 4. Keyboard shortcuts -- every shortcut MainWindow actually registers must
#    have a row in getting_started.md's table.
# ---------------------------------------------------------------------------

_SHORTCUT_REGISTRATION_RE = re.compile(
    r'\.setShortcut\("([^"]+)"\)|QShortcut\(QKeySequence\("([^"]+)"\)'
)
# Qt's QKeySequence name vs. the label most users associate with the key --
# the guide intentionally uses the human label, not Qt's internal name.
_QT_KEY_ALIASES = {"Return": "Enter"}


def _scan_registered_shortcuts() -> set[str]:
    text = _read(_MAIN_WINDOW_PY)
    return {(m.group(1) or m.group(2)) for m in _SHORTCUT_REGISTRATION_RE.finditer(text)}


def _humanize_shortcut(qt_key_sequence: str) -> str:
    return "+".join(_QT_KEY_ALIASES.get(p, p) for p in qt_key_sequence.split("+"))


def test_shortcut_scan_found_shortcuts() -> None:
    """Sanity check on the scanner -- guards against a silently-passing
    empty parametrization if MainWindow's shortcut registration pattern
    ever changes shape."""
    assert len(_scan_registered_shortcuts()) >= 4


def test_help_documents_every_registered_shortcut() -> None:
    registered = _scan_registered_shortcuts()
    guide_text = _help_text("getting_started.md")
    missing = sorted(
        s for s in registered if f"`{_humanize_shortcut(s)}`" not in guide_text
    )
    assert not missing, (
        f"MainWindow registers shortcut(s) {missing} that getting_started.md's "
        f"Keyboard Shortcuts table doesn't document"
    )


# ---------------------------------------------------------------------------
# 5. Settings section references -- "Settings > X" / 'Settings under "X"'
#    must name a section that actually exists in SettingsView. This is the
#    direct regression guard for smoke #241: the critical-failure screen
#    used to point at a "Settings > Restore from Backup" that was never built.
# ---------------------------------------------------------------------------

_SETTINGS_GT_RE = re.compile(r"Settings\s*>\s*([A-Za-z]+)")
_SETTINGS_UNDER_RE = re.compile(r'Settings under "([^"]+)"')
_GROUP_BOX_RE = re.compile(r'QGroupBox\("([^"]+)"')


def _scan_settings_sections() -> set[str]:
    return set(_GROUP_BOX_RE.findall(_read(_SETTINGS_VIEW_PY)))


def test_settings_section_scan_found_sections() -> None:
    assert len(_scan_settings_sections()) >= 3


def test_help_settings_references_are_real_sections() -> None:
    sections = _scan_settings_sections()
    text = _all_help_text()
    referenced = set(_SETTINGS_GT_RE.findall(text)) | set(_SETTINGS_UNDER_RE.findall(text))
    assert referenced, "no 'Settings > X' / 'Settings under \"X\"' references found to check"
    missing = sorted(referenced - sections)
    assert not missing, (
        f"Help text references Settings section(s) {missing} that don't exist "
        f"in SettingsView (real sections: {sorted(sections)})"
    )


# ---------------------------------------------------------------------------
# 6. Markdown structural sanity + cross-file section references.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", _HELP_FILES, ids=lambda p: p.name)
def test_help_file_has_exactly_one_h1(path: Path) -> None:
    lines = _read(path).splitlines()
    h1_lines = [line for line in lines if line.startswith("# ")]
    assert len(h1_lines) == 1, f"{path.name} has {len(h1_lines)} H1 headings, expected 1"
    non_empty = next(line for line in lines if line.strip())
    assert non_empty.startswith("# "), f"{path.name}'s first content line isn't its H1"


@pytest.mark.parametrize("path", _HELP_FILES, ids=lambda p: p.name)
def test_help_file_is_not_empty(path: Path) -> None:
    assert len(_read(path).strip()) > 100, f"{path.name} looks suspiciously short/empty"


def _scan_all_headings() -> set[str]:
    heading_re = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
    headings: set[str] = set()
    for path in _HELP_FILES:
        headings.update(heading_re.findall(_read(path)))
    return headings


# Matches the two cross-reference phrasings used across these guides, e.g.
# `see "Backup Files" in the Troubleshooting section` and
# `"Multi-Source Push" in the Import & Push section`.
_QUOTED_SECTION_REF_RE = re.compile(r'"([A-Z][^"\n]{2,60})"\s+in the [\w &]+ section')


def test_help_quoted_section_cross_references_resolve() -> None:
    headings = _scan_all_headings()
    assert headings, "no headings scanned -- heading regex likely stale"
    text = _all_help_text()
    referenced = set(_QUOTED_SECTION_REF_RE.findall(text))
    assert referenced, "no quoted 'X in the Y section' cross-references found to check"
    missing = sorted(referenced - headings)
    assert not missing, (
        f"Help text cross-references section(s) {missing} by name, but no "
        f"heading with that exact text exists in any help file"
    )
