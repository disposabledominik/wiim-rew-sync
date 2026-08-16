"""Unified WiiM device identification and display naming.

Single authoritative source for determining whether a device's ``project``
field indicates a WiiM device (used by both ``capability_prober`` and
``subnet_scanner``), and for the display-name fallback every screen that
lists discovered devices needs to agree on.
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


def device_display_name(name: str) -> str:
    """Fallback label for a device with a missing or blank name.

    Some mDNS/subnet-scan responses omit a device name or report one as an
    empty string (``subnet_scanner.py``'s ``response.get("DeviceName", "")``
    and ``zeroconf_discover.py``'s ``_decode(...) or ... or ""`` both default
    to blank rather than raising) -- every screen that lists or sorts
    discovered devices by name needs the same fallback, or the same device
    can show up under a different label, or in a different sort position,
    on different screens (#277).
    """
    return name or "Unknown Device"
