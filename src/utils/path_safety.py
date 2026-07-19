"""Filesystem path-segment sanitization -- a traversal backstop, not a display-name formatter.

Used wherever a single untrusted string (a device UUID, a profile name) must become exactly
one path component. Not a general path-validation framework -- callers must not treat the
input as containing multiple segments.
"""

from __future__ import annotations

# Path separators/NUL (traversal), plus the Windows-reserved punctuation set -- this app is a
# cross-platform desktop tool, so a value that would be illegal on Windows must be rejected
# regardless of which OS is running right now.
_FORBIDDEN_CHARS = ("/", "\\", "\x00", ":", "*", "?", '"', "<", ">", "|")

# Windows-reserved device names (case-insensitive, with or without an extension) -- a path
# segment that is exactly one of these resolves to a reserved device rather than a real
# directory/file on Windows.
_RESERVED_NAMES = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})


def sanitize_path_segment(value: str, *, fallback: str = "unknown") -> str:
    """Return *value* unchanged if it is safe to use as a single path segment, otherwise *fallback*.

    Rejects (rather than mutates) any value containing a forbidden character, equal to "."/"..",
    or matching a Windows-reserved device name. Rejecting wholesale is deliberate: stripping
    forbidden characters out of an otherwise-unsafe value is not injective -- two different unsafe
    inputs (e.g. "AB/CD" and "ABCD") could strip down to the same segment and silently collide.
    Every unsafe input instead collapses onto the single shared *fallback* segment, which can never
    collide with a legitimate value.
    """
    if value in ("", ".", "..") or value.upper() in _RESERVED_NAMES:
        return fallback
    if any(char in value for char in _FORBIDDEN_CHARS):
        return fallback
    return value
