"""Shared warning dataclass for the translator package (breaks circular imports)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ValidationWarning:
    """Warning emitted when a value is clamped during translation."""

    field: str
    message: str
    original_value: Any
    clamped_value: Any | None = None
