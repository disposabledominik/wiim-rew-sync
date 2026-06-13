"""WiiM EQBand array → list[CanonicalFilter] parser.

Converts the EQBand / EQBandL / EQBandR arrays returned by the WiiM LV2 PEQ API
into the canonical intermediate representation.

Mode mapping (LV2 EqNp plugin):
    -1 → "OFF"
     0 → "LS"  (Low Shelf)
     1 → "PEAK"
     2 → "HS"  (High Shelf)
"""

from __future__ import annotations

import logging

from src.models.canonical import CanonicalFilter, FilterType
from src.models.errors import ValidationError  # noqa: F401 — kept for backward compat

logger = logging.getLogger("wiim_rew_sync.app")

# Mode value -> CanonicalFilter type mapping
_MODE_MAP: dict[int, FilterType] = {
    -1: "OFF",
    0: "LS",
    1: "PEAK",
    2: "HS",
    3: "LP",
    5: "HP",
}


def parse_wiim_band_array(
    band_array: list[dict[str, int | float | str]],
    channel: str = "stereo",
) -> list[CanonicalFilter]:
    """Parse a WiiM EQBand array into a list of CanonicalFilter objects.

    Parameters
    ----------
    band_array:
        The array of band dicts as returned by the WiiM API
        (already extracted from the response JSON under "EQBand", "EQBandL",
        or "EQBandR").
    channel:
        "stereo", "left", or "right" — used for context/logging only.
        The parsing logic is identical for all channel values.

    Returns
    -------
    list[CanonicalFilter]
        One CanonicalFilter per band in the input array.

    Raises
    ------
    ValidationError
        If an unknown mode value is encountered.
    """
    filters: list[CanonicalFilter] = []

    for band in band_array:
        mode_value: int = int(band["mode"])
        freq: float = float(band["freq"])
        gain: float = float(band["gain"])
        q: float = float(band["q"])

        filter_type = _MODE_MAP.get(mode_value)
        if filter_type is None:
            logger.warning(
                "Unknown WiiM band mode value: %d (channel=%s, freq=%s)",
                mode_value,
                channel,
                freq,
            )
            filters.append(
                CanonicalFilter(
                    type="UNKNOWN",
                    frequency_hz=freq,
                    gain_db=gain,
                    q=q,
                    raw_mode=mode_value,
                )
            )
            continue

        filters.append(
            CanonicalFilter(
                type=filter_type,
                frequency_hz=freq,
                gain_db=gain,
                q=q,
            )
        )

    return filters
