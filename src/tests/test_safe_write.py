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
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adapters.safe_write import RoomFitSafeWrite, SafeWrite, _describe_first_mismatch
from src.adapters.wiim_adapter import WiiMAdapter
from src.models.canonical import CanonicalFilter
from src.models.capabilities import DeviceCapabilities
from src.models.channel_mode import ChannelMode
from src.models.peq import PEQSettings
from src.repository.backup_manager import BackupManager

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
        role="solo",
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
# Tests: RoomFitSafeWrite — named-profile verify and two rollback shapes
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_roomfit_adapter() -> AsyncMock:
    """Mocked WiiMAdapter for RoomFit operations."""
    adapter = AsyncMock(spec=WiiMAdapter)
    adapter.capabilities = _solo_capabilities()
    adapter.list_roomfit_profiles = AsyncMock()
    adapter.read_roomfit = AsyncMock()
    adapter.write_roomfit = AsyncMock()
    adapter.delete_roomfit_profile = AsyncMock()
    return adapter


@pytest.fixture
def roomfit_safe_write(
    mock_roomfit_adapter: AsyncMock, mock_backup_manager: MagicMock
) -> RoomFitSafeWrite:
    """RoomFitSafeWrite instance with mocked dependencies."""
    return RoomFitSafeWrite(
        adapter=mock_roomfit_adapter, backup_manager=mock_backup_manager
    )


class TestRoomFitNewProfile:
    """Profile didn't exist before this write -> rollback shape is DELETE_NEW."""

    async def test_new_profile_success(
        self, roomfit_safe_write: RoomFitSafeWrite, mock_roomfit_adapter: AsyncMock
    ) -> None:
        """New profile, verification passes -> success, no backup, no delete."""
        bands = _make_bands()
        mock_roomfit_adapter.list_roomfit_profiles.return_value = []
        mock_roomfit_adapter.read_roomfit.return_value = _make_settings(bands=bands)

        result = await roomfit_safe_write.execute(
            "wifi", "New Profile", bands, ChannelMode.STEREO
        )

        assert result.success is True
        assert result.backup_path is None
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


# ---------------------------------------------------------------------------
# Structural regression guard (smoke #154)
# ---------------------------------------------------------------------------

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


def _iter_src_python_files() -> list[Path]:
    repo_root = Path(__file__).resolve().parents[2]
    return sorted((repo_root / "src").rglob("*.py"))


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

        for path in _iter_src_python_files():
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
