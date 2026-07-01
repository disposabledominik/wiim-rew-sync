"""REW EQ text file generator — converts CanonicalFilter lists to REW text files."""

from __future__ import annotations

import logging
from pathlib import Path

from src.models.canonical import CanonicalFilter
from src.models.constants import DEFAULT_MAX_BANDS
from src.translator._warnings import ValidationWarning

logger = logging.getLogger("wiim_rew_sync.app")

# Canonical filter type → REW text type token
_REVERSE_TYPE_MAP: dict[str, str] = {
    "PEAK": "PK",
    "LS": "LS",
    "HS": "HS",
    "LP": "LP",
    "HP": "HP",
}

HEADER = "Equaliser: Parametric EQ"


def _format_filter_line(index: int, f: CanonicalFilter) -> str:
    """Format a single CanonicalFilter as a REW EQ text line.

    Args:
        index: 1-based band number.
        f: The canonical filter to format.

    Returns:
        A formatted REW filter line string.
    """
    # Determine state and type token
    if f.type == "OFF":
        state = "OFF"
        rew_type = "PK"
    else:
        state = "ON "
        rew_type = _REVERSE_TYPE_MAP[f.type]

    # Format numeric values
    freq_str = f"{f.frequency_hz:8.2f}"
    gain_str = f"{f.gain_db:6.2f}"
    q_str = f"{f.q:.3f}"

    # Build the line — match REW's exact spacing
    return (
        f"Filter {index:2d}: {state} {rew_type:<2}       "
        f"Fc {freq_str} Hz  Gain {gain_str} dB  Q  {q_str}"
    )


class REWGenerator:
    """Generates REW-compatible EQ text files from CanonicalFilter lists."""

    def generate_file(
        self,
        filters: list[CanonicalFilter],
        path: Path,
        max_filters: int = DEFAULT_MAX_BANDS,
    ) -> list[ValidationWarning]:
        """Write a REW-compatible EQ text file.

        First line: 'Equaliser: Parametric EQ'
        All bands up to max_filters are written; OFF bands use 'OFF PK' format.
        Gain/freq to 2 dp, Q to 3 dp.

        Args:
            filters: List of CanonicalFilter objects to write.
            path: Output file path.
            max_filters: Maximum number of bands to write (default 10).

        Returns:
            List of ValidationWarning for each skipped UNKNOWN band.
        """
        # Truncate to max_filters
        bands = filters[:max_filters]

        lines: list[str] = [HEADER]
        warnings: list[ValidationWarning] = []
        band_index = 1
        for f in bands:
            if f.type == "UNKNOWN":
                # Can't export unknown types to REW format - skip with warning
                logger.warning(
                    "Skipping UNKNOWN filter (raw_mode=%s, freq=%.1f) during REW export",
                    f.raw_mode,
                    f.frequency_hz,
                )
                warnings.append(
                    ValidationWarning(
                        field="type",
                        message=(
                            f"Skipped UNKNOWN filter (raw_mode={f.raw_mode}, "
                            f"freq={f.frequency_hz:.1f} Hz) during REW export"
                        ),
                        original_value=f.raw_mode,
                    )
                )
                continue
            lines.append(_format_filter_line(band_index, f))
            band_index += 1

        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return warnings

    def generate_lr_files(
        self,
        filters_l: list[CanonicalFilter],
        filters_r: list[CanonicalFilter],
        base_path: Path,
        max_filters: int = DEFAULT_MAX_BANDS,
    ) -> tuple[Path, Path, list[ValidationWarning]]:
        """Write two REW files for L/R mode.

        Generates two files with '_L' and '_R' suffixes appended to the base_path stem.

        Args:
            filters_l: Left channel filters.
            filters_r: Right channel filters.
            base_path: Base path without extension. Files will be named
                       base_path_L.txt and base_path_R.txt.
            max_filters: Maximum number of bands per file (default 10).

        Returns:
            Tuple of (left_path, right_path, warnings).
        """
        left_path = base_path.parent / f"{base_path.stem}_L.txt"
        right_path = base_path.parent / f"{base_path.stem}_R.txt"

        warnings_l = self.generate_file(filters_l, left_path, max_filters=max_filters)
        warnings_r = self.generate_file(filters_r, right_path, max_filters=max_filters)

        return (left_path, right_path, warnings_l + warnings_r)
