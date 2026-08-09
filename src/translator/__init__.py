"""Translation Engine package — stateless conversion functions."""

from __future__ import annotations

from pathlib import Path

from src.models.canonical import CanonicalFilter
from src.models.constants import DEFAULT_MAX_BANDS
from src.translator._warnings import ValidationWarning
from src.translator.rew_parser import REWParser
from src.translator.schema_migrator import migrate_profile as migrate_profile_fn
from src.translator.wiim_generator import generate_wiim_band_array as generate_wiim_band_array_fn
from src.translator.wiim_parser import parse_wiim_band_array as parse_wiim_band_array_fn

__all__ = ["TranslationEngine", "ValidationWarning"]


class TranslationEngine:
    """Stateless translation facade — all methods are @staticmethod."""

    @staticmethod
    def parse_rew_file(path: Path) -> list[CanonicalFilter]:
        """Parse a REW EQ text file."""
        return REWParser().parse_file(path)

    @staticmethod
    def parse_wiim_band_array(
        band_array: list[dict[str, int | float | str]], channel: str = "stereo"
    ) -> list[CanonicalFilter]:
        """Parse WiiM EQBand array."""
        return parse_wiim_band_array_fn(band_array, channel=channel)

    @staticmethod
    def generate_wiim_band_array(
        filters: list[CanonicalFilter],
        max_bands: int = DEFAULT_MAX_BANDS,
    ) -> tuple[list[float], list[ValidationWarning]]:
        """Generate WiiM EQBand flat parameter array."""
        return generate_wiim_band_array_fn(filters, max_bands=max_bands)

    @staticmethod
    def migrate_profile(raw: dict[str, object]) -> dict[str, object]:
        """Migrate a profile dict to the current schema version."""
        return migrate_profile_fn(raw)
