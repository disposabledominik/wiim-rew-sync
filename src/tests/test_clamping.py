"""Tests for src.utils.clamping."""

from __future__ import annotations

from src.utils.clamping import clamp, clamp_with_warning


class TestClamp:
    def test_within_range_returned_unchanged(self) -> None:
        assert clamp(5.0, 0.0, 10.0) == 5.0

    def test_above_range_clamped_to_hi(self) -> None:
        assert clamp(15.0, 0.0, 10.0) == 10.0

    def test_below_range_clamped_to_lo(self) -> None:
        assert clamp(-5.0, 0.0, 10.0) == 0.0

    def test_exact_boundary_values_returned_unchanged(self) -> None:
        assert clamp(10.0, 0.0, 10.0) == 10.0
        assert clamp(0.0, 0.0, 10.0) == 0.0


class TestClampWithWarning:
    def test_within_range_no_reason(self) -> None:
        value, reason = clamp_with_warning(5.0, -12.0, 12.0, "gain", unit=" dB", signed=True)
        assert value == 5.0
        assert reason is None

    def test_above_range_clamped_with_reason(self) -> None:
        value, reason = clamp_with_warning(15.0, -12.0, 12.0, "gain", unit=" dB", signed=True)
        assert value == 12.0
        assert reason is not None
        assert "gain" in reason
        assert "+12.0" in reason

    def test_below_range_clamped_with_reason(self) -> None:
        value, reason = clamp_with_warning(-15.0, -12.0, 12.0, "gain", unit=" dB", signed=True)
        assert value == -12.0
        assert reason is not None
        assert "-12.0" in reason

    def test_unsigned_bound_formatting(self) -> None:
        value, reason = clamp_with_warning(30.0, 0.01, 24.0, "Q")
        assert value == 24.0
        assert reason is not None
        assert "24" in reason
        assert "+" not in reason
