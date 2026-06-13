"""Unit tests for REWParser — REW text file and HTTP API FilterSetting parsing."""

from pathlib import Path

import pytest

from src.models.canonical import CanonicalFilter
from src.models.errors import ParseError, ValidationError
from src.translator.rew_parser import REWParser


@pytest.fixture
def parser() -> REWParser:
    return REWParser()


# ---------------------------------------------------------------------------
# Valid file parsing
# ---------------------------------------------------------------------------


class TestParseFileValid:
    """Tests for successfully parsing a valid REW EQ text file."""

    def test_valid_file_with_multiple_filters(self, parser: REWParser, tmp_path: Path) -> None:
        """Parse a valid REW file with PK, LS, HS filter types."""
        content = (
            "Equaliser: Parametric EQ\n"
            "Filter  1: ON  PK       Fc   100.00 Hz  Gain  -3.50 dB  Q  1.410\n"
            "Filter  2: ON  LS       Fc    80.00 Hz  Gain   2.00 dB  Q  0.707\n"
            "Filter  3: ON  HS       Fc 10000.00 Hz  Gain  -1.50 dB  Q  0.500\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters = parser.parse_file(file)

        assert len(filters) == 3
        assert filters[0] == CanonicalFilter(
            type="PEAK", frequency_hz=100.0, gain_db=-3.5, q=1.41
        )
        assert filters[1] == CanonicalFilter(
            type="LS", frequency_hz=80.0, gain_db=2.0, q=0.707
        )
        assert filters[2] == CanonicalFilter(
            type="HS", frequency_hz=10000.0, gain_db=-1.5, q=0.5
        )

    def test_off_filter_maps_to_off_type(self, parser: REWParser, tmp_path: Path) -> None:
        """Disabled filters (OFF) should map to type='OFF' regardless of the type token."""
        content = (
            "Equaliser: Parametric EQ\n"
            "Filter  4: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters = parser.parse_file(file)

        assert len(filters) == 1
        assert filters[0].type == "OFF"
        assert filters[0].frequency_hz == 1000.0
        assert filters[0].gain_db == 0.0
        assert filters[0].q == 1.0

    def test_all_type_mappings(self, parser: REWParser, tmp_path: Path) -> None:
        """Verify PK→PEAK, LS→LS, HS→HS mappings for enabled filters."""
        content = (
            "Equaliser: Parametric EQ\n"
            "Filter  1: ON  PK       Fc   100.00 Hz  Gain  -1.00 dB  Q  1.000\n"
            "Filter  2: ON  LS       Fc    50.00 Hz  Gain   2.00 dB  Q  0.707\n"
            "Filter  3: ON  HS       Fc  8000.00 Hz  Gain  -2.00 dB  Q  0.500\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters = parser.parse_file(file)

        assert filters[0].type == "PEAK"
        assert filters[1].type == "LS"
        assert filters[2].type == "HS"

    def test_blank_lines_are_skipped(self, parser: REWParser, tmp_path: Path) -> None:
        """Blank lines between filter entries should be ignored."""
        content = (
            "Equaliser: Parametric EQ\n"
            "\n"
            "Filter  1: ON  PK       Fc   200.00 Hz  Gain  -1.00 dB  Q  1.000\n"
            "\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters = parser.parse_file(file)
        assert len(filters) == 1


# ---------------------------------------------------------------------------
# Error: wrong header
# ---------------------------------------------------------------------------


class TestParseFileHeaderError:
    """Tests for ParseError when the header is wrong or missing."""

    def test_wrong_header_raises_parse_error(self, parser: REWParser, tmp_path: Path) -> None:
        content = "Equaliser: Graphic EQ\nFilter  1: ON  PK Fc 100.00 Hz  Gain -1.00 dB  Q 1.000\n"
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        with pytest.raises(ParseError) as exc_info:
            parser.parse_file(file)
        assert exc_info.value.line_number == 1

    def test_empty_file_raises_parse_error(self, parser: REWParser, tmp_path: Path) -> None:
        file = tmp_path / "eq.txt"
        file.write_text("", encoding="utf-8")

        with pytest.raises(ParseError) as exc_info:
            parser.parse_file(file)
        assert exc_info.value.line_number == 1


# ---------------------------------------------------------------------------
# Error: malformed filter line
# ---------------------------------------------------------------------------


class TestParseFileMalformedLine:
    """Tests for ParseError on malformed lines."""

    def test_malformed_line_raises_parse_error(self, parser: REWParser, tmp_path: Path) -> None:
        content = (
            "Equaliser: Parametric EQ\n"
            "This is not a valid filter line\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        with pytest.raises(ParseError) as exc_info:
            parser.parse_file(file)
        assert exc_info.value.line_number == 2
        assert "Malformed" in str(exc_info.value)

    def test_missing_q_value_raises_parse_error(self, parser: REWParser, tmp_path: Path) -> None:
        content = (
            "Equaliser: Parametric EQ\n"
            "Filter  1: ON  PK       Fc   100.00 Hz  Gain  -3.50 dB\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        with pytest.raises(ParseError) as exc_info:
            parser.parse_file(file)
        assert exc_info.value.line_number == 2


# ---------------------------------------------------------------------------
# Error: frequency out of range
# ---------------------------------------------------------------------------


class TestParseFileFrequencyError:
    """Tests for ValidationError on out-of-range frequency."""

    def test_frequency_below_10_raises_validation_error(
        self, parser: REWParser, tmp_path: Path
    ) -> None:
        content = (
            "Equaliser: Parametric EQ\n"
            "Filter  1: ON  PK       Fc     5.00 Hz  Gain  -1.00 dB  Q  1.000\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        with pytest.raises(ValidationError, match="outside valid range"):
            parser.parse_file(file)

    def test_frequency_above_22000_raises_validation_error(
        self, parser: REWParser, tmp_path: Path
    ) -> None:
        content = (
            "Equaliser: Parametric EQ\n"
            "Filter  1: ON  PK       Fc 25000.00 Hz  Gain  -1.00 dB  Q  1.000\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        with pytest.raises(ValidationError, match="outside valid range"):
            parser.parse_file(file)


# ---------------------------------------------------------------------------
# Error: unknown type token
# ---------------------------------------------------------------------------


class TestParseFileUnknownType:
    """Tests for ValidationError on unknown filter type tokens."""

    def test_unknown_type_raises_validation_error(
        self, parser: REWParser, tmp_path: Path
    ) -> None:
        content = (
            "Equaliser: Parametric EQ\n"
            "Filter  1: ON  BP       Fc   100.00 Hz  Gain  -1.00 dB  Q  1.000\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        with pytest.raises(ValidationError, match="Unknown filter type 'BP'"):
            parser.parse_file(file)


# ---------------------------------------------------------------------------
# parse_filter_settings (REW HTTP API)
# ---------------------------------------------------------------------------


class TestParseFilterSettings:
    """Tests for parsing REW HTTP API FilterSetting objects."""

    def test_valid_filter_settings(self, parser: REWParser) -> None:
        settings = [
            {"enabled": True, "type": "PK", "frequency": 1000.0, "gain": -3.5, "q": 1.41},
            {"enabled": True, "type": "LS", "frequency": 80.0, "gain": 3.0, "q": 0.707},
            {"enabled": True, "type": "HS", "frequency": 10000.0, "gain": -1.5, "q": 0.5},
        ]

        filters = parser.parse_filter_settings(settings)

        assert len(filters) == 3
        assert filters[0] == CanonicalFilter(
            type="PEAK", frequency_hz=1000.0, gain_db=-3.5, q=1.41
        )
        assert filters[1] == CanonicalFilter(
            type="LS", frequency_hz=80.0, gain_db=3.0, q=0.707
        )
        assert filters[2] == CanonicalFilter(
            type="HS", frequency_hz=10000.0, gain_db=-1.5, q=0.5
        )

    def test_disabled_filter_maps_to_off(self, parser: REWParser) -> None:
        settings = [
            {"enabled": False, "type": "PK", "frequency": 200.0, "gain": 0.0, "q": 1.0},
        ]

        filters = parser.parse_filter_settings(settings)

        assert filters[0].type == "OFF"
        assert filters[0].frequency_hz == 200.0

    def test_on_field_variant(self, parser: REWParser) -> None:
        """The REW API also uses 'on' instead of 'enabled' and 'freq' instead of 'frequency'."""
        settings = [
            {"on": True, "type": "PK", "freq": 500.0, "gain": -2.0, "q": 1.5},
            {"on": False, "type": "HS", "freq": 8000.0, "gain": 0.0, "q": 0.707},
        ]

        filters = parser.parse_filter_settings(settings)

        assert filters[0].type == "PEAK"
        assert filters[0].frequency_hz == 500.0
        assert filters[1].type == "OFF"

    def test_unknown_type_raises_validation_error(self, parser: REWParser) -> None:
        settings = [
            {"enabled": True, "type": "NO", "frequency": 100.0, "gain": 0.0, "q": 1.0},
        ]

        with pytest.raises(ValidationError, match="Unknown filter type 'NO'"):
            parser.parse_filter_settings(settings)

    def test_frequency_out_of_range_raises_validation_error(self, parser: REWParser) -> None:
        settings = [
            {"enabled": True, "type": "PK", "frequency": 5.0, "gain": 0.0, "q": 1.0},
        ]

        with pytest.raises(ValidationError, match="outside valid range"):
            parser.parse_filter_settings(settings)


# ---------------------------------------------------------------------------
# LP/HP filter type support
# ---------------------------------------------------------------------------


class TestParseFileLPHP:
    """Tests for LP and HP filter type parsing."""

    def test_lp_filter_maps_to_lp(self, parser: REWParser, tmp_path: Path) -> None:
        """LP token in REW file maps to canonical type 'LP'."""
        content = (
            "Equaliser: Parametric EQ\n"
            "Filter  1: ON  LP       Fc   200.00 Hz  Gain   0.00 dB  Q  0.707\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters = parser.parse_file(file)

        assert len(filters) == 1
        assert filters[0] == CanonicalFilter(
            type="LP", frequency_hz=200.0, gain_db=0.0, q=0.707
        )

    def test_hp_filter_maps_to_hp(self, parser: REWParser, tmp_path: Path) -> None:
        """HP token in REW file maps to canonical type 'HP'."""
        content = (
            "Equaliser: Parametric EQ\n"
            "Filter  1: ON  HP       Fc    80.00 Hz  Gain   0.00 dB  Q  0.707\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters = parser.parse_file(file)

        assert len(filters) == 1
        assert filters[0] == CanonicalFilter(
            type="HP", frequency_hz=80.0, gain_db=0.0, q=0.707
        )

    def test_mixed_file_with_lp_hp(self, parser: REWParser, tmp_path: Path) -> None:
        """A file with PK, LP, and HP filters parses all correctly."""
        content = (
            "Equaliser: Parametric EQ\n"
            "Filter  1: ON  PK       Fc  1000.00 Hz  Gain  -3.00 dB  Q  1.410\n"
            "Filter  2: ON  LP       Fc  5000.00 Hz  Gain   0.00 dB  Q  0.707\n"
            "Filter  3: ON  HP       Fc    50.00 Hz  Gain   0.00 dB  Q  0.707\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters = parser.parse_file(file)

        assert len(filters) == 3
        assert filters[0].type == "PEAK"
        assert filters[1].type == "LP"
        assert filters[1].frequency_hz == 5000.0
        assert filters[2].type == "HP"
        assert filters[2].frequency_hz == 50.0

    def test_off_lp_maps_to_off(self, parser: REWParser, tmp_path: Path) -> None:
        """Disabled LP filter maps to type='OFF'."""
        content = (
            "Equaliser: Parametric EQ\n"
            "Filter  1: OFF LP       Fc   200.00 Hz  Gain   0.00 dB  Q  0.707\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters = parser.parse_file(file)

        assert filters[0].type == "OFF"
        assert filters[0].frequency_hz == 200.0


class TestParseFilterSettingsLPHP:
    """Tests for LP/HP parsing from REW HTTP API FilterSetting objects."""

    def test_lp_api_filter(self, parser: REWParser) -> None:
        """LP type in API settings maps to canonical 'LP'."""
        settings = [
            {"enabled": True, "type": "LP", "frequency": 5000.0, "gain": 0.0, "q": 0.707},
        ]

        filters = parser.parse_filter_settings(settings)

        assert filters[0] == CanonicalFilter(
            type="LP", frequency_hz=5000.0, gain_db=0.0, q=0.707
        )

    def test_hp_api_filter(self, parser: REWParser) -> None:
        """HP type in API settings maps to canonical 'HP'."""
        settings = [
            {"enabled": True, "type": "HP", "frequency": 80.0, "gain": 0.0, "q": 0.707},
        ]

        filters = parser.parse_filter_settings(settings)

        assert filters[0] == CanonicalFilter(
            type="HP", frequency_hz=80.0, gain_db=0.0, q=0.707
        )
