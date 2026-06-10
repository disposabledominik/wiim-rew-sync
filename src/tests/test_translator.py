"""Property-based tests for the Translation Engine round-trip invariants.

Tests:
  - REW parse-generate-parse round-trip
  - WiiM generate-parse round-trip
  - WiiM value clipping invariant
"""

from __future__ import annotations

from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.models.canonical import CanonicalFilter
from src.tests.conftest import st_canonical_filter_list
from src.translator.rew_generator import REWGenerator
from src.translator.rew_parser import REWParser
from src.translator.wiim_generator import generate_wiim_band_array
from src.translator.wiim_parser import parse_wiim_band_array

# ---------------------------------------------------------------------------
# Task 8: REW parse-generate-parse round-trip
# Validates: Requirements 16.6, 6.1, 6.3, 7.1, 7.2, 7.3, 7.4, 7.5
# ---------------------------------------------------------------------------


@given(filters=st_canonical_filter_list(min_size=1, max_size=10))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_rew_parse_generate_parse_round_trip(
    filters: list[CanonicalFilter], tmp_path: Path
) -> None:
    """**Validates: Requirements 16.6, 6.1, 6.3, 7.1, 7.2, 7.3, 7.4, 7.5**

    Property: for any valid CanonicalFilter list, REWGenerator.generate_file()
    then REWParser.parse_file() must return a list identical to the original
    (type, freq, gain, Q all match exactly after formatting precision).

    REW files format freq/gain to 2 dp and Q to 3 dp, so the round-trip
    comparison accounts for rounding by comparing within formatted precision.
    """
    file_path = tmp_path / "roundtrip.txt"

    generator = REWGenerator()
    parser = REWParser()

    # Generate REW file from filters
    generator.generate_file(filters, file_path)

    # Parse the generated file back
    parsed = parser.parse_file(file_path)

    # Must have same number of filters
    assert len(parsed) == len(filters)

    for original, roundtripped in zip(filters, parsed, strict=True):
        assert roundtripped.type == original.type

        # Frequency: REW formats to 2 dp — compare within that precision
        assert roundtripped.frequency_hz == round(original.frequency_hz, 2)

        # Gain: REW formats to 2 dp
        assert roundtripped.gain_db == round(original.gain_db, 2)

        # Q: REW formats to 3 dp
        assert roundtripped.q == round(original.q, 3)


# ---------------------------------------------------------------------------
# Task 11: WiiM generate-parse round-trip
# Validates: Requirements 16.7, 4.2, 4.4, 4.5
# ---------------------------------------------------------------------------


@st.composite
def st_canonical_filter_wiim_safe(draw: st.DrawFn) -> CanonicalFilter:
    """Generate a CanonicalFilter within WiiM limits (no clipping needed for round-trip)."""
    filter_type = draw(st.sampled_from(["PEAK", "LS", "HS", "OFF"]))
    freq = draw(st.floats(min_value=10.0, max_value=22000.0, allow_nan=False, allow_infinity=False))
    # Constrain gain and Q to WiiM limits so round-trip matches without clipping
    gain = draw(st.floats(min_value=-12.0, max_value=12.0, allow_nan=False, allow_infinity=False))
    q = draw(st.floats(min_value=0.01, max_value=24.0, allow_nan=False, allow_infinity=False))
    return CanonicalFilter(type=filter_type, frequency_hz=freq, gain_db=gain, q=q)  # type: ignore[arg-type]


@st.composite
def st_canonical_filter_list_wiim_safe(
    draw: st.DrawFn, min_size: int = 1, max_size: int = 10
) -> list[CanonicalFilter]:
    """Generate a list of WiiM-safe CanonicalFilters (gain/Q within hardware limits)."""
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    return [draw(st_canonical_filter_wiim_safe()) for _ in range(n)]


def _flat_array_to_band_dicts(flat: list[float]) -> list[dict[str, int | float | str]]:
    """Convert a 40-entry flat parameter array back to the band dict format expected by the parser.

    Each band has 4 entries: [mode, freq, gain, q].
    Returns a list of dicts with keys: mode, freq, gain, q.
    """
    bands: list[dict[str, int | float | str]] = []
    for i in range(0, len(flat), 4):
        bands.append({
            "mode": int(flat[i]),
            "freq": flat[i + 1],
            "gain": flat[i + 2],
            "q": flat[i + 3],
        })
    return bands


@given(filters=st_canonical_filter_list_wiim_safe(min_size=1, max_size=10))
@settings(max_examples=100)
def test_wiim_generate_parse_round_trip(filters: list[CanonicalFilter]) -> None:
    """**Validates: Requirements 16.7, 4.2, 4.4, 4.5**

    Property: for any valid CanonicalFilter list (with gain in [-12, 12] and
    Q in [0.01, 24] to avoid clipping), generate_wiim_band_array() then
    parse_wiim_band_array() must produce filters matching originals within
    tolerances (freq +/-0.1 Hz, gain +/-0.05 dB, Q +/-0.01).
    """
    # Generate the 40-entry flat array
    flat_array, _warnings = generate_wiim_band_array(filters)

    # Convert flat array to band dicts for the parser
    band_dicts = _flat_array_to_band_dicts(flat_array)

    # Parse back — only take the first len(filters) results (rest are OFF padding)
    parsed = parse_wiim_band_array(band_dicts)

    # The first len(filters) bands should match; the rest are OFF padding
    for i, (original, roundtripped) in enumerate(
        zip(filters, parsed[: len(filters)], strict=True)
    ):
        # Type must match exactly
        assert roundtripped.type == original.type, (
            f"Band {i}: type mismatch: {roundtripped.type} != {original.type}"
        )

        # Frequency within tolerance
        assert abs(roundtripped.frequency_hz - original.frequency_hz) <= 0.1, (
            f"Band {i}: freq {roundtripped.frequency_hz} "
            f"not within 0.1 Hz of {original.frequency_hz}"
        )

        # Gain within tolerance
        assert abs(roundtripped.gain_db - original.gain_db) <= 0.05, (
            f"Band {i}: gain {roundtripped.gain_db} not within 0.05 dB of {original.gain_db}"
        )

        # Q within tolerance
        assert abs(roundtripped.q - original.q) <= 0.01, (
            f"Band {i}: Q {roundtripped.q} not within 0.01 of {original.q}"
        )

    # Remaining bands should all be OFF
    for i in range(len(filters), len(parsed)):
        assert parsed[i].type == "OFF", f"Padding band {i} should be OFF"


# ---------------------------------------------------------------------------
# Task 12: WiiM value clipping invariant
# Validates: Requirements 6.7, 6.8, 16.3, 16.4
# ---------------------------------------------------------------------------


@st.composite
def st_canonical_filter_outside_wiim_limits(draw: st.DrawFn) -> CanonicalFilter:
    """Generate a CanonicalFilter with gain and/or Q OUTSIDE WiiM limits.

    At least one of gain or Q will exceed the hardware bounds.
    """
    filter_type = draw(st.sampled_from(["PEAK", "LS", "HS", "OFF"]))
    freq = draw(st.floats(min_value=10.0, max_value=22000.0, allow_nan=False, allow_infinity=False))

    # Generate gain outside [-12, 12] — either above +12 or below -12
    gain = draw(st.one_of(
        st.floats(min_value=12.01, max_value=50.0, allow_nan=False, allow_infinity=False),
        st.floats(min_value=-50.0, max_value=-12.01, allow_nan=False, allow_infinity=False),
    ))

    # Generate Q outside [0.01, 24] — either above 24 or below 0.01 (but > 0 for model validity)
    q = draw(st.one_of(
        st.floats(min_value=24.01, max_value=100.0, allow_nan=False, allow_infinity=False),
        # Q must be > 0 per model validator, so use just-below-0.01 range
        st.floats(min_value=0.001, max_value=0.009, allow_nan=False, allow_infinity=False),
    ))

    return CanonicalFilter(type=filter_type, frequency_hz=freq, gain_db=gain, q=q)  # type: ignore[arg-type]


@st.composite
def st_canonical_filter_list_outside_wiim_limits(
    draw: st.DrawFn, min_size: int = 1, max_size: int = 10
) -> list[CanonicalFilter]:
    """Generate a list of CanonicalFilters with values outside WiiM limits."""
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    return [draw(st_canonical_filter_outside_wiim_limits()) for _ in range(n)]


@given(filters=st_canonical_filter_list_outside_wiim_limits(min_size=1, max_size=10))
@settings(max_examples=100)
def test_wiim_value_clipping_invariant(filters: list[CanonicalFilter]) -> None:
    """**Validates: Requirements 6.7, 6.8, 16.3, 16.4**

    Property: generate_wiim_band_array() must ALWAYS produce entries with
    gain in [-12.0, +12.0] and Q in [0.01, 24.0], regardless of input values.
    The clipping ensures hardware limits are never exceeded.
    """
    flat_array, warnings = generate_wiim_band_array(filters)

    # The flat array has 40 entries: [mode, freq, gain, q] x 10 bands
    assert len(flat_array) == 40

    # Check every band's gain and Q values are within WiiM limits
    for band_idx in range(10):
        offset = band_idx * 4
        gain = flat_array[offset + 2]
        q = flat_array[offset + 3]

        assert -12.0 <= gain <= 12.0, (
            f"Band {band_idx + 1}: gain {gain} is outside [-12.0, +12.0]"
        )
        assert 0.01 <= q <= 24.0, (
            f"Band {band_idx + 1}: Q {q} is outside [0.01, 24.0]"
        )

    # There should be at least some warnings since all inputs are outside limits
    assert len(warnings) > 0, "Expected clipping warnings for out-of-range values"
