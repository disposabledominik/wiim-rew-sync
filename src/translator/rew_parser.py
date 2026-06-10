"""REW EQ text file parser — converts REW text and HTTP API data to CanonicalFilter lists."""

from __future__ import annotations

import re
from pathlib import Path

from src.models.canonical import CanonicalFilter
from src.models.errors import ParseError, ValidationError

# Regex for active filter lines:
# Filter  N: ON  <type> Fc <freq> Hz  Gain <gain> dB  Q <q>
# Regex for disabled filter lines:
# Filter  N: OFF <type> Fc <freq> Hz  Gain <gain> dB  Q <q>
_FILTER_LINE_RE = re.compile(
    r"^Filter\s+\d+:\s+"
    r"(ON|OFF)\s+"
    r"(\w+)\s+"
    r"Fc\s+([\d.]+)\s+Hz\s+"
    r"Gain\s+([-\d.]+)\s+dB\s+"
    r"Q\s+([\d.]+)\s*$"
)

EXPECTED_HEADER = "Equaliser: Parametric EQ"

# REW text type token → Canonical filter type
_TYPE_MAP: dict[str, str] = {
    "PK": "PEAK",
    "LS": "LS",
    "HS": "HS",
}

# REW HTTP API type field → Canonical filter type (same mapping)
_API_TYPE_MAP: dict[str, str] = {
    "PK": "PEAK",
    "LS": "LS",
    "HS": "HS",
}


def _validate_frequency(freq: float, *, line_number: int | None = None) -> None:
    """Raise ValidationError if frequency is outside 10–22000 Hz."""
    if not (10.0 <= freq <= 22000.0):
        msg = f"Frequency {freq} Hz is outside valid range 10–22000 Hz"
        if line_number is not None:
            msg = f"Line {line_number}: {msg}"
        raise ValidationError(msg)


def _validate_type_token(token: str, *, line_number: int | None = None) -> None:
    """Raise ValidationError if the type token is not recognized."""
    if token not in _TYPE_MAP:
        msg = f"Unknown filter type '{token}'"
        if line_number is not None:
            msg = f"Line {line_number}: {msg}"
        raise ValidationError(msg)


class REWParser:
    """Parses REW EQ text files and REW HTTP API FilterSetting objects into CanonicalFilters."""

    def parse_file(self, path: Path) -> list[CanonicalFilter]:
        """Parse a REW EQ text file.

        Raises ParseError on malformed lines (with line number in message).
        Raises ValidationError for unknown type tokens or out-of-range frequency.
        First line must be exactly 'Equaliser: Parametric EQ'.
        """
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()

        if not lines or lines[0].strip() != EXPECTED_HEADER:
            raise ParseError(
                f"Expected first line to be '{EXPECTED_HEADER}'",
                line_number=1,
            )

        filters: list[CanonicalFilter] = []

        for line_idx, line in enumerate(lines[1:], start=2):
            stripped = line.strip()
            if not stripped:
                continue  # Skip blank lines

            match = _FILTER_LINE_RE.match(stripped)
            if match is None:
                raise ParseError(
                    f"Malformed filter line: '{stripped}'",
                    line_number=line_idx,
                )

            state = match.group(1)  # ON or OFF
            type_token = match.group(2)

            # Validate type token
            _validate_type_token(type_token, line_number=line_idx)

            try:
                freq = float(match.group(3))
                gain = float(match.group(4))
                q = float(match.group(5))
            except ValueError as e:
                raise ParseError(
                    f"Unparseable numeric value: {e}",
                    line_number=line_idx,
                ) from e

            # Validate frequency range
            _validate_frequency(freq, line_number=line_idx)

            # Determine canonical type
            if state == "OFF":
                canonical_type = "OFF"
            else:
                canonical_type = _TYPE_MAP[type_token]

            filters.append(
                CanonicalFilter(
                    type=canonical_type,  # type: ignore[arg-type]
                    frequency_hz=freq,
                    gain_db=gain,
                    q=q,
                )
            )

        return filters

    def parse_filter_settings(
        self, filter_settings: list[dict[str, object]]
    ) -> list[CanonicalFilter]:
        """Parse REW HTTP API FilterSetting objects into CanonicalFilters.

        Each FilterSetting has: enabled (bool), type (str), frequency (float),
        gain (float), q (float).

        Same validation rules as parse_file.
        """
        filters: list[CanonicalFilter] = []

        for i, setting in enumerate(filter_settings):
            enabled = setting.get("enabled", setting.get("on", True))
            type_token = str(setting.get("type", ""))
            freq = float(setting.get("frequency", setting.get("freq", 0.0)))  # type: ignore[arg-type]
            gain = float(setting.get("gain", 0.0))  # type: ignore[arg-type]
            q = float(setting.get("q", 1.0))  # type: ignore[arg-type]

            # Validate type token
            if type_token not in _API_TYPE_MAP:
                raise ValidationError(
                    f"Filter {i + 1}: Unknown filter type '{type_token}'"
                )

            # Validate frequency
            if not (10.0 <= freq <= 22000.0):
                raise ValidationError(
                    f"Filter {i + 1}: Frequency {freq} Hz is outside valid range 10–22000 Hz"
                )

            # Determine canonical type
            if not enabled:
                canonical_type = "OFF"
            else:
                canonical_type = _API_TYPE_MAP[type_token]

            filters.append(
                CanonicalFilter(
                    type=canonical_type,  # type: ignore[arg-type]
                    frequency_hz=freq,
                    gain_db=gain,
                    q=q,
                )
            )

        return filters
