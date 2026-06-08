"""Unit tests for floating-point tolerance predicates (src/utils/fp_compare.py).

Tests verify exact boundary behaviour: pass at ε, fail at ε + 0.0001.
"""

from __future__ import annotations

from src.models.canonical import CanonicalFilter
from src.utils.fp_compare import (
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
