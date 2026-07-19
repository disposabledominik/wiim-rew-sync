"""Unit tests for SafeWrite — five-step safe write protocol.

Tests use AsyncMock for adapter and backup_manager to exercise:
- Success path (backup -> write -> readback matches -> commit)
- Verify failure triggers rollback (readback doesn't match -> rollback succeeds)
- Rollback failure logs CRITICAL and returns rollback_success=False

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from unittest.mock import ANY, AsyncMock, MagicMock

import pytest

from src.adapters.safe_write import (
    RoomFitSafeWrite,
    SafeWrite,
    _describe_first_mismatch,
    verify_bands,
)
from src.adapters.wiim_adapter import WiiMAdapter
from src.models.canonical import CanonicalFilter
from src.models.capabilities import DeviceCapabilities
from src.models.channel_mode import ChannelMode
from src.models.peq import PEQSettings
from src.repository.backup_manager import BackupManager
from src.tests.conftest import iter_src_python_files

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_bands(
    freq: float = 100.0, gain: float = -2.0, q: float = 1.0
) -> list[CanonicalFilter]:
    """Create a 10-band filter list (first band active, rest OFF)."""
    bands = [CanonicalFilter(type="PEAK", frequency_hz=freq, gain_db=gain, q=q)]
    for _ in range(9):
        bands.append(CanonicalFilter(type="OFF", frequency_hz=1000.0, gain_db=0.0, q=1.0))
    return bands


def _make_settings(
    bands: list[CanonicalFilter] | None = None,
    channel_mode: str = "stereo",
) -> PEQSettings:
    """Create PEQSettings for testing."""
    if bands is None:
        bands = _make_bands()
    if channel_mode == "stereo":
        return PEQSettings(
            source_name="wifi",
            enabled=True,
            channel_mode=ChannelMode.STEREO,
            bands=bands,
        )
    else:
        return PEQSettings(
            source_name="wifi",
            enabled=True,
            channel_mode=ChannelMode.LR,
            bands_l=bands,
            bands_r=bands,
        )


def _solo_capabilities() -> DeviceCapabilities:
    """Create solo device capabilities."""
    return DeviceCapabilities(
        supports_peq=True,
        supports_batch_write=True,
        supports_lr_filters=True,
        max_filters=10,
        model="WiiM_Ultra",
        firmware="6.0.1.20",
        uuid="test-uuid-1234",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_adapter() -> AsyncMock:
    """Mocked WiiMAdapter."""
    adapter = AsyncMock(spec=WiiMAdapter)
    adapter.capabilities = _solo_capabilities()
    adapter.read_peq = AsyncMock()
    adapter.write_peq = AsyncMock()
    return adapter


@pytest.fixture
def mock_backup_manager() -> MagicMock:
    """Mocked BackupManager."""
    bm = MagicMock(spec=BackupManager)
    bm.create_backup = MagicMock(return_value=Path("/backups/test-uuid-1234/backup.json"))
    return bm


@pytest.fixture
def mock_queue() -> AsyncMock:
    """Mocked WiiMCommandQueue."""
    queue = AsyncMock()
    queue.enqueue = AsyncMock()
    return queue


@pytest.fixture
def safe_write(
    mock_adapter: AsyncMock,
    mock_backup_manager: MagicMock,
    mock_queue: AsyncMock,
) -> SafeWrite:
    """SafeWrite instance with mocked dependencies."""
    return SafeWrite(
        adapter=mock_adapter,
        backup_manager=mock_backup_manager,
        queue=mock_queue,
    )


# ---------------------------------------------------------------------------
# Tests: Success Path
# ---------------------------------------------------------------------------


class TestSuccessPath:
    """Test the happy path: backup -> write -> readback matches -> commit."""

    async def test_success_returns_true(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock, mock_backup_manager: MagicMock
    ) -> None:
        """Success path returns WriteResult(success=True)."""
        intended = _make_settings()
        # read_peq called twice: once for backup, once for read-back verification
        mock_adapter.read_peq.side_effect = [
            intended,  # Step 1: current state for backup
            intended,  # Step 3: read-back matches intended
        ]

        result = await safe_write.execute("wifi", intended)

        assert result.success is True
        assert result.rollback_success is None
        assert result.backup_path is not None

    async def test_success_calls_backup(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock, mock_backup_manager: MagicMock
    ) -> None:
        """Success path creates a pre_write backup."""
        intended = _make_settings()
        mock_adapter.read_peq.side_effect = [intended, intended]

        await safe_write.execute("wifi", intended)

        mock_backup_manager.create_backup.assert_called_once()
        call_args = mock_backup_manager.create_backup.call_args
        assert call_args[0][2] == "pre_write"

    async def test_success_calls_write_peq(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock
    ) -> None:
        """Success path calls adapter.write_peq with correct args."""
        intended = _make_settings()
        mock_adapter.read_peq.side_effect = [intended, intended]

        await safe_write.execute("wifi", intended)

        mock_adapter.write_peq.assert_called_once_with("wifi", intended, safe_write._queue)

    async def test_success_reads_back_fresh(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock
    ) -> None:
        """Success path reads back device state after write (two read_peq calls)."""
        intended = _make_settings()
        mock_adapter.read_peq.side_effect = [intended, intended]

        await safe_write.execute("wifi", intended)

        assert mock_adapter.read_peq.call_count == 2

    async def test_success_with_tolerance_match(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock
    ) -> None:
        """Bands within tolerance thresholds still pass verification."""
        intended_bands = _make_bands(freq=100.0, gain=-2.0, q=1.0)
        intended = _make_settings(bands=intended_bands)

        # Read-back with values within tolerance
        readback_bands = _make_bands(freq=100.05, gain=-2.02, q=1.005)
        readback = _make_settings(bands=readback_bands)

        mock_adapter.read_peq.side_effect = [intended, readback]

        result = await safe_write.execute("wifi", intended)

        assert result.success is True


# ---------------------------------------------------------------------------
# Tests: on_stage callback (#189)
# ---------------------------------------------------------------------------


class TestOnStageCallback:
    """SafeWrite.execute() reports real progress via the optional on_stage callback."""

    async def test_success_calls_stages_in_order(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock
    ) -> None:
        """Success path calls on_stage for all four stages, in order."""
        intended = _make_settings()
        mock_adapter.read_peq.side_effect = [intended, intended]
        seen: list[str] = []

        await safe_write.execute("wifi", intended, on_stage=seen.append)

        assert seen == ["backing_up", "writing", "verifying", "done"]

    async def test_failure_does_not_call_done(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock
    ) -> None:
        """Verification failure stops after 'verifying' -- 'done' is never reported."""
        intended = _make_settings(bands=_make_bands(freq=100.0, gain=-2.0, q=1.0))
        original = _make_settings(bands=_make_bands(freq=200.0, gain=0.0, q=1.5))
        bad_readback = _make_settings(bands=_make_bands(freq=500.0, gain=-2.0, q=1.0))
        mock_adapter.read_peq.side_effect = [
            original, bad_readback, bad_readback, original
        ]
        seen: list[str] = []

        result = await safe_write.execute("wifi", intended, on_stage=seen.append)

        assert result.success is False
        assert seen == ["backing_up", "writing", "verifying"]

    async def test_on_stage_none_is_a_no_op(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock
    ) -> None:
        """Omitting on_stage (the default) does not raise."""
        intended = _make_settings()
        mock_adapter.read_peq.side_effect = [intended, intended]

        result = await safe_write.execute("wifi", intended)

        assert result.success is True


# ---------------------------------------------------------------------------
# Tests: Verify Failure -> Rollback Success
# ---------------------------------------------------------------------------


class TestVerifyFailureRollbackSuccess:
    """Test rollback when verification fails but rollback succeeds."""

    async def test_rollback_triggered_on_mismatch(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock, mock_backup_manager: MagicMock
    ) -> None:
        """Verification failure triggers rollback and returns success=False."""
        intended = _make_settings(bands=_make_bands(freq=100.0, gain=-2.0, q=1.0))
        original = _make_settings(bands=_make_bands(freq=200.0, gain=0.0, q=1.5))

        # Mismatched read-back (frequency far off)
        bad_readback = _make_settings(bands=_make_bands(freq=500.0, gain=-2.0, q=1.0))

        mock_adapter.read_peq.side_effect = [
            original,       # Step 1: current state for backup
            bad_readback,   # Step 3: read-back does NOT match intended
            bad_readback,   # Rollback: read current (corrupted) state for pre_rollback backup
            original,       # Rollback verification: read-back matches original
        ]

        result = await safe_write.execute("wifi", intended)

        assert result.success is False
        assert result.rollback_success is True

    async def test_rollback_creates_pre_rollback_backup(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock, mock_backup_manager: MagicMock
    ) -> None:
        """Rollback creates a pre_rollback backup before restoring."""
        intended = _make_settings(bands=_make_bands(freq=100.0))
        original = _make_settings(bands=_make_bands(freq=200.0))
        bad_readback = _make_settings(bands=_make_bands(freq=500.0))

        mock_adapter.read_peq.side_effect = [
            original, bad_readback, bad_readback, original
        ]

        await safe_write.execute("wifi", intended)

        # Two backups created: pre_write and pre_rollback
        assert mock_backup_manager.create_backup.call_count == 2
        triggers = [
            call[0][2] for call in mock_backup_manager.create_backup.call_args_list
        ]
        assert triggers == ["pre_write", "pre_rollback"]

    async def test_rollback_writes_original_back(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock
    ) -> None:
        """Rollback writes the original settings back via the queue."""
        intended = _make_settings(bands=_make_bands(freq=100.0))
        original = _make_settings(bands=_make_bands(freq=200.0))
        bad_readback = _make_settings(bands=_make_bands(freq=500.0))

        mock_adapter.read_peq.side_effect = [
            original, bad_readback, bad_readback, original
        ]

        await safe_write.execute("wifi", intended)

        # write_peq called twice: once for intended, once for rollback
        assert mock_adapter.write_peq.call_count == 2
        rollback_call = mock_adapter.write_peq.call_args_list[1]
        assert rollback_call[0][0] == "wifi"
        assert rollback_call[0][1] == original

    async def test_rollback_success_has_error_message(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock
    ) -> None:
        """Successful rollback includes an informative error message."""
        intended = _make_settings(bands=_make_bands(freq=100.0))
        original = _make_settings(bands=_make_bands(freq=200.0))
        bad_readback = _make_settings(bands=_make_bands(freq=500.0))

        mock_adapter.read_peq.side_effect = [
            original, bad_readback, bad_readback, original
        ]

        result = await safe_write.execute("wifi", intended)

        assert result.error_message is not None
        assert "restored" in result.error_message.lower()


# ---------------------------------------------------------------------------
# Tests: Rollback Failure -> CRITICAL Log
# ---------------------------------------------------------------------------


class TestRollbackFailure:
    """Test that rollback failure logs CRITICAL and returns correct result."""

    async def test_rollback_failure_returns_false(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock
    ) -> None:
        """Rollback failure returns success=False, rollback_success=False."""
        intended = _make_settings(bands=_make_bands(freq=100.0))
        original = _make_settings(bands=_make_bands(freq=200.0))
        bad_readback = _make_settings(bands=_make_bands(freq=500.0))

        # Rollback read-back also doesn't match original
        mock_adapter.read_peq.side_effect = [
            original,       # Step 1: current state
            bad_readback,   # Step 3: read-back mismatch
            bad_readback,   # Rollback: read current for pre_rollback
            bad_readback,   # Rollback verification: STILL doesn't match
        ]

        result = await safe_write.execute("wifi", intended)

        assert result.success is False
        assert result.rollback_success is False
        assert result.backup_path is not None

    async def test_rollback_failure_logs_critical(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Rollback failure logs CRITICAL with backup path."""
        intended = _make_settings(bands=_make_bands(freq=100.0))
        original = _make_settings(bands=_make_bands(freq=200.0))
        bad_readback = _make_settings(bands=_make_bands(freq=500.0))

        mock_adapter.read_peq.side_effect = [
            original, bad_readback, bad_readback, bad_readback
        ]

        app_logger = logging.getLogger("wiim_rew_sync.app")
        app_logger.propagate = True
        try:
            with caplog.at_level(logging.CRITICAL, logger="wiim_rew_sync.app"):
                await safe_write.execute("wifi", intended)

            critical_records = [
                r for r in caplog.records if r.levelno == logging.CRITICAL
            ]
            assert len(critical_records) >= 1
            assert "backup" in critical_records[0].message.lower()
        finally:
            app_logger.propagate = False

    async def test_rollback_failure_includes_backup_path_in_message(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock
    ) -> None:
        """Rollback failure error_message includes the backup file path."""
        intended = _make_settings(bands=_make_bands(freq=100.0))
        original = _make_settings(bands=_make_bands(freq=200.0))
        bad_readback = _make_settings(bands=_make_bands(freq=500.0))

        mock_adapter.read_peq.side_effect = [
            original, bad_readback, bad_readback, bad_readback
        ]

        result = await safe_write.execute("wifi", intended)

        assert result.error_message is not None
        assert "backup" in result.error_message.lower()


# ---------------------------------------------------------------------------
# Tests: Batch vs Sequential (queue usage)
# ---------------------------------------------------------------------------


class TestBatchVsSequential:
    """Test that queue is passed through to adapter for write operations."""

    async def test_queue_passed_to_write(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock, mock_queue: AsyncMock
    ) -> None:
        """SafeWrite passes the queue to adapter.write_peq."""
        intended = _make_settings()
        mock_adapter.read_peq.side_effect = [intended, intended]

        await safe_write.execute("wifi", intended)

        # write_peq receives the queue argument
        call_args = mock_adapter.write_peq.call_args
        assert call_args[0][2] is mock_queue

    async def test_no_queue_passed_when_none(
        self, mock_adapter: AsyncMock, mock_backup_manager: MagicMock
    ) -> None:
        """SafeWrite passes None when no queue is provided."""
        sw = SafeWrite(adapter=mock_adapter, backup_manager=mock_backup_manager, queue=None)
        intended = _make_settings()
        mock_adapter.read_peq.side_effect = [intended, intended]

        await sw.execute("wifi", intended)

        call_args = mock_adapter.write_peq.call_args
        assert call_args[0][2] is None


# ---------------------------------------------------------------------------
# Tests: Band count tolerance in verification (hardware testing regression)
# ---------------------------------------------------------------------------


class TestBandCountTolerance:
    """Test _compare_band_lists tolerance when device returns more bands than written."""

    async def test_verify_passes_when_device_returns_more_bands(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock
    ) -> None:
        """Intended 10 bands, device returns 12 (first 10 match, extra 2 OFF) -> success."""
        intended_bands = _make_bands(freq=100.0, gain=-2.0, q=1.0)
        assert len(intended_bands) == 10

        # Read-back has 12 bands: first 10 match, last 2 are extra OFF bands
        readback_bands = [
            *intended_bands,
            CanonicalFilter(type="OFF", frequency_hz=1000.0, gain_db=0.0, q=1.0),
            CanonicalFilter(type="OFF", frequency_hz=1000.0, gain_db=0.0, q=1.0),
        ]
        assert len(readback_bands) == 12

        intended = _make_settings(bands=intended_bands)
        readback = _make_settings(bands=readback_bands)

        mock_adapter.read_peq.side_effect = [intended, readback]

        result = await safe_write.execute("wifi", intended)

        assert result.success is True

    async def test_verify_fails_when_first_n_bands_mismatch(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock, mock_backup_manager: MagicMock
    ) -> None:
        """Intended 10 bands, device returns 12 but band 1 has wrong gain -> triggers rollback."""
        intended_bands = _make_bands(freq=100.0, gain=-2.0, q=1.0)
        original_bands = _make_bands(freq=200.0, gain=0.0, q=1.5)

        # Create readback with a mismatch at band index 0 (the active PEAK band)
        readback_bands = list(intended_bands)
        readback_bands[0] = CanonicalFilter(
            type="PEAK", frequency_hz=100.0, gain_db=5.0, q=1.0  # wrong gain
        )
        # Add 2 extra bands to make it 12
        readback_bands.extend([
            CanonicalFilter(type="OFF", frequency_hz=1000.0, gain_db=0.0, q=1.0),
            CanonicalFilter(type="OFF", frequency_hz=1000.0, gain_db=0.0, q=1.0),
        ])

        intended = _make_settings(bands=intended_bands)
        original = _make_settings(bands=original_bands)
        bad_readback = _make_settings(bands=readback_bands)

        mock_adapter.read_peq.side_effect = [
            original,       # Step 1: current state for backup
            bad_readback,   # Step 3: read-back does NOT match intended
            bad_readback,   # Rollback: read current state for pre_rollback backup
            original,       # Rollback verification: matches original
        ]

        result = await safe_write.execute("wifi", intended)

        assert result.success is False
        assert result.rollback_success is True


# ---------------------------------------------------------------------------
# Tests: Verification must compare against post-clamp values, not raw imports
# (hardware testing regression -- a band needing gain/Q clamping always
# failed verification and triggered a spurious rollback)
# ---------------------------------------------------------------------------


class TestDescribeFirstMismatch:
    """_describe_first_mismatch() must mirror compare_band_lists()'s own
    pass/fail logic, or its message can point at the wrong cause -- it
    originally reported "band count mismatch" any time lengths differed,
    even when the truncated comparison compare_band_lists() actually
    performs would have passed (e.g. extra OFF bands, or any case
    matching TestBandCountTolerance/TestClampedVerification above).
    """

    def test_does_not_report_length_difference_when_content_matches(self) -> None:
        """12 read-back bands vs 10 intended, but the first 10 all match
        -- compare_band_lists() passes this, so the diagnostic must not
        claim a "band count mismatch" caused a failure here.
        """
        intended_bands = _make_bands(freq=100.0, gain=-2.0, q=1.0)
        readback_bands = [
            *intended_bands,
            CanonicalFilter(type="OFF", frequency_hz=1000.0, gain_db=0.0, q=1.0),
            CanonicalFilter(type="OFF", frequency_hz=1000.0, gain_db=0.0, q=1.0),
        ]
        intended = _make_settings(bands=intended_bands)
        readback = _make_settings(bands=readback_bands)

        message = _describe_first_mismatch(intended, readback)

        assert "band count" not in message
        assert "nothing to compare" not in message

    def test_reports_genuine_band_count_failure(self) -> None:
        """When one side is empty and the other isn't, compare_band_lists()
        does treat that as a failure -- the diagnostic must still flag it.
        """
        intended = _make_settings(bands=_make_bands())
        readback = _make_settings(bands=[])

        message = _describe_first_mismatch(intended, readback)

        assert "nothing to compare" in message

    def test_reports_actual_value_mismatch_not_length(self) -> None:
        """Lengths differ (10 vs 12) AND content differs -- message should
        point at the real per-band mismatch, not just the length.
        """
        intended_bands = _make_bands(freq=100.0, gain=-2.0, q=1.0)
        readback_bands = list(intended_bands)
        readback_bands[0] = CanonicalFilter(
            type="PEAK", frequency_hz=100.0, gain_db=5.0, q=1.0
        )
        readback_bands.extend([
            CanonicalFilter(type="OFF", frequency_hz=1000.0, gain_db=0.0, q=1.0),
            CanonicalFilter(type="OFF", frequency_hz=1000.0, gain_db=0.0, q=1.0),
        ])
        intended = _make_settings(bands=intended_bands)
        readback = _make_settings(bands=readback_bands)

        message = _describe_first_mismatch(intended, readback)

        assert "band=0" in message
        assert "band count" not in message


class TestClampedVerification:
    """generate_wiim_band_array() clamps out-of-range gain/Q at write time
    without mutating the caller's filters -- verify_bands() must compare
    against the clamped values (what the device actually stores), not the
    raw pre-clamp CanonicalFilter the user imported.
    """

    async def test_verify_passes_when_only_difference_is_clamping(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock
    ) -> None:
        """Intended band has out-of-range gain/Q; device read-back reflects
        the clamped values generate_wiim_band_array() actually wrote -> the
        write must still be reported as a success, not rolled back.
        """
        intended_bands = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=15.0, q=29.255),
            *[
                CanonicalFilter(type="OFF", frequency_hz=1000.0, gain_db=0.0, q=1.0)
                for _ in range(9)
            ],
        ]
        # What the device actually stores after generate_wiim_band_array()
        # clamps gain to +12 dB and Q to 24.0.
        readback_bands = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=12.0, q=24.0),
            *[
                CanonicalFilter(type="OFF", frequency_hz=1000.0, gain_db=0.0, q=1.0)
                for _ in range(9)
            ],
        ]

        intended = _make_settings(bands=intended_bands)
        readback = _make_settings(bands=readback_bands)

        mock_adapter.read_peq.side_effect = [intended, readback]

        result = await safe_write.execute("wifi", intended)

        assert result.success is True

    async def test_verify_still_fails_on_a_genuine_mismatch(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock, mock_backup_manager: MagicMock
    ) -> None:
        """Clamping tolerance must not mask an actual write/verify failure
        unrelated to clamping (e.g. wrong frequency)."""
        intended_bands = _make_bands(freq=100.0, gain=-2.0, q=1.0)
        original_bands = _make_bands(freq=200.0, gain=0.0, q=1.5)
        readback_bands = _make_bands(freq=999.0, gain=-2.0, q=1.0)  # wrong freq

        intended = _make_settings(bands=intended_bands)
        original = _make_settings(bands=original_bands)
        bad_readback = _make_settings(bands=readback_bands)

        mock_adapter.read_peq.side_effect = [
            original,
            bad_readback,
            bad_readback,
            original,
        ]

        result = await safe_write.execute("wifi", intended)

        assert result.success is False
        assert result.rollback_success is True


# ---------------------------------------------------------------------------
# Tests: Rollback with L/R data (hardware testing regression)
# ---------------------------------------------------------------------------


class TestRollbackLR:
    """Test that rollback restores L/R settings correctly."""

    async def test_rollback_restores_lr_bands(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock, mock_backup_manager: MagicMock
    ) -> None:
        """Rollback restores original L/R settings (not just stereo bands)."""
        intended = _make_settings(channel_mode="stereo")
        # Device was originally in L/R mode
        original = _make_settings(channel_mode="lr")
        bad_readback = _make_settings(
            bands=_make_bands(freq=999.0, gain=-10.0, q=0.5),
            channel_mode="stereo",
        )

        mock_adapter.read_peq.side_effect = [
            original,       # Step 1: current state (L/R)
            bad_readback,   # Step 3: read-back mismatch
            bad_readback,   # Rollback: read current for pre_rollback backup
            original,       # Rollback verification: matches original
        ]

        result = await safe_write.execute("wifi", intended)

        assert result.success is False
        assert result.rollback_success is True

        # Verify rollback wrote back the L/R original settings
        rollback_call = mock_adapter.write_peq.call_args_list[1]
        restored_settings = rollback_call[0][1]
        assert restored_settings.channel_mode == ChannelMode.LR
        assert restored_settings.bands_l is not None


# ---------------------------------------------------------------------------
# Tests: Empty-band verification must not vacuously pass when data is lost
# ---------------------------------------------------------------------------


class TestEmptyBands:
    """_compare_band_lists must only vacuously pass when both sides are
    genuinely empty — never when intended bands were dropped on read-back,
    or when unexpected bands appear despite an empty intended write.
    """

    async def test_verify_passes_when_both_intended_and_readback_empty(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock
    ) -> None:
        """Writing zero bands and reading back zero bands is a legitimate pass."""
        intended = _make_settings(bands=[])
        mock_adapter.read_peq.side_effect = [intended, intended]

        result = await safe_write.execute("wifi", intended)

        assert result.success is True

    async def test_verify_fails_when_intended_nonempty_but_readback_empty(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock, mock_backup_manager: MagicMock
    ) -> None:
        """Intended bands present but device reads back none -> must fail, not vacuously pass."""
        intended_bands = _make_bands()
        original = _make_settings(bands=[])
        intended = _make_settings(bands=intended_bands)
        empty_readback = _make_settings(bands=[])

        mock_adapter.read_peq.side_effect = [
            original,        # Step 1: current state for backup
            empty_readback,  # Step 3: read-back has no bands at all
            empty_readback,  # Rollback: read current state for pre_rollback backup
            original,        # Rollback verification: matches original (empty)
        ]

        result = await safe_write.execute("wifi", intended)

        assert result.success is False
        assert result.rollback_success is True

    async def test_verify_fails_when_intended_empty_but_readback_nonempty(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock, mock_backup_manager: MagicMock
    ) -> None:
        """Intended zero bands but device still reports bands -> must fail, not vacuously pass."""
        unexpected_bands = _make_bands()
        original = _make_settings(bands=unexpected_bands)
        intended = _make_settings(bands=[])
        nonempty_readback = _make_settings(bands=unexpected_bands)

        mock_adapter.read_peq.side_effect = [
            original,           # Step 1: current state for backup
            nonempty_readback,  # Step 3: read-back unexpectedly has bands
            nonempty_readback,  # Rollback: read current state for pre_rollback backup
            original,           # Rollback verification: matches original
        ]

        result = await safe_write.execute("wifi", intended)

        assert result.success is False
        assert result.rollback_success is True


# ---------------------------------------------------------------------------
# Tests: SafeWrite enable-state (PEQ redesign, mirrors #191 -- see
# docs/corrections.md)
# ---------------------------------------------------------------------------


class TestPeqEnableOnSuccess:
    """A successful push turns PEQ on for the source -- deliberate, best-effort,
    mirrors RoomFitSafeWrite's success-path enable_roomfit() call.

    set_peq_enabled_best_effort() is auto-provided as an AsyncMock by
    spec=WiiMAdapter -- its own try/except/log best-effort behavior is
    WiiMAdapter's responsibility, tested directly in test_wiim_adapter.py
    (TestSetPeqEnabledBestEffort), mirroring how RoomFit's equivalent
    restore_roomfit_selection_and_enable_state() is tested (#192)."""

    async def test_success_enables_peq_when_it_was_off(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock
    ) -> None:
        original = PEQSettings(
            source_name="wifi", enabled=False,
            channel_mode=ChannelMode.STEREO, bands=_make_bands(),
        )
        intended = _make_settings()
        mock_adapter.read_peq.side_effect = [original, intended]

        result = await safe_write.execute("wifi", intended)

        assert result.success is True
        mock_adapter.set_peq_enabled_best_effort.assert_called_once_with(
            "wifi", True, context=ANY
        )

    async def test_success_enables_peq_even_when_already_on(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock
    ) -> None:
        """set_peq_enabled_best_effort(..., True, ...) is called
        unconditionally on success, not only when there's a before/after
        diff -- confirms deliberate behavior, not a guarded no-op."""
        intended = _make_settings()  # enabled=True
        mock_adapter.read_peq.side_effect = [intended, intended]

        result = await safe_write.execute("wifi", intended)

        assert result.success is True
        mock_adapter.set_peq_enabled_best_effort.assert_called_once_with(
            "wifi", True, context=ANY
        )


class TestPeqEnableRestoreOnFailure:
    """A failed push (verification mismatch + rollback) restores the
    source's original enable-state -- mirrors RoomFitSafeWrite's
    failure-path enable-state restore."""

    async def test_rollback_restores_original_enabled_state(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock
    ) -> None:
        original = PEQSettings(
            source_name="wifi", enabled=True,
            channel_mode=ChannelMode.STEREO, bands=_make_bands(freq=200.0),
        )
        intended = _make_settings(bands=_make_bands(freq=100.0))
        bad_readback = _make_settings(bands=_make_bands(freq=500.0))

        mock_adapter.read_peq.side_effect = [
            original, bad_readback, bad_readback, original,
        ]

        result = await safe_write.execute("wifi", intended)

        assert result.success is False
        mock_adapter.set_peq_enabled_best_effort.assert_called_once_with(
            "wifi", True, context=ANY
        )

    async def test_rollback_restores_original_disabled_state(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock
    ) -> None:
        """Original state was 'off' -- rollback must restore 'off'
        specifically, not a hardcoded True."""
        original = PEQSettings(
            source_name="wifi", enabled=False,
            channel_mode=ChannelMode.STEREO, bands=_make_bands(freq=200.0),
        )
        intended = _make_settings(bands=_make_bands(freq=100.0))
        bad_readback = _make_settings(bands=_make_bands(freq=500.0))

        mock_adapter.read_peq.side_effect = [
            original, bad_readback, bad_readback, original,
        ]

        result = await safe_write.execute("wifi", intended)

        assert result.success is False
        mock_adapter.set_peq_enabled_best_effort.assert_called_once_with(
            "wifi", False, context=ANY
        )


class TestPeqBackupCarriesEnabledState:
    """create_backup() must carry the source's pre-write enable-state so
    undo() can later restore it."""

    async def test_backup_carries_enabled_true(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock,
        mock_backup_manager: MagicMock,
    ) -> None:
        intended = _make_settings()
        mock_adapter.read_peq.side_effect = [intended, intended]

        await safe_write.execute("wifi", intended)

        call_kwargs = mock_backup_manager.create_backup.call_args.kwargs
        assert call_kwargs["pre_write_peq_enabled"] is True

    async def test_backup_carries_enabled_false(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock,
        mock_backup_manager: MagicMock,
    ) -> None:
        original = PEQSettings(
            source_name="wifi", enabled=False,
            channel_mode=ChannelMode.STEREO, bands=_make_bands(),
        )
        intended = _make_settings()
        mock_adapter.read_peq.side_effect = [original, intended]

        await safe_write.execute("wifi", intended)

        call_kwargs = mock_backup_manager.create_backup.call_args.kwargs
        assert call_kwargs["pre_write_peq_enabled"] is False


class TestPeqUndoRestoresEnabledState:
    """SafeWrite.undo() restores both bands and the true original
    enable-state -- using a real BackupManager since undo() reads back what
    create_backup() actually wrote (mirrors
    TestRoomFitPushThenUndoPreservesActiveProfile's fixture reasoning)."""

    async def test_undo_after_push_while_off_restores_off(
        self, mock_adapter: AsyncMock, tmp_path: Path
    ) -> None:
        real_backup_manager = BackupManager(tmp_path)
        sw = SafeWrite(adapter=mock_adapter, backup_manager=real_backup_manager)

        original = PEQSettings(
            source_name="wifi", enabled=False,
            channel_mode=ChannelMode.STEREO, bands=_make_bands(freq=200.0),
        )
        intended = _make_settings(bands=_make_bands(freq=100.0))
        mock_adapter.read_peq.side_effect = [original, intended]

        push_result = await sw.execute("wifi", intended)
        assert push_result.success is True
        assert push_result.backup_path is not None

        # Undo: bands-restore write/read-back matches the original bands.
        mock_adapter.read_peq.side_effect = [intended, original]

        undo_result = await sw.undo(push_result.backup_path, "wifi")

        assert undo_result.success is True
        # Two set_peq_enabled_best_effort calls total: one from the push's
        # own success path (True, "after successful push"), one from undo's
        # post-execute() correction (False, "after undo") -- assert on the
        # latter specifically since that's what this test is about.
        mock_adapter.set_peq_enabled_best_effort.assert_any_call(
            "wifi", False, context=ANY
        )

    async def test_undo_after_push_while_on_leaves_it_on(
        self, mock_adapter: AsyncMock, tmp_path: Path
    ) -> None:
        """No-op restore: pushing while already on, undo must not flip it off."""
        real_backup_manager = BackupManager(tmp_path)
        sw = SafeWrite(adapter=mock_adapter, backup_manager=real_backup_manager)

        original = PEQSettings(
            source_name="wifi", enabled=True,
            channel_mode=ChannelMode.STEREO, bands=_make_bands(freq=200.0),
        )
        intended = _make_settings(bands=_make_bands(freq=100.0))
        mock_adapter.read_peq.side_effect = [original, intended]

        push_result = await sw.execute("wifi", intended)
        assert push_result.success is True

        mock_adapter.read_peq.side_effect = [intended, original]

        undo_result = await sw.undo(push_result.backup_path, "wifi")

        assert undo_result.success is True
        mock_adapter.set_peq_enabled_best_effort.assert_any_call(
            "wifi", True, context=ANY
        )


class TestPeqUndoOldFormatBackup:
    """A backup file written before pre_write_peq_enabled existed must
    degrade gracefully: bands restored, enable-state left untouched by
    undo's own correction step (only execute()'s own enable-on-success
    applies)."""

    async def test_undo_old_format_backup_skips_enable_restore(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock, tmp_path: Path
    ) -> None:
        backup_file = tmp_path / "old_backup.json"
        backup_file.write_text(
            '{"channel_mode": "stereo", "filters": ['
            '{"type": "PEAK", "frequency_hz": 100.0, "gain_db": -2.0, "q": 1.0}'
            ']}',
            encoding="utf-8",
        )
        intended_readback = _make_settings(
            bands=[CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-2.0, q=1.0)]
        )
        mock_adapter.read_peq.side_effect = [intended_readback, intended_readback]

        result = await safe_write.undo(backup_file, "wifi")

        assert result.success is True
        # Only one call, from execute()'s own success path -- undo's own
        # correction step is skipped entirely (pre_write_peq_enabled is
        # None for this old-format backup), not called with a guessed value.
        mock_adapter.set_peq_enabled_best_effort.assert_called_once_with(
            "wifi", True, context=ANY
        )


class TestPeqUndoEmptyBandsBackup:
    """A backup capturing zero bands (the source legitimately had no PEQ
    filters applied before the original push -- a valid "flat EQ" state, not
    malformed data) must still be restorable by undo(). Regression: undo()
    used to refuse any backup with `not filters` ("Backup contains no
    filters"), but parse_backup_filters() can't distinguish a legitimately-
    empty capture from a missing/corrupt one -- both parse to []."""

    async def test_undo_restores_source_to_zero_bands(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock, tmp_path: Path
    ) -> None:
        backup_file = tmp_path / "empty_bands_backup.json"
        backup_file.write_text(
            '{"channel_mode": "stereo", "filters": [], '
            '"pre_write_peq_enabled": true}',
            encoding="utf-8",
        )
        empty_readback = _make_settings(bands=[])
        mock_adapter.read_peq.side_effect = [empty_readback, empty_readback]

        result = await safe_write.undo(backup_file, "wifi")

        assert result.success is True
        mock_adapter.write_peq.assert_called_once()
        settings = mock_adapter.write_peq.call_args[0][1]
        assert settings.bands == []


class TestPeqUndoLRUnequalLengthsNotNaivelySplit:
    """Regression, relocated from test_gui_integration_secondary.py: undo
    must rebuild bands_l/bands_r from the backup's explicit per-channel
    data, never by positionally re-splitting the combined filter list
    50/50 (only "accidentally" correct when both channels happen to have
    equal length). Now exercises the real SafeWrite.undo() (the
    settings-reconstruction logic moved here from
    SecondaryWorkflowManager._do_undo() as part of the PEQ redesign).
    """

    async def test_undo_lr_unequal_lengths_preserves_channel_split(
        self, safe_write: SafeWrite, mock_adapter: AsyncMock, tmp_path: Path
    ) -> None:
        backup_data = (
            '{"channel_mode": "left", '
            '"filters_l": ['
            '{"type": "PEAK", "frequency_hz": 100.0, "gain_db": -2.0, "q": 1.0}, '
            '{"type": "PEAK", "frequency_hz": 110.0, "gain_db": -2.0, "q": 1.0}, '
            '{"type": "PEAK", "frequency_hz": 120.0, "gain_db": -2.0, "q": 1.0}'
            '], "filters_r": ['
            '{"type": "PEAK", "frequency_hz": 200.0, "gain_db": -4.0, "q": 1.5}, '
            '{"type": "PEAK", "frequency_hz": 210.0, "gain_db": -4.0, "q": 1.5}, '
            '{"type": "PEAK", "frequency_hz": 220.0, "gain_db": -4.0, "q": 1.5}, '
            '{"type": "PEAK", "frequency_hz": 230.0, "gain_db": -4.0, "q": 1.5}, '
            '{"type": "PEAK", "frequency_hz": 240.0, "gain_db": -4.0, "q": 1.5}'
            ']}'
        )
        backup_file = tmp_path / "backup_lr_unequal.json"
        backup_file.write_text(backup_data, encoding="utf-8")

        # read-back must match the split bands exactly, or verify_bands()
        # would fail and execute() would fall through to rollback -- which
        # would exhaust this side_effect list and raise, instead of letting
        # this test observe the single write_peq() call it cares about.
        matching_readback = PEQSettings(
            source_name="wifi",
            channel_mode=ChannelMode.LR,
            bands_l=[
                CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-2.0, q=1.0),
                CanonicalFilter(type="PEAK", frequency_hz=110.0, gain_db=-2.0, q=1.0),
                CanonicalFilter(type="PEAK", frequency_hz=120.0, gain_db=-2.0, q=1.0),
            ],
            bands_r=[
                CanonicalFilter(type="PEAK", frequency_hz=200.0, gain_db=-4.0, q=1.5),
                CanonicalFilter(type="PEAK", frequency_hz=210.0, gain_db=-4.0, q=1.5),
                CanonicalFilter(type="PEAK", frequency_hz=220.0, gain_db=-4.0, q=1.5),
                CanonicalFilter(type="PEAK", frequency_hz=230.0, gain_db=-4.0, q=1.5),
                CanonicalFilter(type="PEAK", frequency_hz=240.0, gain_db=-4.0, q=1.5),
            ],
        )
        mock_adapter.read_peq.side_effect = [matching_readback, matching_readback]

        await safe_write.undo(backup_file, "wifi")

        mock_adapter.write_peq.assert_called_once()
        call_args = mock_adapter.write_peq.call_args
        settings = call_args[0][1]

        assert settings.bands_l is not None and len(settings.bands_l) == 3
        assert settings.bands_r is not None and len(settings.bands_r) == 5
        assert [f.frequency_hz for f in settings.bands_l] == [100.0, 110.0, 120.0]
        assert [f.frequency_hz for f in settings.bands_r] == [
            200.0, 210.0, 220.0, 230.0, 240.0,
        ]


# ---------------------------------------------------------------------------
# Tests: RoomFitSafeWrite — named-profile verify and two rollback shapes
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_roomfit_adapter() -> AsyncMock:
    """Mocked WiiMAdapter for RoomFit operations.

    get_roomfit_status defaults to "" (no active profile known) so the
    #178 restore-previous-active-profile step is a no-op for tests that
    don't care about it -- tests that do (TestRoomFitActiveProfileRestore
    below) override the return value explicitly.
    """
    adapter = AsyncMock(spec=WiiMAdapter)
    adapter.capabilities = _solo_capabilities()
    adapter.list_roomfit_profiles = AsyncMock()
    adapter.read_roomfit = AsyncMock()
    adapter.write_roomfit = AsyncMock()
    adapter.delete_roomfit_profile = AsyncMock()
    adapter.get_roomfit_status = AsyncMock(return_value=(True, ""))
    # restore_roomfit_selection_and_enable_state is auto-provided as an
    # AsyncMock by spec=WiiMAdapter -- execute()'s failure paths and undo()
    # call it to restore pre-write selection/enable-state (#191/#192); its
    # own skip-if-empty/skip-if-same-name/skip-if-None decisions are
    # WiiMAdapter's responsibility, tested directly in test_wiim_adapter.py.
    return adapter


@pytest.fixture
def roomfit_safe_write(
    mock_roomfit_adapter: AsyncMock, mock_backup_manager: MagicMock
) -> RoomFitSafeWrite:
    """RoomFitSafeWrite instance with mocked dependencies."""
    return RoomFitSafeWrite(
        adapter=mock_roomfit_adapter, backup_manager=mock_backup_manager
    )


class TestRoomFitOnStageCallback:
    """RoomFitSafeWrite.execute() reports real progress via on_stage (#189)."""

    async def test_success_calls_stages_in_order(
        self, roomfit_safe_write: RoomFitSafeWrite, mock_roomfit_adapter: AsyncMock
    ) -> None:
        """Success path calls on_stage for all four stages, in order."""
        bands = _make_bands()
        mock_roomfit_adapter.list_roomfit_profiles.return_value = []
        mock_roomfit_adapter.read_roomfit.return_value = _make_settings(bands=bands)
        seen: list[str] = []

        await roomfit_safe_write.execute(
            "wifi", "New Profile", bands, ChannelMode.STEREO, on_stage=seen.append
        )

        assert seen == ["backing_up", "writing", "verifying", "done"]

    async def test_failure_does_not_call_done(
        self, roomfit_safe_write: RoomFitSafeWrite, mock_roomfit_adapter: AsyncMock
    ) -> None:
        """Verification failure stops after 'verifying' -- 'done' is never reported."""
        intended_bands = _make_bands(freq=100.0)
        bad_readback = _make_settings(bands=_make_bands(freq=999.0))
        mock_roomfit_adapter.list_roomfit_profiles.return_value = []
        mock_roomfit_adapter.read_roomfit.return_value = bad_readback
        seen: list[str] = []

        result = await roomfit_safe_write.execute(
            "wifi", "New Profile", intended_bands, ChannelMode.STEREO, on_stage=seen.append
        )

        assert result.success is False
        assert seen == ["backing_up", "writing", "verifying"]


class TestRoomFitNewProfile:
    """Profile didn't exist before this write -> rollback shape is DELETE_NEW."""

    async def test_new_profile_success(
        self, roomfit_safe_write: RoomFitSafeWrite, mock_roomfit_adapter: AsyncMock
    ) -> None:
        """New profile, verification passes -> success, no delete. backup_path
        IS populated even for a new profile (#191) -- a metadata-only backup
        carrying the pre-push selection/enable state, so Undo can later
        restore it even though there are no prior bands to restore."""
        bands = _make_bands()
        mock_roomfit_adapter.list_roomfit_profiles.return_value = []
        mock_roomfit_adapter.read_roomfit.return_value = _make_settings(bands=bands)

        result = await roomfit_safe_write.execute(
            "wifi", "New Profile", bands, ChannelMode.STEREO
        )

        assert result.success is True
        assert result.backup_path is not None
        mock_roomfit_adapter.delete_roomfit_profile.assert_not_called()

    async def test_new_profile_mismatch_deletes_profile(
        self, roomfit_safe_write: RoomFitSafeWrite, mock_roomfit_adapter: AsyncMock
    ) -> None:
        """New profile, verification fails -> profile is deleted, not restored."""
        intended_bands = _make_bands(freq=100.0)
        bad_readback = _make_settings(bands=_make_bands(freq=999.0))
        mock_roomfit_adapter.list_roomfit_profiles.return_value = []
        mock_roomfit_adapter.read_roomfit.return_value = bad_readback

        result = await roomfit_safe_write.execute(
            "wifi", "New Profile", intended_bands, ChannelMode.STEREO
        )

        assert result.success is False
        assert result.rollback_success is True
        assert result.backup_path is None
        mock_roomfit_adapter.delete_roomfit_profile.assert_called_once_with(
            "New Profile"
        )
        assert "removed" in (result.error_message or "").lower()

    async def test_new_profile_lr_mode_verified_per_channel(
        self, roomfit_safe_write: RoomFitSafeWrite, mock_roomfit_adapter: AsyncMock
    ) -> None:
        """L/R write builds intended settings from filters_l/filters_r, not filters."""
        left = _make_bands(freq=100.0)
        right = _make_bands(freq=200.0)
        mock_roomfit_adapter.list_roomfit_profiles.return_value = []
        mock_roomfit_adapter.read_roomfit.return_value = PEQSettings(
            source_name="wifi", channel_mode=ChannelMode.LR, bands_l=left, bands_r=right
        )

        result = await roomfit_safe_write.execute(
            "wifi", "LR Profile", [], ChannelMode.LR, filters_l=left, filters_r=right
        )

        assert result.success is True
        write_call = mock_roomfit_adapter.write_roomfit.call_args
        assert write_call.kwargs["filters_l"] == left
        assert write_call.kwargs["filters_r"] == right


class TestRoomFitOverwriteProfile:
    """Profile already existed -> rollback shape is RESTORE."""

    async def test_overwrite_success_backs_up_existing(
        self,
        roomfit_safe_write: RoomFitSafeWrite,
        mock_roomfit_adapter: AsyncMock,
        mock_backup_manager: MagicMock,
    ) -> None:
        """Overwriting an existing profile backs it up, then verifies the new write."""
        new_bands = _make_bands(freq=100.0)
        existing = _make_settings(bands=_make_bands(freq=200.0))
        mock_roomfit_adapter.list_roomfit_profiles.return_value = [{"Name": "Existing"}]
        mock_roomfit_adapter.read_roomfit.side_effect = [
            existing,  # backup read
            _make_settings(bands=new_bands),  # post-write verify read
        ]

        result = await roomfit_safe_write.execute(
            "wifi", "Existing", new_bands, ChannelMode.STEREO
        )

        assert result.success is True
        assert result.backup_path is not None
        mock_backup_manager.create_backup.assert_called_once()
        assert mock_backup_manager.create_backup.call_args[0][2] == "pre_write"

    async def test_overwrite_mismatch_restores_original(
        self, roomfit_safe_write: RoomFitSafeWrite, mock_roomfit_adapter: AsyncMock
    ) -> None:
        """Verification fails on an existing profile -> original bands restored."""
        new_bands = _make_bands(freq=100.0)
        existing = _make_settings(bands=_make_bands(freq=200.0))
        bad_readback = _make_settings(bands=_make_bands(freq=999.0))
        mock_roomfit_adapter.list_roomfit_profiles.return_value = [{"Name": "Existing"}]
        mock_roomfit_adapter.read_roomfit.side_effect = [
            existing,       # backup read
            bad_readback,   # post-write verify read: mismatch
            existing,       # rollback verify read: matches original
        ]

        result = await roomfit_safe_write.execute(
            "wifi", "Existing", new_bands, ChannelMode.STEREO
        )

        assert result.success is False
        assert result.rollback_success is True
        assert "restored" in (result.error_message or "").lower()
        mock_roomfit_adapter.delete_roomfit_profile.assert_not_called()
        # write_roomfit called twice: once for the new bands, once to restore
        assert mock_roomfit_adapter.write_roomfit.call_count == 2

    async def test_overwrite_mismatch_restore_failure_logs_critical(
        self,
        roomfit_safe_write: RoomFitSafeWrite,
        mock_roomfit_adapter: AsyncMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Restore itself fails verification -> rollback_success False, CRITICAL logged."""
        new_bands = _make_bands(freq=100.0)
        existing = _make_settings(bands=_make_bands(freq=200.0))
        bad_readback = _make_settings(bands=_make_bands(freq=999.0))
        mock_roomfit_adapter.list_roomfit_profiles.return_value = [{"Name": "Existing"}]
        mock_roomfit_adapter.read_roomfit.side_effect = [
            existing,       # backup read
            bad_readback,   # post-write verify read: mismatch
            bad_readback,   # rollback verify read: STILL doesn't match
        ]

        app_logger = logging.getLogger("wiim_rew_sync.app")
        app_logger.propagate = True
        try:
            with caplog.at_level(logging.CRITICAL, logger="wiim_rew_sync.app"):
                result = await roomfit_safe_write.execute(
                    "wifi", "Existing", new_bands, ChannelMode.STEREO
                )

            assert result.success is False
            assert result.rollback_success is False
            critical_records = [
                r for r in caplog.records if r.levelno == logging.CRITICAL
            ]
            assert len(critical_records) >= 1
        finally:
            app_logger.propagate = False


class TestRoomFitActiveProfileRestore:
    """#191 (redesign): a SUCCESSFUL push now deliberately activates the
    written profile and enables RoomFit, via load_roomfit_profile()/
    enable_roomfit() -- it must NOT call
    restore_roomfit_selection_and_enable_state() at all (that would undo the
    activation). A FAILED push restores the original pre-write
    selection/enable-state instead, via that same method (#192)."""

    async def test_new_profile_success_activates_and_enables(
        self, roomfit_safe_write: RoomFitSafeWrite, mock_roomfit_adapter: AsyncMock
    ) -> None:
        """Pushing a brand-new profile activates it and enables RoomFit;
        the previously-active profile is NOT restored."""
        bands = _make_bands()
        mock_roomfit_adapter.get_roomfit_status.return_value = (True, "Living Room")
        mock_roomfit_adapter.list_roomfit_profiles.return_value = []
        mock_roomfit_adapter.read_roomfit.return_value = _make_settings(bands=bands)

        result = await roomfit_safe_write.execute(
            "wifi", "New Profile", bands, ChannelMode.STEREO
        )

        assert result.success is True
        mock_roomfit_adapter.load_roomfit_profile.assert_called_once_with("New Profile")
        mock_roomfit_adapter.enable_roomfit.assert_called_once()
        mock_roomfit_adapter.restore_roomfit_selection_and_enable_state.assert_not_called()

    async def test_overwrite_non_active_profile_success_activates_it(
        self, roomfit_safe_write: RoomFitSafeWrite, mock_roomfit_adapter: AsyncMock
    ) -> None:
        """Overwriting a different, non-active profile activates THAT
        profile (not the one that was previously active)."""
        new_bands = _make_bands(freq=100.0)
        existing = _make_settings(bands=_make_bands(freq=200.0))
        mock_roomfit_adapter.get_roomfit_status.return_value = (True, "Living Room")
        mock_roomfit_adapter.list_roomfit_profiles.return_value = [{"Name": "Existing"}]
        mock_roomfit_adapter.read_roomfit.side_effect = [
            existing,
            _make_settings(bands=new_bands),
        ]

        result = await roomfit_safe_write.execute(
            "wifi", "Existing", new_bands, ChannelMode.STEREO
        )

        assert result.success is True
        mock_roomfit_adapter.load_roomfit_profile.assert_called_once_with("Existing")
        mock_roomfit_adapter.enable_roomfit.assert_called_once()
        mock_roomfit_adapter.restore_roomfit_selection_and_enable_state.assert_not_called()

    async def test_overwrite_active_profile_success_stays_active(
        self, roomfit_safe_write: RoomFitSafeWrite, mock_roomfit_adapter: AsyncMock
    ) -> None:
        """Overwriting the profile that's already active keeps it active
        (and enabled) -- same activate-on-success path as any other push."""
        new_bands = _make_bands(freq=100.0)
        existing = _make_settings(bands=_make_bands(freq=200.0))
        mock_roomfit_adapter.get_roomfit_status.return_value = (True, "Existing")
        mock_roomfit_adapter.list_roomfit_profiles.return_value = [{"Name": "Existing"}]
        mock_roomfit_adapter.read_roomfit.side_effect = [
            existing,
            _make_settings(bands=new_bands),
        ]

        result = await roomfit_safe_write.execute(
            "wifi", "Existing", new_bands, ChannelMode.STEREO
        )

        assert result.success is True
        mock_roomfit_adapter.load_roomfit_profile.assert_called_once_with("Existing")
        mock_roomfit_adapter.enable_roomfit.assert_called_once()

    async def test_no_prior_active_profile_success_still_activates(
        self, roomfit_safe_write: RoomFitSafeWrite, mock_roomfit_adapter: AsyncMock
    ) -> None:
        """No profile was active before the write -> the new push still
        activates and enables RoomFit; nothing to restore either way."""
        bands = _make_bands()
        mock_roomfit_adapter.get_roomfit_status.return_value = (False, "")
        mock_roomfit_adapter.list_roomfit_profiles.return_value = []
        mock_roomfit_adapter.read_roomfit.return_value = _make_settings(bands=bands)

        result = await roomfit_safe_write.execute(
            "wifi", "New Profile", bands, ChannelMode.STEREO
        )

        assert result.success is True
        mock_roomfit_adapter.load_roomfit_profile.assert_called_once_with("New Profile")
        mock_roomfit_adapter.enable_roomfit.assert_called_once()
        mock_roomfit_adapter.restore_roomfit_selection_and_enable_state.assert_not_called()

    async def test_restore_runs_after_failed_verification_and_rollback(
        self, roomfit_safe_write: RoomFitSafeWrite, mock_roomfit_adapter: AsyncMock
    ) -> None:
        """A failed push restores the original pre-write selection AND
        enable-state -- a failure must have no lasting device-visible effect."""
        new_bands = _make_bands(freq=100.0)
        existing = _make_settings(bands=_make_bands(freq=200.0))
        bad_readback = _make_settings(bands=_make_bands(freq=999.0))
        mock_roomfit_adapter.get_roomfit_status.return_value = (True, "Living Room")
        mock_roomfit_adapter.list_roomfit_profiles.return_value = [{"Name": "Existing"}]
        mock_roomfit_adapter.read_roomfit.side_effect = [
            existing,
            bad_readback,
            existing,
        ]

        result = await roomfit_safe_write.execute(
            "wifi", "Existing", new_bands, ChannelMode.STEREO
        )

        assert result.success is False
        assert result.rollback_success is True
        mock_roomfit_adapter.restore_roomfit_selection_and_enable_state.assert_called_once_with(
            "Living Room", True, "Existing", context=ANY
        )
        # Success-path activation must NOT also have fired.
        mock_roomfit_adapter.load_roomfit_profile.assert_not_called()
        mock_roomfit_adapter.enable_roomfit.assert_not_called()

    async def test_get_status_failure_degrades_without_raising(
        self, roomfit_safe_write: RoomFitSafeWrite, mock_roomfit_adapter: AsyncMock
    ) -> None:
        """A transient failure reading the pre-write status must not abort
        the write -- and since the write succeeds, the profile is still
        activated and enabled regardless of the earlier read failure."""
        bands = _make_bands()
        mock_roomfit_adapter.get_roomfit_status.side_effect = RuntimeError("boom")
        mock_roomfit_adapter.list_roomfit_profiles.return_value = []
        mock_roomfit_adapter.read_roomfit.return_value = _make_settings(bands=bands)

        result = await roomfit_safe_write.execute(
            "wifi", "New Profile", bands, ChannelMode.STEREO
        )

        assert result.success is True
        mock_roomfit_adapter.load_roomfit_profile.assert_called_once_with("New Profile")
        mock_roomfit_adapter.enable_roomfit.assert_called_once()
        mock_roomfit_adapter.restore_roomfit_selection_and_enable_state.assert_not_called()


# ---------------------------------------------------------------------------
# Structural regression guard (smoke #154)
# ---------------------------------------------------------------------------
# Integration-style test: push-then-undo must leave the *original* active
# profile active throughout, not just restore content (#178).
# ---------------------------------------------------------------------------


class _FakeRoomFitDevice:
    """Minimal stateful RoomFit device model: a profile store plus one
    global "active" name and on/off state, mirroring the real single-buffer
    semantics documented in docs/wiim_api_notes.md (the buffer adopts
    whatever name was last loaded or saved). Used instead of a plain
    AsyncMock here because this test asserts on state *across two separate
    calls* (a push followed by an undo), which a stateless mock can't model.

    `capabilities` is an instance attribute (not class-level) deliberately:
    RoomFitSafeWrite.execute() now mutates `supports_roomfit_write` in
    place on a successful push when it was previously unconfirmed (#191) --
    a class-level attribute would leak that mutation across every test that
    instantiates this fake, since they'd all share the same object.
    """

    def __init__(self, active_name: str = "", enabled: bool = True) -> None:
        self.capabilities = _solo_capabilities()
        self.profiles: dict[str, PEQSettings] = {}
        self.active_name = active_name
        self.enabled = enabled

    async def list_roomfit_profiles(self, source_name: str) -> list[dict[str, str]]:
        return [{"Name": name} for name in self.profiles]

    async def read_roomfit(self, source_name: str, profile_name: str) -> PEQSettings:
        self.active_name = profile_name
        return self.profiles[profile_name]

    async def write_roomfit(
        self,
        source_name: str,
        profile_name: str,
        filters: list[CanonicalFilter],
        channel_mode: ChannelMode = ChannelMode.STEREO,
        filters_l: list[CanonicalFilter] | None = None,
        filters_r: list[CanonicalFilter] | None = None,
    ) -> None:
        if channel_mode.is_lr:
            settings = PEQSettings(
                source_name=source_name,
                channel_mode=ChannelMode.LR,
                bands_l=filters_l or [],
                bands_r=filters_r or [],
            )
        else:
            settings = PEQSettings(
                source_name=source_name, channel_mode=ChannelMode.STEREO, bands=filters
            )
        self.profiles[profile_name] = settings
        self.active_name = profile_name

    async def delete_roomfit_profile(self, profile_name: str) -> None:
        self.profiles.pop(profile_name, None)

    async def get_roomfit_status(self) -> tuple[bool, str]:
        return self.enabled, self.active_name

    async def load_roomfit_profile(self, profile_name: str) -> None:
        self.active_name = profile_name

    async def restore_roomfit_active_profile(
        self, original_name: str, current_name: str, *, context: str
    ) -> None:
        if not original_name or original_name == current_name:
            return
        await self.load_roomfit_profile(original_name)

    async def enable_roomfit(self) -> None:
        self.enabled = True

    async def disable_roomfit(self) -> None:
        self.enabled = False

    async def set_roomfit_enabled(self, enabled: bool) -> None:
        self.enabled = enabled

    async def restore_roomfit_selection_and_enable_state(
        self, active_name: str, enabled: bool | None, current_name: str, *, context: str
    ) -> None:
        await self.restore_roomfit_active_profile(active_name, current_name, context=context)
        if enabled is not None:
            await self.set_roomfit_enabled(enabled)


class TestRoomFitPushThenUndoPreservesActiveProfile:
    async def test_push_then_undo_leaves_original_active_profile_and_state(
        self, tmp_path: Path
    ) -> None:
        """Reproduces the reported bug: overwriting a non-active profile
        ('Movie Night') while RoomFit is off must activate+enable it
        (#191's new push contract) without disturbing 'Movie Night' vs.
        'Living Room' bands -- and undoing that push must restore 'Living
        Room' as active AND put RoomFit back to its pre-push (off) state,
        not just restore Movie Night's old content.

        Uses a real BackupManager (not a mock) since undo() needs to read
        back the restore-metadata create_backup() actually wrote.
        """
        device = _FakeRoomFitDevice(active_name="Living Room", enabled=False)
        old_bands = _make_bands(freq=200.0)
        device.profiles["Living Room"] = _make_settings(bands=_make_bands(freq=50.0))
        device.profiles["Movie Night"] = _make_settings(bands=old_bands)

        backup_manager = BackupManager(tmp_path)
        safe_write = RoomFitSafeWrite(adapter=device, backup_manager=backup_manager)

        new_bands = _make_bands(freq=100.0)
        push_result = await safe_write.execute(
            "wifi", "Movie Night", new_bands, ChannelMode.STEREO
        )
        assert push_result.success is True
        assert device.active_name == "Movie Night"
        assert device.enabled is True
        assert push_result.backup_path is not None

        undo_result = await safe_write.undo(
            push_result.backup_path, "wifi", "Movie Night"
        )
        assert undo_result.success is True
        assert device.active_name == "Living Room"
        assert device.enabled is False
        assert verify_bands(_make_settings(bands=old_bands), device.profiles["Movie Night"])

    async def test_push_then_undo_new_profile_keeps_it_but_restores_state(
        self, tmp_path: Path
    ) -> None:
        """Undoing a push that created a brand-new profile does NOT delete
        it (non-destructive, product decision) -- only selection/enable
        state is restored."""
        device = _FakeRoomFitDevice(active_name="Living Room", enabled=False)
        device.profiles["Living Room"] = _make_settings(bands=_make_bands(freq=50.0))

        backup_manager = BackupManager(tmp_path)
        safe_write = RoomFitSafeWrite(adapter=device, backup_manager=backup_manager)

        new_bands = _make_bands(freq=100.0)
        push_result = await safe_write.execute(
            "wifi", "Movie Night", new_bands, ChannelMode.STEREO
        )
        assert push_result.success is True
        assert device.active_name == "Movie Night"
        assert device.enabled is True
        assert push_result.backup_path is not None

        undo_result = await safe_write.undo(
            push_result.backup_path, "wifi", "Movie Night"
        )
        assert undo_result.success is True
        assert "Movie Night" in device.profiles  # not deleted
        assert device.active_name == "Living Room"
        assert device.enabled is False


class TestRoomFitLevelUpgrade:
    """#191: a verified-successful push when write capability was
    previously unconfirmed upgrades the adapter's in-memory
    `supports_roomfit_write` to True -- it serves as its own
    write-capability confirmation. A failed push must NOT upgrade it,
    since an unverified write proves nothing."""

    async def test_successful_push_upgrades_unconfirmed_write(
        self, roomfit_safe_write: RoomFitSafeWrite, mock_roomfit_adapter: AsyncMock
    ) -> None:
        bands = _make_bands()
        mock_roomfit_adapter.capabilities.supports_roomfit_write = False
        mock_roomfit_adapter.list_roomfit_profiles.return_value = []
        mock_roomfit_adapter.read_roomfit.return_value = _make_settings(bands=bands)

        result = await roomfit_safe_write.execute(
            "wifi", "New Profile", bands, ChannelMode.STEREO
        )

        assert result.success is True
        assert mock_roomfit_adapter.capabilities.supports_roomfit_write is True

    async def test_failed_push_does_not_upgrade_write_capability(
        self, roomfit_safe_write: RoomFitSafeWrite, mock_roomfit_adapter: AsyncMock
    ) -> None:
        intended_bands = _make_bands(freq=100.0)
        bad_readback = _make_settings(bands=_make_bands(freq=999.0))
        mock_roomfit_adapter.capabilities.supports_roomfit_write = False
        mock_roomfit_adapter.list_roomfit_profiles.return_value = []
        mock_roomfit_adapter.read_roomfit.return_value = bad_readback

        result = await roomfit_safe_write.execute(
            "wifi", "New Profile", intended_bands, ChannelMode.STEREO
        )

        assert result.success is False
        assert mock_roomfit_adapter.capabilities.supports_roomfit_write is False

    async def test_successful_push_already_confirmed_does_not_change_it(
        self, roomfit_safe_write: RoomFitSafeWrite, mock_roomfit_adapter: AsyncMock
    ) -> None:
        """Already confirmed -- no-op, not re-logged as an "upgrade"."""
        bands = _make_bands()
        mock_roomfit_adapter.capabilities.supports_roomfit_write = True
        mock_roomfit_adapter.list_roomfit_profiles.return_value = []
        mock_roomfit_adapter.read_roomfit.return_value = _make_settings(bands=bands)

        result = await roomfit_safe_write.execute(
            "wifi", "New Profile", bands, ChannelMode.STEREO
        )

        assert result.success is True
        assert mock_roomfit_adapter.capabilities.supports_roomfit_write is True


class TestRoomFitUndoOldFormatBackup:
    """#191: a backup file written before pre_write_active_profile/
    pre_write_roomfit_enabled/was_new_profile existed has all three as
    absent -- undo() must degrade to bands-only restore (today's
    pre-redesign behavior) rather than raise or guess."""

    async def test_old_format_backup_restores_bands_only(
        self, tmp_path: Path
    ) -> None:
        import json as json_module

        device = _FakeRoomFitDevice(active_name="Existing", enabled=True)
        old_bands = _make_bands(freq=200.0)
        device.profiles["Existing"] = _make_settings(bands=_make_bands(freq=999.0))

        # Hand-construct an old-format backup: no restore-metadata keys.
        backup_path = tmp_path / "old_backup.json"
        backup_path.write_text(
            json_module.dumps(
                {
                    "schema_version": 1,
                    "name": "backup_old",
                    "channel_mode": "stereo",
                    "filters": [f.model_dump() for f in old_bands],
                    "tags": [],
                    "timestamp": "2026-01-01T00:00:00+00:00",
                    "device_uuid": "test-uuid-1234",
                    "firmware_version": "6.0.1.20",
                    "trigger": "pre_write",
                    "profile_type": "backup",
                }
            ),
            encoding="utf-8",
        )

        backup_manager = BackupManager(tmp_path)
        safe_write = RoomFitSafeWrite(adapter=device, backup_manager=backup_manager)

        result = await safe_write.undo(backup_path, "wifi", "Existing")

        assert result.success is True
        assert verify_bands(_make_settings(bands=old_bands), device.profiles["Existing"])
        # No selection/enable-state restore attempted -- degrades to
        # bands-only, matching pre-redesign behavior exactly.
        assert device.active_name == "Existing"
        assert device.enabled is True


# Files allowed to call adapter.write_peq()/write_roomfit() directly: the
# safe-write module itself (the only legitimate caller), the adapter module
# that defines the methods (matched only via leading "." below, so method
# *definitions* never match), and the test suite (which mocks adapters and
# must be free to call/assert on them).
_DIRECT_WRITE_PATTERN = re.compile(r"\.write_peq\(|\.write_roomfit\(")
_ALLOWED_DIRECT_WRITE_FILES = {
    Path("src/adapters/safe_write.py"),
    Path("src/adapters/wiim_adapter.py"),
}


class TestNoDirectWriteBypass:
    """Every device write must go through SafeWrite/RoomFitSafeWrite (the
    five-step backup/write/read-back/verify/rollback protocol) -- never a
    bare adapter.write_peq()/write_roomfit() call. Smoke #154 found two such
    bypasses (Copy to Another Device's RoomFit branch, the CLI's
    set-roomfit-filters command) that were each added independently and
    never cross-checked against this invariant. This test makes a future
    bypass fail CI instead of waiting for someone to notice during a manual
    audit.
    """

    def test_no_file_outside_safe_write_calls_adapter_write_directly(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        violations: list[str] = []

        for path in iter_src_python_files():
            rel_path = path.relative_to(repo_root)
            if rel_path in _ALLOWED_DIRECT_WRITE_FILES:
                continue
            if rel_path.parts[:2] == ("src", "tests"):
                continue  # tests mock adapters; calling/asserting is expected

            text = path.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), start=1):
                if _DIRECT_WRITE_PATTERN.search(line):
                    violations.append(f"{rel_path}:{line_no}: {line.strip()}")

        assert not violations, (
            "Found direct adapter.write_peq()/write_roomfit() call(s) outside "
            "SafeWrite/RoomFitSafeWrite -- every device write must go through "
            "the verified five-step protocol (see safe_write.py):\n"
            + "\n".join(violations)
        )
