"""Translation Engine package — stateless conversion functions."""

from __future__ import annotations

from pathlib import Path

from src.models.canonical import CanonicalFilter
from src.translator._warnings import ValidationWarning
from src.translator.rew_generator import REWGenerator
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
    def parse_rew_filter_settings(
        settings: list[dict[str, object]],
    ) -> list[CanonicalFilter]:
        """Parse REW HTTP API FilterSetting objects."""
        return REWParser().parse_filter_settings(settings)

    @staticmethod
    def generate_rew_file(
        filters: list[CanonicalFilter], path: Path, max_filters: int = 10
    ) -> None:
        """Generate a REW EQ text file."""
        REWGenerator().generate_file(filters, path, max_filters=max_filters)

    @staticmethod
    def generate_rew_lr_files(
        filters_l: list[CanonicalFilter],
        filters_r: list[CanonicalFilter],
        base_path: Path,
        max_filters: int = 10,
    ) -> tuple[Path, Path]:
        """Generate L/R REW text files."""
        return REWGenerator().generate_lr_files(
            filters_l, filters_r, base_path, max_filters=max_filters
        )

    @staticmethod
    def parse_wiim_band_array(
        band_array: list[dict[str, int | float | str]], channel: str = "stereo"
    ) -> list[CanonicalFilter]:
        """Parse WiiM EQBand array."""
        return parse_wiim_band_array_fn(band_array, channel=channel)

    @staticmethod
    def generate_wiim_band_array(
        filters: list[CanonicalFilter],
        max_bands: int = 10,
    ) -> tuple[list[float], list[ValidationWarning]]:
        """Generate WiiM EQBand flat parameter array."""
        return generate_wiim_band_array_fn(filters, max_bands=max_bands)

    @staticmethod
    def migrate_profile(raw: dict[str, object]) -> dict[str, object]:
        """Migrate a profile dict to the current schema version."""
        return migrate_profile_fn(raw)
