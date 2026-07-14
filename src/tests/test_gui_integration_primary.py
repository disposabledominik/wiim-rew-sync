"""Integration tests for PrimaryWorkflowManager with mocked dependencies.

Tests the primary workflows (discovery, capability probing, file import) by
driving the async `_do_*` methods directly and verifying bridge signal
emissions — mirrors test_gui_integration_secondary.py's structure. None of
these methods do their own error handling (they rely on the injected
MainWindow._bridge_wrapper, tested separately), so there's no exception-path
coverage here for that reason — see primary_workflows.py's configure()
docstring.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.gui.primary_workflows import PrimaryWorkflowManager
from src.models.canonical import CanonicalFilter
from src.models.channel_mode import ChannelMode


def _wizard_controller_stub() -> MagicMock:
    """A MagicMock WizardController with a plain, mutable .state namespace."""
    controller = MagicMock()
    controller.state = SimpleNamespace(
        current_filters=[],
        channel_mode=ChannelMode.STEREO,
        pending_rows=[],
        pending_conversion_notes=[],
        filters_origin="",
        pending_rows_l=[],
        pending_rows_r=[],
        pending_conversion_notes_l=[],
        pending_conversion_notes_r=[],
        primary_source="wifi",
    )
    return controller


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class TestDiscovery:
    """Test PrimaryWorkflowManager._do_discovery."""

    @pytest.mark.asyncio
    async def test_success_caches_devices_and_emits_complete(self) -> None:
        device = SimpleNamespace(name="Living Room", ip="192.168.1.5", model="Amp Ultra")

        manager = PrimaryWorkflowManager()
        manager._discovery_module = MagicMock(discover=AsyncMock(return_value=[device]))
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge

        await manager._do_discovery()

        assert manager.discovered_devices == [device]
        mock_bridge.discovery_complete.emit.assert_called_once_with(
            [{"name": "Living Room", "ip": "192.168.1.5", "model": "Amp Ultra"}]
        )

    @pytest.mark.asyncio
    async def test_progress_callback_emits_discovery_progress(self) -> None:
        device = SimpleNamespace(name="Living Room", ip="192.168.1.5", model="Amp Ultra")

        def fake_discover(on_found):
            on_found([device])
            return [device]

        manager = PrimaryWorkflowManager()
        manager._discovery_module = MagicMock(discover=AsyncMock(side_effect=fake_discover))
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge

        await manager._do_discovery()

        mock_bridge.discovery_progress.emit.assert_called_once_with(
            [{"name": "Living Room", "ip": "192.168.1.5", "model": "Amp Ultra"}]
        )


# ---------------------------------------------------------------------------
# Capability probing
# ---------------------------------------------------------------------------


class TestProbe:
    """Test PrimaryWorkflowManager._do_probe and probe-generation tracking."""

    def test_bump_probe_generation_increments(self) -> None:
        manager = PrimaryWorkflowManager()
        assert manager.bump_probe_generation() == 1
        assert manager.bump_probe_generation() == 2

    @pytest.mark.asyncio
    async def test_success_emits_capabilities_ready(self) -> None:
        manager = PrimaryWorkflowManager()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge
        generation = manager.bump_probe_generation()

        caps = MagicMock()
        prober = MagicMock(probe=AsyncMock(return_value=caps))

        await manager._do_probe(prober, generation)

        mock_bridge.capabilities_ready.emit.assert_called_once_with(caps)

    @pytest.mark.asyncio
    async def test_stale_generation_discarded(self) -> None:
        """A probe started for a superseded device selection must not emit."""
        manager = PrimaryWorkflowManager()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge
        stale_generation = manager.bump_probe_generation()
        manager.bump_probe_generation()  # a newer selection supersedes it

        prober = MagicMock(probe=AsyncMock(return_value=MagicMock()))

        await manager._do_probe(prober, stale_generation)

        mock_bridge.capabilities_ready.emit.assert_not_called()


# ---------------------------------------------------------------------------
# File import (stereo)
# ---------------------------------------------------------------------------


class TestFileImport:
    """Test PrimaryWorkflowManager._do_file_import."""

    @pytest.mark.asyncio
    async def test_success_populates_wizard_state_and_emits_peq_ready(
        self, tmp_path
    ) -> None:
        manager = PrimaryWorkflowManager()
        manager._wizard_controller = _wizard_controller_stub()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge

        rew_file = tmp_path / "filters.txt"
        rew_file.write_text("irrelevant — parser is mocked", encoding="utf-8")

        filters = [CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=-3.0, q=1.0)]
        with patch("src.translator.rew_parser.REWParser") as mock_parser_cls:
            mock_parser_cls.return_value.parse_file_with_rows.return_value = (
                filters, [], [], [],
            )
            await manager._do_file_import(str(rew_file))

        state = manager._wizard_controller.state
        assert state.current_filters == filters
        assert state.channel_mode == ChannelMode.STEREO
        assert state.filters_origin == f"Imported from REW file: {rew_file.name}"
        mock_bridge.peq_ready.emit.assert_called_once_with(filters)
        mock_bridge.progress_update.emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_warnings_emit_progress_update(self, tmp_path) -> None:
        manager = PrimaryWorkflowManager()
        manager._wizard_controller = _wizard_controller_stub()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge

        rew_file = tmp_path / "filters.txt"
        rew_file.write_text("irrelevant — parser is mocked", encoding="utf-8")

        filters = [CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=-3.0, q=1.0)]
        with patch("src.translator.rew_parser.REWParser") as mock_parser_cls:
            mock_parser_cls.return_value.parse_file_with_rows.return_value = (
                filters, ["skipped: unsupported band"], [], [],
            )
            await manager._do_file_import(str(rew_file))

        mock_bridge.progress_update.emit.assert_called_once_with(
            "1 filters loaded, 1 unsupported band(s) skipped"
        )


# ---------------------------------------------------------------------------
# File import (L/R)
# ---------------------------------------------------------------------------


class TestFileImportLr:
    """Test PrimaryWorkflowManager._do_file_import_lr."""

    @pytest.mark.asyncio
    async def test_success_combines_lr_and_emits_peq_ready(self, tmp_path) -> None:
        manager = PrimaryWorkflowManager()
        manager._wizard_controller = _wizard_controller_stub()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge

        file_l = tmp_path / "l.txt"
        file_r = tmp_path / "r.txt"
        file_l.write_text("irrelevant — parser is mocked", encoding="utf-8")
        file_r.write_text("irrelevant — parser is mocked", encoding="utf-8")

        filters_l = [CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=1.0, q=1.0)]
        filters_r = [CanonicalFilter(type="PEAK", frequency_hz=200.0, gain_db=2.0, q=1.0)]
        with patch("src.translator.rew_parser.REWParser") as mock_parser_cls:
            mock_parser_cls.return_value.parse_file_with_rows.side_effect = [
                (filters_l, [], [], []),
                (filters_r, [], [], []),
            ]
            await manager._do_file_import_lr(str(file_l), str(file_r))

        state = manager._wizard_controller.state
        assert state.current_filters == filters_l + filters_r
        assert state.channel_mode == ChannelMode.LR
        assert state.filters_origin == (
            f"Imported from REW files: L={file_l.name}, R={file_r.name}"
        )
        mock_bridge.peq_ready.emit.assert_called_once()
        emitted = mock_bridge.peq_ready.emit.call_args[0][0]
        assert emitted.bands_l == filters_l
        assert emitted.bands_r == filters_r
        assert emitted.source_name == "wifi"
        mock_bridge.progress_update.emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_combined_warnings_emit_progress_update(self, tmp_path) -> None:
        manager = PrimaryWorkflowManager()
        manager._wizard_controller = _wizard_controller_stub()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge

        file_l = tmp_path / "l.txt"
        file_r = tmp_path / "r.txt"
        file_l.write_text("irrelevant — parser is mocked", encoding="utf-8")
        file_r.write_text("irrelevant — parser is mocked", encoding="utf-8")

        filters_l = [CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=1.0, q=1.0)]
        filters_r: list[CanonicalFilter] = []
        with patch("src.translator.rew_parser.REWParser") as mock_parser_cls:
            mock_parser_cls.return_value.parse_file_with_rows.side_effect = [
                (filters_l, [], [], []),
                (filters_r, ["skipped: unsupported band"], [], []),
            ]
            await manager._do_file_import_lr(str(file_l), str(file_r))

        mock_bridge.progress_update.emit.assert_called_once_with(
            "L/R import: Left 1 bands (0 skipped), Right 0 bands (1 skipped)"
        )
