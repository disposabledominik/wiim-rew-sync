"""Hardware limit constants for WiiM devices.

Single source of truth for gain and Q clamping boundaries.  Imported by
the translator layer (for clamping logic) and the GUI layer (for validation
warnings).
"""

from __future__ import annotations

# Gain limits (dB)
GAIN_MIN: float = -12.0
GAIN_MAX: float = 12.0

# Q factor limits
Q_MIN: float = 0.01
Q_MAX: float = 24.0

# Default number of PEQ bands a WiiM device supports, used as a fallback
# when capability probing can't determine the device's actual band count.
DEFAULT_MAX_BANDS: int = 10
