"""Integration tests for discovery → device selection → probe → push flow.

Tests the full primary wizard flow through MainWindow with mocked backend adapters.
End-to-end signal chain verifying wizard state transitions and page population
at each step.

Requirements: 1.1-1.7, 2.1-2.7, 6.1-6.7
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.adapters.safe_write import WriteResult
from src.gui.app_settings import AppSettings
from src.gui.main_window import PAGE_INDICES, MainWindow
from src.gui.wizard_controller import FlowType, WizardStep
from src.models.canonical import CanonicalFilter
from src.models.capabilities import DeviceInfo
from src.models.channel_mode import ChannelMode
from src.models.errors import WiiMConnectionError, WiiMTimeoutError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def window(qtbot):
    """Create a MainWindow with mocked AsyncBridge for integration testing."""
    mock_bridge = MagicMock()
    mock_bridge.start = MagicMock()
    mock_bridge.shutdown = MagicMock()
    # Signal mocks — allow .emit() to be called and tracked
    mock_bridge.peq_ready = MagicMock()
    mock_bridge.operation_error = MagicMock()
    mock_bridge.progress_update = MagicMock()
    mock_bridge.rew_measurements_ready = MagicMock()
    mock_bridge.rew_filters_ready = MagicMock()
    mock_bridge.operation_started = MagicMock()
    mock_bridge.operation_finished = MagicMock()
    mock_bridge.discovery_complete = MagicMock()
    mock_bridge.capabilities_ready = MagicMock()
    mock_bridge.write_complete = MagicMock()
    mock_bridge.run_async = MagicMock()

    app_settings = AppSettings(first_run_complete=True)
    with (
        patch("src.gui.app_settings.AppSettings.load", return_value=app_settings),
        patch("src.gui.app_settings.AppSettings.save"),
    ):
        w = MainWindow(async_bridge=mock_bridge)
        qtbot.addWidget(w)
        yield w
        # Clear filters to prevent UnsavedChangesDialog from blocking on close
        w._wizard_controller.state.current_filters = []
        w.close()


def _make_filter(freq: float = 1000.0, gain: float = -3.0) -> CanonicalFilter:
    """Create a minimal CanonicalFilter for testing."""
    return CanonicalFilter(
        type="PEAK",
        frequency_hz=freq,
        gain_db=gain,
        q=1.0,
    )


def _make_caps(roomfit_level: int = 0) -> MagicMock:
    """Create a mock DeviceCapabilities with given roomfit_level.

    Args:
        roomfit_level: 0 = PEQ-only device, 2+ = RoomFit capable.
    """
    caps = MagicMock()
    caps.roomfit_level = roomfit_level
    caps.device_name = "WiiM Pro Plus"
    caps.model = "WiiM Pro Plus"
    caps.source_names = ["wifi", "optical", "hdmi"]
    caps.active_source = "wifi"
    caps.supports_profile_enumeration = False
    return caps


def _make_empty_sources_caps() -> MagicMock:
    """Create a mock DeviceCapabilities with empty source_names."""
    caps = MagicMock()
    caps.roomfit_level = 0
    caps.device_name = "WiiM Mini"
    caps.model = "WiiM Mini"
    caps.source_names = []
    caps.active_source = ""
    caps.supports_profile_enumeration = False
    return caps


# ---------------------------------------------------------------------------
# Test: Full wizard flow — discovery → device selection → probe → push
# ---------------------------------------------------------------------------


class TestFullWizardFlow:
    """Integration test: full primary wizard flow from discovery to push."""

    @pytest.mark.asyncio
    async def test_full_wizard_flow_discovery_to_push(self, window) -> None:
        """End-to-end integration test simulating the complete primary flow.

        Steps:
        a. Create MainWindow with mocked AsyncBridge (done via fixture)
        b. Mock DiscoveryModule.discover() to return device list
        c. Trigger discovery (call _on_refresh_requested)
        d. Directly call _do_discovery() and verify discovery_complete emitted
        e. Simulate device selection → verify WiiMHttpClient created, probe launched
        f. Directly call _do_probe() (mock CapabilityProber.probe())
        g. Verify _on_capabilities_ready creates WiiMAdapter/SafeWrite, determines flow
        h. Verify wizard advances past CONNECT step
        i. Set up wizard state for push (source selected, filters loaded)
        j. Directly call _do_push() (mock SafeWrite.execute)
        k. Verify write_complete emitted

        Requirements: 1.1-1.7, 2.1-2.7, 6.1-6.7
        """
        # --- Step b: Mock DiscoveryModule.discover() ---
        mock_devices = [
            DeviceInfo(
                ip="192.168.1.100",
                name="WiiM Pro Plus",
                model="WiiM Pro Plus",
                firmware="5.6.0",
                uuid="abc-123",
            ),
            DeviceInfo(
                ip="192.168.1.101",
                name="WiiM Mini",
                model="WiiM Mini",
                firmware="5.5.0",
                uuid="def-456",
            ),
        ]
        window._discovery_module.discover = AsyncMock(return_value=mock_devices)

        # --- Step c: Trigger discovery ---
        # Verify initial state
        assert window._wizard_controller.current_step == WizardStep.CONNECT
        window._on_refresh_requested()
        # Bridge.run_async should have been called (scheduling _bridge_wrapper)
        window._bridge.run_async.assert_called()

        # --- Step d: Directly call _do_discovery() and verify signal ---
        await window._do_discovery()

        # Verify discovery_complete emitted with transformed device dicts
        window._bridge.discovery_complete.emit.assert_called_once()
        emitted_devices = window._bridge.discovery_complete.emit.call_args[0][0]
        assert len(emitted_devices) == 2
        assert emitted_devices[0]["name"] == "WiiM Pro Plus"
        assert emitted_devices[0]["ip"] == "192.168.1.100"
        assert emitted_devices[0]["model"] == "WiiM Pro Plus"
        assert emitted_devices[1]["name"] == "WiiM Mini"
        assert emitted_devices[1]["ip"] == "192.168.1.101"

        # Verify discovered devices cached for picker dialogs
        assert len(window._discovered_devices) == 2

        # --- Step e: Simulate device selection ---
        window._on_device_selected("192.168.1.100")

        # Verify WiiMHttpClient and CapabilityProber created
        assert window._wiim_http_client is not None
        assert window._capability_prober is not None
        assert window._wizard_controller.state.selected_device == "192.168.1.100"

        # --- Step f: Mock and call _do_probe() ---
        caps = _make_caps(roomfit_level=0)
        window._capability_prober.probe = AsyncMock(return_value=caps)
        await window._do_probe()

        # Verify capabilities_ready emitted
        window._bridge.capabilities_ready.emit.assert_called_once_with(caps)

        # --- Step g: Call _on_capabilities_ready to process probe results ---
        window._on_capabilities_ready(caps)

        # Verify WiiMAdapter and SafeWrite created
        assert window._wiim_adapter is not None
        assert window._safe_write is not None

        # --- Step h: Verify wizard advances past CONNECT ---
        assert window._wizard_controller.flow_type == FlowType.PEQ_ONLY
        assert window._wizard_controller.current_step == WizardStep.SOURCE
        assert window._stacked_widget.currentIndex() == PAGE_INDICES["source"]

        # --- Step i: Set up wizard state for push ---
        window._on_source_selected("wifi", "Stereo")
        assert window._wizard_controller.state.selected_source == "wifi"
        assert window._wizard_controller.current_step == WizardStep.FILTERS

        # Load filters into state
        filters = [_make_filter(100.0), _make_filter(200.0), _make_filter(500.0)]
        window._wizard_controller.state.current_filters = filters
        window._on_filters_accepted()
        assert window._wizard_controller.current_step == WizardStep.REVIEW

        # Advance to PUSH step
        window._wizard_controller.state.dry_run = False
        window._on_push_requested()
        assert window._wizard_controller.current_step == WizardStep.PUSH

        # --- Step j: Mock SafeWrite and call _do_push() ---
        mock_safe_write = AsyncMock()
        push_result = WriteResult(
            success=True,
            rollback_success=None,
            backup_path=Path("/backups/wifi_backup.json"),
        )
        mock_safe_write.execute = AsyncMock(return_value=push_result)
        window._safe_write = mock_safe_write

        await window._do_push()

        # --- Step k: Verify write_complete emitted ---
        window._bridge.write_complete.emit.assert_called_once()
        emitted_result = window._bridge.write_complete.emit.call_args[0][0]
        assert emitted_result.success is True
        assert "wifi=" in emitted_result.backup_path
        assert "/backups/wifi_backup.json" in emitted_result.backup_path
        mock_safe_write.execute.assert_called_once()

        # Verify correct source and settings passed to SafeWrite
        call_args = mock_safe_write.execute.call_args
        assert call_args[0][0] == "wifi"
        settings = call_args[0][1]
        assert settings.channel_mode == ChannelMode.STEREO
        assert settings.bands == filters


# ---------------------------------------------------------------------------
# Test: Discovery error emits operation_error
# ---------------------------------------------------------------------------


class TestDiscoveryError:
    """Integration test: discovery error flows through _bridge_wrapper to operation_error."""

    @pytest.mark.asyncio
    async def test_discovery_error_emits_operation_error(self, window) -> None:
        """Mock discover() to raise WiiMTimeoutError, verify operation_error emitted.

        Requirements: 1.4, 12.1, 12.2
        """
        window._discovery_module.discover = AsyncMock(
            side_effect=WiiMTimeoutError("Discovery timed out")
        )

        # Call via _bridge_wrapper to exercise the error mapping path
        await window._bridge_wrapper("discovery", window._do_discovery())

        # Verify operation_error emitted with correct error type and mapped message
        window._bridge.operation_error.emit.assert_called_once()
        error_type, message = window._bridge.operation_error.emit.call_args[0]
        assert error_type == "WiiMTimeoutError"
        assert message == "Device not responding"


# ---------------------------------------------------------------------------
# Test: Probe error emits operation_error
# ---------------------------------------------------------------------------


class TestProbeError:
    """Integration test: probe error flows through _bridge_wrapper to operation_error."""

    @pytest.mark.asyncio
    async def test_probe_error_emits_operation_error(self, window) -> None:
        """Mock probe() to raise WiiMConnectionError, verify operation_error emitted.

        Requirements: 2.5, 12.1, 12.2
        """
        # Set up required state for probe (device must be selected)
        window._on_device_selected("192.168.1.100")
        window._capability_prober.probe = AsyncMock(
            side_effect=WiiMConnectionError("Connection refused")
        )

        # Call via _bridge_wrapper to exercise the error mapping path
        await window._bridge_wrapper("capability_probe", window._do_probe())

        # Verify operation_error emitted with correct error type and mapped message
        window._bridge.operation_error.emit.assert_called_once()
        error_type, message = window._bridge.operation_error.emit.call_args[0]
        assert error_type == "WiiMConnectionError"
        assert message == "Could not reach device"


# ---------------------------------------------------------------------------
# Test: Empty sources shows error
# ---------------------------------------------------------------------------


class TestEmptySourcesError:
    """Integration test: empty source_names uses model-based fallback (smoke fix #1)."""

    def test_empty_sources_uses_model_fallback(self, window) -> None:
        """Mock capabilities with empty source_names, verify model-based fallback.

        Previously this was an error condition (Req 2.7), but smoke fix #1
        changed behavior to use model-based defaults when the device doesn't
        report InputList. WiiM Mini gets ["wifi", "bluetooth"].

        Requirements: 2.7, smoke fix #1, smoke fix #35.
        """
        # Set up device selection first
        window._on_device_selected("192.168.1.100")

        # Create caps with empty source_names (WiiM Mini)
        caps = _make_empty_sources_caps()
        window._on_capabilities_ready(caps)

        # Verify NO error — fallback sources used instead
        window._bridge.operation_error.emit.assert_not_called()

        # Wizard should have advanced (PEQ_ONLY flow for Mini with roomfit_level=0)
        from src.gui.wizard_controller import FlowType

        assert window._wizard_controller.flow_type == FlowType.PEQ_ONLY
        # Wizard advances past CONNECT since fallback sources work
        assert window._wizard_controller.current_step != WizardStep.CONNECT
