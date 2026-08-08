"""Unit tests for WiiM device name sanitization (src/utils/device_name.py)."""

from __future__ import annotations

import unicodedata

from src.utils.device_name import has_invalid_device_name_chars, sanitize_device_name


class TestSanitizeDeviceName:
    """sanitize_device_name strips characters outside the accepted set."""

    def test_allows_letters_numbers_underscore_dash_space(self) -> None:
        """Letters, numbers, underscore, dash, and space all pass through
        unchanged (per the app's stated rule plus user-confirmed extras)."""
        name = "Living Room_2-Main"
        assert sanitize_device_name(name) == name

    def test_strips_disallowed_punctuation(self) -> None:
        """Characters outside the allowed set are removed, not replaced."""
        assert sanitize_device_name("Living Room!") == "Living Room"
        assert sanitize_device_name("A <b>Bold</b> & Loud") == "A bBoldb  Loud"

    def test_empty_string_unchanged(self) -> None:
        assert sanitize_device_name("") == ""

    def test_all_disallowed_characters_yields_empty(self) -> None:
        assert sanitize_device_name("!!!@@@") == ""

    def test_allows_non_latin_alphabet_letters(self) -> None:
        """QA-reported bug (docs/corrections.md, 2026-08-07): the device
        accepts non-Latin-alphabet letters (e.g. Cyrillic/Slavic) the same
        as it does for ASCII ones via WiiM Home -- the old ASCII-only
        [A-Za-z0-9_] set stripped these out entirely."""
        name = "Гостиная_2-Основной"
        assert sanitize_device_name(name) == name

    def test_nfd_decomposed_accents_survive(self) -> None:
        """PR #25 review finding: ``\\w`` matches a precomposed accented
        letter (one codepoint) but not a standalone combining mark on its
        own, so an NFD-decomposed name (base letter + separate combining
        accent, as produced by some IMEs and by macOS's filesystem)
        previously had its accents silently stripped even though the
        equivalent NFC form of the same name passed through untouched.
        Built from explicit codepoints, not a source-literal accented
        character, so the file's own encoding can't quietly normalize
        away the exact case this regression test exists to catch.
        """
        nfd_name = "e\u0301"  # combining acute accent (U+0301) on a bare "e"
        nfc_name = unicodedata.normalize("NFC", nfd_name)
        assert sanitize_device_name(nfd_name) == nfc_name
        assert not has_invalid_device_name_chars(nfd_name)


class TestHasInvalidDeviceNameChars:
    """has_invalid_device_name_chars flags any character outside the set."""

    def test_false_for_allowed_only(self) -> None:
        assert not has_invalid_device_name_chars("Living Room_2-Main")

    def test_true_for_any_disallowed_character(self) -> None:
        assert has_invalid_device_name_chars("Living Room!")

    def test_false_for_empty_string(self) -> None:
        assert not has_invalid_device_name_chars("")

    def test_false_for_non_latin_alphabet_letters(self) -> None:
        assert not has_invalid_device_name_chars("Гостиная")
