#!/usr/bin/env python3
"""Guard against the documentation drift patterns found in the 2026-07-28 review.

Three checks, each catching a drift class that actually slipped through review
before:

1. A `docs/smoke_test_issues.md` row marked `FIXED` but still showing the
   `(pending commit)` placeholder, when the real fix commit already exists in
   git history (message starting with `Fix #<N>`) -- the #244 bug this script
   was written alongside: the row was never backfilled once the commit landed.
2. Investigation-narrative phrasing in `docs/wiim_api_notes.md`, which
   CLAUDE.md requires to stay a spec ("state the current rule, point at
   docs/corrections.md") rather than restating the "previously believed X,
   revised to Y" history that belongs in corrections.md.
3. References to WiiM/LinkPlay app internals (decompiled names, smali, APK
   contents) anywhere in docs/ -- CLAUDE.md bans these outright.

`docs/qa_signoff.md` is intentionally excluded from all three checks here: it's
a point-in-time sign-off snapshot still under active iteration, and syncing it
against the live issue ledger is a manual, one-off concern for now rather than
an automatable rule.

Usage:
    python3 scripts/check_docs_consistency.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DOCS_DIR = _REPO_ROOT / "docs"
_SMOKE_TEST_ISSUES = _DOCS_DIR / "smoke_test_issues.md"
_WIIM_API_NOTES = _DOCS_DIR / "wiim_api_notes.md"

# Docs exempt from these checks. qa_signoff.md is WIP and synced manually for now.
_EXCLUDED_DOCS = {"qa_signoff.md"}

_ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|(.*)$")

# CLAUDE.md: wiim_api_notes.md "should only ever point at [corrections.md],
# never restate it" -- these phrases are the restatement tell.
_BANNED_NARRATIVE_PHRASES = (
    "previously believed",
    "previously thought",
    "originally thought",
    "originally believed",
    "used to think",
    "revised to",
)

# CLAUDE.md: "no decompiled class/method names, smali paths, APK contents,
# or app UI/architecture" in checked-in docs.
_BANNED_APP_INTERNALS = (
    "smali",
    "decompil",  # decompile / decompiled / decompiling
    ".apk",
    "apktool",
)


_FIX_SUBJECT_RE = re.compile(r"^Fix\s+((?:#\d+[/,]?\s*)+)", re.IGNORECASE)


def _issue_numbers_from_subject(subject: str) -> set[str]:
    """Extract every issue number from a 'Fix #241/#242: ...'-style commit subject line."""
    match = _FIX_SUBJECT_RE.match(subject)
    if not match:
        return set()
    return set(re.findall(r"\d+", match.group(1)))


def _fix_commits_by_issue() -> dict[str, str]:
    """Map each issue number to the short hash of the (first, oldest) commit whose subject fixes it.

    Scoped to history reachable from the current checkout (not `--all`), and matched against the
    commit *subject* line only -- `git log --grep` otherwise matches anywhere in the full message,
    which would also catch a later commit merely quoting/discussing an earlier "Fix #N" subject.
    Raises on subprocess failure rather than swallowing it: a broken git environment must fail this
    check loudly, not silently report "no violations found".
    """
    result = subprocess.run(
        ["git", "log", "--format=%h%x1f%s"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    mapping: dict[str, str] = {}
    for line in result.stdout.splitlines():
        commit_hash, _, subject = line.partition("\x1f")
        for issue_num in _issue_numbers_from_subject(subject):
            mapping.setdefault(issue_num, commit_hash)
    return mapping


def find_stale_pending_commits() -> list[str]:
    """Rows marked FIXED with a '(pending commit)' placeholder whose real fix commit already exists."""
    violations: list[str] = []
    if not _SMOKE_TEST_ISSUES.exists():
        return violations
    text = _SMOKE_TEST_ISSUES.read_text(encoding="utf-8")
    fix_commits = _fix_commits_by_issue()
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = _ROW_RE.match(line)
        if not match:
            continue
        issue_num, rest = match.group(1), match.group(2)
        # Columns are `Issue | Status | Test | Fix Commit | Notes | Test Reference`; `rest` starts
        # right after the Issue column's closing pipe, so index 1 is Status and 3 is Fix Commit.
        fields = rest.split("|")
        status = fields[1].strip() if len(fields) > 1 else ""
        fix_commit_cell = fields[3].strip() if len(fields) > 3 else ""
        if status != "FIXED" or "(pending commit)" not in fix_commit_cell:
            continue
        real_hash = fix_commits.get(issue_num)
        if real_hash:
            violations.append(
                f"docs/smoke_test_issues.md:{lineno}: row #{issue_num} is FIXED with a "
                f"'(pending commit)' placeholder, but {real_hash} already fixes it "
                f"(commit subject starts with 'Fix #{issue_num}') -- backfill the hash."
            )
    return violations


def find_banned_phrasing() -> list[str]:
    """wiim_api_notes.md must be a spec, not a lab notebook (CLAUDE.md rule)."""
    violations: list[str] = []
    if not _WIIM_API_NOTES.exists():
        return violations
    text = _WIIM_API_NOTES.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        lower = line.lower()
        for phrase in _BANNED_NARRATIVE_PHRASES:
            if phrase in lower:
                violations.append(
                    f"docs/wiim_api_notes.md:{lineno}: investigation-narrative phrasing "
                    f"({phrase!r}) -- state the current rule and point at docs/corrections.md instead."
                )
    return violations


_HELP_DOCS_DIR = _REPO_ROOT / "src" / "gui" / "assets" / "help"


def find_app_internals_references() -> list[str]:
    """No WiiM/LinkPlay app internals (decompiled names, smali, APK contents) in any doc.

    Scans docs/ recursively (not just its top level) plus src/gui/assets/help/ -- the latter is
    bundled into and shown by the packaged app, so a leak there would ship straight to end users.
    """
    violations: list[str] = []
    paths = sorted(_DOCS_DIR.rglob("*.md")) + sorted(_HELP_DOCS_DIR.glob("*.md"))
    for path in paths:
        if path.name in _EXCLUDED_DOCS:
            continue
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            lower = line.lower()
            for token in _BANNED_APP_INTERNALS:
                if token in lower:
                    rel = path.relative_to(_REPO_ROOT)
                    violations.append(f"{rel}:{lineno}: references app internals ({token!r})")
    return violations


def find_violations() -> list[str]:
    """Return every documentation-drift violation found, across all three checks."""
    return (
        find_stale_pending_commits()
        + find_banned_phrasing()
        + find_app_internals_references()
    )


def main() -> int:
    violations = find_violations()
    if not violations:
        print("OK: no documentation drift patterns found.")
        return 0

    print("error: documentation drift found:", file=sys.stderr)
    for violation in violations:
        print(f"  {violation}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
