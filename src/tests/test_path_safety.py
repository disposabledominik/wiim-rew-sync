"""Tests for src.utils.path_safety.sanitize_path_segment."""

from __future__ import annotations

import pytest

from src.utils.path_safety import sanitize_path_segment


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("normal-uuid-1234", "normal-uuid-1234"),
        ("My Preset", "My Preset"),
        ("", "unknown"),
        (".", "unknown"),
        ("..", "unknown"),
        ("../../../etc/passwd", "......etcpasswd"),
        ("/etc/passwd", "etcpasswd"),
        ("..\\..\\evil", "....evil"),
        ("a/b\\c", "abc"),
    ],
)
def test_sanitize_path_segment(value: str, expected: str) -> None:
    """Separators and null bytes are stripped; "." / ".." collapse to the fallback."""
    assert sanitize_path_segment(value) == expected


def test_sanitize_path_segment_custom_fallback() -> None:
    """A caller-supplied fallback is used instead of the default."""
    assert sanitize_path_segment("", fallback="unknown-device") == "unknown-device"
    assert sanitize_path_segment("..", fallback="unknown-device") == "unknown-device"


def test_sanitize_path_segment_strips_null_byte() -> None:
    """Null bytes are stripped, not merely rejected."""
    assert sanitize_path_segment("foo\x00bar") == "foobar"


def test_sanitize_path_segment_result_never_contains_separators() -> None:
    """The sanitized result never contains a path separator, for any input."""
    for value in ("../../../x", "a/b/../c", "\\\\server\\share", "...."):
        result = sanitize_path_segment(value)
        assert "/" not in result
        assert "\\" not in result
