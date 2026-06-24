"""Unit tests for src.translator.wiim_generator — Canonical → WiiM EQBand array generation.

Validates: Requirements 6.7, 6.8, 16.3, 16.4, 16.5
"""

from __future__ import annotations

import logging

from src.models.canonical import CanonicalFilter
from src.translator.wiim_generator import generate_wiim_band_array
from src.translator.wiim_parser import parse_wiim_band_array

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _peak(freq: float = 1000.0, gain: float = 0.0, q: float = 1.0) -> CanonicalFilter:
    return CanonicalFilter(type="PEAK", frequency_hz=freq, gain_db=gain, q=q)


def _off(freq: float = 1000.0, gain: float = 0.0, q: float = 1.0) -> CanonicalFilter:
    return CanonicalFilter(type="OFF", frequency_hz=freq, gain_db=gain, q=q)


def _ls(freq: float = 100.0, gain: float = 0.0, q: float = 0.71) -> CanonicalFilter:
    return CanonicalFilter(type="LS", frequency_hz=freq, gain_db=gain, q=q)


def _hs(freq: float = 8000.0, gain: float = 0.0, q: float = 0.71) -> CanonicalFilter:
    return CanonicalFilter(type="HS", frequency_hz=freq, gain_db=gain, q=q)


# ---------------------------------------------------------------------------
# Test: 10 filters produce exactly 40 entries
# ---------------------------------------------------------------------------


class TestOutputLength:
    """Requirement 16.5: generate_wiim_band_array produces 40-entry list."""

    def test_10_filters_produce_40_entries(self):
        """A full set of 10 filters produces exactly 40 float entries."""
        filters = [_peak(freq=100.0 * (i + 1), gain=-3.0, q=1.41) for i in range(10)]

        result, warnings = generate_wiim_band_array(filters)

        assert len(result) == 40
        assert warnings == []

    def test_fewer_than_10_filters_still_produces_40_entries(self):
        """If fewer than 10 filters are provided, padding produces 40 entries."""
        filters = [_peak(freq=200.0, gain=-2.0, q=1.0)]

        result, warnings = generate_wiim_band_array(filters)

        assert len(result) == 40
        assert warnings == []

    def test_padding_uses_off_mode(self):
        """Padded bands use mode -1 (OFF), freq=1000, gain=0, q=1."""
        filters = [_peak(freq=200.0, gain=-2.0, q=1.0)]

        result, _ = generate_wiim_band_array(filters)

        # Second band onwards should be OFF padding
        # Band 2 starts at index 4
        assert result[4] == -1.0   # mode OFF
        assert result[5] == 1000.0  # freq
        assert result[6] == 0.0    # gain
        assert result[7] == 1.0    # q

    def test_empty_list_produces_40_off_entries(self):
        """An empty filter list produces 40 entries, all OFF bands."""
        result, _ = generate_wiim_band_array([])

        assert len(result) == 40
        for i in range(10):
            base = i * 4
            assert result[base] == -1.0      # mode OFF
            assert result[base + 1] == 1000.0  # freq
            assert result[base + 2] == 0.0    # gain
            assert result[base + 3] == 1.0    # q

    def test_more_than_10_filters_truncates_to_40_entries(self):
        """More than 10 filters truncates to 10 bands (40 entries) with a warning."""
        filters = [_peak(freq=100.0 * (i + 1)) for i in range(12)]

        result, warnings = generate_wiim_band_array(filters)

        assert len(result) == 40
        assert any("truncated" in w.message.lower() for w in warnings)


# ---------------------------------------------------------------------------
# Test: OFF maps to mode -1
# ---------------------------------------------------------------------------


class TestModeMapping:
    """Requirement 16.5: Canonical types map to correct WiiM mode values."""

    def test_off_maps_to_mode_negative_1(self):
        """OFF type maps to mode -1."""
        filters = [_off()]

        result, _ = generate_wiim_band_array(filters)

        assert result[0] == -1.0

    def test_peak_maps_to_mode_1(self):
        """PEAK type maps to mode 1."""
        filters = [_peak()]

        result, _ = generate_wiim_band_array(filters)

        assert result[0] == 1.0

    def test_ls_maps_to_mode_0(self):
        """LS type maps to mode 0."""
        filters = [_ls()]

        result, _ = generate_wiim_band_array(filters)

        assert result[0] == 0.0

    def test_hs_maps_to_mode_2(self):
        """HS type maps to mode 2."""
        filters = [_hs()]

        result, _ = generate_wiim_band_array(filters)

        assert result[0] == 2.0


class TestValuePrecision:
    """WiiM write generation should round wire values to 3 decimal places."""

    def test_values_are_rounded_to_three_decimals(self):
        filters = [
            CanonicalFilter(
                type="PEAK",
                frequency_hz=1234.56789,
                gain_db=3.1415926,
                q=0.1234567,
            )
        ]

        result, warnings = generate_wiim_band_array(filters)

        assert warnings == []
        assert result[1] == 1234.568
        assert result[2] == 3.142
        assert result[3] == 0.123


# ---------------------------------------------------------------------------
# Test: Gain clipping
# ---------------------------------------------------------------------------


class TestGainClipping:
    """Requirements 16.3, 6.7: Gain clipped to ±12 dB with logged WARNING."""

    def test_gain_above_12_clipped_to_12(self):
        """Gain >12 dB is clamped to +12 dB."""
        filters = [_peak(gain=15.0)]

        result, warnings = generate_wiim_band_array(filters)

        # gain is at index 2 (mode=0, freq=1, gain=2, q=3)
        assert result[2] == 12.0
        assert any("band_1_gain" in w.field for w in warnings)

    def test_gain_below_negative_12_clipped_to_negative_12(self):
        """Gain <-12 dB is clamped to -12 dB."""
        filters = [_peak(gain=-18.5)]

        result, warnings = generate_wiim_band_array(filters)

        assert result[2] == -12.0
        assert any("band_1_gain" in w.field for w in warnings)

    def test_gain_at_boundary_not_clipped(self):
        """Gain exactly at ±12 dB is not clipped."""
        filters = [_peak(gain=12.0), _peak(gain=-12.0)]

        result, warnings = generate_wiim_band_array(filters)

        assert result[2] == 12.0
        assert result[6] == -12.0
        # No gain warnings
        assert not any("gain" in w.field for w in warnings)

    def test_gain_clipping_logs_warning(self, caplog):
        """Gain clipping emits a logging WARNING."""
        filters = [_peak(gain=20.0)]
        log = logging.getLogger("wiim_rew_sync.app")
        log.propagate = True

        with caplog.at_level(logging.WARNING, logger="wiim_rew_sync.app"):
            generate_wiim_band_array(filters)

        assert any("gain" in record.message.lower() for record in caplog.records)


# ---------------------------------------------------------------------------
# Test: Q clipping
# ---------------------------------------------------------------------------


class TestQClipping:
    """Requirements 16.4, 6.8: Q clipped to [0.01, 24.0] with logged WARNING."""

    def test_q_above_24_clipped_to_24(self):
        """Q >24 is clamped to 24.0."""
        filters = [_peak(q=30.0)]

        result, warnings = generate_wiim_band_array(filters)

        # q is at index 3
        assert result[3] == 24.0
        assert any("band_1_q" in w.field for w in warnings)

    def test_q_below_001_clipped_to_001(self):
        """Q <0.01 is clamped to 0.01."""
        # CanonicalFilter validator requires q > 0, so use a small positive value
        filters = [CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=0.0, q=0.005)]

        result, warnings = generate_wiim_band_array(filters)

        assert result[3] == 0.01
        assert any("band_1_q" in w.field for w in warnings)

    def test_q_at_boundary_not_clipped(self):
        """Q exactly at 0.01 and 24.0 is not clipped."""
        filters = [_peak(q=0.01), _peak(q=24.0)]

        result, warnings = generate_wiim_band_array(filters)

        assert result[3] == 0.01
        assert result[7] == 24.0
        assert not any("q" in w.field for w in warnings)

    def test_q_clipping_logs_warning(self, caplog):
        """Q clipping emits a logging WARNING."""
        filters = [_peak(q=50.0)]
        log = logging.getLogger("wiim_rew_sync.app")
        log.propagate = True

        with caplog.at_level(logging.WARNING, logger="wiim_rew_sync.app"):
            generate_wiim_band_array(filters)

        assert any("q" in record.message.lower() for record in caplog.records)


# ---------------------------------------------------------------------------
# Test: Round-trip — generate → parse matches within tolerance
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """Requirement 16.7: Round-trip generate → parse produces matching filters."""

    def test_round_trip_within_tolerance(self):
        """Generating a WiiM array then parsing it back matches the originals."""
        original_filters = [
            CanonicalFilter(type="PEAK", frequency_hz=80.0, gain_db=-4.0, q=1.41),
            CanonicalFilter(type="LS", frequency_hz=100.0, gain_db=3.0, q=0.71),
            CanonicalFilter(type="HS", frequency_hz=8000.0, gain_db=-1.5, q=0.71),
            CanonicalFilter(type="OFF", frequency_hz=1000.0, gain_db=0.0, q=1.0),
            CanonicalFilter(type="PEAK", frequency_hz=3000.0, gain_db=-6.0, q=4.0),
            CanonicalFilter(type="PEAK", frequency_hz=500.0, gain_db=2.0, q=1.41),
            CanonicalFilter(type="LS", frequency_hz=50.0, gain_db=4.0, q=0.5),
            CanonicalFilter(type="HS", frequency_hz=12000.0, gain_db=-3.0, q=1.0),
            CanonicalFilter(type="PEAK", frequency_hz=200.0, gain_db=-2.5, q=2.0),
            CanonicalFilter(type="OFF", frequency_hz=16000.0, gain_db=0.0, q=1.0),
        ]

        # Generate WiiM array
        flat_array, warnings = generate_wiim_band_array(original_filters)
        assert warnings == []

        # Convert flat array to band dicts for the parser
        band_dicts = _flat_array_to_band_dicts(flat_array)

        # Parse back
        parsed_filters = parse_wiim_band_array(band_dicts)

        # Compare
        assert len(parsed_filters) == len(original_filters)
        for orig, parsed in zip(original_filters, parsed_filters, strict=True):
            assert orig.type == parsed.type
            assert abs(orig.frequency_hz - parsed.frequency_hz) < 0.1
            assert abs(orig.gain_db - parsed.gain_db) < 0.05
            assert abs(orig.q - parsed.q) < 0.01

    def test_round_trip_with_padding(self):
        """Fewer than 10 filters round-trip correctly (padding becomes OFF bands)."""
        original_filters = [
            CanonicalFilter(type="PEAK", frequency_hz=440.0, gain_db=-5.0, q=2.0),
            CanonicalFilter(type="LS", frequency_hz=80.0, gain_db=3.0, q=0.71),
        ]

        flat_array, _ = generate_wiim_band_array(original_filters)
        band_dicts = _flat_array_to_band_dicts(flat_array)
        parsed_filters = parse_wiim_band_array(band_dicts)

        # First two should match
        assert parsed_filters[0].type == "PEAK"
        assert abs(parsed_filters[0].frequency_hz - 440.0) < 0.1
        assert parsed_filters[1].type == "LS"
        assert abs(parsed_filters[1].frequency_hz - 80.0) < 0.1

        # Remaining 8 should be OFF
        for f in parsed_filters[2:]:
            assert f.type == "OFF"


# ---------------------------------------------------------------------------
# Helper: convert flat array back to band dicts for parse_wiim_band_array
# ---------------------------------------------------------------------------


def _flat_array_to_band_dicts(flat: list[float]) -> list[dict]:
    """Convert a 40-entry flat array to a list of 10 band dicts for the parser."""
    letters = list("abcdefghij")
    bands = []
    for i in range(10):
        base = i * 4
        bands.append({
            "letter": letters[i],
            "mode": int(flat[base]),
            "freq": flat[base + 1],
            "gain": flat[base + 2],
            "q": flat[base + 3],
        })
    return bands


# ---------------------------------------------------------------------------
# Test: LP/HP mode generation (hardware validation findings)
# ---------------------------------------------------------------------------


class TestLPHPModeGeneration:
    """Hardware validation: LP → mode 3, HP → mode 5 in generator output."""

    def test_lp_maps_to_mode_3(self):
        """CanonicalFilter(type='LP') generates mode 3 in WiiM output."""
        filters = [CanonicalFilter(type="LP", frequency_hz=200.0, gain_db=0.0, q=0.71)]

        result, warnings = generate_wiim_band_array(filters)

        assert result[0] == 3.0  # mode
        assert result[1] == 200.0  # freq
        assert result[2] == 0.0  # gain
        assert result[3] == 0.71  # q
        assert warnings == []

    def test_hp_maps_to_mode_5(self):
        """CanonicalFilter(type='HP') generates mode 5 in WiiM output."""
        filters = [CanonicalFilter(type="HP", frequency_hz=80.0, gain_db=0.0, q=0.71)]

        result, warnings = generate_wiim_band_array(filters)

        assert result[0] == 5.0  # mode
        assert result[1] == 80.0  # freq
        assert result[2] == 0.0  # gain
        assert result[3] == 0.71  # q
        assert warnings == []


# ---------------------------------------------------------------------------
# Test: 12-band device support (hardware validation findings)
# ---------------------------------------------------------------------------


class Test12BandDevice:
    """Hardware validation: 12-band devices produce 48-entry arrays."""

    def test_12_band_output_produces_48_entries(self):
        """12 filters with max_bands=12 produces exactly 48 float entries."""
        filters = [_peak(freq=100.0 * (i + 1), gain=-3.0, q=1.41) for i in range(12)]

        result, warnings = generate_wiim_band_array(filters, max_bands=12)

        assert len(result) == 48
        assert warnings == []

    def test_padding_to_12_bands(self):
        """5 filters with max_bands=12 produces 48 entries, last 7 are OFF."""
        filters = [_peak(freq=100.0 * (i + 1), gain=-2.0, q=1.0) for i in range(5)]

        result, warnings = generate_wiim_band_array(filters, max_bands=12)

        assert len(result) == 48
        assert warnings == []

        # First 5 bands should be PEAK (mode 1)
        for i in range(5):
            assert result[i * 4] == 1.0  # mode PEAK

        # Last 7 bands should be OFF (mode -1)
        for i in range(5, 12):
            base = i * 4
            assert result[base] == -1.0  # mode OFF
            assert result[base + 1] == 1000.0  # default freq
            assert result[base + 2] == 0.0  # default gain
            assert result[base + 3] == 1.0  # default q


# ---------------------------------------------------------------------------
# Test: UNKNOWN filter type handling (forward compatibility)
# ---------------------------------------------------------------------------


class TestUnknownFilterGeneration:
    """Forward compatibility: UNKNOWN filters with raw_mode pass through correctly."""

    def test_unknown_with_raw_mode_produces_original_mode(self):
        """UNKNOWN filter with raw_mode=99 produces mode 99 in output."""
        filters = [
            CanonicalFilter(
                type="UNKNOWN", frequency_hz=1000.0, gain_db=-2.0, q=1.41, raw_mode=99
            )
        ]

        result, warnings = generate_wiim_band_array(filters)

        assert result[0] == 99.0  # mode preserved from raw_mode
        assert result[1] == 1000.0  # freq
        assert result[2] == -2.0  # gain
        assert result[3] == 1.41  # q
        assert warnings == []

    def test_unknown_without_raw_mode_falls_back_to_off(self):
        """UNKNOWN filter without raw_mode produces mode -1 (OFF) as safe fallback."""
        filters = [
            CanonicalFilter(
                type="UNKNOWN", frequency_hz=500.0, gain_db=0.0, q=1.0, raw_mode=None
            )
        ]

        result, warnings = generate_wiim_band_array(filters)

        assert result[0] == -1.0  # mode OFF fallback
        assert result[1] == 500.0
        assert result[2] == 0.0
        assert result[3] == 1.0
        assert warnings == []

    def test_unknown_with_raw_mode_6(self):
        """UNKNOWN filter with raw_mode=6 (hypothetical NOTCH) preserves mode 6."""
        filters = [
            CanonicalFilter(
                type="UNKNOWN", frequency_hz=2000.0, gain_db=-5.0, q=3.0, raw_mode=6
            )
        ]

        result, _warnings = generate_wiim_band_array(filters)

        assert result[0] == 6.0  # mode 6 preserved
        assert result[1] == 2000.0
        assert result[2] == -5.0
        assert result[3] == 3.0
