"""Integration tests for SecondaryWorkflowManager with mocked adapters.

Tests the secondary workflows (copy-to-sources, multi-device push, undo,
copy-preset-to-device) by driving the async methods directly with mocked
adapter factories and verifying signal emissions.

Requirements: 8.1-8.6, 9.3-9.7, 10.3-10.7
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.gui.secondary_workflows import (
    MultiDeviceRequest,
    SecondaryWorkflowManager,
)
from src.models.canonical import CanonicalFilter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_filters() -> list[CanonicalFilter]:
    """Create a minimal valid filter list for test purposes."""
    return [
        CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=-3.0, q=1.4),
        CanonicalFilter(type="HS", frequency_hz=8000.0, gain_db=2.0, q=0.7),
    ]


# ---------------------------------------------------------------------------
# Test 1: Copy to sources with mixed success/failure results
# ---------------------------------------------------------------------------


class TestCopyToSourcesMixedResults:
    """Test copy_to_sources with mixed success/failure results.

    Requirements: 9.3, 9.4, 9.5, 9.6, 9.7
    """

    @pytest.mark.asyncio
    async def test_copy_to_sources_mixed_results(self) -> None:
        """Configure SecondaryWorkflowManager with mock SafeWrite that succeeds
        for 'hdmi' but raises for 'optical'. Verify 2 results: hdmi success=True,
        optical success=False. Verify copy_to_sources_complete signal emitted.
        """
        manager = SecondaryWorkflowManager()

        # Configure mock SafeWrite that succeeds for "hdmi" but fails for "optical"
        mock_sw = AsyncMock()

        async def execute_side_effect(source_name, settings):
            if source_name == "optical":
                raise RuntimeError("Optical port unavailable")
            return None

        mock_sw.execute = AsyncMock(side_effect=execute_side_effect)

        # Inject dependencies directly
        mock_adapter = MagicMock()
        manager._current_adapter = mock_adapter
        manager._safe_write_factory = MagicMock(return_value=mock_sw)

        # Capture emitted signals
        complete_results: list = []
        manager.copy_to_sources_complete.connect(lambda r: complete_results.append(r))

        progress_messages: list[str] = []
        manager.copy_to_sources_progress.connect(lambda m: progress_messages.append(m))

        # Execute
        filters = _make_filters()
        await manager._do_copy_to_sources(filters, ["hdmi", "optical"])

        # Verify signal emitted exactly once
        assert len(complete_results) == 1

        results = complete_results[0]
        assert len(results) == 2

        # hdmi should succeed
        hdmi_result = results[0]
        assert hdmi_result.source_name == "hdmi"
        assert hdmi_result.success is True

        # optical should fail
        optical_result = results[1]
        assert optical_result.source_name == "optical"
        assert optical_result.success is False
        assert "Optical port unavailable" in optical_result.message

        # Verify progress messages were emitted
        assert any("hdmi" in m for m in progress_messages)
        assert any("optical" in m for m in progress_messages)


# ---------------------------------------------------------------------------
# Test 2: Multi-device push with connection failure
# ---------------------------------------------------------------------------


class TestMultiDeviceConnectionFailure:
    """Test multi-device push with connection failures.

    Requirements: 10.3, 10.4, 10.5, 10.6, 10.7
    """

    @pytest.mark.asyncio
    async def test_multi_device_connection_failure(self) -> None:
        """Configure with mock factory that raises ConnectionError for device
        '192.168.1.20' but succeeds for '192.168.1.10'. Verify results show
        success for .10 and failure for .20.
        """
        manager = SecondaryWorkflowManager()

        # Build request with two devices
        request = MultiDeviceRequest(
            device_source_map={
                "192.168.1.10": ["wifi"],
                "192.168.1.20": ["wifi"],
            },
            device_names={
                "192.168.1.10": "Living Room",
                "192.168.1.20": "Bedroom",
            },
        )

        # Factory that raises ConnectionError for .20
        def adapter_factory(ip: str):
            if ip == "192.168.1.20":
                raise ConnectionError(f"Cannot connect to {ip}")
            adapter = MagicMock()
            adapter.ip = ip
            return adapter

        # SafeWrite factory that always succeeds
        def safe_write_factory(adapter):
            mock_sw = AsyncMock()
            mock_sw.execute = AsyncMock(return_value=None)
            return mock_sw

        manager._wiim_adapter_factory = MagicMock(side_effect=adapter_factory)
        manager._safe_write_factory = MagicMock(side_effect=safe_write_factory)

        # Capture emitted signals
        complete_results: list = []
        manager.multi_device_complete.connect(lambda r: complete_results.append(r))

        progress_messages: list[str] = []
        manager.multi_device_progress.connect(lambda m: progress_messages.append(m))

        # Execute
        filters = _make_filters()
        await manager._do_apply_to_devices(filters, request)

        # Verify signal emitted once
        assert len(complete_results) == 1

        results = complete_results[0]
        assert len(results) == 2

        # .10 should succeed
        result_10 = next(r for r in results if r.device_ip == "192.168.1.10")
        assert result_10.success is True
        assert result_10.device_name == "Living Room"

        # .20 should fail
        result_20 = next(r for r in results if r.device_ip == "192.168.1.20")
        assert result_20.success is False
        assert result_20.device_name == "Bedroom"
        assert "Cannot connect" in result_20.message


# ---------------------------------------------------------------------------
# Test 3: Undo with missing backup file
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
# Test 4: Undo success with valid backup file
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
# Test 5: Copy preset to device success
# ---------------------------------------------------------------------------


class TestCopyPresetToDeviceSuccess:
    """Test copy-preset-to-device with successful adapter/SafeWrite.

    Requirements: 15.3, 15.4, 15.5, 15.6
    """

    @pytest.mark.asyncio
    async def test_copy_preset_to_device_success(self) -> None:
        """Configure manager, call _do_copy_preset_to_device(filters,
        '192.168.1.50', 'wifi'). Mock factory creates adapter and SafeWrite
        that succeed. Verify copy_to_device_complete(True, ...) emitted.
        """
        manager = SecondaryWorkflowManager()

        # Mock adapter factory
        mock_adapter = MagicMock()
        mock_adapter.ip = "192.168.1.50"
        manager._wiim_adapter_factory = MagicMock(return_value=mock_adapter)

        # Mock SafeWrite that succeeds
        mock_sw = AsyncMock()
        mock_sw.execute = AsyncMock(return_value=None)
        manager._safe_write_factory = MagicMock(return_value=mock_sw)

        # Capture copy_to_device_complete signal
        device_signals: list[tuple[bool, str]] = []
        manager.copy_to_device_complete.connect(
            lambda ok, msg: device_signals.append((ok, msg))
        )

        # Execute
        filters = _make_filters()
        await manager._do_copy_preset_to_device(filters, "192.168.1.50", "wifi")

        # Verify copy_to_device_complete(True, ...)
        assert len(device_signals) == 1
        success, message = device_signals[0]
        assert success is True
        assert "192.168.1.50" in message

        # Verify adapter factory was called with correct IP
        manager._wiim_adapter_factory.assert_called_once_with("192.168.1.50")
        # Verify SafeWrite.execute was called
        mock_sw.execute.assert_called_once()


# ---------------------------------------------------------------------------
# Test 6: Copy preset to device failure
# ---------------------------------------------------------------------------


class TestCopyPresetToDeviceFailure:
    """Test copy-preset-to-device with SafeWrite failure.

    Requirements: 15.3, 15.6
    """

    @pytest.mark.asyncio
    async def test_copy_preset_to_device_failure(self) -> None:
        """Same as success but SafeWrite raises. Verify
        copy_to_device_complete(False, ...) emitted.
        """
        manager = SecondaryWorkflowManager()

        # Mock adapter factory
        mock_adapter = MagicMock()
        mock_adapter.ip = "192.168.1.50"
        manager._wiim_adapter_factory = MagicMock(return_value=mock_adapter)

        # Mock SafeWrite that raises
        mock_sw = AsyncMock()
        mock_sw.execute = AsyncMock(
            side_effect=RuntimeError("Device write verification failed")
        )
        manager._safe_write_factory = MagicMock(return_value=mock_sw)

        # Capture copy_to_device_complete signal
        device_signals: list[tuple[bool, str]] = []
        manager.copy_to_device_complete.connect(
            lambda ok, msg: device_signals.append((ok, msg))
        )

        # Execute
        filters = _make_filters()
        await manager._do_copy_preset_to_device(filters, "192.168.1.50", "wifi")

        # Verify copy_to_device_complete(False, ...)
        assert len(device_signals) == 1
        success, message = device_signals[0]
        assert success is False
        assert "Device write verification failed" in message
