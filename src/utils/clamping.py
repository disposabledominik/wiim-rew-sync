"""Shared clamp-and-warn logic for WiiM gain/Q value limits.

Centralizes the boundary check and clamped-value computation used both by
the WiiM generator (which performs the clamp at write time) and the GUI's
pre-write validation (which only needs to detect whether a clamp *would*
happen, for the Review page's orange indicators) -- so the two can't end
up disagreeing about what counts as out of range.
"""

from __future__ import annotations


def clamp_with_warning(
    value: float,
    lo: float,
    hi: float,
    label: str,
    *,
    unit: str = "",
    signed: bool = False,
) -> tuple[float, str | None]:
    """Clamp `value` into [lo, hi].

    Returns (clamped_value, reason). `reason` is a human-readable message
    naming `label` if `value` fell outside [lo, hi], or None if it was
    already in range. `signed` renders the offending bound with an
    explicit +/- sign (e.g. gain's "+12.0"); leave it False for unitless
    bounds like Q where a sign wouldn't make sense.
    """
    bound_fmt = "+.1f" if signed else "g"

    if value > hi:
        bound = format(hi, bound_fmt)
        reason = f"{label} {value:g}{unit} exceeds {bound}{unit} limit, clamped to {bound}{unit}"
        return hi, reason
    if value < lo:
        bound = format(lo, bound_fmt)
        reason = f"{label} {value:g}{unit} exceeds {bound}{unit} limit, clamped to {bound}{unit}"
        return lo, reason
    return value, None
