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


def test_ensure_suffix_appends_after_a_different_suffix() -> None:
    """A pre-existing, different suffix is not replaced -- it's kept, with the
    target suffix appended. Losing information (e.g. that the file was a
    .csv) is preferable to Path.with_suffix()'s silent truncation below."""
    assert ensure_suffix(Path("foo.csv"), ".txt") == Path("foo.csv.txt")


def test_ensure_suffix_never_truncates_a_name_containing_an_unrelated_dot() -> None:
    """A version-number-style dot in a user-typed filename must never be
    silently dropped -- this is the regression Path.with_suffix() caused:
    Path("Living Room v1.2").with_suffix(".txt") == Path("Living Room v1.txt"),
    silently discarding the ".2"."""
    result = ensure_suffix(Path("Living Room v1.2"), ".txt")
    assert result == Path("Living Room v1.2.txt")
    assert "v1.2" in str(result)
