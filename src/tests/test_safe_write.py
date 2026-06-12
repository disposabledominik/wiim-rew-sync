"""Unit tests for SafeWrite — five-step safe write protocol.

Tests use AsyncMock for adapter and backup_manager to exercise:
- Success path (backup -> write -> readback matches -> commit)
- Verify failure triggers rollback (readback doesn't match -> rollback succeeds)
- Rollback failure logs CRITICAL and returns rollback_success=False
- Slave device raises WiiMSlaveTargetError

Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.7, 5.8, 5.9, 5.10, 5.11
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adapters.safe_write import SafeWrite
from src.adapters.wiim_adapter import WiiMAdapter
from src.models.canonical import CanonicalFilter
from src.models.capabilities import DeviceCapabilities
from src.models.errors import WiiMSlaveTargetError
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
            channel_mode="stereo",
            bands=bands,
        )
    else:
        return PEQSettings(
            source_name="wifi",
            enabled=True,
            channel_mode="lr",
            bands_l=bands,
            bands_r=bands,
        )


def _solo_capabilities() -> DeviceCapabilities:
    """Create solo device capabilities."""
    return DeviceCapabilities(
        supports_peq=True,
        supports_batch_write=True,
        supports_channel_peq=True,
        max_filters=10,
        model="WiiM_Ultra",
        firmware="6.0.1.20",
        uuid="test-uuid-1234",
        role="solo",
    )


def _slave_capabilities() -> DeviceCapabilities:
    """Create slave device capabilities."""
    return DeviceCapabilities(
        supports_peq=True,
        supports_batch_write=True,
        max_filters=10,
        model="WiiM_Ultra",
        firmware="6.0.1.20",
        uuid="test-uuid-1234",
        role="slave",
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_adapter() -> AsyncMock:
    """Mocked WiiMAdapter."""
    adapter = AsyncMock(spec=WiiMAdapter)
    adapter._capabilities = _solo_capabilities()
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
# Tests: Slave Guard
# ---------------------------------------------------------------------------


class TestSlaveGuard:
    """Test that slave devices raise WiiMSlaveTargetError."""

    async def test_slave_raises_error(self, mock_backup_manager: MagicMock) -> None:
        """Writing to a slave device raises WiiMSlaveTargetError."""
        adapter = AsyncMock(spec=WiiMAdapter)
        adapter._capabilities = _slave_capabilities()

        sw = SafeWrite(adapter=adapter, backup_manager=mock_backup_manager)
        settings = _make_settings()

        with pytest.raises(WiiMSlaveTargetError, match="slave"):
            await sw.execute("wifi", settings)

    async def test_slave_no_backup_created(self, mock_backup_manager: MagicMock) -> None:
        """Slave guard fires before any backup or write."""
        adapter = AsyncMock(spec=WiiMAdapter)
        adapter._capabilities = _slave_capabilities()

        sw = SafeWrite(adapter=adapter, backup_manager=mock_backup_manager)
        settings = _make_settings()

        with pytest.raises(WiiMSlaveTargetError):
            await sw.execute("wifi", settings)

        mock_backup_manager.create_backup.assert_not_called()
        adapter.write_peq.assert_not_called()
        adapter.read_peq.assert_not_called()


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
