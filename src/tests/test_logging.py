"""
Unit tests for src/logging/setup.py

Covers:
  1. ensure_logs_directory() creates the directory when absent
  2. ensure_logs_directory() raises RuntimeError if creation fails
  3. configure_logging() creates all three log files
  4. Each channel writes independently (no cross-channel contamination)
  5. Log entries contain all required fields: timestamp, level, name, message
  6. configure_logging() is idempotent (no duplicate handlers)
  7. RotatingFileHandler is configured with maxBytes=10*1024*1024 and backupCount=5

Requirements: 15.1, 15.2, 15.3, 15.8, 19.2
"""

from __future__ import annotations

import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import patch

import pytest

# Always import from the module under test directly.
from src.logging.setup import (
    LOG_BACKUP_COUNT,
    LOG_MAX_BYTES,
    LOGGER_APP,
    LOGGER_REW_API,
    LOGGER_WIIM_API,
    configure_logging,
    ensure_logs_directory,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_rotating_handlers(logger: logging.Logger) -> list[RotatingFileHandler]:
    return [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]


def _remove_all_handlers(logger: logging.Logger) -> None:
    """Close and remove all handlers from *logger*."""
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def _cleanup_loggers(*names: str) -> None:
    """Remove all handlers from the named loggers (test isolation)."""
    for name in names:
        _remove_all_handlers(logging.getLogger(name))
    # Also strip any StreamHandlers added to the root logger
    root = logging.getLogger()
    for h in list(root.handlers):
        h.close()
        root.removeHandler(h)


# ---------------------------------------------------------------------------
# 1. ensure_logs_directory() creates the directory when absent
# ---------------------------------------------------------------------------

class TestEnsureLogsDirectory:
    def test_creates_directory_when_absent(self, tmp_path: Path) -> None:
        logs_dir = tmp_path / "logs"
        assert not logs_dir.exists()

        ensure_logs_directory(logs_dir)

        assert logs_dir.is_dir()

    def test_does_not_raise_when_directory_already_exists(self, tmp_path: Path) -> None:
        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()

        # Should be a no-op
        ensure_logs_directory(logs_dir)

        assert logs_dir.is_dir()

    def test_creates_nested_directories(self, tmp_path: Path) -> None:
        logs_dir = tmp_path / "a" / "b" / "logs"
        assert not logs_dir.exists()

        ensure_logs_directory(logs_dir)

        assert logs_dir.is_dir()

    # ---------------------------------------------------------------------------
    # 2. ensure_logs_directory() raises RuntimeError if creation fails
    # ---------------------------------------------------------------------------

    def test_raises_runtime_error_when_creation_fails(self, tmp_path: Path) -> None:
        logs_dir = tmp_path / "logs"

        with patch("src.logging.setup.Path.mkdir", side_effect=OSError("Permission denied")):
            with pytest.raises(RuntimeError, match="Cannot create logs directory"):
                ensure_logs_directory(logs_dir)

    def test_runtime_error_message_contains_path(self, tmp_path: Path) -> None:
        logs_dir = tmp_path / "no_permission" / "logs"

        with patch("src.logging.setup.Path.mkdir", side_effect=OSError("denied")):
            with pytest.raises(RuntimeError) as exc_info:
                ensure_logs_directory(logs_dir)

        assert str(logs_dir) in str(exc_info.value)


# ---------------------------------------------------------------------------
# 3. configure_logging() creates all three log files
# ---------------------------------------------------------------------------

class TestConfigureLoggingCreatesFiles:
    def test_creates_app_log(self, tmp_path: Path) -> None:
        _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)
        try:
            configure_logging(tmp_path)
            assert (tmp_path / "app.log").exists()
        finally:
            _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)

    def test_creates_wiim_api_log(self, tmp_path: Path) -> None:
        _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)
        try:
            configure_logging(tmp_path)
            assert (tmp_path / "wiim_api.log").exists()
        finally:
            _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)

    def test_creates_rew_api_log(self, tmp_path: Path) -> None:
        _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)
        try:
            configure_logging(tmp_path)
            assert (tmp_path / "rew_api.log").exists()
        finally:
            _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)

    def test_creates_all_three_log_files(self, tmp_path: Path) -> None:
        _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)
        try:
            configure_logging(tmp_path)
            assert (tmp_path / "app.log").exists()
            assert (tmp_path / "wiim_api.log").exists()
            assert (tmp_path / "rew_api.log").exists()
        finally:
            _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)

    def test_creates_logs_directory_automatically(self, tmp_path: Path) -> None:
        logs_dir = tmp_path / "logs"
        _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)
        try:
            configure_logging(logs_dir)
            assert logs_dir.is_dir()
        finally:
            _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)


# ---------------------------------------------------------------------------
# 4. Each channel writes independently
# ---------------------------------------------------------------------------

class TestChannelIndependence:
    def test_app_logger_does_not_write_to_wiim_api_log(self, tmp_path: Path) -> None:
        _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)
        try:
            configure_logging(tmp_path)

            app_log = logging.getLogger(LOGGER_APP)
            app_log.info("exclusive-app-message-xyz")

            # Flush handlers
            for h in app_log.handlers:
                h.flush()

            wiim_log_path = tmp_path / "wiim_api.log"
            content = wiim_log_path.read_text(encoding="utf-8")
            assert "exclusive-app-message-xyz" not in content
        finally:
            _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)

    def test_wiim_logger_does_not_write_to_app_log(self, tmp_path: Path) -> None:
        _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)
        try:
            configure_logging(tmp_path)

            wiim_log = logging.getLogger(LOGGER_WIIM_API)
            wiim_log.info("exclusive-wiim-message-xyz")

            for h in wiim_log.handlers:
                h.flush()

            app_log_path = tmp_path / "app.log"
            content = app_log_path.read_text(encoding="utf-8")
            assert "exclusive-wiim-message-xyz" not in content
        finally:
            _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)

    def test_rew_logger_does_not_write_to_other_logs(self, tmp_path: Path) -> None:
        _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)
        try:
            configure_logging(tmp_path)

            rew_log = logging.getLogger(LOGGER_REW_API)
            rew_log.info("exclusive-rew-message-xyz")

            for h in rew_log.handlers:
                h.flush()

            app_content = (tmp_path / "app.log").read_text(encoding="utf-8")
            wiim_content = (tmp_path / "wiim_api.log").read_text(encoding="utf-8")
            assert "exclusive-rew-message-xyz" not in app_content
            assert "exclusive-rew-message-xyz" not in wiim_content
        finally:
            _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)

    def test_each_channel_writes_to_its_own_log(self, tmp_path: Path) -> None:
        _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)
        try:
            configure_logging(tmp_path)

            logging.getLogger(LOGGER_APP).info("app-only-msg")
            logging.getLogger(LOGGER_WIIM_API).info("wiim-only-msg")
            logging.getLogger(LOGGER_REW_API).info("rew-only-msg")

            for name in (LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API):
                for h in logging.getLogger(name).handlers:
                    h.flush()

            assert "app-only-msg" in (tmp_path / "app.log").read_text(encoding="utf-8")
            assert "wiim-only-msg" in (tmp_path / "wiim_api.log").read_text(encoding="utf-8")
            assert "rew-only-msg" in (tmp_path / "rew_api.log").read_text(encoding="utf-8")
        finally:
            _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)


# ---------------------------------------------------------------------------
# 5. Log entries contain all required fields: timestamp, level, name, message
# ---------------------------------------------------------------------------

class TestLogEntryFormat:
    # Pattern: "2024-01-15T12:34:56 | DEBUG    | wiim_rew_sync.app | some message"
    LOG_LINE_RE = re.compile(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"  # timestamp
        r" \| "
        r"[A-Z]+-*\s*"                              # level (e.g. "DEBUG   ")
        r" \| "
        r"[\w\.]+"                                  # logger name
        r" \| "
        r".+$",                                     # message
        re.MULTILINE,
    )

    def test_app_log_entry_has_all_required_fields(self, tmp_path: Path) -> None:
        _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)
        try:
            configure_logging(tmp_path)

            logger = logging.getLogger(LOGGER_APP)
            logger.info("test-format-check")
            for h in logger.handlers:
                h.flush()

            content = (tmp_path / "app.log").read_text(encoding="utf-8")
            assert self.LOG_LINE_RE.search(content), (
                f"Log entry does not match expected format. Content:\n{content}"
            )
        finally:
            _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)

    def test_log_entry_contains_timestamp(self, tmp_path: Path) -> None:
        _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)
        try:
            configure_logging(tmp_path)
            logger = logging.getLogger(LOGGER_APP)
            logger.debug("timestamp-test")
            for h in logger.handlers:
                h.flush()

            content = (tmp_path / "app.log").read_text(encoding="utf-8")
            # ISO 8601-style timestamp
            assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", content)
        finally:
            _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)

    def test_log_entry_contains_level(self, tmp_path: Path) -> None:
        _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)
        try:
            configure_logging(tmp_path)
            logger = logging.getLogger(LOGGER_APP)
            logger.warning("level-test")
            for h in logger.handlers:
                h.flush()

            content = (tmp_path / "app.log").read_text(encoding="utf-8")
            assert "WARNING" in content
        finally:
            _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)

    def test_log_entry_contains_component_name(self, tmp_path: Path) -> None:
        _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)
        try:
            configure_logging(tmp_path)
            logger = logging.getLogger(LOGGER_WIIM_API)
            logger.debug("name-test")
            for h in logger.handlers:
                h.flush()

            content = (tmp_path / "wiim_api.log").read_text(encoding="utf-8")
            assert LOGGER_WIIM_API in content
        finally:
            _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)

    def test_log_entry_contains_message(self, tmp_path: Path) -> None:
        _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)
        try:
            configure_logging(tmp_path)
            logger = logging.getLogger(LOGGER_REW_API)
            logger.info("my-unique-test-payload-12345")
            for h in logger.handlers:
                h.flush()

            content = (tmp_path / "rew_api.log").read_text(encoding="utf-8")
            assert "my-unique-test-payload-12345" in content
        finally:
            _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)


# ---------------------------------------------------------------------------
# 6. configure_logging() is idempotent — no duplicate handlers
# ---------------------------------------------------------------------------

class TestIdempotency:
    def test_calling_twice_does_not_add_duplicate_handlers(self, tmp_path: Path) -> None:
        _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)
        try:
            configure_logging(tmp_path)
            configure_logging(tmp_path)

            for name in (LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API):
                rotating = _get_rotating_handlers(logging.getLogger(name))
                assert len(rotating) == 1, (
                    f"Logger '{name}' has {len(rotating)} RotatingFileHandlers after two calls; expected 1"
                )
        finally:
            _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)

    def test_calling_three_times_still_single_handler(self, tmp_path: Path) -> None:
        _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)
        try:
            configure_logging(tmp_path)
            configure_logging(tmp_path)
            configure_logging(tmp_path)

            for name in (LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API):
                rotating = _get_rotating_handlers(logging.getLogger(name))
                assert len(rotating) == 1
        finally:
            _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)

    def test_messages_not_duplicated_after_double_configure(self, tmp_path: Path) -> None:
        _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)
        try:
            configure_logging(tmp_path)
            configure_logging(tmp_path)

            logger = logging.getLogger(LOGGER_APP)
            logger.info("idempotency-check-msg")
            for h in logger.handlers:
                h.flush()

            content = (tmp_path / "app.log").read_text(encoding="utf-8")
            # Message should appear exactly once
            assert content.count("idempotency-check-msg") == 1
        finally:
            _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)


# ---------------------------------------------------------------------------
# 7. RotatingFileHandler configured with maxBytes=10 MB and backupCount=5
# ---------------------------------------------------------------------------

class TestHandlerConfiguration:
    def test_max_bytes_is_10_mb(self, tmp_path: Path) -> None:
        _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)
        try:
            configure_logging(tmp_path)

            for name in (LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API):
                handlers = _get_rotating_handlers(logging.getLogger(name))
                assert len(handlers) == 1
                assert handlers[0].maxBytes == LOG_MAX_BYTES, (
                    f"Logger '{name}': maxBytes={handlers[0].maxBytes}, expected {LOG_MAX_BYTES}"
                )
        finally:
            _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)

    def test_backup_count_is_5(self, tmp_path: Path) -> None:
        _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)
        try:
            configure_logging(tmp_path)

            for name in (LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API):
                handlers = _get_rotating_handlers(logging.getLogger(name))
                assert len(handlers) == 1
                assert handlers[0].backupCount == LOG_BACKUP_COUNT, (
                    f"Logger '{name}': backupCount={handlers[0].backupCount}, expected {LOG_BACKUP_COUNT}"
                )
        finally:
            _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)

    def test_max_bytes_constant_value(self) -> None:
        assert LOG_MAX_BYTES == 10 * 1024 * 1024

    def test_backup_count_constant_value(self) -> None:
        assert LOG_BACKUP_COUNT == 5

    def test_handlers_use_utf8_encoding(self, tmp_path: Path) -> None:
        _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)
        try:
            configure_logging(tmp_path)

            for name in (LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API):
                handlers = _get_rotating_handlers(logging.getLogger(name))
                assert len(handlers) == 1
                assert handlers[0].encoding == "utf-8"
        finally:
            _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)

    def test_each_logger_points_to_correct_file(self, tmp_path: Path) -> None:
        _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)
        try:
            configure_logging(tmp_path)

            expected = {
                LOGGER_APP: "app.log",
                LOGGER_WIIM_API: "wiim_api.log",
                LOGGER_REW_API: "rew_api.log",
            }
            for name, filename in expected.items():
                handlers = _get_rotating_handlers(logging.getLogger(name))
                assert len(handlers) == 1
                handler_path = Path(handlers[0].baseFilename).resolve()
                expected_path = (tmp_path / filename).resolve()
                assert handler_path == expected_path, (
                    f"Logger '{name}' points to {handler_path}, expected {expected_path}"
                )
        finally:
            _cleanup_loggers(LOGGER_APP, LOGGER_WIIM_API, LOGGER_REW_API)
