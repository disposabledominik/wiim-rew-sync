"""Unit tests for WiiM device name sanitization (src/utils/device_name.py)."""

from __future__ import annotations

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


class TestHasInvalidDeviceNameChars:
    """has_invalid_device_name_chars flags any character outside the set."""

    def test_false_for_allowed_only(self) -> None:
        assert not has_invalid_device_name_chars("Living Room_2-Main")

    def test_true_for_any_disallowed_character(self) -> None:
        assert has_invalid_device_name_chars("Living Room!")

    def test_false_for_empty_string(self) -> None:
        assert not has_invalid_device_name_chars("")
