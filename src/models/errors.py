"""Domain exception hierarchy for WiiM ↔ REW PEQ Sync Tool."""


class WiiMREWSyncError(Exception):
    """Base exception for all domain errors."""


# --- Network / device ---


class WiiMConnectionError(WiiMREWSyncError):
    """Device unreachable or connection failed."""


class WiiMTimeoutError(WiiMConnectionError):
    """Device did not respond within the timeout window."""


class WiiMResponseError(WiiMREWSyncError):
    """Malformed or unexpected response from a WiiM device."""


# --- Translation / parsing ---


class ParseError(WiiMREWSyncError):
    """REW file or WiiM response could not be parsed."""

    def __init__(self, message: str, *, line_number: int | None = None) -> None:
        self.line_number = line_number
        if line_number is not None:
            message = f"Line {line_number}: {message}"
        super().__init__(message)


class ValidationError(WiiMREWSyncError):
    """Out-of-range or invalid value encountered during validation."""


class SchemaVersionError(WiiMREWSyncError):
    """Profile schema version mismatch or migration failure."""


# --- Repository ---


class ProfileNotFoundError(WiiMREWSyncError):
    """Attempted to load a profile that does not exist."""


class BackupError(WiiMREWSyncError):
    """Backup creation or retention policy failure."""


# --- REW API ---


class REWNotConnectedError(WiiMREWSyncError):
    """Connection refused from REW HTTP API (localhost:4735)."""


class REWMeasurementNotFoundError(WiiMREWSyncError):
    """Requested measurement UUID was not found in REW."""
