"""Filesystem path helpers shared across export flows."""

from __future__ import annotations

import os
from pathlib import Path


def is_writable_directory(path: str | Path) -> bool:
    """Return True if *path* is an existing directory this process can write to."""
    return Path(path).is_dir() and os.access(path, os.W_OK)


def ensure_suffix(path: Path, suffix: str) -> Path:
    """Return *path* with *suffix* appended if not already present (case-insensitive).

    Appends rather than replacing any existing suffix -- Path.with_suffix() would
    silently drop everything after the last "." instead, which truncates a filename
    that merely contains an unrelated dot (e.g. "Living Room v1.2" -> "Living Room
    v1.txt", quietly discarding the ".2"). Appending is idempotent (an already-.txt
    path is returned unchanged) and never destroys part of a user-typed name.
    """
    if str(path).lower().endswith(suffix.lower()):
        return path
    return Path(str(path) + suffix)
