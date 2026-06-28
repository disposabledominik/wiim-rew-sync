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

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

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
    """

    @pytest.mark.asyncio
    async def test_undo_success_with_valid_backup(self, tmp_path) -> None:
        """Create a real temp JSON backup file with filter data. Call
        _do_undo(source_name, temp_path). Mock SafeWrite.execute to succeed.
        Verify undo_complete(True, 'Previous filters restored') emitted.
        """
        # Create a backup JSON file
        backup_data = {
            "channel_mode": "stereo",
            "filters": [
                {"type": "PEAK", "frequency_hz": 500.0, "gain_db": -2.0, "q": 1.0},
                {"type": "HS", "frequency_hz": 10000.0, "gain_db": 1.5, "q": 0.8},
            ],
        }
        backup_file = tmp_path / "backup.json"
        backup_file.write_text(json.dumps(backup_data), encoding="utf-8")

        manager = SecondaryWorkflowManager()

        # Mock SafeWrite that succeeds
        mock_sw = AsyncMock()
        mock_sw.execute = AsyncMock(return_value=None)

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

        # Verify SafeWrite.execute was called with correct source
        mock_sw.execute.assert_called_once()
        call_args = mock_sw.execute.call_args
        assert call_args[0][0] == "wifi"  # source_name


# ---------------------------------------------------------------------------
# Undo with unequal-length L/R backup must not naively re-split
# ---------------------------------------------------------------------------


class TestUndoLRUnequalLengthsNotNaivelySplit:
    """Regression: undo must rebuild bands_l/bands_r from the backup's
    explicit per-channel data, never by positionally re-splitting the
    combined filter list 50/50 (that re-split is only "accidentally"
    correct when both channels happen to have equal length).
    """

    @pytest.mark.asyncio
    async def test_undo_lr_unequal_lengths_preserves_channel_split(
        self, tmp_path
    ) -> None:
        """Backup has 3 L-channel bands and 5 R-channel bands (unequal).

        A naive 50/50 split of the combined 8-band list would produce 4/4,
        which would not match either real channel's content. Assert the
        PEQSettings passed to SafeWrite.execute has bands_l/bands_r exactly
        matching the backup's per-channel lists.
        """
        backup_data = {
            "channel_mode": "left",
            "filters_l": [
                {"type": "PEAK", "frequency_hz": 100.0, "gain_db": -2.0, "q": 1.0},
                {"type": "PEAK", "frequency_hz": 110.0, "gain_db": -2.0, "q": 1.0},
                {"type": "PEAK", "frequency_hz": 120.0, "gain_db": -2.0, "q": 1.0},
            ],
            "filters_r": [
                {"type": "PEAK", "frequency_hz": 200.0, "gain_db": -4.0, "q": 1.5},
                {"type": "PEAK", "frequency_hz": 210.0, "gain_db": -4.0, "q": 1.5},
                {"type": "PEAK", "frequency_hz": 220.0, "gain_db": -4.0, "q": 1.5},
                {"type": "PEAK", "frequency_hz": 230.0, "gain_db": -4.0, "q": 1.5},
                {"type": "PEAK", "frequency_hz": 240.0, "gain_db": -4.0, "q": 1.5},
            ],
        }
        backup_file = tmp_path / "backup_lr_unequal.json"
        backup_file.write_text(json.dumps(backup_data), encoding="utf-8")

        manager = SecondaryWorkflowManager()

        mock_sw = AsyncMock()
        mock_sw.execute = AsyncMock(return_value=None)

        mock_adapter = MagicMock()
        manager._current_adapter = mock_adapter
        manager._safe_write_factory = MagicMock(return_value=mock_sw)

        await manager._do_undo("wifi", str(backup_file))

        mock_sw.execute.assert_called_once()
        call_args = mock_sw.execute.call_args
        settings = call_args[0][1]

        assert settings.bands_l is not None and len(settings.bands_l) == 3
        assert settings.bands_r is not None and len(settings.bands_r) == 5
        assert [f.frequency_hz for f in settings.bands_l] == [100.0, 110.0, 120.0]
        assert [f.frequency_hz for f in settings.bands_r] == [
            200.0, 210.0, 220.0, 230.0, 240.0,
        ]
