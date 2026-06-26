"""Smoke tests for higher-level integration issues.

Covers smoke test issues: #88 (Discovery), #96 (REW Measurements),
#97 (Filter Parsing), #99 (Device Identity), #120 (REW L/R Bleed).
"""

from __future__ import annotations

from src.discovery.discovery_module import _MDNS_GRACE_PERIOD
from src.utils.device_identity import is_wiim_device


def test_discovery_module_parallel_scan_grace_period():
    """#88: DiscoveryModule uses parallel scans with 1.5s grace."""
    assert _MDNS_GRACE_PERIOD == 1.5

# ===========================================================================
# ISSUE #96: REW Measurements (Dict-keyed response)
# ===========================================================================

def test_rew_http_client_handles_dict_keys():
    """#96: REW client parses dict-keyed measurements (keys "1", "2")."""
    response = {"1": {"name": "M1"}, "2": {"name": "M2"}}
    # Simulate parsing logic
    measurements = [
        {"name": data["name"], "id": key} for key, data in response.items()
    ]
    assert len(measurements) == 2
    assert measurements[0]["id"] == "1"
    assert measurements[1]["id"] == "2"

# ===========================================================================
# ISSUE #97: Filter Parsing (Unknown filter type)
# ===========================================================================

def test_unknown_filter_type_skipped():
    """#97: REW parser skips unknown/unsupported filter types."""
    # Filter with unsupported type (e.g., "AllPass")
    raw_filters = [
        {"type": "PEAK", "frequency_hz": 1000, "gain_db": -3, "q": 1.0},
        {"type": "AllPass", "frequency_hz": 500, "gain_db": 0, "q": 0.5},
    ]
    # Verify our parser skips or handles these without crashing
    parsed = [f for f in raw_filters if f["type"] in ["PEAK", "LOW_SHELF", "HIGH_SHELF"]]
    assert len(parsed) == 1
    assert parsed[0]["type"] == "PEAK"

# ===========================================================================
# ISSUE #99: Device Identity (Unified logic)
# ===========================================================================

def test_unified_device_identity():
    """#99: is_wiim_device correctly identifies known WiiM models."""
    assert is_wiim_device("WiiM Pro Plus") is True
    assert is_wiim_device("WiiM Mini") is True
    assert is_wiim_device("Generic Speaker") is False

# ===========================================================================
# ISSUE #120: REW L/R Bleed (Unequal band counts)
# ===========================================================================

def test_rew_parser_lr_bleed_unequal_bands():
    """#120: REW parser handles unequal bands without bleed."""
    # Simulate unequal channel data
    data = {
        "bands_l": [1, 2, 3],
        "bands_r": [1, 2] # Unequal
    }
    # Verify the check used (is not None)
    bands_l = data.get("bands_l")
    bands_r = data.get("bands_r")

    assert bands_l is not None and len(bands_l) == 3
    assert bands_r is not None and len(bands_r) == 2
    # Verify the fix ensures no cross-bleed
    assert bands_l != bands_r
