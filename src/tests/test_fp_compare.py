"""Unit tests for floating-point tolerance predicates (src/utils/fp_compare.py).

Tests verify exact boundary behaviour: pass at ε, fail at ε + 0.0001.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.models.canonical import CanonicalFilter
from src.tests.conftest import st_float_near_boundary
from src.utils.fp_compare import (
    _FP_EPS,
    FREQ_TOLERANCE_HZ,
    GAIN_TOLERANCE_DB,
    Q_TOLERANCE,
    band_matches,
    freq_matches,
    gain_matches,
    q_matches,
)

# ---------------------------------------------------------------------------
# freq_matches
# ---------------------------------------------------------------------------


class TestFreqMatches:
    """Tests for freq_matches predicate."""

    def test_exact_match(self) -> None:
        assert freq_matches(1000.0, 1000.0) is True

    def test_at_boundary_positive(self) -> None:
        """Exactly at tolerance (1000.0, 1000.1) → should pass."""
        assert freq_matches(1000.0, 1000.1) is True

    def test_at_boundary_negative(self) -> None:
        """Exactly at tolerance negative direction (1000.0, 999.9) → should pass."""
        assert freq_matches(1000.0, 999.9) is True

    def test_just_past_boundary(self) -> None:
        """Just past tolerance (1000.0, 1000.1001) → should fail."""
        assert freq_matches(1000.0, 1000.1001) is False

    def test_just_past_boundary_negative(self) -> None:
        """Just past tolerance negative direction → should fail."""
        assert freq_matches(1000.0, 999.8999) is False


# ---------------------------------------------------------------------------
# gain_matches
# ---------------------------------------------------------------------------


class TestGainMatches:
    """Tests for gain_matches predicate."""

    def test_exact_match(self) -> None:
        assert gain_matches(3.0, 3.0) is True

    def test_at_boundary_positive(self) -> None:
        """Exactly at tolerance (3.0, 3.05) → should pass."""
        assert gain_matches(3.0, 3.05) is True

    def test_at_boundary_negative(self) -> None:
        """Exactly at tolerance negative direction (3.0, 2.95) → should pass."""
        assert gain_matches(3.0, 2.95) is True

    def test_just_past_boundary(self) -> None:
        """Just past tolerance (3.0, 3.0501) → should fail."""
        assert gain_matches(3.0, 3.0501) is False

    def test_just_past_boundary_negative(self) -> None:
        """Just past tolerance negative direction → should fail."""
        assert gain_matches(3.0, 2.9499) is False


# ---------------------------------------------------------------------------
# q_matches
# ---------------------------------------------------------------------------


class TestQMatches:
    """Tests for q_matches predicate."""

    def test_exact_match(self) -> None:
        assert q_matches(1.0, 1.0) is True

    def test_at_boundary_positive(self) -> None:
        """Exactly at tolerance (1.0, 1.01) → should pass."""
        assert q_matches(1.0, 1.01) is True

    def test_at_boundary_negative(self) -> None:
        """Exactly at tolerance negative direction (1.0, 0.99) → should pass."""
        assert q_matches(1.0, 0.99) is True

    def test_just_past_boundary(self) -> None:
        """Just past tolerance → should fail."""
        assert q_matches(1.0, 1.0101) is False

    def test_just_past_boundary_negative(self) -> None:
        """Just past tolerance (negative direction) → should fail."""
        assert q_matches(1.0, 0.9899) is False


# ---------------------------------------------------------------------------
# band_matches
# ---------------------------------------------------------------------------


def _make_filter(
    type_: str = "PEAK",
    freq: float = 1000.0,
    gain: float = 3.0,
    q: float = 1.0,
) -> CanonicalFilter:
    """Helper to create a CanonicalFilter with sensible defaults."""
    return CanonicalFilter(type=type_, frequency_hz=freq, gain_db=gain, q=q)


class TestBandMatches:
    """Tests for band_matches predicate."""

    def test_off_intended_only_checks_type(self) -> None:
        """OFF bands match regardless of freq/gain/Q values."""
        intended = _make_filter(type_="OFF", freq=100.0, gain=0.0, q=1.0)
        read_back = _make_filter(type_="OFF", freq=5000.0, gain=6.0, q=10.0)
        assert band_matches(intended, read_back) is True

    def test_off_vs_peak_type_mismatch(self) -> None:
        """OFF intended vs PEAK read-back → False."""
        intended = _make_filter(type_="OFF")
        read_back = _make_filter(type_="PEAK")
        assert band_matches(intended, read_back) is False

    def test_peak_type_mismatch(self) -> None:
        """PEAK vs LS type mismatch → False."""
        intended = _make_filter(type_="PEAK")
        read_back = _make_filter(type_="LS")
        assert band_matches(intended, read_back) is False

    def test_peak_all_within_tolerance(self) -> None:
        """PEAK with all values within tolerance → True."""
        intended = _make_filter(type_="PEAK", freq=1000.0, gain=3.0, q=1.0)
        read_back = _make_filter(
            type_="PEAK",
            freq=1000.1,
            gain=3.05,
            q=1.01,
        )
        assert band_matches(intended, read_back) is True

    def test_peak_freq_out_of_tolerance(self) -> None:
        """PEAK with frequency just outside tolerance → False."""
        intended = _make_filter(type_="PEAK", freq=1000.0, gain=3.0, q=1.0)
        read_back = _make_filter(type_="PEAK", freq=1000.1001, gain=3.0, q=1.0)
        assert band_matches(intended, read_back) is False

    def test_peak_gain_out_of_tolerance(self) -> None:
        """PEAK with gain just outside tolerance → False."""
        intended = _make_filter(type_="PEAK", freq=1000.0, gain=3.0, q=1.0)
        read_back = _make_filter(type_="PEAK", freq=1000.0, gain=3.0501, q=1.0)
        assert band_matches(intended, read_back) is False

    def test_peak_q_out_of_tolerance(self) -> None:
        """PEAK with Q just outside tolerance → False."""
        intended = _make_filter(type_="PEAK", freq=1000.0, gain=3.0, q=1.0)
        read_back = _make_filter(type_="PEAK", freq=1000.0, gain=3.0, q=1.0101)
        assert band_matches(intended, read_back) is False

    def test_ls_all_within_tolerance(self) -> None:
        """LS filter with all values within tolerance → True."""
        intended = _make_filter(type_="LS", freq=200.0, gain=-2.0, q=0.7)
        read_back = _make_filter(type_="LS", freq=200.05, gain=-2.03, q=0.705)
        assert band_matches(intended, read_back) is True

    def test_hs_all_within_tolerance(self) -> None:
        """HS filter with all values within tolerance → True."""
        intended = _make_filter(type_="HS", freq=8000.0, gain=1.5, q=0.5)
        read_back = _make_filter(type_="HS", freq=8000.09, gain=1.54, q=0.509)
        assert band_matches(intended, read_back) is True


# ---------------------------------------------------------------------------
# Property-based tests (Hypothesis)
# Validates: Requirements 5.6, 16.7
# ---------------------------------------------------------------------------


class TestFreqMatchesProperty:
    """Property tests for freq_matches.

    **Validates: Requirements 5.6, 16.7**
    """

    @given(
        center=st.floats(min_value=10.0, max_value=22000.0, allow_nan=False, allow_infinity=False),
        delta=st_float_near_boundary(0.0, FREQ_TOLERANCE_HZ),
    )
    @settings(max_examples=100)
    def test_freq_matches_iff_within_tolerance(self, center: float, delta: float) -> None:
        """freq_matches(a, b) returns True iff |a - b| <= FREQ_TOLERANCE_HZ + _FP_EPS."""
        b = center + delta
        expected = abs(delta) <= FREQ_TOLERANCE_HZ + _FP_EPS
        assert freq_matches(center, b) is expected


class TestGainMatchesProperty:
    """Property tests for gain_matches.

    **Validates: Requirements 5.6, 16.7**
    """

    @given(
        center=st.floats(min_value=-20.0, max_value=20.0, allow_nan=False, allow_infinity=False),
        delta=st_float_near_boundary(0.0, GAIN_TOLERANCE_DB),
    )
    @settings(max_examples=100)
    def test_gain_matches_iff_within_tolerance(self, center: float, delta: float) -> None:
        """gain_matches(a, b) returns True iff |a - b| <= GAIN_TOLERANCE_DB + _FP_EPS."""
        b = center + delta
        expected = abs(center - b) <= GAIN_TOLERANCE_DB + _FP_EPS
        assert gain_matches(center, b) is expected


class TestQMatchesProperty:
    """Property tests for q_matches.

    **Validates: Requirements 5.6, 16.7**
    """

    @given(
        center=st.floats(min_value=0.01, max_value=24.0, allow_nan=False, allow_infinity=False),
        delta=st_float_near_boundary(0.0, Q_TOLERANCE),
    )
    @settings(max_examples=100)
    def test_q_matches_iff_within_tolerance(self, center: float, delta: float) -> None:
        """q_matches(a, b) returns True iff |a - b| <= Q_TOLERANCE + _FP_EPS."""
        b = center + delta
        expected = abs(center - b) <= Q_TOLERANCE + _FP_EPS
        assert q_matches(center, b) is expected


class TestBandMatchesOffProperty:
    """Property tests for band_matches with OFF bands.

    **Validates: Requirements 5.6, 16.7**
    """

    @given(
        freq_a=st.floats(min_value=10.0, max_value=22000.0, allow_nan=False, allow_infinity=False),
        freq_b=st.floats(min_value=10.0, max_value=22000.0, allow_nan=False, allow_infinity=False),
        gain_a=st.floats(min_value=-20.0, max_value=20.0, allow_nan=False, allow_infinity=False),
        gain_b=st.floats(min_value=-20.0, max_value=20.0, allow_nan=False, allow_infinity=False),
        q_a=st.floats(min_value=0.01, max_value=24.0, allow_nan=False, allow_infinity=False),
        q_b=st.floats(min_value=0.01, max_value=24.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_off_bands_always_match(
        self,
        freq_a: float,
        freq_b: float,
        gain_a: float,
        gain_b: float,
        q_a: float,
        q_b: float,
    ) -> None:
        """band_matches with OFF type always returns True regardless of numeric values."""
        intended = CanonicalFilter(type="OFF", frequency_hz=freq_a, gain_db=gain_a, q=q_a)
        read_back = CanonicalFilter(type="OFF", frequency_hz=freq_b, gain_db=gain_b, q=q_b)
        assert band_matches(intended, read_back) is True


# Strategy for non-OFF filter types
_NON_OFF_TYPES = ["PEAK", "LS", "HS"]


class TestBandMatchesTypeMismatchProperty:
    """Property tests for band_matches with type mismatches.

    **Validates: Requirements 5.6, 16.7**
    """

    @given(
        type_a=st.sampled_from(_NON_OFF_TYPES),
        type_b=st.sampled_from(_NON_OFF_TYPES),
        freq=st.floats(min_value=10.0, max_value=22000.0, allow_nan=False, allow_infinity=False),
        gain=st.floats(min_value=-20.0, max_value=20.0, allow_nan=False, allow_infinity=False),
        q=st.floats(min_value=0.01, max_value=24.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_band_matches_type_mismatch_always_false(
        self,
        type_a: str,
        type_b: str,
        freq: float,
        gain: float,
        q: float,
    ) -> None:
        """band_matches with different non-OFF types always returns False."""
        from hypothesis import assume

        assume(type_a != type_b)
        intended = CanonicalFilter(type=type_a, frequency_hz=freq, gain_db=gain, q=q)
        read_back = CanonicalFilter(type=type_b, frequency_hz=freq, gain_db=gain, q=q)
        assert band_matches(intended, read_back) is False
