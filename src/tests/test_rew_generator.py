"""Unit tests for REWGenerator — CanonicalFilter list to REW text file generation."""

from pathlib import Path

import pytest

from src.models.canonical import CanonicalFilter
from src.translator._warnings import ValidationWarning
from src.translator.rew_generator import REWGenerator


@pytest.fixture
def generator() -> REWGenerator:
    return REWGenerator()


# ---------------------------------------------------------------------------
# First-line format
# ---------------------------------------------------------------------------


class TestFirstLineFormat:
    """Tests that the first line is exactly 'Equaliser: Parametric EQ'."""

    def test_first_line_is_header(self, generator: REWGenerator, tmp_path: Path) -> None:
        """The generated file must start with exactly 'Equaliser: Parametric EQ'."""
        filters = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-3.5, q=1.41),
        ]
        out = tmp_path / "eq.txt"
        generator.generate_file(filters, out)

        lines = out.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "Equaliser: Parametric EQ"

    def test_first_line_with_empty_filter_list(
        self, generator: REWGenerator, tmp_path: Path
    ) -> None:
        """Header is written even when there are no filters."""
        out = tmp_path / "eq.txt"
        generator.generate_file([], out)

        lines = out.read_text(encoding="utf-8").splitlines()
        assert lines[0] == "Equaliser: Parametric EQ"


# ---------------------------------------------------------------------------
# Band numbering
# ---------------------------------------------------------------------------


class TestBandNumbering:
    """Tests for 1-based, right-justified band numbering."""

    def test_single_digit_numbering(self, generator: REWGenerator, tmp_path: Path) -> None:
        """Single-digit numbers are right-justified (e.g. 'Filter  1:')."""
        filters = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-1.0, q=1.0),
        ]
        out = tmp_path / "eq.txt"
        generator.generate_file(filters, out)

        lines = out.read_text(encoding="utf-8").splitlines()
        assert lines[1].startswith("Filter  1:")

    def test_ten_bands_numbering(self, generator: REWGenerator, tmp_path: Path) -> None:
        """10 bands numbered Filter  1: through Filter 10:."""
        filters = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0 * (i + 1), gain_db=-1.0, q=1.0)
            for i in range(10)
        ]
        out = tmp_path / "eq.txt"
        generator.generate_file(filters, out)

        lines = out.read_text(encoding="utf-8").splitlines()
        # First band: right-justified single digit
        assert "Filter  1:" in lines[1]
        # Tenth band: two-digit number
        assert "Filter 10:" in lines[10]

    def test_numbering_is_one_based(self, generator: REWGenerator, tmp_path: Path) -> None:
        """Numbering starts at 1, not 0."""
        filters = [
            CanonicalFilter(type="PEAK", frequency_hz=200.0, gain_db=0.0, q=1.0),
            CanonicalFilter(type="LS", frequency_hz=80.0, gain_db=2.0, q=0.707),
        ]
        out = tmp_path / "eq.txt"
        generator.generate_file(filters, out)

        lines = out.read_text(encoding="utf-8").splitlines()
        assert "Filter  1:" in lines[1]
        assert "Filter  2:" in lines[2]


# ---------------------------------------------------------------------------
# Decimal precision
# ---------------------------------------------------------------------------


class TestDecimalPrecision:
    """Tests for gain/freq at 2 dp and Q at 3 dp."""

    def test_frequency_two_decimal_places(self, generator: REWGenerator, tmp_path: Path) -> None:
        """Frequency values are formatted with exactly 2 decimal places."""
        filters = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=0.0, q=1.0),
        ]
        out = tmp_path / "eq.txt"
        generator.generate_file(filters, out)

        content = out.read_text(encoding="utf-8")
        assert "100.00 Hz" in content

    def test_gain_two_decimal_places(self, generator: REWGenerator, tmp_path: Path) -> None:
        """Gain values are formatted with exactly 2 decimal places."""
        filters = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-3.5, q=1.0),
        ]
        out = tmp_path / "eq.txt"
        generator.generate_file(filters, out)

        content = out.read_text(encoding="utf-8")
        assert "-3.50 dB" in content

    def test_q_three_decimal_places(self, generator: REWGenerator, tmp_path: Path) -> None:
        """Q values are formatted with exactly 3 decimal places."""
        filters = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=0.0, q=1.41),
        ]
        out = tmp_path / "eq.txt"
        generator.generate_file(filters, out)

        content = out.read_text(encoding="utf-8")
        assert "1.410" in content

    def test_high_frequency_precision(self, generator: REWGenerator, tmp_path: Path) -> None:
        """Large frequency values still get 2 decimal places."""
        filters = [
            CanonicalFilter(type="PEAK", frequency_hz=10000.0, gain_db=0.0, q=1.0),
        ]
        out = tmp_path / "eq.txt"
        generator.generate_file(filters, out)

        content = out.read_text(encoding="utf-8")
        assert "10000.00 Hz" in content


# ---------------------------------------------------------------------------
# OFF band format
# ---------------------------------------------------------------------------


class TestOffBandFormat:
    """Tests for OFF band formatting: 'OFF PK Fc <freq> Hz Gain <gain> dB Q <q>'."""

    def test_off_band_uses_off_state(self, generator: REWGenerator, tmp_path: Path) -> None:
        """OFF bands should have 'OFF' state marker."""
        filters = [
            CanonicalFilter(type="OFF", frequency_hz=1000.0, gain_db=0.0, q=1.0),
        ]
        out = tmp_path / "eq.txt"
        generator.generate_file(filters, out)

        lines = out.read_text(encoding="utf-8").splitlines()
        assert "OFF PK" in lines[1]

    def test_off_band_preserves_values(self, generator: REWGenerator, tmp_path: Path) -> None:
        """OFF bands preserve frequency, gain, and Q values."""
        filters = [
            CanonicalFilter(type="OFF", frequency_hz=500.0, gain_db=-2.5, q=0.707),
        ]
        out = tmp_path / "eq.txt"
        generator.generate_file(filters, out)

        content = out.read_text(encoding="utf-8")
        assert "500.00 Hz" in content
        assert "-2.50 dB" in content
        assert "0.707" in content

    def test_off_band_uses_pk_type_token(self, generator: REWGenerator, tmp_path: Path) -> None:
        """OFF bands always use 'PK' as the default type token."""
        filters = [
            CanonicalFilter(type="OFF", frequency_hz=1000.0, gain_db=0.0, q=1.0),
        ]
        out = tmp_path / "eq.txt"
        generator.generate_file(filters, out)

        lines = out.read_text(encoding="utf-8").splitlines()
        # Should contain OFF PK, not OFF LS or OFF HS
        assert "OFF PK" in lines[1]


# ---------------------------------------------------------------------------
# L/R suffix naming
# ---------------------------------------------------------------------------


class TestLRSuffixNaming:
    """Tests for generate_lr_files producing files with _L and _R suffixes."""

    def test_lr_files_have_correct_suffixes(
        self, generator: REWGenerator, tmp_path: Path
    ) -> None:
        """L/R files are named with _L.txt and _R.txt suffixes."""
        filters_l = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-3.0, q=1.0),
        ]
        filters_r = [
            CanonicalFilter(type="PEAK", frequency_hz=200.0, gain_db=-2.0, q=1.5),
        ]
        base = tmp_path / "my_eq"

        left_path, right_path, _warnings = generator.generate_lr_files(filters_l, filters_r, base)

        assert left_path.name == "my_eq_L.txt"
        assert right_path.name == "my_eq_R.txt"

    def test_lr_files_exist_on_disk(self, generator: REWGenerator, tmp_path: Path) -> None:
        """Both L and R files are actually created."""
        filters_l = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-1.0, q=1.0),
        ]
        filters_r = [
            CanonicalFilter(type="LS", frequency_hz=80.0, gain_db=2.0, q=0.707),
        ]
        base = tmp_path / "export"

        left_path, right_path, _warnings = generator.generate_lr_files(filters_l, filters_r, base)

        assert left_path.exists()
        assert right_path.exists()

    def test_lr_files_contain_correct_data(
        self, generator: REWGenerator, tmp_path: Path
    ) -> None:
        """Left file has left filters and right file has right filters."""
        filters_l = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-3.0, q=1.0),
        ]
        filters_r = [
            CanonicalFilter(type="PEAK", frequency_hz=200.0, gain_db=-2.0, q=1.5),
        ]
        base = tmp_path / "export"

        left_path, right_path, _warnings = generator.generate_lr_files(filters_l, filters_r, base)

        left_content = left_path.read_text(encoding="utf-8")
        right_content = right_path.read_text(encoding="utf-8")

        assert "100.00 Hz" in left_content
        assert "200.00 Hz" in right_content

    def test_lr_returns_path_tuple(self, generator: REWGenerator, tmp_path: Path) -> None:
        """generate_lr_files returns a tuple of (left_path, right_path, warnings)."""
        filters_l = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=0.0, q=1.0),
        ]
        filters_r = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=0.0, q=1.0),
        ]
        base = tmp_path / "test"

        result = generator.generate_lr_files(filters_l, filters_r, base)

        assert isinstance(result, tuple)
        assert len(result) == 3
        assert isinstance(result[0], Path)
        assert isinstance(result[1], Path)
        assert isinstance(result[2], list)


# ---------------------------------------------------------------------------
# max_filters truncation
# ---------------------------------------------------------------------------


class TestMaxFilters:
    """Tests for max_filters truncation behaviour."""

    def test_truncates_to_max_filters(self, generator: REWGenerator, tmp_path: Path) -> None:
        """Only the first max_filters bands are written."""
        filters = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0 * (i + 1), gain_db=-1.0, q=1.0)
            for i in range(15)
        ]
        out = tmp_path / "eq.txt"
        generator.generate_file(filters, out, max_filters=10)

        lines = out.read_text(encoding="utf-8").splitlines()
        # Header + 10 filter lines
        assert len(lines) == 11

    def test_custom_max_filters(self, generator: REWGenerator, tmp_path: Path) -> None:
        """Custom max_filters value is respected."""
        filters = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0 * (i + 1), gain_db=-1.0, q=1.0)
            for i in range(10)
        ]
        out = tmp_path / "eq.txt"
        generator.generate_file(filters, out, max_filters=5)

        lines = out.read_text(encoding="utf-8").splitlines()
        # Header + 5 filter lines
        assert len(lines) == 6


# ---------------------------------------------------------------------------
# Type token mapping
# ---------------------------------------------------------------------------


class TestTypeTokenMapping:
    """Tests for correct reverse type mapping (Canonical → REW tokens)."""

    def test_peak_maps_to_pk(self, generator: REWGenerator, tmp_path: Path) -> None:
        """PEAK canonical type maps to PK in output."""
        filters = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=0.0, q=1.0),
        ]
        out = tmp_path / "eq.txt"
        generator.generate_file(filters, out)

        content = out.read_text(encoding="utf-8")
        assert "ON  PK" in content

    def test_ls_maps_to_ls(self, generator: REWGenerator, tmp_path: Path) -> None:
        """LS canonical type maps to LS in output."""
        filters = [
            CanonicalFilter(type="LS", frequency_hz=80.0, gain_db=2.0, q=0.707),
        ]
        out = tmp_path / "eq.txt"
        generator.generate_file(filters, out)

        content = out.read_text(encoding="utf-8")
        assert "ON  LS" in content

    def test_hs_maps_to_hs(self, generator: REWGenerator, tmp_path: Path) -> None:
        """HS canonical type maps to HS in output."""
        filters = [
            CanonicalFilter(type="HS", frequency_hz=10000.0, gain_db=-1.5, q=0.5),
        ]
        out = tmp_path / "eq.txt"
        generator.generate_file(filters, out)

        content = out.read_text(encoding="utf-8")
        assert "ON  HS" in content


# ---------------------------------------------------------------------------
# LP/HP filter type support
# ---------------------------------------------------------------------------


class TestLPHPTypeMapping:
    """Tests for LP and HP canonical types generating correct REW tokens."""

    def test_lp_maps_to_lp(self, generator: REWGenerator, tmp_path: Path) -> None:
        """LP canonical type maps to LP in output."""
        filters = [
            CanonicalFilter(type="LP", frequency_hz=5000.0, gain_db=0.0, q=0.707),
        ]
        out = tmp_path / "eq.txt"
        generator.generate_file(filters, out)

        content = out.read_text(encoding="utf-8")
        assert "ON  LP" in content
        assert "5000.00 Hz" in content

    def test_hp_maps_to_hp(self, generator: REWGenerator, tmp_path: Path) -> None:
        """HP canonical type maps to HP in output."""
        filters = [
            CanonicalFilter(type="HP", frequency_hz=80.0, gain_db=0.0, q=0.707),
        ]
        out = tmp_path / "eq.txt"
        generator.generate_file(filters, out)

        content = out.read_text(encoding="utf-8")
        assert "ON  HP" in content
        assert "80.00 Hz" in content

    def test_mixed_filters_with_lp_hp(self, generator: REWGenerator, tmp_path: Path) -> None:
        """A mix of PK, LP, HP filters all render correctly."""
        filters = [
            CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=-3.0, q=1.41),
            CanonicalFilter(type="LP", frequency_hz=5000.0, gain_db=0.0, q=0.707),
            CanonicalFilter(type="HP", frequency_hz=50.0, gain_db=0.0, q=0.707),
        ]
        out = tmp_path / "eq.txt"
        generator.generate_file(filters, out)

        lines = out.read_text(encoding="utf-8").splitlines()
        assert "ON  PK" in lines[1]
        assert "ON  LP" in lines[2]
        assert "ON  HP" in lines[3]


# ---------------------------------------------------------------------------
# LP/HP round-trip
# ---------------------------------------------------------------------------


class TestLPHPRoundTrip:
    """Round-trip: generate REW file with LP/HP then parse it back."""

    def test_lp_hp_round_trip(self, generator: REWGenerator, tmp_path: Path) -> None:
        """LP/HP filters survive generate → parse → compare."""
        from src.translator.rew_parser import REWParser

        original = [
            CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=-2.5, q=1.410),
            CanonicalFilter(type="LP", frequency_hz=5000.0, gain_db=0.0, q=0.707),
            CanonicalFilter(type="HP", frequency_hz=80.0, gain_db=0.0, q=0.707),
        ]
        out = tmp_path / "eq.txt"
        generator.generate_file(original, out)

        parser = REWParser()
        parsed = parser.parse_file(out)

        assert len(parsed) == len(original)
        for orig, back in zip(original, parsed, strict=True):
            assert orig.type == back.type
            assert orig.frequency_hz == pytest.approx(back.frequency_hz)
            assert orig.gain_db == pytest.approx(back.gain_db)
            assert orig.q == pytest.approx(back.q, abs=1e-3)


# ---------------------------------------------------------------------------
# UNKNOWN filter type skipping (forward compatibility)
# ---------------------------------------------------------------------------


class TestUnknownFilterSkipping:
    """Forward compatibility: UNKNOWN bands are skipped in REW export."""

    def test_unknown_bands_skipped_in_output(
        self, generator: REWGenerator, tmp_path: Path
    ) -> None:
        """UNKNOWN bands are omitted from the REW output file."""
        filters = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-3.0, q=1.41),
            CanonicalFilter(
                type="UNKNOWN", frequency_hz=500.0, gain_db=0.0, q=1.0, raw_mode=99
            ),
            CanonicalFilter(type="HS", frequency_hz=8000.0, gain_db=-1.5, q=0.71),
        ]
        out = tmp_path / "eq.txt"
        generator.generate_file(filters, out)

        lines = out.read_text(encoding="utf-8").splitlines()
        # Header + 2 filter lines (UNKNOWN skipped)
        assert len(lines) == 3
        assert "100.00 Hz" in lines[1]
        assert "8000.00 Hz" in lines[2]

    def test_sequential_numbering_after_skip(
        self, generator: REWGenerator, tmp_path: Path
    ) -> None:
        """Band numbering is sequential even after skipping UNKNOWN bands."""
        filters = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-3.0, q=1.41),
            CanonicalFilter(
                type="UNKNOWN", frequency_hz=500.0, gain_db=0.0, q=1.0, raw_mode=6
            ),
            CanonicalFilter(type="HS", frequency_hz=8000.0, gain_db=-1.5, q=0.71),
        ]
        out = tmp_path / "eq.txt"
        generator.generate_file(filters, out)

        lines = out.read_text(encoding="utf-8").splitlines()
        assert "Filter  1:" in lines[1]
        assert "Filter  2:" in lines[2]

    def test_all_unknown_produces_header_only(
        self, generator: REWGenerator, tmp_path: Path
    ) -> None:
        """If all bands are UNKNOWN, the file contains only the header."""
        filters = [
            CanonicalFilter(
                type="UNKNOWN", frequency_hz=500.0, gain_db=0.0, q=1.0, raw_mode=99
            ),
            CanonicalFilter(
                type="UNKNOWN", frequency_hz=1000.0, gain_db=0.0, q=1.0, raw_mode=6
            ),
        ]
        out = tmp_path / "eq.txt"
        generator.generate_file(filters, out)

        lines = out.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        assert lines[0] == "Equaliser: Parametric EQ"

    def test_unknown_band_returns_warning(
        self, generator: REWGenerator, tmp_path: Path
    ) -> None:
        """Each skipped UNKNOWN band produces a ValidationWarning."""
        filters = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-3.0, q=1.41),
            CanonicalFilter(
                type="UNKNOWN", frequency_hz=500.0, gain_db=0.0, q=1.0, raw_mode=99
            ),
            CanonicalFilter(type="HS", frequency_hz=8000.0, gain_db=-1.5, q=0.71),
        ]
        out = tmp_path / "eq.txt"
        warnings = generator.generate_file(filters, out)

        assert len(warnings) == 1
        assert isinstance(warnings[0], ValidationWarning)
        assert warnings[0].field == "type"
        assert warnings[0].original_value == 99
        assert "raw_mode=99" in warnings[0].message
        assert "500.0 Hz" in warnings[0].message

    def test_multiple_unknown_bands_return_multiple_warnings(
        self, generator: REWGenerator, tmp_path: Path
    ) -> None:
        """Multiple UNKNOWN bands produce one warning per skipped band."""
        filters = [
            CanonicalFilter(
                type="UNKNOWN", frequency_hz=500.0, gain_db=0.0, q=1.0, raw_mode=99
            ),
            CanonicalFilter(
                type="UNKNOWN", frequency_hz=1000.0, gain_db=0.0, q=1.0, raw_mode=6
            ),
        ]
        out = tmp_path / "eq.txt"
        warnings = generator.generate_file(filters, out)

        assert len(warnings) == 2
        assert warnings[0].original_value == 99
        assert warnings[1].original_value == 6

    def test_no_unknown_returns_empty_warnings(
        self, generator: REWGenerator, tmp_path: Path
    ) -> None:
        """When there are no UNKNOWN bands, an empty list is returned."""
        filters = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-3.0, q=1.41),
        ]
        out = tmp_path / "eq.txt"
        warnings = generator.generate_file(filters, out)

        assert warnings == []

    def test_lr_files_aggregate_warnings(
        self, generator: REWGenerator, tmp_path: Path
    ) -> None:
        """generate_lr_files aggregates warnings from both channels."""
        filters_l = [
            CanonicalFilter(
                type="UNKNOWN", frequency_hz=500.0, gain_db=0.0, q=1.0, raw_mode=99
            ),
        ]
        filters_r = [
            CanonicalFilter(
                type="UNKNOWN", frequency_hz=1000.0, gain_db=0.0, q=1.0, raw_mode=6
            ),
        ]
        base = tmp_path / "export"

        _left, _right, warnings = generator.generate_lr_files(filters_l, filters_r, base)

        assert len(warnings) == 2
        assert warnings[0].original_value == 99
        assert warnings[1].original_value == 6
