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

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.gui.primary_workflows import EmptyPresetFiltersError, PrimaryWorkflowManager
from src.models.canonical import CanonicalFilter
from src.models.channel_mode import ChannelMode
from src.models.peq import PEQSettings


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

    @pytest.mark.asyncio
    async def test_cancelled_discovery_reports_itself_abandoned(self) -> None:
        """A cancelled scan (Escape/Cancel while cancellable) must report
        itself abandoned so ConnectPage's scanning indicator doesn't stay
        shown forever -- discovery_complete never fires for a cancellation."""
        manager = PrimaryWorkflowManager()
        manager._discovery_module = MagicMock(
            discover=AsyncMock(side_effect=asyncio.CancelledError())
        )
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge

        with pytest.raises(asyncio.CancelledError):
            await manager._do_discovery()

        mock_bridge.discovery_complete.emit.assert_not_called()
        mock_bridge.discovery_abandoned.emit.assert_called_once_with()


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

        await manager._do_probe(prober, generation, "192.168.1.100")

        mock_bridge.capabilities_ready.emit.assert_called_once_with(caps)
        mock_bridge.probe_abandoned.emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_stale_generation_discarded(self) -> None:
        """A probe started for a superseded device selection must not emit
        capabilities_ready -- and must report itself abandoned so the
        stale device's card doesn't keep pulsing "connecting" forever."""
        manager = PrimaryWorkflowManager()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge
        stale_generation = manager.bump_probe_generation()
        manager.bump_probe_generation()  # a newer selection supersedes it

        prober = MagicMock(probe=AsyncMock(return_value=MagicMock()))

        await manager._do_probe(prober, stale_generation, "192.168.1.100")

        mock_bridge.capabilities_ready.emit.assert_not_called()
        mock_bridge.probe_abandoned.emit.assert_called_once_with("192.168.1.100")

    @pytest.mark.asyncio
    async def test_cancelled_probe_reports_itself_abandoned(self) -> None:
        """A cancelled probe (Escape/Cancel while cancellable) must also
        report itself abandoned -- CancelledError propagates through the
        `finally` block same as a normal exception would."""
        manager = PrimaryWorkflowManager()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge
        generation = manager.bump_probe_generation()

        prober = MagicMock(probe=AsyncMock(side_effect=asyncio.CancelledError()))

        with pytest.raises(asyncio.CancelledError):
            await manager._do_probe(prober, generation, "192.168.1.100")

        mock_bridge.capabilities_ready.emit.assert_not_called()
        mock_bridge.probe_abandoned.emit.assert_called_once_with("192.168.1.100")


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


# ---------------------------------------------------------------------------
# Device pull
# ---------------------------------------------------------------------------


class TestDevicePull:
    """Test PrimaryWorkflowManager._do_device_pull."""

    @pytest.mark.asyncio
    async def test_success_populates_wizard_state_and_emits_peq_ready(self) -> None:
        manager = PrimaryWorkflowManager()
        manager._wizard_controller = _wizard_controller_stub()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge

        filters = [CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=-3.0, q=1.0)]
        settings = PEQSettings(source_name="wifi", channel_mode=ChannelMode.STEREO, bands=filters)
        manager._current_adapter = MagicMock(read_peq=AsyncMock(return_value=settings))

        await manager._do_device_pull()

        state = manager._wizard_controller.state
        assert state.current_filters == filters
        assert state.device_filters == filters
        assert state.filters_origin == "Pulled from device (source: wifi)"
        mock_bridge.peq_ready.emit.assert_called_once_with(settings)


# ---------------------------------------------------------------------------
# RoomFit pull
# ---------------------------------------------------------------------------


class TestRoomfitPull:
    """Test PrimaryWorkflowManager._do_roomfit_pull."""

    @pytest.mark.asyncio
    async def test_success_populates_wizard_state_and_emits_peq_ready(self) -> None:
        manager = PrimaryWorkflowManager()
        manager._wizard_controller = _wizard_controller_stub()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge

        filters = [CanonicalFilter(type="PEAK", frequency_hz=500.0, gain_db=2.0, q=1.0)]
        settings = PEQSettings(source_name="wifi", channel_mode=ChannelMode.STEREO, bands=filters)
        manager._current_adapter = MagicMock(
            read_roomfit_preset_preview=AsyncMock(return_value=settings)
        )

        await manager._do_roomfit_pull("Living Room")

        state = manager._wizard_controller.state
        assert state.current_filters == filters
        assert state.device_filters == filters
        assert state.filters_origin == "RoomFit profile: Living Room"
        mock_bridge.peq_ready.emit.assert_called_once_with(settings)


# ---------------------------------------------------------------------------
# Load PEQ preset
# ---------------------------------------------------------------------------


class TestLoadPeqPreset:
    """Test PrimaryWorkflowManager._do_load_peq_preset."""

    @pytest.mark.asyncio
    async def test_stereo_preset_sets_stereo_channel_mode(self) -> None:
        manager = PrimaryWorkflowManager()
        manager._wizard_controller = _wizard_controller_stub()
        manager._wizard_controller.state.channel_mode = ChannelMode.LR
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge

        filters = [CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=1.0, q=1.0)]
        settings = PEQSettings(source_name="wifi", channel_mode=ChannelMode.STEREO, bands=filters)
        manager._current_adapter = MagicMock(
            read_peq_preset_preview=AsyncMock(return_value=settings)
        )

        await manager._do_load_peq_preset("Movie Night")

        state = manager._wizard_controller.state
        assert state.channel_mode == ChannelMode.STEREO
        assert state.current_filters == filters
        assert state.filters_origin == "PEQ preset: Movie Night"
        mock_bridge.peq_ready.emit.assert_called_once_with(settings)

    @pytest.mark.asyncio
    async def test_lr_preset_sets_lr_channel_mode(self) -> None:
        manager = PrimaryWorkflowManager()
        manager._wizard_controller = _wizard_controller_stub()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge

        filters_l = [CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=1.0, q=1.0)]
        filters_r = [CanonicalFilter(type="PEAK", frequency_hz=200.0, gain_db=1.0, q=1.0)]
        settings = PEQSettings(
            source_name="wifi", channel_mode=ChannelMode.LR,
            bands_l=filters_l, bands_r=filters_r,
        )
        manager._current_adapter = MagicMock(
            read_peq_preset_preview=AsyncMock(return_value=settings)
        )

        await manager._do_load_peq_preset("LR Preset")

        state = manager._wizard_controller.state
        assert state.channel_mode == ChannelMode.LR
        assert state.current_filters == filters_l + filters_r


# ---------------------------------------------------------------------------
# Export (stereo)
# ---------------------------------------------------------------------------


class TestExport:
    """Test PrimaryWorkflowManager._do_export."""

    @pytest.mark.asyncio
    async def test_success_emits_progress_update(self, tmp_path) -> None:
        manager = PrimaryWorkflowManager()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge

        filters = [CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=-3.0, q=1.0)]
        path = tmp_path / "eq.txt"
        with patch(
            "src.translator.rew_generator.REWGenerator.generate_file", return_value=[]
        ):
            await manager._do_export(filters, str(path))

        mock_bridge.progress_update.emit.assert_called_once_with("File exported successfully")

    @pytest.mark.asyncio
    async def test_warnings_emit_skip_count(self, tmp_path) -> None:
        manager = PrimaryWorkflowManager()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge

        filters = [CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=-3.0, q=1.0)]
        path = tmp_path / "eq.txt"
        with patch(
            "src.translator.rew_generator.REWGenerator.generate_file",
            return_value=["skipped: unsupported band"],
        ):
            await manager._do_export(filters, str(path))

        mock_bridge.progress_update.emit.assert_called_once_with(
            "File exported successfully (1 unsupported band(s) skipped)"
        )


# ---------------------------------------------------------------------------
# Export (L/R)
# ---------------------------------------------------------------------------


class TestExportLr:
    """Test PrimaryWorkflowManager._do_export_lr."""

    @pytest.mark.asyncio
    async def test_success_emits_filenames(self, tmp_path) -> None:
        manager = PrimaryWorkflowManager()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge

        filters_l = [CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=1.0, q=1.0)]
        filters_r = [CanonicalFilter(type="PEAK", frequency_hz=200.0, gain_db=1.0, q=1.0)]
        path_l = tmp_path / "eq_L.txt"
        path_r = tmp_path / "eq_R.txt"
        with patch(
            "src.translator.rew_generator.REWGenerator.generate_file", return_value=[]
        ):
            await manager._do_export_lr(filters_l, filters_r, path_l, path_r)

        mock_bridge.progress_update.emit.assert_called_once_with(
            f"L/R files exported: {path_l.name} and {path_r.name}"
        )

    @pytest.mark.asyncio
    async def test_combined_warnings_emit_skip_count(self, tmp_path) -> None:
        manager = PrimaryWorkflowManager()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge

        filters_l = [CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=1.0, q=1.0)]
        filters_r = [CanonicalFilter(type="PEAK", frequency_hz=200.0, gain_db=1.0, q=1.0)]
        path_l = tmp_path / "eq_L.txt"
        path_r = tmp_path / "eq_R.txt"
        with patch(
            "src.translator.rew_generator.REWGenerator.generate_file",
            side_effect=[["skip 1"], ["skip 2", "skip 3"]],
        ):
            await manager._do_export_lr(filters_l, filters_r, path_l, path_r)

        mock_bridge.progress_update.emit.assert_called_once_with(
            "L/R files exported (3 unsupported band(s) skipped)"
        )


# ---------------------------------------------------------------------------
# REW: list measurements
# ---------------------------------------------------------------------------


class TestRewListMeasurements:
    """Test PrimaryWorkflowManager._do_rew_list_measurements."""

    @pytest.mark.asyncio
    async def test_success_emits_measurements_ready(self) -> None:
        manager = PrimaryWorkflowManager()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge
        measurement = SimpleNamespace(uuid="abc-123", name="Living Room")
        manager._rew_client = MagicMock(
            list_measurements=AsyncMock(return_value=[measurement])
        )

        await manager._do_rew_list_measurements()

        mock_bridge.rew_measurements_ready.emit.assert_called_once_with([measurement])
        mock_bridge.progress_update.emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_result_emits_info_progress_update(self) -> None:
        manager = PrimaryWorkflowManager()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge
        manager._rew_client = MagicMock(list_measurements=AsyncMock(return_value=[]))

        await manager._do_rew_list_measurements()

        mock_bridge.rew_measurements_ready.emit.assert_not_called()
        args, _ = mock_bridge.progress_update.emit.call_args
        assert args[0].startswith("__info__No measurements found in REW.")


# ---------------------------------------------------------------------------
# REW: get filters (stereo)
# ---------------------------------------------------------------------------


class TestRewGetFilters:
    """Test PrimaryWorkflowManager._do_rew_get_filters."""

    @pytest.mark.asyncio
    async def test_success_populates_wizard_state_and_emits_filters_ready(self) -> None:
        manager = PrimaryWorkflowManager()
        manager._wizard_controller = _wizard_controller_stub()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge

        filters = [CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=-3.0, q=1.0)]
        manager._rew_client = MagicMock(
            get_filters_with_rows=AsyncMock(return_value=(filters, filters, []))
        )

        await manager._do_rew_get_filters("uuid-1", "Living Room")

        state = manager._wizard_controller.state
        assert state.current_filters == filters
        assert state.channel_mode == ChannelMode.STEREO
        assert state.filters_origin == "Pulled from REW measurement: Living Room"
        mock_bridge.rew_filters_ready.emit.assert_called_once_with(filters)


# ---------------------------------------------------------------------------
# REW: get filters (L/R)
# ---------------------------------------------------------------------------


class TestRewGetFiltersLr:
    """Test PrimaryWorkflowManager._do_rew_get_filters_lr."""

    @pytest.mark.asyncio
    async def test_success_combines_lr_and_emits_peq_ready(self) -> None:
        manager = PrimaryWorkflowManager()
        manager._wizard_controller = _wizard_controller_stub()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge

        filters_l = [CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=1.0, q=1.0)]
        filters_r = [CanonicalFilter(type="PEAK", frequency_hz=200.0, gain_db=1.0, q=1.0)]
        manager._rew_client = MagicMock(
            get_filters_with_rows=AsyncMock(
                side_effect=[(filters_l, filters_l, []), (filters_r, filters_r, [])]
            )
        )

        await manager._do_rew_get_filters_lr("uuid-l", "uuid-r", "Left", "Right")

        state = manager._wizard_controller.state
        assert state.current_filters == filters_l + filters_r
        assert state.channel_mode == ChannelMode.LR
        assert state.filters_origin == "Pulled from REW measurements: L=Left, R=Right"
        emitted_settings = mock_bridge.peq_ready.emit.call_args[0][0]
        assert emitted_settings.bands_l == filters_l
        assert emitted_settings.bands_r == filters_r
        mock_bridge.progress_update.emit.assert_not_called()

    @pytest.mark.asyncio
    async def test_skipped_bands_emit_progress_update(self) -> None:
        from src.translator._warnings import SkippedBand

        manager = PrimaryWorkflowManager()
        manager._wizard_controller = _wizard_controller_stub()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge

        filters_l = [CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=1.0, q=1.0)]
        filters_r: list[CanonicalFilter] = []
        skipped = SkippedBand(
            original_type="LP", reason="unsupported", frequency_hz=50.0, gain_db=0.0, q=1.0
        )
        manager._rew_client = MagicMock(
            get_filters_with_rows=AsyncMock(
                side_effect=[
                    (filters_l, filters_l, []),
                    (filters_r, [skipped], []),
                ]
            )
        )

        await manager._do_rew_get_filters_lr("uuid-l", "uuid-r")

        mock_bridge.progress_update.emit.assert_called_once_with(
            "L/R import: Left 1 bands (0 skipped), Right 0 bands (1 skipped)"
        )


# ---------------------------------------------------------------------------
# Preset export
# ---------------------------------------------------------------------------


class TestPresetExport:
    """Test PrimaryWorkflowManager._do_preset_export."""

    @pytest.mark.asyncio
    async def test_stereo_success_emits_progress_update(self, tmp_path) -> None:
        manager = PrimaryWorkflowManager()
        manager._wizard_controller = _wizard_controller_stub()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge

        filters = [CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=-3.0, q=1.0)]
        settings = PEQSettings(source_name="wifi", channel_mode=ChannelMode.STEREO, bands=filters)
        manager._current_adapter = MagicMock(
            read_peq_preset_preview=AsyncMock(return_value=settings),
            read_preset_preview=AsyncMock(return_value=settings),
            read_preset_preview_or_live=AsyncMock(return_value=settings),
        )
        path = tmp_path / "movie-night.txt"

        with patch(
            "src.translator.rew_generator.REWGenerator.generate_file", return_value=[]
        ):
            await manager._do_preset_export("Movie Night", "PEQ", str(path))

        mock_bridge.progress_update.emit.assert_called_once_with(
            f"Exported 'Movie Night' to {path.name}"
        )

    @pytest.mark.asyncio
    async def test_stereo_empty_filters_raises(self, tmp_path) -> None:
        manager = PrimaryWorkflowManager()
        manager._wizard_controller = _wizard_controller_stub()
        manager._bridge = MagicMock()

        settings = PEQSettings(source_name="wifi", channel_mode=ChannelMode.STEREO, bands=[])
        manager._current_adapter = MagicMock(
            read_peq_preset_preview=AsyncMock(return_value=settings),
            read_preset_preview=AsyncMock(return_value=settings),
            read_preset_preview_or_live=AsyncMock(return_value=settings),
        )

        with pytest.raises(EmptyPresetFiltersError, match="has no filters to export"):
            await manager._do_preset_export(
                "Empty Preset", "PEQ", str(tmp_path / "empty.txt")
            )

    @pytest.mark.asyncio
    async def test_lr_empty_filters_raises(self, tmp_path) -> None:
        manager = PrimaryWorkflowManager()
        manager._wizard_controller = _wizard_controller_stub()
        manager._bridge = MagicMock()

        settings = PEQSettings(
            source_name="wifi", channel_mode=ChannelMode.LR, bands_l=[], bands_r=[]
        )
        manager._current_adapter = MagicMock(
            read_roomfit_preset_preview=AsyncMock(return_value=settings),
            read_preset_preview=AsyncMock(return_value=settings),
            read_preset_preview_or_live=AsyncMock(return_value=settings),
        )

        with pytest.raises(EmptyPresetFiltersError, match="has no filters to export"):
            await manager._do_preset_export(
                "Empty LR", "RoomFit", str(tmp_path / "empty.txt")
            )


# ---------------------------------------------------------------------------
# Preset save
# ---------------------------------------------------------------------------


class TestPresetSave:
    """Test PrimaryWorkflowManager._do_preset_save."""

    @pytest.mark.asyncio
    async def test_success_saves_and_emits_progress_update(self) -> None:
        manager = PrimaryWorkflowManager()
        manager._wizard_controller = _wizard_controller_stub()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge
        manager._profile_repository = MagicMock()

        filters = [CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=-3.0, q=1.0)]
        settings = PEQSettings(source_name="wifi", channel_mode=ChannelMode.STEREO, bands=filters)
        manager._current_adapter = MagicMock(
            read_peq_preset_preview=AsyncMock(return_value=settings),
            read_preset_preview=AsyncMock(return_value=settings),
            read_preset_preview_or_live=AsyncMock(return_value=settings),
        )

        await manager._do_preset_save("Movie Night", "PEQ", "WiiM - Movie Night")

        manager._profile_repository.save.assert_called_once()
        saved_profile = manager._profile_repository.save.call_args[0][0]
        assert saved_profile.name == "WiiM - Movie Night"
        mock_bridge.progress_update.emit.assert_called_once_with(
            "Saved 'WiiM - Movie Night' to My Presets"
        )

    @pytest.mark.asyncio
    async def test_empty_filters_raises(self) -> None:
        manager = PrimaryWorkflowManager()
        manager._wizard_controller = _wizard_controller_stub()
        manager._bridge = MagicMock()
        manager._profile_repository = MagicMock()

        settings = PEQSettings(source_name="wifi", channel_mode=ChannelMode.STEREO, bands=[])
        manager._current_adapter = MagicMock(
            read_peq_preset_preview=AsyncMock(return_value=settings),
            read_preset_preview=AsyncMock(return_value=settings),
            read_preset_preview_or_live=AsyncMock(return_value=settings),
        )

        with pytest.raises(EmptyPresetFiltersError, match="has no filters to save"):
            await manager._do_preset_save("Empty Preset", "PEQ", "WiiM - Empty Preset")

        manager._profile_repository.save.assert_not_called()


def _capture_signal(signal: object) -> list[tuple[object, ...]]:
    """Connect a plain list-collector to a manager-owned Signal (not a
    mocked AsyncBridge) and return the list its emitted args land in.

    name_profiles_ready (like peq_presets_ready/roomfit_profiles_ready
    before it) is a real Qt signal declared on PrimaryWorkflowManager
    itself, not routed through the injected bridge mock -- so a mocked
    bridge's `.emit` is never called for it and asserting on it silently
    checks nothing.
    """
    captured: list[tuple[object, ...]] = []
    signal.connect(lambda *args: captured.append(args))  # type: ignore[attr-defined]
    return captured


# ---------------------------------------------------------------------------
# Preset export/save batches (#165c follow-up: Export/Save must process
# every selected preset, not silently only the first)
# ---------------------------------------------------------------------------


class TestPresetExportBatch:
    """Test PrimaryWorkflowManager._do_export_presets."""

    @pytest.mark.asyncio
    async def test_processes_all_requests_and_emits_complete(self, tmp_path) -> None:
        manager = PrimaryWorkflowManager()
        manager._wizard_controller = _wizard_controller_stub()
        manager._bridge = MagicMock()
        captured = _capture_signal(manager.presets_export_complete)

        filters = [CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=-3.0, q=1.0)]
        settings = PEQSettings(source_name="wifi", channel_mode=ChannelMode.STEREO, bands=filters)
        manager._current_adapter = MagicMock(
            read_preset_preview_or_live=AsyncMock(return_value=settings)
        )

        requests = [
            ("Preset A", "PEQ", str(tmp_path / "a.txt"), False),
            ("Preset B", "PEQ", str(tmp_path / "b.txt"), False),
        ]

        with patch(
            "src.translator.rew_generator.REWGenerator.generate_file", return_value=[]
        ):
            await manager._do_export_presets(requests)

        assert manager._current_adapter.read_preset_preview_or_live.await_count == 2
        assert (tmp_path / "a.txt").parent.exists()  # sanity: real tmp_path used
        assert captured == [(2, 0)]

    @pytest.mark.asyncio
    async def test_partial_failure_continues_and_counts(self, tmp_path) -> None:
        """One preset with no filters (EmptyPresetFiltersError) doesn't
        abort the batch -- the rest are still exported, and the failure is
        counted rather than propagated."""
        manager = PrimaryWorkflowManager()
        manager._wizard_controller = _wizard_controller_stub()
        manager._bridge = MagicMock()
        captured = _capture_signal(manager.presets_export_complete)

        filters = [CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=-3.0, q=1.0)]
        good_settings = PEQSettings(
            source_name="wifi", channel_mode=ChannelMode.STEREO, bands=filters
        )
        empty_settings = PEQSettings(
            source_name="wifi", channel_mode=ChannelMode.STEREO, bands=[]
        )
        manager._current_adapter = MagicMock(
            read_preset_preview_or_live=AsyncMock(
                side_effect=[empty_settings, good_settings]
            )
        )

        requests = [
            ("Empty Preset", "PEQ", str(tmp_path / "empty.txt"), False),
            ("Preset B", "PEQ", str(tmp_path / "b.txt"), False),
        ]

        with patch(
            "src.translator.rew_generator.REWGenerator.generate_file", return_value=[]
        ):
            await manager._do_export_presets(requests)

        # Both were attempted despite the first one failing.
        assert manager._current_adapter.read_preset_preview_or_live.await_count == 2
        assert captured == [(1, 1)]


class TestPresetSaveBatch:
    """Test PrimaryWorkflowManager._do_save_presets."""

    @pytest.mark.asyncio
    async def test_processes_all_requests_and_emits_complete(self) -> None:
        manager = PrimaryWorkflowManager()
        manager._wizard_controller = _wizard_controller_stub()
        manager._bridge = MagicMock()
        manager._profile_repository = MagicMock()
        captured = _capture_signal(manager.presets_save_complete)

        filters = [CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=-3.0, q=1.0)]
        settings = PEQSettings(source_name="wifi", channel_mode=ChannelMode.STEREO, bands=filters)
        manager._current_adapter = MagicMock(
            read_preset_preview_or_live=AsyncMock(return_value=settings)
        )

        requests = [
            ("Preset A", "PEQ", "WiiM - Preset A", False),
            ("Preset B", "PEQ", "WiiM - Preset B", False),
        ]

        await manager._do_save_presets(requests)

        assert manager._profile_repository.save.call_count == 2
        saved_names = {
            call.args[0].name for call in manager._profile_repository.save.call_args_list
        }
        assert saved_names == {"WiiM - Preset A", "WiiM - Preset B"}
        assert captured == [(2, 0)]

    @pytest.mark.asyncio
    async def test_partial_failure_continues_and_counts(self) -> None:
        manager = PrimaryWorkflowManager()
        manager._wizard_controller = _wizard_controller_stub()
        manager._bridge = MagicMock()
        manager._profile_repository = MagicMock()
        captured = _capture_signal(manager.presets_save_complete)

        filters = [CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=-3.0, q=1.0)]
        good_settings = PEQSettings(
            source_name="wifi", channel_mode=ChannelMode.STEREO, bands=filters
        )
        empty_settings = PEQSettings(
            source_name="wifi", channel_mode=ChannelMode.STEREO, bands=[]
        )
        manager._current_adapter = MagicMock(
            read_preset_preview_or_live=AsyncMock(
                side_effect=[empty_settings, good_settings]
            )
        )

        requests = [
            ("Empty Preset", "PEQ", "WiiM - Empty Preset", False),
            ("Preset B", "PEQ", "WiiM - Preset B", False),
        ]

        await manager._do_save_presets(requests)

        assert manager._profile_repository.save.call_count == 1
        assert captured == [(1, 1)]


# ---------------------------------------------------------------------------
# RoomFit: populate NameProfilePage
# ---------------------------------------------------------------------------


class TestPopulateNameProfiles:
    """Test PrimaryWorkflowManager._do_populate_name_profiles."""

    @pytest.mark.asyncio
    async def test_success_emits_profiles_active_and_enabled(self) -> None:
        manager = PrimaryWorkflowManager()
        manager._wizard_controller = _wizard_controller_stub()
        manager._bridge = MagicMock()
        captured = _capture_signal(manager.name_profiles_ready)

        manager._current_adapter = MagicMock(
            capabilities=SimpleNamespace(supports_roomfit=True),
            list_roomfit_profiles=AsyncMock(
                return_value=[{"Name": "Living Room"}, {"Name": "Office"}]
            ),
            get_roomfit_status=AsyncMock(return_value=(True, "Living Room")),
        )

        await manager._do_populate_name_profiles()

        assert captured == [(["Living Room", "Office"], "Living Room", True)]

    @pytest.mark.asyncio
    async def test_unsupported_emits_empty(self) -> None:
        manager = PrimaryWorkflowManager()
        manager._wizard_controller = _wizard_controller_stub()
        manager._bridge = MagicMock()
        captured = _capture_signal(manager.name_profiles_ready)

        manager._current_adapter = MagicMock(
            capabilities=SimpleNamespace(supports_roomfit=False),
        )

        await manager._do_populate_name_profiles()

        assert captured == [([], "", False)]

    @pytest.mark.asyncio
    async def test_status_failure_degrades_gracefully(self) -> None:
        manager = PrimaryWorkflowManager()
        manager._wizard_controller = _wizard_controller_stub()
        manager._bridge = MagicMock()
        captured = _capture_signal(manager.name_profiles_ready)

        manager._current_adapter = MagicMock(
            capabilities=SimpleNamespace(supports_roomfit=True),
            list_roomfit_profiles=AsyncMock(return_value=[{"Name": "Living Room"}]),
            get_roomfit_status=AsyncMock(side_effect=RuntimeError("boom")),
        )

        await manager._do_populate_name_profiles()

        assert captured == [(["Living Room"], "", False)]

    @pytest.mark.asyncio
    async def test_list_failure_emits_empty(self) -> None:
        manager = PrimaryWorkflowManager()
        manager._wizard_controller = _wizard_controller_stub()
        manager._bridge = MagicMock()
        captured = _capture_signal(manager.name_profiles_ready)

        manager._current_adapter = MagicMock(
            capabilities=SimpleNamespace(supports_roomfit=True),
            list_roomfit_profiles=AsyncMock(side_effect=RuntimeError("boom")),
        )

        await manager._do_populate_name_profiles()

        assert captured == [([], "", False)]


# ---------------------------------------------------------------------------
# Delete presets
# ---------------------------------------------------------------------------


class TestDeletePresets:
    """Test PrimaryWorkflowManager._do_delete_presets."""

    @pytest.mark.asyncio
    async def test_success_emits_counts_and_refreshes(self) -> None:
        manager = PrimaryWorkflowManager()
        manager._bridge = MagicMock()
        captured = _capture_signal(manager.presets_delete_complete)

        manager._current_adapter = MagicMock(
            delete_peq_profile=AsyncMock(),
            delete_roomfit_profile=AsyncMock(),
        )
        manager.refresh_presets = AsyncMock()

        items = [
            SimpleNamespace(name="Movie", preset_type="PEQ"),
            SimpleNamespace(name="Living Room", preset_type="RoomFit"),
        ]

        await manager._do_delete_presets(items)

        manager._current_adapter.delete_peq_profile.assert_awaited_once_with("Movie")
        manager._current_adapter.delete_roomfit_profile.assert_awaited_once_with(
            "Living Room"
        )
        manager.refresh_presets.assert_awaited_once()
        assert captured == [(2, 0)]

    @pytest.mark.asyncio
    async def test_partial_failure_emits_counts(self) -> None:
        manager = PrimaryWorkflowManager()
        manager._bridge = MagicMock()
        captured = _capture_signal(manager.presets_delete_complete)

        manager._current_adapter = MagicMock(
            delete_peq_profile=AsyncMock(side_effect=RuntimeError("boom")),
            delete_roomfit_profile=AsyncMock(),
        )
        manager.refresh_presets = AsyncMock()

        items = [
            SimpleNamespace(name="Movie", preset_type="PEQ"),
            SimpleNamespace(name="Living Room", preset_type="RoomFit"),
        ]

        await manager._do_delete_presets(items)

        assert captured == [(1, 1)]

    @pytest.mark.asyncio
    async def test_skips_items_without_name(self) -> None:
        manager = PrimaryWorkflowManager()
        manager._bridge = MagicMock()
        captured = _capture_signal(manager.presets_delete_complete)

        manager._current_adapter = MagicMock(
            delete_peq_profile=AsyncMock(),
            delete_roomfit_profile=AsyncMock(),
        )
        manager.refresh_presets = AsyncMock()

        items = [SimpleNamespace(name="", preset_type="PEQ")]

        await manager._do_delete_presets(items)

        manager._current_adapter.delete_peq_profile.assert_not_awaited()
        assert captured == [(0, 0)]


class TestRawCommand:
    """Test PrimaryWorkflowManager._do_raw_command."""

    @pytest.mark.asyncio
    async def test_dict_response_formatted_as_json(self) -> None:
        manager = PrimaryWorkflowManager()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge
        manager._current_adapter = MagicMock(
            raw_command=AsyncMock(return_value={"foo": "bar"})
        )

        await manager._do_raw_command("getStatusEx")

        manager._current_adapter.raw_command.assert_awaited_once_with("getStatusEx")
        emitted = mock_bridge.progress_update.emit.call_args[0][0]
        assert emitted.startswith("__raw_response__")
        assert '"foo": "bar"' in emitted

    @pytest.mark.asyncio
    async def test_string_response_passed_through(self) -> None:
        manager = PrimaryWorkflowManager()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge
        manager._current_adapter = MagicMock(raw_command=AsyncMock(return_value="OK"))

        await manager._do_raw_command("EQPowerOn")

        mock_bridge.progress_update.emit.assert_called_once_with("__raw_response__OK")

    @pytest.mark.asyncio
    async def test_exception_caught_and_formatted_as_error(self) -> None:
        """The exception is caught here (not left to bridge_wrapper's usual
        error-mapping) so the diagnostics panel gets a formatted error
        response instead of a status-banner error."""
        manager = PrimaryWorkflowManager()
        mock_bridge = MagicMock()
        manager._bridge = mock_bridge
        manager._current_adapter = MagicMock(
            raw_command=AsyncMock(side_effect=RuntimeError("device unreachable"))
        )

        await manager._do_raw_command("getStatusEx")

        mock_bridge.progress_update.emit.assert_called_once_with(
            "__raw_response__Error: device unreachable"
        )
