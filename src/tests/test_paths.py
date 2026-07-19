"""Tests for src.utils.paths.ensure_suffix."""

from __future__ import annotations

from pathlib import Path

from src.utils.paths import ensure_suffix


def test_ensure_suffix_appends_when_missing() -> None:
    assert ensure_suffix(Path("foo"), ".txt") == Path("foo.txt")


def test_ensure_suffix_does_not_double_extension_on_case_mismatch() -> None:
    """A pre-existing suffix that only differs in case is left alone, not
    doubled up (the bug the old `path.lower().endswith(...)` + `+=` string
    style produced, e.g. foo.TXT.txt)."""
    assert ensure_suffix(Path("foo.TXT"), ".txt") == Path("foo.TXT")


def test_ensure_suffix_is_idempotent() -> None:
    assert ensure_suffix(Path("foo.txt"), ".txt") == Path("foo.txt")


def test_ensure_suffix_replaces_a_different_suffix() -> None:
    assert ensure_suffix(Path("foo.csv"), ".txt") == Path("foo.txt")
