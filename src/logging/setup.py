"""
Logging configuration for the WiiM ↔ REW PEQ Sync Tool.

Sets up three rotating log channels:
  - logs/app.log       — lifecycle events, UI events, errors, rollback events
  - logs/wiim_api.log  — all HTTP exchanges with WiiM devices
  - logs/rew_api.log   — all HTTP exchanges with the REW local API

Each channel rotates at 10 MB and retains 5 backup archives.

Requirements: 15.1, 15.2, 15.3, 15.8, 19.2
"""

from __future__ import annotations

import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LOG_MAX_BYTES: int = 10 * 1024 * 1024  # 10 MB
LOG_BACKUP_COUNT: int = 5
LOG_FORMAT: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
LOG_DATE_FORMAT: str = "%Y-%m-%dT%H:%M:%S"

LOGGER_APP = "wiim_rew_sync.app"
LOGGER_WIIM_API = "wiim_rew_sync.wiim_api"
LOGGER_REW_API = "wiim_rew_sync.rew_api"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def ensure_logs_directory(logs_dir: Path) -> None:
    """Create *logs_dir* if it does not already exist.

    Raises:
        RuntimeError: If the directory cannot be created, with a message
            describing the path and the underlying OS error.  The caller
            (application startup) is expected to display this to the user
            and abort startup (Requirement 19.2).
    """
    if logs_dir.exists():
        return
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"Cannot create logs directory '{logs_dir}': {exc}"
        ) from exc


def configure_logging(logs_dir: Path, level: int = logging.DEBUG) -> None:
    """Configure all three rotating log channels.

    This function is idempotent — calling it multiple times with the same
    *logs_dir* does not add duplicate handlers.

    Args:
        logs_dir: Directory where log files will be written.  Must already
            exist (call :func:`ensure_logs_directory` first).
        level:    Root log level.  Defaults to ``logging.DEBUG``.

    Raises:
        RuntimeError: If a log file cannot be opened for writing.
    """
    ensure_logs_directory(logs_dir)

    formatter = logging.Formatter(fmt=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)

    _setup_channel(
        logger_name=LOGGER_APP,
        filepath=logs_dir / "app.log",
        formatter=formatter,
        level=level,
    )
    _setup_channel(
        logger_name=LOGGER_WIIM_API,
        filepath=logs_dir / "wiim_api.log",
        formatter=formatter,
        level=level,
    )
    _setup_channel(
        logger_name=LOGGER_REW_API,
        filepath=logs_dir / "rew_api.log",
        formatter=formatter,
        level=level,
    )

    # Also emit WARNING+ to stderr so operators see critical errors in the console.
    root = logging.getLogger()
    if not any(isinstance(h, logging.StreamHandler) and h.stream is sys.stderr
               for h in root.handlers):
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.WARNING)
        stderr_handler.setFormatter(formatter)
        root.addHandler(stderr_handler)

    root.setLevel(level)


def install_crash_handler(log_dir: Path) -> None:
    """Install a global crash handler via :func:`sys.excepthook`.

    The hook writes the full traceback to ``app.log`` at CRITICAL level
    including: timestamp, exception type, message, and full stack trace.
    Works even if the GUI event loop has crashed because it writes directly
    to the app logger's handlers.

    Preserves the original ``sys.excepthook`` by calling it after logging.

    Args:
        log_dir: Directory containing the log files.  Used to ensure the
            app logger has a handler configured (calls :func:`configure_logging`
            if necessary).
    """
    original_hook = sys.excepthook

    def _crash_hook(
        exc_type: type[BaseException],
        exc_value: BaseException,
        exc_tb: TracebackType | None,
    ) -> None:
        # Format the full traceback
        tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
        tb_text = "".join(tb_lines)

        # Log at CRITICAL level to app.log
        logger = logging.getLogger(LOGGER_APP)
        logger.critical(
            "Unhandled exception: %s: %s\n%s",
            exc_type.__name__,
            exc_value,
            tb_text,
        )

        # Flush all handlers to ensure the crash is persisted
        for handler in logger.handlers:
            handler.flush()

        # Preserve original hook behaviour
        original_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = _crash_hook


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_channel(
    logger_name: str,
    filepath: Path,
    formatter: logging.Formatter,
    level: int,
) -> None:
    """Attach a :class:`RotatingFileHandler` to *logger_name* if one is not
    already present, avoiding duplicate handlers on re-import.
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.propagate = False  # Prevent messages bubbling to the root logger

    # Guard against duplicate handlers (e.g. when module is reloaded in tests)
    if any(
        isinstance(h, RotatingFileHandler) and Path(h.baseFilename) == filepath.resolve()
        for h in logger.handlers
    ):
        return

    try:
        handler = RotatingFileHandler(
            filename=filepath,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    except OSError as exc:
        raise RuntimeError(f"Cannot open log file '{filepath}': {exc}") from exc

    handler.setLevel(level)
    handler.setFormatter(formatter)
    logger.addHandler(handler)


# ---------------------------------------------------------------------------
# Module-level convenience loggers (imported by other packages)
# ---------------------------------------------------------------------------

app_logger: logging.Logger = logging.getLogger(LOGGER_APP)
wiim_api_logger: logging.Logger = logging.getLogger(LOGGER_WIIM_API)
rew_api_logger: logging.Logger = logging.getLogger(LOGGER_REW_API)
