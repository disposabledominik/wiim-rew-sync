"""Tests for ErrorDialog and error handling paths in MainWindow."""

from __future__ import annotations

import logging
import sys
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication, QLineEdit, QTextBrowser

from src.gui.dialogs.error_dialog import ErrorDialog

# Ensure QApplication instance exists for widget tests
_app = QApplication.instance() or QApplication(sys.argv)


class TestErrorDialogInstantiation:
    """Test ErrorDialog creation at each severity level."""

    def test_info_severity(self) -> None:
        """INFO severity creates dialog with correct properties."""
        dialog = ErrorDialog("INFO", "Info Title", "Info message")

        assert dialog.severity == "INFO"
        assert dialog.windowTitle() == "Info Title"
        assert dialog.backup_path is None
        dialog.close()

    def test_warning_severity(self) -> None:
        """WARNING severity creates dialog with correct properties."""
        dialog = ErrorDialog("WARNING", "Warning Title", "Warning message")

        assert dialog.severity == "WARNING"
        assert dialog.windowTitle() == "Warning Title"
        dialog.close()

    def test_error_severity(self) -> None:
        """ERROR severity creates dialog with correct properties."""
        dialog = ErrorDialog("ERROR", "Error Title", "Error message")

        assert dialog.severity == "ERROR"
        assert dialog.windowTitle() == "Error Title"
        dialog.close()

    def test_critical_severity_without_backup(self) -> None:
        """CRITICAL severity without backup_path still shows recovery steps."""
        dialog = ErrorDialog("CRITICAL", "Critical Title", "Critical message")

        assert dialog.severity == "CRITICAL"
        # Recovery browser should exist
        browser = dialog.findChild(QTextBrowser, "recovery_browser")
        assert browser is not None
        dialog.close()

    def test_critical_severity_with_backup_path(self) -> None:
        """CRITICAL severity with backup_path shows copyable path field."""
        path = "/tmp/backup_20250101_120000.json"
        dialog = ErrorDialog(
            "CRITICAL",
            "Critical: Device State May Be Incorrect",
            "Rollback failed after write verification failure.",
            backup_path=path,
        )

        assert dialog.severity == "CRITICAL"
        assert dialog.backup_path == path

        # Backup path edit should be present and contain the path
        path_edit = dialog.findChild(QLineEdit, "backup_path_edit")
        assert path_edit is not None
        assert path_edit.text() == path
        assert path_edit.isReadOnly()
        dialog.close()

    def test_critical_with_custom_recovery_steps(self) -> None:
        """CRITICAL severity with custom recovery steps displays them."""
        custom_steps = "<b>Custom steps:</b><ol><li>Do X</li></ol>"
        dialog = ErrorDialog(
            "CRITICAL",
            "Critical",
            "Something critical",
            recovery_steps=custom_steps,
        )

        browser = dialog.findChild(QTextBrowser, "recovery_browser")
        assert browser is not None
        assert "Custom steps" in browser.toHtml()
        dialog.close()

    def test_no_backup_path_widget_for_non_critical(self) -> None:
        """Non-CRITICAL dialogs do not have a backup path widget."""
        dialog = ErrorDialog("ERROR", "Error", "Some error")

        path_edit = dialog.findChild(QLineEdit, "backup_path_edit")
        assert path_edit is None
        dialog.close()


class TestErrorDialogShowError:
    """Test the static show_error convenience method."""

    def test_show_error_creates_and_execs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """show_error creates dialog and calls exec."""
        execs: list[object] = []
        monkeypatch.setattr(ErrorDialog, "exec", lambda self: execs.append(self))

        ErrorDialog.show_error("WARNING", "Test", "Test message")
        assert len(execs) == 1
        assert execs[0].severity == "WARNING"  # type: ignore[attr-defined]


class TestMainWindowErrorHandling:
    """Test _on_operation_error dispatching in MainWindow."""

    @pytest.fixture
    def main_window(self):
        """Create a MainWindow with mocked async bridge."""
        from src.gui.main_window import MainWindow

        bridge = MagicMock()
        bridge.operation_started = MagicMock()
        bridge.operation_finished = MagicMock()
        bridge.progress_update = MagicMock()
        bridge.discovery_complete = MagicMock()
        bridge.capabilities_ready = MagicMock()
        bridge.peq_ready = MagicMock()
        bridge.write_complete = MagicMock()
        bridge.operation_error = MagicMock()

        # Ensure signal connect/disconnect don't fail
        for attr_name in [
            "operation_started", "operation_finished", "progress_update",
            "discovery_complete", "capabilities_ready", "peq_ready",
            "write_complete", "operation_error",
        ]:
            sig = getattr(bridge, attr_name)
            sig.connect = MagicMock()

        with patch.object(MainWindow, "_connect_signals"):
            window = MainWindow(async_bridge=bridge)
        yield window
        window.close()

    @pytest.mark.parametrize(
        "error_type,expected_severity,expected_title",
        [
            ("WiiMConnectionError", "ERROR", "Device Offline"),
            ("WiiMTimeoutError", "ERROR", "Device Offline"),
            ("WiiMResponseError", "ERROR", "Communication Error"),
            ("ParseError", "ERROR", "Parse Error"),
            ("ValidationError", "WARNING", "Validation Warning"),
            ("SchemaVersionError", "ERROR", "Profile Incompatible"),
            ("ProfileNotFoundError", "ERROR", "Profile Not Found"),
            ("BackupError", "ERROR", "Backup Failed"),
            ("REWNotConnectedError", "WARNING", "REW Not Connected"),
            ("REWMeasurementNotFoundError", "ERROR", "Measurement Not Found"),
        ],
    )
    def test_error_type_mapping(
        self,
        main_window,
        error_type: str,
        expected_severity: str,
        expected_title: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Each error_type maps to the correct severity and title."""
        calls: list[dict[str, object]] = []

        def mock_show_error(
            severity,
            title,
            message,
            *,
            backup_path=None,
            recovery_steps=None,
            parent=None,
        ) -> None:
            calls.append({
                "severity": severity,
                "title": title,
                "message": message,
                "backup_path": backup_path,
            })

        monkeypatch.setattr(ErrorDialog, "show_error", staticmethod(mock_show_error))

        main_window._on_operation_error(error_type, "test message")

        assert len(calls) == 1
        assert calls[0]["severity"] == expected_severity
        assert calls[0]["title"] == expected_title
        assert calls[0]["message"] == "test message"

    def test_rollback_error_extracts_backup_path(
        self, main_window, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RollbackError extracts backup path from message and passes to dialog."""
        calls: list[dict[str, object]] = []

        def mock_show_error(
            severity,
            title,
            message,
            *,
            backup_path=None,
            recovery_steps=None,
            parent=None,
        ) -> None:
            calls.append({
                "severity": severity,
                "title": title,
                "backup_path": backup_path,
            })

        monkeypatch.setattr(ErrorDialog, "show_error", staticmethod(mock_show_error))

        msg = "Rollback failed. Backup at /home/user/.local/share/wiim/backup_20250101.json"
        main_window._on_operation_error("RollbackError", msg)

        assert len(calls) == 1
        assert calls[0]["severity"] == "CRITICAL"
        assert calls[0]["backup_path"] == "/home/user/.local/share/wiim/backup_20250101.json"

    def test_rollback_error_windows_path(
        self, main_window, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RollbackError extracts Windows-style backup path."""
        calls: list[dict[str, object]] = []

        def mock_show_error(
            severity,
            title,
            message,
            *,
            backup_path=None,
            recovery_steps=None,
            parent=None,
        ) -> None:
            calls.append({"backup_path": backup_path})

        monkeypatch.setattr(ErrorDialog, "show_error", staticmethod(mock_show_error))

        msg = r"Rollback failed. Backup at C:\Users\test\backup.json was preserved"
        main_window._on_operation_error("RollbackError", msg)

        assert calls[0]["backup_path"] == r"C:\Users\test\backup.json"

    def test_unknown_error_type_defaults_to_error(
        self, main_window, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unknown error types default to ERROR severity."""
        calls: list[dict[str, object]] = []

        def mock_show_error(
            severity,
            title,
            message,
            *,
            backup_path=None,
            recovery_steps=None,
            parent=None,
        ) -> None:
            calls.append({"severity": severity, "title": title})

        monkeypatch.setattr(ErrorDialog, "show_error", staticmethod(mock_show_error))

        main_window._on_operation_error("SomeRandomError", "unknown error")

        assert calls[0]["severity"] == "ERROR"
        assert calls[0]["title"] == "Error"

    def test_rollback_error_logs_critical(
        self, main_window, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """RollbackError is logged at CRITICAL level."""
        monkeypatch.setattr(
            ErrorDialog, "show_error",
            staticmethod(lambda *a, **kw: None),
        )

        app_logger = logging.getLogger("wiim_rew_sync.app")
        app_logger.propagate = True
        try:
            with caplog.at_level(logging.CRITICAL, logger="wiim_rew_sync.app"):
                main_window._on_operation_error("RollbackError", "rollback failed")
            assert "RollbackError" in caplog.text
        finally:
            app_logger.propagate = False

    def test_normal_error_logs_error_level(
        self, main_window, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-critical errors are logged at ERROR level."""
        monkeypatch.setattr(
            ErrorDialog, "show_error",
            staticmethod(lambda *a, **kw: None),
        )

        app_logger = logging.getLogger("wiim_rew_sync.app")
        app_logger.propagate = True
        try:
            with caplog.at_level(logging.ERROR, logger="wiim_rew_sync.app"):
                main_window._on_operation_error("ParseError", "parse failed")
            assert "ParseError" in caplog.text
        finally:
            app_logger.propagate = False


class TestExtractBackupPath:
    """Test the static _extract_backup_path utility."""

    def test_unix_path_extraction(self) -> None:
        """Extract Unix-style path from message."""
        from src.gui.main_window import MainWindow

        msg = "Failed to restore. Backup: /var/data/wiim/backup_123.json"
        result = MainWindow._extract_backup_path(msg)
        assert result == "/var/data/wiim/backup_123.json"

    def test_windows_path_extraction(self) -> None:
        """Extract Windows-style path from message."""
        from src.gui.main_window import MainWindow

        msg = r"Backup at C:\Users\test\backup.json was preserved"
        result = MainWindow._extract_backup_path(msg)
        assert result == r"C:\Users\test\backup.json"

    def test_no_path_returns_none(self) -> None:
        """Returns None when no path is found."""
        from src.gui.main_window import MainWindow

        result = MainWindow._extract_backup_path("No path here")
        assert result is None
