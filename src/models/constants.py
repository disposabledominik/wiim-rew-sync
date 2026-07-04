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

# Generic superset of WiiM audio input names, used as a fallback when a
# device's real source list can't be enumerated (getAudioInputEnable
# unsupported, e.g. WiiM Mini, and no capability-file override for the
# model). The PEQ engine accepts any source name, so showing extra sources
# is harmless -- the user just picks which input to apply EQ to. Real
# per-model lists (see docs/wiim_api_notes.md): Mini has wifi/bluetooth/
# line-in; Pro/Pro Plus/Amp/Ultra add optical/HDMI; Sound/Sound Lite use
# auxIn instead of line-in.
DEFAULT_SOURCE_NAMES: tuple[str, ...] = (
    "wifi", "bluetooth", "line-in", "auxIn", "optical", "HDMI",
)
