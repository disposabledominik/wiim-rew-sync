"""Unified WiiM device identification.

Single authoritative source for determining whether a device's ``project``
field indicates a WiiM device.  Used by both ``capability_prober`` and
``subnet_scanner`` modules.
"""

from __future__ import annotations

# Authoritative list of known WiiM project field values.
# Source: docs/wiim_api_notes.md — Capability Nuances table.
# Includes underscore (firmware) and space (user-facing) variants.
KNOWN_WIIM_PROJECTS: frozenset[str] = frozenset({
    # Canonical underscore format (as reported by firmware)
    "WiiM_Ultra",
    "WiiM_Amp_Ultra",
    "WiiM_Amp_Pro",
    "WiiM_Pro",
    "WiiM_Pro_Plus",
    "WiiM_Amp",
    "WiiM_Sound",
    "WiiM_Sound_Lite",
    "WiiM_Mini",
    "Muzo_Mini",
    # Space-separated variants (seen in some firmware versions)
    "WiiM Ultra",
    "WiiM Amp Ultra",
    "WiiM Amp Pro",
    "WiiM Pro",
    "WiiM Pro Plus",
    "WiiM Amp",
    "WiiM Sound",
    "WiiM Sound Lite",
    "WiiM Mini",
})


def is_wiim_device(project: str) -> bool:
    """Determine whether a ``project`` field value indicates a WiiM device.

    Performs case-insensitive normalised matching against known WiiM project
    names, plus a forward-compatible prefix check for future models.

    Args:
        project: The ``project`` field value from a getStatusEx response.

    Returns:
        True if the project field indicates a WiiM device.
    """
    if not project:
        return False

    # Exact match (case-insensitive, normalised underscores)
    normalised = project.lower().replace(" ", "_")
    if normalised in {p.lower().replace(" ", "_") for p in KNOWN_WIIM_PROJECTS}:
        return True

    # Forward-compatible: accept any value starting with "WiiM" or "Muzo"
    lower = project.lower()
    return lower.startswith("wiim") or lower.startswith("muzo")
