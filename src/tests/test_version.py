"""Unit tests for app version resolution (src/utils/version.py)."""

from __future__ import annotations

import importlib.metadata
import sys
import types
from collections.abc import Generator

import pytest

from src.utils.version import _FALLBACK_VERSION, get_app_version


@pytest.fixture(autouse=True)
def _clear_generated_version_module() -> Generator[None, None, None]:
    """Ensure a prior test's fake ``src._version`` doesn't leak into the next."""
    sys.modules.pop("src._version", None)
    yield
    sys.modules.pop("src._version", None)


class TestGetAppVersion:
    """get_app_version() resolves in order: generated module, package metadata, fallback."""

    def test_prefers_generated_version_module(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The setuptools_scm-generated src/_version.py wins when present."""
        fake_module = types.ModuleType("src._version")
        fake_module.__version__ = "1.2.3"  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "src._version", fake_module)

        assert get_app_version() == "1.2.3"

    def test_falls_back_to_installed_metadata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When the generated module is absent, installed package metadata is used."""
        monkeypatch.setitem(sys.modules, "src._version", None)
        monkeypatch.setattr(importlib.metadata, "version", lambda _name: "4.5.6")

        assert get_app_version() == "4.5.6"

    def test_falls_back_to_hardcoded_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When neither source is available, the hardcoded fallback is returned."""
        monkeypatch.setitem(sys.modules, "src._version", None)

        def _raise_not_found(_name: str) -> str:
            raise importlib.metadata.PackageNotFoundError(_name)

        monkeypatch.setattr(importlib.metadata, "version", _raise_not_found)

        assert get_app_version() == _FALLBACK_VERSION
