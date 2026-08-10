"""Integration tests for SecondaryWorkflowManager with mocked adapters.

Tests the secondary workflows (undo, profile recall) by driving the async
methods directly with mocked adapter factories and verifying signal
emissions.

Note: copy-preset-to-device coverage (_write_preset_to_adapter,
_do_copy_presets_batch_multi, etc.) lives in
test_smoke_regression_operations.py instead of here (issue26/34/58/69/74/
78/79/153/194 and others) -- those characterization tests were written
against MainWindow during the original Phase D extraction (docs/backlog.md
item 2) and never relocated. This file's own convention is undo/
profile-recall workflows driven directly against the manager via mocked
factories; a 2026-06-28 code-quality audit removed an earlier, unrelated
set of copy-to-sources/multi-device-push tests here for methods that were
genuinely dead at the time -- that note is retired as of the 2026-07-17
branch-quality review, which found it had gone stale: the copy-to-device
methods above are very much alive and wired to real UI actions in
main_window.py (_on_copy_to_device_requested, _on_local_preset_copy_to_device_requested).
_do_copy_local_profiles_to_devices's write path is still exercised via
MainWindow in test_smoke_regression_operations.py, but its PEQSettings
build/validation step moved into the manager itself (2026-08-02, GUI
business-logic-leak fix) and is tested directly against the coroutine below
in TestCopyLocalProfileToDevicesValidation.

Requirements: 8.1-8.6
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adapters.safe_write import WriteResult
from src.gui.secondary_workflows import SecondaryWorkflowManager
from src.models.canonical import CanonicalFilter
from src.models.channel_mode import ChannelMode

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

    @pytest.mark.asyncio
    async def test_restore_backup_raises_when_bridge_not_configured(
        self, tmp_path
    ) -> None:
        """configure()-invariant violations are programmer errors, not
        ordinary undo failures -- _restore_backup() must let the
        `self._bridge is not None` assert propagate (for _bridge_wrapper's
        loud crash-log path) rather than swallowing it into a graceful
        undo_complete(False, ...) signal. Only reachable if a real backup
        file exists but configure() was never called -- round-5 code-review
        finding, 2026-07-26.
        """
        backup_file = tmp_path / "backup.json"
        backup_file.write_text("{}", encoding="utf-8")

        manager = SecondaryWorkflowManager()
        manager._current_adapter = MagicMock()
        manager._safe_write_factory = MagicMock()
        # manager._bridge deliberately left at its default (None).

        with pytest.raises(AssertionError, match="configure"):
            await manager._restore_backup("wifi", str(backup_file))


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
        manager._bridge = MagicMock()

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
        manager._bridge = MagicMock()

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


# ---------------------------------------------------------------------------
# Source-slot overview fetch (#194 follow-up diagnostic)
# ---------------------------------------------------------------------------


class TestFetchSourceSlots:
    """Test SecondaryWorkflowManager._do_fetch_source_slots."""

    @pytest.mark.asyncio
    async def test_no_adapter_emits_error(self) -> None:
        manager = SecondaryWorkflowManager()
        manager._current_adapter = None

        errors: list[str] = []
        manager.source_slots_error.connect(errors.append)

        await manager._do_fetch_source_slots()

        assert errors == ["No device connected"]

    @pytest.mark.asyncio
    async def test_success_emits_ready_with_slots(self) -> None:
        from src.models.source_slot import SourceSlotInfo

        manager = SecondaryWorkflowManager()
        slots = [SourceSlotInfo(source_name="wifi", is_known_source=True)]
        mock_adapter = MagicMock()
        mock_adapter.get_source_slot_overview = AsyncMock(return_value=slots)
        manager._current_adapter = mock_adapter

        ready_signals: list[list] = []
        manager.source_slots_ready.connect(ready_signals.append)

        await manager._do_fetch_source_slots()

        assert ready_signals == [slots]

    @pytest.mark.asyncio
    async def test_adapter_error_emits_error_signal(self) -> None:
        manager = SecondaryWorkflowManager()
        mock_adapter = MagicMock()
        mock_adapter.get_source_slot_overview = AsyncMock(
            side_effect=RuntimeError("device rejected EQGetSourceModes")
        )
        manager._current_adapter = mock_adapter

        errors: list[str] = []
        manager.source_slots_error.connect(errors.append)

        await manager._do_fetch_source_slots()

        assert errors == ["device rejected EQGetSourceModes"]


# ---------------------------------------------------------------------------
# Undo RoomFit profile (moved here from MainWindow, docs/backlog.md item 2
# Phase D -- was _do_undo_roomfit)
# ---------------------------------------------------------------------------


class TestUndoRoomfit:
    """Test SecondaryWorkflowManager._do_undo_roomfit."""

    @pytest.mark.asyncio
    async def test_raises_when_bridge_not_configured(self, tmp_path) -> None:
        """Same configure()-invariant-must-propagate requirement as
        _restore_backup() -- see
        test_restore_backup_raises_when_bridge_not_configured above.
        Round-5 code-review finding, 2026-07-26.
        """
        backup_file = tmp_path / "roomfit_backup.json"
        backup_file.write_text('{"was_new_profile": false}', encoding="utf-8")

        manager = SecondaryWorkflowManager()
        manager._current_adapter = MagicMock()
        manager._roomfit_safe_write_factory = MagicMock()
        # manager._bridge deliberately left at its default (None).

        with pytest.raises(AssertionError, match="configure"):
            await manager._do_undo_roomfit(str(backup_file), "wifi", "My Profile")

    @pytest.mark.asyncio
    async def test_missing_backup_file_emits_failure(self) -> None:
        manager = SecondaryWorkflowManager()
        manager._bridge = MagicMock()
        manager._current_adapter = MagicMock()
        manager._roomfit_safe_write_factory = MagicMock()

        undo_signals: list[tuple[bool, str]] = []
        manager.undo_complete.connect(lambda ok, msg: undo_signals.append((ok, msg)))

        await manager._do_undo_roomfit("/nonexistent/backup.json", "wifi", "My Profile")

        assert undo_signals == [(False, "No backup available for undo")]
        manager._roomfit_safe_write_factory.assert_not_called()

    @pytest.mark.asyncio
    async def test_success_emits_restored_message(self, tmp_path) -> None:
        backup_file = tmp_path / "roomfit_backup.json"
        backup_file.write_text('{"was_new_profile": false}', encoding="utf-8")

        manager = SecondaryWorkflowManager()
        manager._bridge = MagicMock()
        manager._current_adapter = MagicMock()
        mock_roomfit_safe_write = AsyncMock()
        mock_roomfit_safe_write.undo = AsyncMock(return_value=WriteResult(success=True))
        manager._roomfit_safe_write_factory = MagicMock(
            return_value=mock_roomfit_safe_write
        )

        undo_signals: list[tuple[bool, str]] = []
        manager.undo_complete.connect(lambda ok, msg: undo_signals.append((ok, msg)))

        await manager._do_undo_roomfit(str(backup_file), "wifi", "My Profile")

        assert undo_signals == [(True, "Profile 'My Profile' restored from backup")]
        mock_roomfit_safe_write.undo.assert_called_once()
        call_args = mock_roomfit_safe_write.undo.call_args
        assert call_args[0][0] == backup_file
        assert call_args[0][1] == "wifi"
        assert call_args[0][2] == "My Profile"

    @pytest.mark.asyncio
    async def test_verification_failure_emits_error_message(self, tmp_path) -> None:
        backup_file = tmp_path / "roomfit_backup.json"
        backup_file.write_text('{"was_new_profile": false}', encoding="utf-8")

        manager = SecondaryWorkflowManager()
        manager._bridge = MagicMock()
        manager._current_adapter = MagicMock()
        mock_roomfit_safe_write = AsyncMock()
        mock_roomfit_safe_write.undo = AsyncMock(
            return_value=WriteResult(success=False, error_message="Rollback failed")
        )
        manager._roomfit_safe_write_factory = MagicMock(
            return_value=mock_roomfit_safe_write
        )

        undo_signals: list[tuple[bool, str]] = []
        manager.undo_complete.connect(lambda ok, msg: undo_signals.append((ok, msg)))

        await manager._do_undo_roomfit(str(backup_file), "wifi", "My Profile")

        assert undo_signals == [(False, "Rollback failed")]

    @pytest.mark.asyncio
    async def test_exception_emits_failure_with_exception_text(self, tmp_path) -> None:
        backup_file = tmp_path / "roomfit_backup.json"
        backup_file.write_text('{"was_new_profile": false}', encoding="utf-8")

        manager = SecondaryWorkflowManager()
        manager._bridge = MagicMock()
        manager._current_adapter = MagicMock()
        mock_roomfit_safe_write = AsyncMock()
        mock_roomfit_safe_write.undo = AsyncMock(
            side_effect=ConnectionError("device unreachable")
        )
        manager._roomfit_safe_write_factory = MagicMock(
            return_value=mock_roomfit_safe_write
        )

        undo_signals: list[tuple[bool, str]] = []
        manager.undo_complete.connect(lambda ok, msg: undo_signals.append((ok, msg)))

        await manager._do_undo_roomfit(str(backup_file), "wifi", "My Profile")

        assert undo_signals == [(False, "device unreachable")]


# ---------------------------------------------------------------------------
# Undo multi-source push (moved here from MainWindow, docs/backlog.md item 2
# Phase D -- was _do_undo_multi_source)
# ---------------------------------------------------------------------------


class TestUndoMultiSource:
    """Test SecondaryWorkflowManager._do_undo_multi_source.

    _do_undo_multi_source awaits each source's real restore via
    _restore_backup() directly (fixed branch-quality review, 2026-07-18 --
    previously it called the fire-and-forget undo_last_push() and tallied
    scheduling success, not actual outcome; full characterization of that
    prior gap lives in test_smoke_regression_operations.py, captured before
    this method moved here). These tests mock _restore_backup() directly to
    isolate this method's aggregation logic; _restore_backup()'s own
    correctness (SafeWrite.undo() success/failure/missing-backup-file
    handling) is covered by TestUndoSuccessWithValidBackup and
    TestUndoMissingBackupFile above, which exercise it via _do_undo().
    """

    @pytest.mark.asyncio
    async def test_single_entry_restores_and_emits_success(self) -> None:
        manager = SecondaryWorkflowManager()
        manager._bridge = MagicMock()
        restored: list[tuple[str, str]] = []

        async def _restore(src: str, path: str) -> tuple[bool, str]:
            restored.append((src, path))
            return True, "Previous filters restored"

        manager._restore_backup = _restore  # type: ignore[assignment]

        undo_signals: list[tuple[int, int, str]] = []
        manager.undo_multi_source_complete.connect(
            lambda succeeded, failed, msg: undo_signals.append((succeeded, failed, msg))
        )

        await manager._do_undo_multi_source("wifi=/tmp/backup_wifi.json")

        assert restored == [("wifi", "/tmp/backup_wifi.json")]
        assert undo_signals == [(1, 0, "All 1 source(s) restored from backup")]

    @pytest.mark.asyncio
    async def test_restore_failure_emits_failure_tally(self) -> None:
        manager = SecondaryWorkflowManager()
        manager._bridge = MagicMock()

        async def _restore(src: str, path: str) -> tuple[bool, str]:
            return False, "Verification failed"

        manager._restore_backup = _restore  # type: ignore[assignment]

        undo_signals: list[tuple[int, int, str]] = []
        manager.undo_multi_source_complete.connect(
            lambda succeeded, failed, msg: undo_signals.append((succeeded, failed, msg))
        )

        await manager._do_undo_multi_source("wifi=/tmp/backup_wifi.json")

        assert undo_signals == [(0, 1, "0 restored, 1 failed")]

    @pytest.mark.asyncio
    async def test_partial_success_emits_both_counts(self) -> None:
        """2 of 3 sources actually restore, 1 genuinely fails (e.g. device
        unreachable during that source's SafeWrite.undo()).

        Regression coverage for the snapshot-clearing bug (branch-quality
        review, 2026-07-17): the manager's own tally must report succeeded=2
        so MainWindow._on_undo_multi_source_complete can clear the pushed
        snapshot on a partial success, not just a full one. Also regression
        coverage for the scheduling-vs-outcome fix (2026-07-18): the tally
        now reflects each source's real restore outcome, not just whether
        scheduling it raised.
        """
        manager = SecondaryWorkflowManager()
        manager._bridge = MagicMock()
        restored: list[tuple[str, str]] = []

        async def _restore(src: str, path: str) -> tuple[bool, str]:
            if src == "bluetooth":
                return False, "Device unreachable"
            restored.append((src, path))
            return True, "Previous filters restored"

        manager._restore_backup = _restore  # type: ignore[assignment]

        undo_signals: list[tuple[int, int, str]] = []
        manager.undo_multi_source_complete.connect(
            lambda succeeded, failed, msg: undo_signals.append((succeeded, failed, msg))
        )

        await manager._do_undo_multi_source(
            "wifi=/tmp/backup_wifi.json;bluetooth=/tmp/backup_bt.json;optical=/tmp/backup_opt.json"
        )

        assert restored == [
            ("wifi", "/tmp/backup_wifi.json"),
            ("optical", "/tmp/backup_opt.json"),
        ]
        assert undo_signals == [(2, 1, "2 restored, 1 failed")]

    @pytest.mark.asyncio
    async def test_zero_entries_emits_failure_not_false_success(self) -> None:
        """A backup_paths_str that decodes to zero entries (empty or fully
        malformed) must not fall through the loop and emit a misleading
        "All 0 source(s) restored" success -- no current producer of
        backup_paths_str can generate this today, but the guard is cheap
        and correct to keep (round-4 review finding #6, PLAUSIBLE,
        2026-07-19)."""
        manager = SecondaryWorkflowManager()
        manager._bridge = MagicMock()
        restore_calls: list[tuple[str, str]] = []

        async def _restore(src: str, path: str) -> tuple[bool, str]:
            restore_calls.append((src, path))
            return True, "Previous filters restored"

        manager._restore_backup = _restore  # type: ignore[assignment]

        undo_signals: list[tuple[int, int, str]] = []
        manager.undo_multi_source_complete.connect(
            lambda succeeded, failed, msg: undo_signals.append((succeeded, failed, msg))
        )

        await manager._do_undo_multi_source("")

        assert restore_calls == []
        assert len(undo_signals) == 1
        succeeded, failed, _msg = undo_signals[0]
        assert succeeded == 0
        assert failed != 0


class TestCopyLocalProfileToDevicesValidation:
    """SecondaryWorkflowManager._do_copy_local_profiles_to_devices builds and
    validates a PEQSettings from each local Profile's raw fields itself now
    (moved out of MainWindow, branch-quality review 2026-08-02, GUI
    business-logic-leak fix). An incomplete L/R split (build_peq_settings()'s
    ValueError, require_lr_filters, ca14e26) must be reported the same way a
    live-device read failure is in _do_copy_presets_batch_multi: via
    copy_batch_complete with the failing profile's device-count added to
    failed, plus a progress_update naming the failure -- not raised back
    into the caller, and without blocking the rest of the batch.
    """

    @pytest.mark.asyncio
    async def test_incomplete_lr_split_reports_failure_without_writing(self) -> None:
        manager = SecondaryWorkflowManager()
        manager._bridge = MagicMock()

        complete_signals: list[tuple[int, int, int, int]] = []
        manager.copy_batch_complete.connect(
            lambda n_items, n, ok, fail: complete_signals.append((n_items, n, ok, fail))
        )

        target_devices = [MagicMock(ip="192.168.1.200", name="Other Device")]

        await manager._do_copy_local_profiles_to_devices(
            [
                (
                    "Broken LR Profile",
                    ChannelMode.LR,
                    None,
                    [],
                    [CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-2.0, q=1.0)],
                )
            ],
            "PEQ",
            target_devices,
            "wifi",
        )

        assert complete_signals == [(1, 1, 0, 1)]
        manager._bridge.progress_update.emit.assert_called_once()
        assert "Copy failed" in manager._bridge.progress_update.emit.call_args[0][0]

    @pytest.mark.asyncio
    async def test_valid_stereo_profile_proceeds_to_write(self) -> None:
        """A valid split must still reach the write path (not short-circuit
        the way the invalid-split case above does)."""
        manager = SecondaryWorkflowManager()
        manager._bridge = MagicMock()
        manager._safe_write_factory = MagicMock()

        write_calls: list[tuple] = []

        async def _fake_write(reads, target_devices, target_source):
            write_calls.append((reads, target_devices, target_source))
            return len(target_devices), 0

        manager._write_preset_copies_to_devices = _fake_write

        complete_signals: list[tuple[int, int, int, int]] = []
        manager.copy_batch_complete.connect(
            lambda n_items, n, ok, fail: complete_signals.append((n_items, n, ok, fail))
        )

        target_devices = [MagicMock(ip="192.168.1.200", name="Other Device")]
        stereo_filters = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-2.0, q=1.0)
        ]

        await manager._do_copy_local_profiles_to_devices(
            [("Good Profile", ChannelMode.STEREO, stereo_filters, None, None)],
            "PEQ",
            target_devices,
            "wifi",
        )

        assert len(write_calls) == 1
        assert complete_signals == [(1, 1, 1, 0)]

    @pytest.mark.asyncio
    async def test_batch_of_multiple_profiles_writes_all_and_aggregates_counts(
        self,
    ) -> None:
        """Multi-select Copy to Another Device (My Saved Presets) sends every
        selected profile through in one batch, not just the first -- this is
        the regression case for the "Copy greyed out under multi-select"
        report: the batch must actually reach the write path with every
        profile represented, and a single build failure partway through
        must not drop the rest of the batch."""
        manager = SecondaryWorkflowManager()
        manager._bridge = MagicMock()

        write_calls: list[tuple] = []

        async def _fake_write(reads, target_devices, target_source):
            write_calls.append((reads, target_devices, target_source))
            return len(reads) * len(target_devices), 0

        manager._write_preset_copies_to_devices = _fake_write

        complete_signals: list[tuple[int, int, int, int]] = []
        manager.copy_batch_complete.connect(
            lambda n_items, n, ok, fail: complete_signals.append((n_items, n, ok, fail))
        )

        target_devices = [
            MagicMock(ip="192.168.1.200", name="Device A"),
            MagicMock(ip="192.168.1.201", name="Device B"),
        ]
        filters = [CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-2.0, q=1.0)]

        await manager._do_copy_local_profiles_to_devices(
            [
                ("Profile One", ChannelMode.STEREO, filters, None, None),
                ("Broken LR Profile", ChannelMode.LR, None, [], filters),
                ("Profile Two", ChannelMode.STEREO, filters, None, None),
            ],
            "PEQ",
            target_devices,
            "wifi",
        )

        # The two valid profiles reach the shared write primitive together;
        # the broken one is excluded from `reads` but still counted as
        # failed (2 target devices) rather than silently dropped.
        assert len(write_calls) == 1
        reads_arg = write_calls[0][0]
        assert [r[0] for r in reads_arg] == ["Profile One", "Profile Two"]
        assert complete_signals == [(3, 2, 4, 2)]
