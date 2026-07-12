"""Validation for names pushed to a WiiM device (RoomFit profiles, PEQ presets).

The WiiM Home app states its naming rule as "only letters, numbers, and
underscore are allowed", but hardware testing found dash ("-") and space
(" ") are also accepted by the device (see docs/corrections.md, 2026-07-12).
This module encodes that broader, verified set so the GUI can warn and
sanitize a name before a push attempt fails on a rejected character.

# ASSUMPTION: the exact device-side validation rule is not documented by
# WiiM; this set is the WiiM Home app's stated rule plus the two additional
# characters confirmed via hardware testing (docs/corrections.md,
# 2026-07-12). If a push is ever rejected for a name that passes this
# check, log the corrected rule in docs/corrections.md.
"""

from __future__ import annotations

import re

_ALLOWED_NAME_CHARS = re.compile(r"[^A-Za-z0-9_\- ]")

#: User-facing description of the allowed character set, for warning text.
DEVICE_NAME_RULE_TEXT = "letters, numbers, spaces, - and _"


def sanitize_device_name(name: str) -> str:
    """Strip characters not accepted by the WiiM device naming API.

    Returns:
        *name* with every disallowed character removed. Does not collapse
        or trim whitespace left behind by removal -- callers should
        `.strip()` the result themselves if needed.
    """
    return _ALLOWED_NAME_CHARS.sub("", name)


def has_invalid_device_name_chars(name: str) -> bool:
    """True if *name* contains a character the device naming API rejects."""
    return bool(_ALLOWED_NAME_CHARS.search(name))
