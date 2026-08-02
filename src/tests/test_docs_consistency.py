"""Regression guard: documentation must not drift the way it did before.

Each assertion here corresponds to a drift class actually found during the
2026-07-28 codebase review: a smoke_test_issues.md row left on the
"(pending commit)" placeholder after its real fix commit landed (#244),
investigation-narrative phrasing creeping into wiim_api_notes.md's spec, and
WiiM/LinkPlay app-internals references leaking into checked-in docs. See
scripts/check_docs_consistency.py for the full rationale.

docs/qa_signoff.md is intentionally out of scope -- see that script's
module docstring.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))

from check_docs_consistency import (  # type: ignore[import-not-found]
    _fix_commits_by_issue,
    find_app_internals_references,
    find_banned_phrasing,
    find_stale_pending_commits,
)


def test_no_stale_pending_commit_placeholders() -> None:
    """A FIXED row's Fix Commit column must be backfilled once the commit exists."""
    violations = find_stale_pending_commits()

    assert not violations, (
        "smoke_test_issues.md row(s) still show '(pending commit)' though the "
        "real fix commit already exists:\n" + "\n".join(violations)
    )


def test_wiim_api_notes_has_no_investigation_narrative() -> None:
    """wiim_api_notes.md is a spec; investigation history belongs in corrections.md."""
    violations = find_banned_phrasing()

    assert not violations, (
        "wiim_api_notes.md contains investigation-narrative phrasing that "
        "belongs in docs/corrections.md instead:\n" + "\n".join(violations)
    )


def test_docs_have_no_app_internals_references() -> None:
    """No decompiled class/method names, smali paths, or APK contents in docs/."""
    violations = find_app_internals_references()

    assert not violations, (
        "Doc(s) reference WiiM/LinkPlay app internals, which CLAUDE.md bans "
        "outright:\n" + "\n".join(violations)
    )


def test_fix_commit_lookup_finds_combined_issue_commits() -> None:
    """A commit fixing several issues at once ("Fix #241/#242: ...") must be
    found when looking up either issue number individually -- this repo's own
    history already uses that convention, and an earlier version of the lookup
    only matched a single anchored issue number and silently missed it."""
    fix_commits = _fix_commits_by_issue()

    assert fix_commits.get("241") is not None
    assert fix_commits.get("241") == fix_commits.get("242")
