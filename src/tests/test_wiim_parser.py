"""Unit tests for src.translator.wiim_parser — WiiM EQBand → CanonicalFilter parsing.

Validates: Requirements 4.2, 4.3, 4.4, 4.5
"""

from __future__ import annotations

import pytest

from src.models.canonical import CanonicalFilter
from src.models.errors import ValidationError
from src.translator.wiim_parser import parse_wiim_band_array


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_band(letter: str, mode: int, freq: float, q: float, gain: float) -> dict:
    """Create a WiiM band dict matching the API response format."""
    return {"letter": letter, "mode": mode, "freq": freq, "q": q, "gain": gain}


LETTERS = list("abcdefghij")


# ---------------------------------------------------------------------------
# Test: Full 10-band stereo array
# ---------------------------------------------------------------------------

class TestParse10BandStereo:
    """Requirement 4.2: Stereo mode returns 10 CanonicalFilter objects from EQBand."""

    def test_10_band_array_returns_10_filters(self):
        """A full 10-band array produces exactly 10 CanonicalFilter objects."""
        band_array = [
            _make_band(LETTERS[0], 1, 80.0, 1.41, -4.0),
            _make_band(LETTERS[1], 1, 200.0, 2.0, -2.5),
            _make_band(LETTERS[2], 0, 100.0, 0.71, 3.0),
            _make_band(LETTERS[3], 2, 8000.0, 0.71, -1.5),
            _make_band(LETTERS[4], -1, 1000.0, 1.0, 0.0),
            _make_band(LETTERS[5], 1, 3000.0, 4.0, -6.0),
            _make_band(LETTERS[6], 1, 500.0, 1.41, 2.0),
            _make_band(LETTERS[7], 0, 50.0, 0.5, 4.0),
            _make_band(LETTERS[8], 2, 12000.0, 1.0, -3.0),
            _make_band(LETTERS[9], -1, 16000.0, 1.0, 0.0),
        ]

        result = parse_wiim_band_array(band_array, channel="stereo")

        assert len(result) == 10
        # Check specific bands
        assert result[0] == CanonicalFilter(type="PEAK", frequency_hz=80.0, gain_db=-4.0, q=1.41)
        assert result[2] == CanonicalFilter(type="LS", frequency_hz=100.0, gain_db=3.0, q=0.71)
        assert result[3] == CanonicalFilter(type="HS", frequency_hz=8000.0, gain_db=-1.5, q=0.71)
        assert result[4] == CanonicalFilter(type="OFF", frequency_hz=1000.0, gain_db=0.0, q=1.0)

    def test_all_filters_are_canonical_filter_instances(self):
        """Every item in the result list is a CanonicalFilter."""
        band_array = [_make_band(LETTERS[i], 1, 1000.0, 1.0, 0.0) for i in range(10)]
        result = parse_wiim_band_array(band_array)

        for f in result:
            assert isinstance(f, CanonicalFilter)


# ---------------------------------------------------------------------------
# Test: L/R channel mode
# ---------------------------------------------------------------------------

class TestParseLRMode:
    """Requirement 4.3: L/R mode produces separate left and right filter lists."""

    def test_left_channel_parses_correctly(self):
        """EQBandL parsed with channel='left' returns correct filters."""
        band_array = [
            _make_band("a", 1, 100.0, 1.41, -3.0),
            _make_band("b", 0, 80.0, 0.71, 2.0),
        ]

        result = parse_wiim_band_array(band_array, channel="left")

        assert len(result) == 2
        assert result[0] == CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-3.0, q=1.41)
        assert result[1] == CanonicalFilter(type="LS", frequency_hz=80.0, gain_db=2.0, q=0.71)

    def test_right_channel_parses_correctly(self):
        """EQBandR parsed with channel='right' returns correct filters."""
        band_array = [
            _make_band("a", 2, 10000.0, 1.0, -2.0),
            _make_band("b", -1, 5000.0, 1.0, 0.0),
        ]

        result = parse_wiim_band_array(band_array, channel="right")

        assert len(result) == 2
        assert result[0] == CanonicalFilter(type="HS", frequency_hz=10000.0, gain_db=-2.0, q=1.0)
        assert result[1] == CanonicalFilter(type="OFF", frequency_hz=5000.0, gain_db=0.0, q=1.0)

    def test_channel_parameter_does_not_affect_parsing_logic(self):
        """The channel parameter is for context only — same input gives same output."""
        band_array = [_make_band("a", 1, 1000.0, 1.41, -2.0)]

        stereo = parse_wiim_band_array(band_array, channel="stereo")
        left = parse_wiim_band_array(band_array, channel="left")
        right = parse_wiim_band_array(band_array, channel="right")

        assert stereo == left == right


# ---------------------------------------------------------------------------
# Test: Mode value mappings
# ---------------------------------------------------------------------------

class TestModeMapping:
    """Requirements 4.4, 4.5: All mode values are mapped correctly."""

    @pytest.mark.parametrize(
        "mode_value,expected_type",
        [
            (-1, "OFF"),
            (0, "LS"),
            (1, "PEAK"),
            (2, "HS"),
        ],
        ids=["OFF", "LS", "PEAK", "HS"],
    )
    def test_mode_maps_to_expected_type(self, mode_value, expected_type):
        """Each WiiM mode integer maps to the correct CanonicalFilter type."""
        band_array = [_make_band("a", mode_value, 1000.0, 1.0, 0.0)]

        result = parse_wiim_band_array(band_array)

        assert result[0].type == expected_type

    def test_unknown_mode_raises_validation_error(self):
        """An unknown mode value (e.g. 3, 99) raises ValidationError."""
        band_array = [_make_band("a", 3, 1000.0, 1.0, 0.0)]

        with pytest.raises(ValidationError, match="Unknown WiiM band mode value: 3"):
            parse_wiim_band_array(band_array)

    def test_unknown_negative_mode_raises_validation_error(self):
        """Negative mode values other than -1 raise ValidationError."""
        band_array = [_make_band("a", -2, 1000.0, 1.0, 0.0)]

        with pytest.raises(ValidationError, match="Unknown WiiM band mode value: -2"):
            parse_wiim_band_array(band_array)


# ---------------------------------------------------------------------------
# Test: Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Edge cases for robustness."""

    def test_empty_band_array_returns_empty_list(self):
        """An empty band array produces an empty filter list."""
        result = parse_wiim_band_array([])
        assert result == []

    def test_preserves_frequency_gain_q_values(self):
        """Frequency, gain, and Q values are preserved through parsing."""
        band_array = [_make_band("a", 1, 440.0, 2.5, -7.3)]

        result = parse_wiim_band_array(band_array)

        assert result[0].frequency_hz == 440.0
        assert result[0].gain_db == -7.3
        assert result[0].q == 2.5

    def test_off_band_preserves_freq_gain_q(self):
        """OFF bands still carry their frequency, gain, and Q values."""
        band_array = [_make_band("a", -1, 500.0, 1.41, -3.0)]

        result = parse_wiim_band_array(band_array)

        assert result[0].type == "OFF"
        assert result[0].frequency_hz == 500.0
        assert result[0].gain_db == -3.0
        assert result[0].q == 1.41
