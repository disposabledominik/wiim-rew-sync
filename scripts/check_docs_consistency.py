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
import shutil
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

# Matches a "Fix #<N>" or combined "Fix #<N>/#<M>" commit-subject prefix, e.g.
# "Fix #244: ..." or "Fix #241/#242: ...". Only the text up to the first colon
# is treated as issue references, so mentions of numbers later in the subject
# don't get misread as additional fixed issues.
_FIX_PREFIX_RE = re.compile(r"^Fix ((?:#\d+[/,]?\s*)+):")

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


def _git_fix_commit_for_issue(issue_num: str) -> str | None:
    """Return the short hash of the commit whose message starts with `Fix #<issue_num>`, if any.

    Also matches commits that fix several issues together, e.g.
    `Fix #241/#242: ...` (an established convention in this repo's history).
    Bounded to history reachable from HEAD, not `--all` refs, so a `Fix #<N>`
    commit sitting only on some other local/remote branch can't be mistaken
    for one that's actually landed.
    """
    git = shutil.which("git")
    if git is None:
        return None
    try:
        # All args are static; `git` is resolved via shutil.which(), not
        # user input.
        result = subprocess.run(  # noqa: S603
            [git, "log", "HEAD", "--oneline", "--grep", r"^Fix #[0-9]", "-E"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    for line in result.stdout.strip().splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        commit_hash, subject = parts
        match = _FIX_PREFIX_RE.match(subject)
        if not match:
            continue
        if issue_num in set(re.findall(r"\d+", match.group(1))):
            return commit_hash
    return None


def find_stale_pending_commits() -> list[str]:
    """Rows marked FIXED with a '(pending commit)' placeholder whose real fix commit exists."""
    violations: list[str] = []
    if not _SMOKE_TEST_ISSUES.exists():
        return violations
    text = _SMOKE_TEST_ISSUES.read_text(encoding="utf-8")
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = _ROW_RE.match(line)
        if not match:
            continue
        issue_num, rest = match.group(1), match.group(2)
        if "(pending commit)" not in rest or "FIXED" not in rest:
            continue
        real_hash = _git_fix_commit_for_issue(issue_num)
        if real_hash:
            violations.append(
                f"docs/smoke_test_issues.md:{lineno}: row #{issue_num} is FIXED with a "
                f"'(pending commit)' placeholder, but {real_hash} already fixes it "
                f"(commit message starts with 'Fix #{issue_num}') -- backfill the hash."
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
                    f"({phrase!r}) -- state the current rule, point at docs/corrections.md."
                )
    return violations


def find_app_internals_references() -> list[str]:
    """No WiiM/LinkPlay app internals (decompiled names, smali, APK contents) in any doc."""
    violations: list[str] = []
    for path in sorted(_DOCS_DIR.rglob("*.md")):
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
