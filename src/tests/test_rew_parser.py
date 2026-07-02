"""Unit tests for REWParser — REW text file and HTTP API FilterSetting parsing.

Covers both the simple 'Equaliser: Parametric EQ' format and the full
REW "Filter Settings file" export format with preamble, various filter types,
and duplicate measurement sections.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.models.canonical import CanonicalFilter
from src.models.errors import ParseError, ValidationError
from src.translator.rew_parser import REWParser


@pytest.fixture
def parser() -> REWParser:
    return REWParser()


# ---------------------------------------------------------------------------
# Valid file parsing (legacy simple format)
# ---------------------------------------------------------------------------


class TestParseFileValid:
    """Tests for successfully parsing a valid REW EQ text file (legacy format)."""

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
        """Verify PK->PEAK, LS->LS, HS->HS mappings for enabled filters."""
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
# Real REW export format: preamble and Equaliser header
# ---------------------------------------------------------------------------


class TestParseFileRealFormat:
    """Tests for the full REW 'Filter Settings file' export format."""

    def test_generic_peq_only(self, parser: REWParser) -> None:
        """Parse docs/rew_export_examples/generic_peq_only.txt."""
        file = Path("docs/rew_export_examples/generic_peq_only.txt")
        filters = parser.parse_file(file)

        # 6 PK filters + 14 None filters, but stop at duplicate section
        # Filters 1-6 are PK, 7-20 are None, then Filter 1/2 repeat (stop)
        assert len(filters) == 20
        assert filters[0].type == "PEAK"
        assert filters[0].frequency_hz == 48.0
        assert filters[0].gain_db == -12.0
        assert filters[0].q == 5.0
        assert filters[5].type == "PEAK"
        assert filters[5].frequency_hz == 277.0
        assert filters[5].gain_db == -4.0
        # Filters 7-20 are None -> OFF
        for i in range(6, 20):
            assert filters[i].type == "OFF"

    def test_configurable_peq(self, parser: REWParser) -> None:
        """Parse docs/rew_export_examples/configurable_peq.txt."""
        file = Path("docs/rew_export_examples/configurable_peq.txt")
        filters = parser.parse_file(file)

        # 10 filters total (no duplicate section in this file)
        assert len(filters) == 10
        # Filter 1 is None
        assert filters[0].type == "OFF"
        # Filter 2 is PK at 50 Hz
        assert filters[1].type == "PEAK"
        assert filters[1].frequency_hz == 50.0
        assert filters[1].gain_db == 3.0
        assert filters[1].q == 3.0
        # Filter 5 is PK at 300 Hz
        assert filters[4].type == "PEAK"
        assert filters[4].frequency_hz == 300.0
        assert filters[4].gain_db == -6.0
        assert filters[4].q == 10.0

    def test_generic_with_hp_lp(self, parser: REWParser) -> None:
        """Parse docs/rew_export_examples/generic_with_hp_lp.txt."""
        file = Path("docs/rew_export_examples/generic_with_hp_lp.txt")
        filters = parser.parse_file(file)

        # 20 filters before duplicate section
        assert len(filters) == 20
        # Filter 1: HP Q at 20 Hz, Q 0.71
        assert filters[0].type == "HP"
        assert filters[0].frequency_hz == 20.0
        assert filters[0].gain_db == 0.0
        assert filters[0].q == 0.71
        # Filter 2: PK at 50 Hz
        assert filters[1].type == "PEAK"
        assert filters[1].frequency_hz == 50.0
        assert filters[1].gain_db == 3.0
        # Filter 3: LS Q at 100 Hz
        assert filters[2].type == "LS"
        assert filters[2].frequency_hz == 100.0
        assert filters[2].gain_db == -3.0
        assert filters[2].q == 0.71
        # Filter 7: HS Q at 1000 Hz
        assert filters[6].type == "HS"
        assert filters[6].frequency_hz == 1000.0
        assert filters[6].gain_db == -2.0
        assert filters[6].q == 0.71
        # Filter 9: LP Q at 10000 Hz
        assert filters[8].type == "LP"
        assert filters[8].frequency_hz == 10000.0
        assert filters[8].gain_db == 0.0
        assert filters[8].q == 0.71

    def test_generic_with_all_types(self, parser: REWParser) -> None:
        """Parse docs/rew_export_examples/generic_with_all_types.txt.

        Filters 4, 5, 8, 9 (LS 12dB, HS 12dB, bare LS, bare HS) all use REW's
        shelf-slope S parameter rather than Q, which has no validated WiiM
        equivalent — so they're skipped, alongside filter 10 (All pass).
        """
        file = Path("docs/rew_export_examples/generic_with_all_types.txt")
        filters, warnings = parser.parse_file_with_warnings(file)

        assert len(filters) == 15
        assert len(warnings) == 5
        assert "LS 12dB" in warnings[0].message
        assert "HS 12dB" in warnings[1].message
        assert "LS" in warnings[2].message
        assert "HS" in warnings[3].message
        assert "All pass" in warnings[4].message

        # Filter 1: HP Butterworth at 40 Hz
        assert filters[0].type == "HP"
        assert filters[0].frequency_hz == 40.0
        assert filters[0].gain_db == 0.0
        assert filters[0].q == 0.7071

        # Filter 2: PK at 44 Hz
        assert filters[1].type == "PEAK"
        assert filters[1].frequency_hz == 44.0
        assert filters[1].gain_db == -11.0
        assert filters[1].q == 5.0

        # Filter 3: LP Butterworth at 126 Hz
        assert filters[2].type == "LP"
        assert filters[2].frequency_hz == 126.0
        assert filters[2].gain_db == 0.0
        assert filters[2].q == 0.7071

        # Filter 6: PK at 186 Hz (filters 4/5 were skipped LS 12dB/HS 12dB)
        assert filters[3].type == "PEAK"
        assert filters[3].frequency_hz == 186.0

        # Filter 7: PK at 277 Hz
        assert filters[4].type == "PEAK"
        assert filters[4].frequency_hz == 277.0

        # Filters 11-20: None -> OFF (filters 8/9/10 were skipped LS/HS/All pass)
        for i in range(5, 15):
            assert filters[i].type == "OFF"

    def test_real_14band_measurement(self, parser: REWParser) -> None:
        """Parse docs/rew_export_examples/real_14band_measurement.txt."""
        file = Path("docs/rew_export_examples/real_14band_measurement.txt")
        filters = parser.parse_file(file)

        # 20 filters before duplicate section
        assert len(filters) == 20
        # Filter 1: PK at 25.80 Hz
        assert filters[0].type == "PEAK"
        assert filters[0].frequency_hz == 25.8
        assert filters[0].gain_db == -1.4
        assert filters[0].q == 3.325
        # Filter 10: HS Q at 250 Hz
        assert filters[9].type == "HS"
        assert filters[9].frequency_hz == 250.0
        assert filters[9].gain_db == -4.0
        assert filters[9].q == 0.8
        # Filter 14: None
        assert filters[13].type == "OFF"
        # Filters 15-20: OFF (state=OFF, body=None)
        for i in range(14, 20):
            assert filters[i].type == "OFF"

    def test_preamble_skipped(self, parser: REWParser, tmp_path: Path) -> None:
        """Preamble lines before Equaliser: are skipped."""
        content = (
            "Filter Settings file\n"
            "\n"
            "Room EQ V5.40 Beta 125\n"
            "Dated: 2026 Jun 13 22:11:11\n"
            "\n"
            "Notes:\n"
            "\n"
            "Equaliser: Generic\n"
            "Filter  1: ON  PK       Fc   100.00 Hz  Gain  -3.00 dB  Q  2.000\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters = parser.parse_file(file)
        assert len(filters) == 1
        assert filters[0].type == "PEAK"
        assert filters[0].frequency_hz == 100.0

    def test_any_equaliser_type_accepted(self, parser: REWParser, tmp_path: Path) -> None:
        """Any Equaliser type string is accepted (Generic, Configurable PEQ, etc.)."""
        for eq_type in ["Generic", "Configurable PEQ", "Parametric EQ", "Something New"]:
            content = (
                f"Equaliser: {eq_type}\n"
                "Filter  1: ON  PK       Fc   200.00 Hz  Gain  -1.00 dB  Q  1.000\n"
            )
            file = tmp_path / "eq.txt"
            file.write_text(content, encoding="utf-8")

            filters = parser.parse_file(file)
            assert len(filters) == 1

    def test_duplicate_section_stops_parsing(self, parser: REWParser, tmp_path: Path) -> None:
        """When a filter number repeats, parsing stops (duplicate section)."""
        content = (
            "Equaliser: Generic\n"
            "Filter  1: ON  PK       Fc   100.00 Hz  Gain  -3.00 dB  Q  2.000\n"
            "Filter  2: ON  PK       Fc   200.00 Hz  Gain  -2.00 dB  Q  1.000\n"
            "Filter  3: ON  None   \n"
            "Filter  1: ON  PK       Fc   999.00 Hz  Gain  -9.00 dB  Q  9.000\n"
            "Filter  2: ON  None   \n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters = parser.parse_file(file)
        # Should only get filters 1-3 from first section
        assert len(filters) == 3
        assert filters[0].frequency_hz == 100.0
        assert filters[1].frequency_hz == 200.0

    def test_integer_frequency(self, parser: REWParser, tmp_path: Path) -> None:
        """Frequency can be integer (50 Hz) or decimal (50.00 Hz)."""
        content = (
            "Equaliser: Configurable PEQ\n"
            "Filter  1: ON  PK       Fc      50 Hz  Gain    3.0 dB  Q    3.0\n"
            "Filter  2: ON  PK       Fc   50.00 Hz  Gain    3.0 dB  Q    3.0\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters = parser.parse_file(file)
        assert len(filters) == 2
        assert filters[0].frequency_hz == 50.0
        assert filters[1].frequency_hz == 50.0

    def test_non_filter_lines_after_header_skipped(
        self, parser: REWParser, tmp_path: Path
    ) -> None:
        """Lines like 'L+R+Sub (closed)' or 'No measurement' are silently skipped."""
        content = (
            "Equaliser: Generic\n"
            "L+R+Sub (closed)\n"
            "Filter  1: ON  PK       Fc   100.00 Hz  Gain  -3.00 dB  Q  2.000\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters = parser.parse_file(file)
        assert len(filters) == 1


# ---------------------------------------------------------------------------
# Filter type variants
# ---------------------------------------------------------------------------


class TestFilterTypeVariants:
    """Tests for various filter line formats."""

    def test_hp_butterworth(self, parser: REWParser, tmp_path: Path) -> None:
        """HP Fc <freq> Hz (Butterworth, no Q) -> HP with REW's documented Q=0.7071."""
        content = (
            "Equaliser: Generic\n"
            "Filter  1: ON  HP       Fc   40.00 Hz \n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters = parser.parse_file(file)
        assert filters[0].type == "HP"
        assert filters[0].frequency_hz == 40.0
        assert filters[0].gain_db == 0.0
        assert filters[0].q == 0.7071

    def test_lp_butterworth(self, parser: REWParser, tmp_path: Path) -> None:
        """LP Fc <freq> Hz (Butterworth, no Q) -> LP with REW's documented Q=0.7071."""
        content = (
            "Equaliser: Generic\n"
            "Filter  1: ON  LP       Fc  126.00 Hz \n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters = parser.parse_file(file)
        assert filters[0].type == "LP"
        assert filters[0].frequency_hz == 126.0
        assert filters[0].gain_db == 0.0
        assert filters[0].q == 0.7071

    def test_bare_hp_butterworth_surfaces_conversion_note(
        self, parser: REWParser, tmp_path: Path
    ) -> None:
        """Bare HP (no Q in source) gets a conversion note about the default Q.

        Unlike HP Q (a direct, lossless match), the fixed Butterworth Q is a
        substituted value -- this must be visible to the user, not silent.
        """
        content = (
            "Equaliser: Generic\n"
            "Filter  1: ON  HP       Fc   40.00 Hz \n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        _filters, _warnings, _rows, notes = parser.parse_file_with_rows(file)
        assert 0 in notes
        assert "0.7071" in notes[0][0]
        assert "HP" in notes[0][0]

    def test_hp_q_does_not_surface_a_conversion_note(
        self, parser: REWParser, tmp_path: Path
    ) -> None:
        """HP Q (explicit Q in source) is a direct match -- no conversion note."""
        content = (
            "Equaliser: Generic\n"
            "Filter  1: ON  HP Q     Fc   40.00 Hz  Q   0.71\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        _filters, _warnings, _rows, notes = parser.parse_file_with_rows(file)
        assert notes == {}

    def test_hp_q(self, parser: REWParser, tmp_path: Path) -> None:
        """HP Q Fc <freq> Hz Q <q> -> HP with specified Q, gain=0."""
        content = (
            "Equaliser: Generic\n"
            "Filter  1: ON  HP Q     Fc   20.00 Hz  Q   0.71\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters = parser.parse_file(file)
        assert filters[0].type == "HP"
        assert filters[0].frequency_hz == 20.0
        assert filters[0].gain_db == 0.0
        assert filters[0].q == 0.71

    def test_lp_q(self, parser: REWParser, tmp_path: Path) -> None:
        """LP Q Fc <freq> Hz Q <q> -> LP with specified Q, gain=0."""
        content = (
            "Equaliser: Generic\n"
            "Filter  1: ON  LP Q     Fc 10000.00 Hz  Q   0.71\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters = parser.parse_file(file)
        assert filters[0].type == "LP"
        assert filters[0].frequency_hz == 10000.0
        assert filters[0].gain_db == 0.0
        assert filters[0].q == 0.71

    def test_ls_q(self, parser: REWParser, tmp_path: Path) -> None:
        """LS Q Fc <freq> Hz Gain <gain> dB Q <q> -> LS with specified Q."""
        content = (
            "Equaliser: Generic\n"
            "Filter  1: ON  LS Q     Fc  100.00 Hz  Gain   -3.0 dB Q   0.71\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters = parser.parse_file(file)
        assert filters[0].type == "LS"
        assert filters[0].frequency_hz == 100.0
        assert filters[0].gain_db == -3.0
        assert filters[0].q == 0.71

    def test_hs_q(self, parser: REWParser, tmp_path: Path) -> None:
        """HS Q Fc <freq> Hz Gain <gain> dB Q <q> -> HS with specified Q."""
        content = (
            "Equaliser: Generic\n"
            "Filter  1: ON  HS Q     Fc 1000.00 Hz  Gain   -2.0 dB Q   0.71\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters = parser.parse_file(file)
        assert filters[0].type == "HS"
        assert filters[0].frequency_hz == 1000.0
        assert filters[0].gain_db == -2.0
        assert filters[0].q == 0.71

    def test_ls_12db_unsupported(self, parser: REWParser, tmp_path: Path) -> None:
        """LS 12dB uses REW's shelf-slope S parameter, not Q -> skipped, not approximated."""
        content = (
            "Equaliser: Generic\n"
            "Filter  1: ON  LS 12dB  Fc  126.00 Hz  Gain   -2.0 dB\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters, warnings = parser.parse_file_with_warnings(file)
        assert len(filters) == 0
        assert len(warnings) == 1
        assert "LS 12dB" in warnings[0].message

    def test_hs_12db_unsupported(self, parser: REWParser, tmp_path: Path) -> None:
        """HS 12dB uses REW's shelf-slope S parameter, not Q -> skipped, not approximated."""
        content = (
            "Equaliser: Generic\n"
            "Filter  1: ON  HS 12dB  Fc  137.00 Hz  Gain    2.0 dB\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters, warnings = parser.parse_file_with_warnings(file)
        assert len(filters) == 0
        assert len(warnings) == 1
        assert "HS 12dB" in warnings[0].message

    def test_ls_fixed_slope_unsupported(self, parser: REWParser, tmp_path: Path) -> None:
        """Bare LS (fixed slope) uses REW's shelf-slope S parameter, not Q -> skipped."""
        content = (
            "Equaliser: Generic\n"
            "Filter  1: ON  LS       Fc  100.00 Hz  Gain   -5.0 dB\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters, warnings = parser.parse_file_with_warnings(file)
        assert len(filters) == 0
        assert len(warnings) == 1
        assert "LS" in warnings[0].message

    def test_hs_fixed_slope_unsupported(self, parser: REWParser, tmp_path: Path) -> None:
        """Bare HS (fixed slope) uses REW's shelf-slope S parameter, not Q -> skipped."""
        content = (
            "Equaliser: Generic\n"
            "Filter  1: ON  HS       Fc 10000.00 Hz  Gain    3.0 dB\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters, warnings = parser.parse_file_with_warnings(file)
        assert len(filters) == 0
        assert len(warnings) == 1
        assert "HS" in warnings[0].message

    def test_none_filter(self, parser: REWParser, tmp_path: Path) -> None:
        """None filter -> OFF type."""
        content = (
            "Equaliser: Generic\n"
            "Filter  1: ON  None   \n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters = parser.parse_file(file)
        assert filters[0].type == "OFF"


# ---------------------------------------------------------------------------
# Unsupported filter types (warnings, not crashes)
# ---------------------------------------------------------------------------


class TestUnsupportedFilterTypes:
    """Tests for unsupported filter types emitting warnings and being skipped."""

    def test_all_pass_emits_warning(self, parser: REWParser, tmp_path: Path) -> None:
        """All pass filter emits a warning and is skipped."""
        content = (
            "Equaliser: Generic\n"
            "Filter  1: ON  PK       Fc   100.00 Hz  Gain  -3.00 dB  Q  2.000\n"
            "Filter  2: ON  All pass  Fc  160.00 Hz  Q   0.71\n"
            "Filter  3: ON  PK       Fc   200.00 Hz  Gain  -1.00 dB  Q  1.000\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters, warnings = parser.parse_file_with_warnings(file)
        assert len(filters) == 2  # All pass skipped
        assert len(warnings) == 1
        assert "All pass" in warnings[0].message
        assert filters[0].frequency_hz == 100.0
        assert filters[1].frequency_hz == 200.0

    def test_all_pass_hyphenated_input_normalizes_to_space(
        self, parser: REWParser, tmp_path: Path
    ) -> None:
        """A hyphenated 'All-pass' token is tolerated but normalized to 'All pass'
        on output, matching the label the live-API path reports (REW's API
        always uses the space form).
        """
        content = (
            "Equaliser: Generic\n"
            "Filter  1: ON  All-pass  Fc  160.00 Hz  Q   0.71\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters, warnings = parser.parse_file_with_warnings(file)
        assert len(filters) == 0
        assert len(warnings) == 1
        assert "All pass" in warnings[0].message
        assert "All-pass" not in warnings[0].message

    def test_modal_emits_warning(self, parser: REWParser, tmp_path: Path) -> None:
        """Modal filter emits a warning and is skipped."""
        content = (
            "Equaliser: Generic\n"
            "Filter  1: ON  Modal    Fc   50.00 Hz  Gain  -5.0 dB  Q  3.000\n"
            "Filter  2: ON  PK       Fc  100.00 Hz  Gain  -1.00 dB  Q  1.000\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters, warnings = parser.parse_file_with_warnings(file)
        assert len(filters) == 1
        assert len(warnings) == 1
        assert "Modal" in warnings[0].message

    def test_notch_emits_warning(self, parser: REWParser, tmp_path: Path) -> None:
        """Notch filter emits a warning and is skipped."""
        content = (
            "Equaliser: Generic\n"
            "Filter  1: ON  Notch    Fc  100.00 Hz  Q  5.000\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters, warnings = parser.parse_file_with_warnings(file)
        assert len(filters) == 0
        assert len(warnings) == 1
        assert "Notch" in warnings[0].message

    def test_ls_6db_emits_warning(self, parser: REWParser, tmp_path: Path) -> None:
        """LS 6dB filter emits a warning and is skipped."""
        content = (
            "Equaliser: Generic\n"
            "Filter  1: ON  LS 6dB   Fc  100.00 Hz  Gain  -3.0 dB\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters, warnings = parser.parse_file_with_warnings(file)
        assert len(filters) == 0
        assert len(warnings) == 1
        assert "LS 6dB" in warnings[0].message

    def test_hs_6db_emits_warning(self, parser: REWParser, tmp_path: Path) -> None:
        """HS 6dB filter emits a warning and is skipped."""
        content = (
            "Equaliser: Generic\n"
            "Filter  1: ON  HS 6dB   Fc  100.00 Hz  Gain  -3.0 dB\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters, warnings = parser.parse_file_with_warnings(file)
        assert len(filters) == 0
        assert len(warnings) == 1
        assert "HS 6dB" in warnings[0].message

    def test_multiple_unsupported_types(self, parser: REWParser, tmp_path: Path) -> None:
        """Multiple unsupported types each emit a warning."""
        content = (
            "Equaliser: Generic\n"
            "Filter  1: ON  Modal    Fc   50.00 Hz  Gain  -5.0 dB  Q  3.000\n"
            "Filter  2: ON  All pass  Fc  160.00 Hz  Q   0.71\n"
            "Filter  3: ON  PK       Fc  100.00 Hz  Gain  -1.00 dB  Q  1.000\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters, warnings = parser.parse_file_with_warnings(file)
        assert len(filters) == 1
        assert len(warnings) == 2

    def test_parse_file_with_rows_interleaves_skip_at_original_position(
        self, parser: REWParser, tmp_path: Path
    ) -> None:
        """parse_file_with_rows keeps a skipped band at its original slot."""
        from src.translator._warnings import SkippedBand

        content = (
            "Equaliser: Generic\n"
            "Filter  1: ON  PK       Fc   50.00 Hz  Gain  -5.0 dB  Q  3.000\n"
            "Filter  2: ON  Modal    Fc  160.00 Hz  Gain  -1.0 dB  Q   0.71\n"
            "Filter  3: ON  PK       Fc  100.00 Hz  Gain  -1.00 dB  Q  1.000\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters, warnings, rows, notes = parser.parse_file_with_rows(file)

        assert len(filters) == 2
        assert len(warnings) == 1
        assert len(rows) == 3
        assert rows[0] is filters[0]
        assert isinstance(rows[1], SkippedBand)
        assert rows[1].original_type == "Modal"
        assert rows[2] is filters[1]
        assert notes == {}


# ---------------------------------------------------------------------------
# Error: wrong/missing header
# ---------------------------------------------------------------------------


class TestParseFileHeaderError:
    """Tests for ParseError when the header is wrong or missing."""

    def test_no_equaliser_line_raises_parse_error(
        self, parser: REWParser, tmp_path: Path
    ) -> None:
        """File with no Equaliser: line raises ParseError."""
        content = "Some random content\nFilter  1: ON  PK Fc 100.00 Hz  Gain -1.00 dB  Q 1.000\n"
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        with pytest.raises(ParseError, match="Equaliser"):
            parser.parse_file(file)

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

    def test_malformed_filter_body_raises_parse_error(
        self, parser: REWParser, tmp_path: Path
    ) -> None:
        """A filter line with an unrecognizable body raises ParseError."""
        content = (
            "Equaliser: Parametric EQ\n"
            "Filter  1: ON  PK       Fc   100.00 Hz  Gain  -3.50 dB  Q  1.410\n"
            "Filter  2: ON  INVALID BODY FORMAT\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        with pytest.raises(ParseError) as exc_info:
            parser.parse_file(file)
        assert exc_info.value.line_number == 3
        assert "Malformed" in str(exc_info.value)


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
# OFF state handling
# ---------------------------------------------------------------------------


class TestOffStateHandling:
    """Tests for OFF state prefix across different filter types."""

    def test_off_pk_maps_to_off(self, parser: REWParser, tmp_path: Path) -> None:
        content = (
            "Equaliser: Generic\n"
            "Filter  1: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters = parser.parse_file(file)
        assert filters[0].type == "OFF"
        assert filters[0].frequency_hz == 1000.0

    def test_off_none_maps_to_off(self, parser: REWParser, tmp_path: Path) -> None:
        content = (
            "Equaliser: Generic\n"
            "Filter  1: OFF None   \n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters = parser.parse_file(file)
        assert filters[0].type == "OFF"

    def test_off_hp_butterworth_maps_to_off(self, parser: REWParser, tmp_path: Path) -> None:
        content = (
            "Equaliser: Generic\n"
            "Filter  1: OFF HP       Fc   40.00 Hz \n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters = parser.parse_file(file)
        assert filters[0].type == "OFF"
        assert filters[0].frequency_hz == 40.0
        assert filters[0].q == 0.7071


# ---------------------------------------------------------------------------
# Backward compatibility with old simple format
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Tests ensuring backward compatibility with the simple Parametric EQ format."""

    def test_simple_parametric_eq_format(self, parser: REWParser, tmp_path: Path) -> None:
        """The old simple format (first line = Equaliser: Parametric EQ) still works."""
        content = (
            "Equaliser: Parametric EQ\n"
            "Filter  1: ON  PK       Fc   100.00 Hz  Gain  -3.50 dB  Q  1.410\n"
            "Filter  2: OFF PK       Fc  1000.00 Hz  Gain   0.00 dB  Q  1.000\n"
        )
        file = tmp_path / "eq.txt"
        file.write_text(content, encoding="utf-8")

        filters = parser.parse_file(file)
        assert len(filters) == 2
        assert filters[0].type == "PEAK"
        assert filters[1].type == "OFF"

    def test_generated_file_can_be_parsed_back(self, parser: REWParser, tmp_path: Path) -> None:
        """Files generated by REWGenerator can be parsed by the new parser."""
        from src.translator.rew_generator import REWGenerator

        original = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-3.5, q=1.41),
            CanonicalFilter(type="LS", frequency_hz=80.0, gain_db=2.0, q=0.707),
            CanonicalFilter(type="HP", frequency_hz=50.0, gain_db=0.0, q=0.707),
            CanonicalFilter(type="LP", frequency_hz=5000.0, gain_db=0.0, q=0.707),
            CanonicalFilter(type="OFF", frequency_hz=1000.0, gain_db=0.0, q=1.0),
        ]

        generator = REWGenerator()
        out = tmp_path / "roundtrip.txt"
        generator.generate_file(original, out)

        parsed = parser.parse_file(out)
        assert len(parsed) == len(original)
        for orig, par in zip(original, parsed, strict=True):
            assert par.type == orig.type
            assert par.frequency_hz == pytest.approx(orig.frequency_hz, abs=0.01)
            assert par.gain_db == pytest.approx(orig.gain_db, abs=0.01)
            assert par.q == pytest.approx(orig.q, abs=0.001)


# ---------------------------------------------------------------------------
# parse_filter_settings (REW HTTP API)
# ---------------------------------------------------------------------------


class TestParseFilterSettings:
    """Tests for parsing REW HTTP API FilterSetting objects."""

    def test_valid_filter_settings(self, parser: REWParser) -> None:
        settings = [
            {"enabled": True, "type": "PK", "frequency": 1000.0, "gain": -3.5, "q": 1.41},
            {"enabled": True, "type": "LS Q", "frequency": 80.0, "gain": 3.0, "q": 0.707},
            {"enabled": True, "type": "HS Q", "frequency": 10000.0, "gain": -1.5, "q": 0.5},
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
            {"on": False, "type": "HS Q", "freq": 8000.0, "gain": 0.0, "q": 0.707},
        ]

        filters = parser.parse_filter_settings(settings)

        assert filters[0].type == "PEAK"
        assert filters[0].frequency_hz == 500.0
        assert filters[1].type == "OFF"

    def test_bare_shelf_and_first_order_skipped(self, parser: REWParser) -> None:
        """LS/HS/LS 6dB/HS 6dB/LS 12dB/HS 12dB (shelf-slope S, not Q) and LP1/HP1
        (1st-order, no Q) are skipped via the live API path exactly like the
        text-file path -- this was previously a real divergence: REW's API
        reports no 'q' key for these types (confirmed against real REW output),
        so they used to silently translate through with an arbitrary Q=1.0.
        """
        settings = [
            {"enabled": True, "type": "LS", "frequency": 125.0, "gaindB": -14.0},
            {"enabled": True, "type": "HS", "frequency": 160.0, "gaindB": 0.0},
            {"enabled": True, "type": "LS 6dB", "frequency": 200.0, "gaindB": 0.0},
            {"enabled": True, "type": "HS 6dB", "frequency": 250.0, "gaindB": 0.0},
            {"enabled": True, "type": "LS 12dB", "frequency": 315.0, "gaindB": 0.0},
            {"enabled": True, "type": "HS 12dB", "frequency": 400.0, "gaindB": 0.0},
            {"enabled": True, "type": "LP1", "frequency": 50.0},
            {"enabled": True, "type": "HP1", "frequency": 63.0},
            {"enabled": True, "type": "PK", "frequency": 300.0, "gaindB": -3.0, "q": 1.41},
        ]

        filters = parser.parse_filter_settings(settings)

        assert len(filters) == 1
        assert filters[0].type == "PEAK"

    def test_lp_hp_missing_q_defaults_to_butterworth(self, parser: REWParser) -> None:
        """REW's live API omits 'q' for LP/HP when no explicit Q was set --
        confirmed against real REW API output. Missing 'q' must default to
        REW's documented fixed Q (0.7071), not an arbitrary 1.0.
        """
        settings = [
            {"enabled": True, "type": "LP", "frequency": 31.5},
            {"enabled": True, "type": "HP", "frequency": 40.0},
        ]

        filters = parser.parse_filter_settings(settings)

        assert filters[0] == CanonicalFilter(
            type="LP", frequency_hz=31.5, gain_db=0.0, q=0.7071
        )
        assert filters[1] == CanonicalFilter(
            type="HP", frequency_hz=40.0, gain_db=0.0, q=0.7071
        )

    def test_unknown_type_skipped(self, parser: REWParser) -> None:
        """Unknown filter types are skipped (not raised as errors)."""
        settings = [
            {"enabled": True, "type": "NO", "frequency": 100.0, "gain": 0.0, "q": 1.0},
            {"enabled": True, "type": "PK", "frequency": 200.0, "gaindB": -3.0, "q": 1.41},
        ]

        result = parser.parse_filter_settings(settings)
        # Only the PK filter should be in the result (NO was skipped)
        assert len(result) == 1
        assert result[0].type == "PEAK"
        assert result[0].frequency_hz == 200.0

    def test_frequency_below_range_raises_validation_error(self, parser: REWParser) -> None:
        """Frequencies outside valid range are rejected, not silently clamped.

        Matches the text-file import path's behavior (TestParseFileFrequencyError) --
        clamping a frequency to the device's supported range silently changes
        the EQ curve the user is applying, which is not a safe substitution.
        """
        settings = [
            {"enabled": True, "type": "PK", "frequency": 5.0, "gaindB": 0.0, "q": 1.0},
        ]

        with pytest.raises(ValidationError, match="outside valid range"):
            parser.parse_filter_settings(settings)

    def test_frequency_above_range_raises_validation_error(self, parser: REWParser) -> None:
        """Frequencies outside valid range are rejected, not silently clamped."""
        settings = [
            {"enabled": True, "type": "PK", "frequency": 30000.0, "gaindB": 0.0, "q": 1.0},
        ]

        with pytest.raises(ValidationError, match="outside valid range"):
            parser.parse_filter_settings(settings)

    def test_filter_type_none_handling(self, parser: REWParser) -> None:
        """Smoke #97: Filter type 'None' becomes an explicit OFF band.

        Matches the text-file import path's _NONE_RE handling exactly -- a
        "None" slot is never omitted and never treated as "unsupported".
        """
        # The REW API returns "type": "None" for empty slots.
        settings = [
            {"enabled": True, "type": "None", "frequency": 100.0, "gain": 0.0, "q": 1.0},
            {"enabled": True, "type": "PK", "frequency": 300.0, "gaindB": -3.0, "q": 1.41},
        ]

        filters = parser.parse_filter_settings(settings)

        assert len(filters) == 2
        assert filters[0] == CanonicalFilter(
            type="OFF", frequency_hz=1000.0, gain_db=0.0, q=1.0
        )
        assert filters[1].type == "PEAK"

    def test_filter_type_none_at_middle_index_no_band_shift(
        self, parser: REWParser
    ) -> None:
        """Smoke #97 (refined): a 'None' slot at a MIDDLE index (not first/last)
        must become an OFF band exactly at that index, with no shift of the
        bands before or after it.

        This is the actual regression the bug fix targeted: the live-API path
        used to silently *omit* None slots entirely, which shifts every
        subsequent filter's index by one -- and WiiM band letters (A, B, C...)
        are assigned by list index, so a shift silently reassigns filters to
        the wrong hardware band. A None slot only at index 0 (or the edges)
        can't distinguish "omitted" from "kept" as clearly as a middle slot,
        where an omission would visibly pull a later filter's frequency back
        by one position.
        """
        settings = [
            {"enabled": True, "type": "PK", "frequency": 100.0, "gaindB": -1.0, "q": 1.0},
            {"enabled": True, "type": "PK", "frequency": 200.0, "gaindB": -2.0, "q": 1.1},
            {"enabled": True, "type": "None", "frequency": 500.0, "gain": 0.0, "q": 1.0},
            {"enabled": True, "type": "PK", "frequency": 400.0, "gaindB": -3.0, "q": 1.2},
            {"enabled": True, "type": "PK", "frequency": 500.0, "gaindB": -4.0, "q": 1.3},
        ]

        filters = parser.parse_filter_settings(settings)

        # Nothing was omitted -- 5 slots in, 5 CanonicalFilters out.
        assert len(filters) == 5

        # The None slot (index 2) became an explicit OFF band at that exact
        # index -- not skipped, not moved.
        assert filters[2].type == "OFF"
        assert filters[2] == CanonicalFilter(
            type="OFF", frequency_hz=1000.0, gain_db=0.0, q=1.0
        )

        # The two bands before the None slot kept their original values at
        # their original indices.
        assert filters[0].type == "PEAK"
        assert filters[0].frequency_hz == 100.0
        assert filters[0].gain_db == -1.0
        assert filters[1].type == "PEAK"
        assert filters[1].frequency_hz == 200.0
        assert filters[1].gain_db == -2.0

        # The two bands after the None slot also kept their original values
        # at their original indices -- proving no shift occurred.
        assert filters[3].type == "PEAK"
        assert filters[3].frequency_hz == 400.0
        assert filters[3].gain_db == -3.0
        assert filters[4].type == "PEAK"
        assert filters[4].frequency_hz == 500.0
        assert filters[4].gain_db == -4.0

    def test_filter_type_none_in_rows_not_a_skipped_band(self, parser: REWParser) -> None:
        """A 'None' slot's row is the OFF CanonicalFilter itself, not a SkippedBand."""
        settings = [
            {"enabled": True, "type": "None", "frequency": 100.0, "gain": 0.0, "q": 1.0},
            {"enabled": True, "type": "PK", "frequency": 300.0, "gaindB": -3.0, "q": 1.41},
        ]

        filters, rows, notes = parser.parse_filter_settings_with_rows(settings)

        assert len(filters) == 2
        assert len(rows) == 2
        assert rows[0] is filters[0]
        assert rows[0].type == "OFF"
        assert rows[1] is filters[1]
        assert notes == {}

    def test_filter_type_none_at_middle_index_rows_identity_no_shift(
        self, parser: REWParser
    ) -> None:
        """Smoke #97 (refined): with a 'None' slot at a MIDDLE index among 5+
        filters, `rows[i] is filters[i]` must hold for EVERY index (not just
        the None one), and the surrounding bands' values must be unchanged at
        their original indices -- proving parse_filter_settings_with_rows()
        doesn't shift WiiM band-letter alignment either.
        """
        settings = [
            {"enabled": True, "type": "PK", "frequency": 110.0, "gaindB": -1.1, "q": 1.0},
            {"enabled": True, "type": "PK", "frequency": 220.0, "gaindB": -2.2, "q": 1.1},
            {"enabled": True, "type": "PK", "frequency": 330.0, "gaindB": -3.3, "q": 1.2},
            {"enabled": True, "type": "None", "frequency": 999.0, "gain": 0.0, "q": 1.0},
            {"enabled": True, "type": "PK", "frequency": 440.0, "gaindB": -4.4, "q": 1.3},
            {"enabled": True, "type": "PK", "frequency": 550.0, "gaindB": -5.5, "q": 1.4},
        ]

        filters, rows, notes = parser.parse_filter_settings_with_rows(settings)

        assert len(filters) == 6
        assert len(rows) == 6

        # Identity holds for every index, not just the None slot (index 3).
        for i in range(6):
            assert rows[i] is filters[i], f"rows[{i}] is not filters[{i}]"

        # The None slot became OFF at its original index.
        assert filters[3].type == "OFF"

        # Bands before and after kept their original freq/gain at their
        # original indices -- no shift.
        expected = [
            (0, "PEAK", 110.0, -1.1),
            (1, "PEAK", 220.0, -2.2),
            (2, "PEAK", 330.0, -3.3),
            (4, "PEAK", 440.0, -4.4),
            (5, "PEAK", 550.0, -5.5),
        ]
        for idx, expected_type, expected_freq, expected_gain in expected:
            assert filters[idx].type == expected_type
            assert filters[idx].frequency_hz == expected_freq
            assert filters[idx].gain_db == expected_gain

        assert notes == {}

    def test_filter_type_none_disabled_still_becomes_off(self, parser: REWParser) -> None:
        """A 'None' slot with enabled=False still becomes OFF, same as enabled=True.

        Real REW API output includes disabled None slots (e.g. {"type": "None",
        "enabled": false}) -- the empty-slot check must not depend on `enabled`.
        """
        settings = [
            {"enabled": False, "type": "None"},
        ]

        filters = parser.parse_filter_settings(settings)

        assert filters == [
            CanonicalFilter(type="OFF", frequency_hz=1000.0, gain_db=0.0, q=1.0)
        ]

    def test_filter_type_none_disabled_at_middle_index_no_band_shift(
        self, parser: REWParser
    ) -> None:
        """Smoke #97 (refined): a disabled ('enabled': False) 'None' slot at a
        MIDDLE index among 5+ filters still becomes OFF at its exact index,
        with no shift to the surrounding bands -- same guarantee as the
        enabled=True case, proving the empty-slot check truly doesn't depend
        on `enabled`.
        """
        settings = [
            {"enabled": True, "type": "PK", "frequency": 60.0, "gaindB": -0.6, "q": 1.0},
            {"enabled": True, "type": "PK", "frequency": 70.0, "gaindB": -0.7, "q": 1.0},
            {"enabled": False, "type": "None"},
            {"enabled": True, "type": "PK", "frequency": 80.0, "gaindB": -0.8, "q": 1.0},
            {"enabled": True, "type": "PK", "frequency": 90.0, "gaindB": -0.9, "q": 1.0},
        ]

        filters, rows, _notes = parser.parse_filter_settings_with_rows(settings)

        assert len(filters) == 5
        for i in range(5):
            assert rows[i] is filters[i], f"rows[{i}] is not filters[{i}]"

        assert filters[2] == CanonicalFilter(
            type="OFF", frequency_hz=1000.0, gain_db=0.0, q=1.0
        )
        assert filters[0].frequency_hz == 60.0
        assert filters[1].frequency_hz == 70.0
        assert filters[3].frequency_hz == 80.0
        assert filters[4].frequency_hz == 90.0

    def test_notch_skipped_not_converted_to_peak(self, parser: REWParser) -> None:
        """Notch implies >60 dB attenuation, which WiiM can't reproduce (-12 dB cap).

        Must be skipped here exactly like the text-file import path, not
        silently auto-converted to PEAK.
        """
        settings = [
            {"enabled": True, "type": "Notch", "frequency": 60.0, "gain": -60.0, "q": 10.0},
            {"enabled": True, "type": "PK", "frequency": 300.0, "gaindB": -3.0, "q": 1.41},
        ]

        filters = parser.parse_filter_settings(settings)

        assert len(filters) == 1
        assert filters[0].type == "PEAK"

    def test_parse_filter_settings_with_rows_marks_unsupported(
        self, parser: REWParser
    ) -> None:
        """parse_filter_settings_with_rows surfaces a SkippedBand for Notch."""
        from src.translator._warnings import SkippedBand

        settings = [
            {"enabled": True, "type": "Notch", "frequency": 60.0, "gain": -60.0, "q": 10.0},
            {"enabled": True, "type": "PK", "frequency": 300.0, "gaindB": -3.0, "q": 1.41},
        ]

        filters, rows, notes = parser.parse_filter_settings_with_rows(settings)

        assert len(filters) == 1
        assert len(rows) == 2
        assert isinstance(rows[0], SkippedBand)
        assert rows[0].original_type == "Notch"
        assert rows[1] is filters[0]
        assert notes == {}

    def test_api_bare_lp_surfaces_conversion_note(self, parser: REWParser) -> None:
        """API path: LP with no 'q' key gets the same default-Q conversion note."""
        settings = [
            {"enabled": True, "type": "LP", "frequency": 31.5},
        ]

        filters, _rows, notes = parser.parse_filter_settings_with_rows(settings)

        assert filters[0].q == 0.7071
        assert 0 in notes
        assert "0.7071" in notes[0][0]
        assert "LP" in notes[0][0]

    def test_api_lp_q_does_not_surface_a_conversion_note(self, parser: REWParser) -> None:
        """API path: LP Q (explicit 'q' key) is a direct match -- no conversion note."""
        settings = [
            {"enabled": True, "type": "LP Q", "frequency": 80.0, "q": 0.71},
        ]

        _filters, _rows, notes = parser.parse_filter_settings_with_rows(settings)

        assert notes == {}



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
