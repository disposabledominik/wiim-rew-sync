"""Integration tests for SecondaryWorkflowManager with mocked adapters.

Tests the secondary workflows (undo, profile recall) by driving the async
methods directly with mocked adapter factories and verifying signal
emissions.

Note: copy-to-sources, multi-device push, and copy-preset-to-device tests
were removed (code quality audit, 2026-06-28) along with the corresponding
dead SecondaryWorkflowManager methods — see docs/backlog.md.

Requirements: 8.1-8.6
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adapters.safe_write import WriteResult
from src.gui.secondary_workflows import SecondaryWorkflowManager

# ---------------------------------------------------------------------------
# Undo with missing backup file
# ---------------------------------------------------------------------------


class TestUndoMissingBackupFile:
    """Test undo with non-existent backup file.

    Requirements: 8.1, 8.5
    """

    @pytest.mark.asyncio
    async def test_undo_missing_backup_file(self) -> None:
        """Configure manager with a non-existent backup_path. Call
        _do_undo(source_name, '/nonexistent/backup.json'). Verify
        undo_complete(False, 'No backup available') emitted.
        """
        manager = SecondaryWorkflowManager()

        # Inject dependencies
        mock_adapter = MagicMock()
        manager._current_adapter = mock_adapter
        manager._safe_write_factory = MagicMock()

        # Capture undo_complete signal
        undo_signals: list[tuple[bool, str]] = []
        manager.undo_complete.connect(lambda ok, msg: undo_signals.append((ok, msg)))

        # Execute with non-existent path
        await manager._do_undo("wifi", "/nonexistent/backup.json")

        # Verify undo_complete(False, "No backup available")
        assert len(undo_signals) == 1
        success, message = undo_signals[0]
        assert success is False
        assert message == "No backup available"


# ---------------------------------------------------------------------------
# Undo success with valid backup file
# ---------------------------------------------------------------------------


class TestUndoSuccessWithValidBackup:
    """Test undo with a real temporary JSON backup file.

    Requirements: 8.1, 8.2, 8.3

    _do_undo() now delegates entirely to SafeWrite.undo() (backup parsing
    and PEQSettings reconstruction moved into SafeWrite itself -- see
    test_safe_write.py's TestPeqUndo* classes for coverage of that logic,
    including the L/R-unequal-lengths regression that used to live here).
    """

    @pytest.mark.asyncio
    async def test_undo_success_with_valid_backup(self, tmp_path) -> None:
        """Create a real temp JSON backup file. Call _do_undo(source_name,
        temp_path). Mock SafeWrite.undo() to succeed. Verify
        undo_complete(True, 'Previous filters restored') emitted.
        """
        backup_file = tmp_path / "backup.json"
        backup_file.write_text("{}", encoding="utf-8")

        manager = SecondaryWorkflowManager()

        mock_sw = AsyncMock()
        mock_sw.undo = AsyncMock(return_value=WriteResult(success=True, backup_path=None))

        mock_adapter = MagicMock()
        manager._current_adapter = mock_adapter
        manager._safe_write_factory = MagicMock(return_value=mock_sw)

        # Capture undo_complete signal
        undo_signals: list[tuple[bool, str]] = []
        manager.undo_complete.connect(lambda ok, msg: undo_signals.append((ok, msg)))

        # Execute with real backup file
        await manager._do_undo("wifi", str(backup_file))

        # Verify undo_complete(True, "Previous filters restored")
        assert len(undo_signals) == 1
        success, message = undo_signals[0]
        assert success is True
        assert message == "Previous filters restored"

        # Verify SafeWrite.undo() was called with the backup path + source
        mock_sw.undo.assert_called_once()
        call_args = mock_sw.undo.call_args
        assert call_args[0][0] == backup_file
        assert call_args[0][1] == "wifi"

    @pytest.mark.asyncio
    async def test_undo_failure_propagates_error_not_hardcoded_success(
        self, tmp_path
    ) -> None:
        """A failed/rolled-back undo (SafeWrite.undo() returning
        success=False) must be reported to the user as a failure -- not the
        old hardcoded (True, 'Previous filters restored') regardless of
        outcome (latent bug fixed alongside the SafeWrite.undo() rewrite).
        """
        backup_file = tmp_path / "backup.json"
        backup_file.write_text("{}", encoding="utf-8")

        manager = SecondaryWorkflowManager()

        mock_sw = AsyncMock()
        mock_sw.undo = AsyncMock(
            return_value=WriteResult(success=False, error_message="Rollback failed")
        )

        mock_adapter = MagicMock()
        manager._current_adapter = mock_adapter
        manager._safe_write_factory = MagicMock(return_value=mock_sw)

        undo_signals: list[tuple[bool, str]] = []
        manager.undo_complete.connect(lambda ok, msg: undo_signals.append((ok, msg)))

        await manager._do_undo("wifi", str(backup_file))

        assert len(undo_signals) == 1
        success, message = undo_signals[0]
        assert success is False
        assert message == "Rollback failed"
