"""Models package — Pydantic domain models."""

from src.models.canonical import CanonicalFilter, FilterType
from src.models.capabilities import DeviceCapabilities, DeviceInfo
from src.models.errors import (
    BackupError,
    ParseError,
    ProfileNotFoundError,
    REWMeasurementNotFoundError,
    REWNotConnectedError,
    SchemaVersionError,
    ValidationError,
    WiiMConnectionError,
    WiiMResponseError,
    WiiMREWSyncError,
    WiiMTimeoutError,
)
from src.models.peq import PEQSettings
from src.models.profile import BackupRecord, Profile

__all__ = [
    "BackupError",
    "BackupRecord",
    "CanonicalFilter",
    "DeviceCapabilities",
    "DeviceInfo",
    "FilterType",
    "PEQSettings",
    "ParseError",
    "Profile",
    "ProfileNotFoundError",
    "REWMeasurementNotFoundError",
    "REWNotConnectedError",
    "SchemaVersionError",
    "ValidationError",
    "WiiMConnectionError",
    "WiiMREWSyncError",
    "WiiMResponseError",
    "WiiMTimeoutError",
]
