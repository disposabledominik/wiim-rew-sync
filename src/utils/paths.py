"""Filesystem path helpers shared across export flows."""

from __future__ import annotations

from pathlib import Path


def ensure_suffix(path: Path, suffix: str) -> Path:
    """Return *path* with *suffix* enforced, case-insensitively.

    Leaves an already-matching suffix untouched (case-preserving) instead of
    appending a second one.
    """
    if path.suffix.lower() != suffix.lower():
        return path.with_suffix(suffix)
    return path
