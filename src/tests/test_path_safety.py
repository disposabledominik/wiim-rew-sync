"""Tests for src.utils.path_safety.sanitize_path_segment."""

from __future__ import annotations

import pytest

from src.utils.path_safety import sanitize_path_segment


@pytest.mark.parametrize(
    "value",
    [
        "normal-uuid-1234",
        "My Preset",
        "FF31F09E1A2B3C4D",
        "living-room-v2",
    ],
)
def test_sanitize_path_segment_passes_through_safe_values_unchanged(value: str) -> None:
    """A value with no forbidden characters and no reserved name is returned as-is."""
    assert sanitize_path_segment(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        ".",
        "..",
        "../../../etc/passwd",
        "/etc/passwd",
        "..\\..\\evil",
        "a/b\\c",
        "foo\x00bar",
        "AB/CD",
        "AABB:CCDD",
        'foo"bar',
        "a*b",
        "a?b",
        "a<b>c",
        "a|b",
    ],
)
def test_sanitize_path_segment_rejects_unsafe_values(value: str) -> None:
    """Any value containing a forbidden character, or equal to "."/"..", is rejected wholesale
    (not stripped) -- falls back to the sentinel."""
    assert sanitize_path_segment(value) == "unknown"


@pytest.mark.parametrize("name", ["CON", "con", "Aux", "NUL", "COM1", "com9", "LPT1", "lpt9"])
def test_sanitize_path_segment_rejects_windows_reserved_names(name: str) -> None:
    """Windows-reserved device names are rejected case-insensitively."""
    assert sanitize_path_segment(name) == "unknown"


def test_sanitize_path_segment_custom_fallback() -> None:
    """A caller-supplied fallback is used instead of the default."""
    assert sanitize_path_segment("", fallback="unknown-device") == "unknown-device"
    assert sanitize_path_segment("..", fallback="unknown-device") == "unknown-device"
    assert sanitize_path_segment("../evil", fallback="unknown-device") == "unknown-device"


def test_sanitize_path_segment_is_not_a_collision_vector() -> None:
    """Two different unsafe inputs must never sanitize to two different, non-fallback strings
    that happen to collide with each other or with a real legitimate value -- both of these
    collapse to the *same* fallback rather than to two different mutated strings."""
    assert sanitize_path_segment("AB/CD") == sanitize_path_segment("ABCD/") == "unknown"
    # And the fallback itself never equals a value that would pass through unchanged for a
    # plausible legitimate UUID/profile name.
    assert sanitize_path_segment("AB/CD") != "ABCD"
