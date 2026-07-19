"""Filesystem path-segment sanitization -- a traversal backstop, not a display-name formatter.

Used wherever a single untrusted string (a device UUID, a profile name) must become exactly
one path component. Not a general path-validation framework -- callers must not treat the
input as containing multiple segments.
"""

from __future__ import annotations

_FORBIDDEN_CHARS = ("/", "\\", "\x00")


def sanitize_path_segment(value: str, *, fallback: str = "unknown") -> str:
    """Reduce *value* to a single safe path-segment component.

    Strips path separators and null bytes, and rejects "." / ".." (whether the
    whole value or the stripped result), returning *fallback* if nothing usable
    remains.
    """
    stripped = value
    for char in _FORBIDDEN_CHARS:
        stripped = stripped.replace(char, "")
    if stripped in ("", ".", ".."):
        return fallback
    return stripped
