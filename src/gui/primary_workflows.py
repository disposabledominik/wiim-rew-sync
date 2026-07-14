"""Primary workflow orchestration for discovery, capability probing, and file import.

Phase 1 of the MainWindow god-object extraction (docs/backlog.md item 3): moves
the adapter-free `_do_*` methods out of MainWindow into a dedicated QObject
manager, following the pattern established by SecondaryWorkflowManager
(src/gui/secondary_workflows.py) — no direct Qt widget access, dependencies
injected via configure(), workflow results delivered as signals or, for the
four methods here, via AsyncBridge's existing signals directly (see
_do_discovery/_do_probe/_do_file_import/_do_file_import_lr — none of them
declare new signals of their own).

Unlike SecondaryWorkflowManager, none of these four methods need a live
device adapter, so configure() is called eagerly from MainWindow.__init__
rather than waiting for a device to be selected/probed.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Signal

from src.models.channel_mode import ChannelMode
from src.models.peq import PEQSettings

if TYPE_CHECKING:
    from src.adapters.capability_prober import CapabilityProber
    from src.adapters.wiim_adapter import WiiMAdapter
    from src.discovery.discovery_module import DiscoveryModule
    from src.gui.async_bridge import AsyncBridge
    from src.gui.wizard_controller import WizardController
    from src.models.capabilities import DeviceInfo

logger = logging.getLogger("wiim_rew_sync.primary_workflows")

# Signature of MainWindow._bridge_wrapper, injected via configure() rather
# than reimplemented here — see configure()'s docstring for why.
BridgeWrapper = Callable[[str, "Coroutine[Any, Any, Any]"], "Coroutine[Any, Any, None]"]


class PrimaryWorkflowManager(QObject):
    """Orchestrates primary wizard workflows: discovery, probing, file import.

    This manager coordinates the adapter-free half of MainWindow's `_do_*`
    methods. It does NOT perform direct network calls itself for discovery
    (that's DiscoveryModule) or file I/O (that's REWParser); it just
    relocates the existing orchestration bodies verbatim out of MainWindow.

    Results are delivered via AsyncBridge's existing signals
    (discovery_progress, discovery_complete, capabilities_ready, peq_ready,
    progress_update) — this manager declares no new signals of its own for
    those four workflows, so MainWindow's existing `_on_*` slot connections
    need no rewiring. list_presets()/refresh_presets() is the exception: it
    declares four signals of its own (see below), one per PresetsDeviceView
    setter it used to call directly.

    Signals:
        peq_presets_ready(list, str): PEQ PresetItem list + active preset
            name, mirrors PresetsDeviceView.set_peq_presets().
        peq_presets_unavailable(): mirrors set_peq_unavailable().
        roomfit_profiles_ready(list, str): RoomFit PresetItem list + active
            profile name, mirrors set_roomfit_profiles().
        roomfit_profiles_hidden(): mirrors set_roomfit_hidden().

        Four signals rather than one combined result: the PEQ and RoomFit
        fetches inside refresh_presets() run concurrently and update
        independently of each other (#174) — one combined signal emitted
        after both finish would make the slower fetch block the faster
        one's UI update, changing that behavior.
    """

    peq_presets_ready = Signal(list, str)
    peq_presets_unavailable = Signal()
    roomfit_profiles_ready = Signal(list, str)
    roomfit_profiles_hidden = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bridge: AsyncBridge | None = None
        self._discovery_module: DiscoveryModule | None = None
        self._wizard_controller: WizardController | None = None
        self._bridge_wrapper: BridgeWrapper | None = None
        self._discovered_devices: list[DeviceInfo] = []
        self._current_adapter: WiiMAdapter | None = None
        # Bumped on every device selection; lets a stale/superseded capability
        # probe (e.g. user selects a second device before the first probe
        # resolves) detect that it's no longer current and avoid corrupting
        # wizard state (double-advance, wrong "Connected" step). Owned here
        # rather than in MainWindow since its only purpose is guarding
        # probe()/_do_probe() below.
        self._probe_generation = 0

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def configure(
        self,
        bridge: AsyncBridge,
        discovery_module: DiscoveryModule,
        wizard_controller: WizardController,
        bridge_wrapper: BridgeWrapper,
    ) -> None:
        """Inject dependencies for workflow execution.

        Called eagerly from MainWindow.__init__, right after the wizard
        controller is constructed — unlike SecondaryWorkflowManager, none of
        these four methods need a live device adapter, so there's no reason
        to wait for device selection.

        Args:
            bridge: The AsyncBridge for run_async calls and result signals.
            discovery_module: Shared DiscoveryModule instance (mDNS/subnet scan).
            wizard_controller: Shared WizardController, for reading/writing
                filter state on file import.
            bridge_wrapper: MainWindow._bridge_wrapper, injected as a plain
                callable rather than reimplemented here. It already does
                exactly what these methods need (catch any exception, log it,
                map it to a user-friendly message, emit operation_error) and
                is the sole error handling every one of these methods relies
                on today (none has its own try/except) — duplicating that
                logic inside this manager would just be two copies of the
                same code to keep in sync.
        """
        self._bridge = bridge
        self._discovery_module = discovery_module
        self._wizard_controller = wizard_controller
        self._bridge_wrapper = bridge_wrapper
        logger.info("PrimaryWorkflowManager configured")

    def set_current_adapter(self, adapter: WiiMAdapter | None) -> None:
        """Set the current device adapter for same-device workflows.

        Called from MainWindow whenever the active device changes (mirrors
        SecondaryWorkflowManager.set_current_adapter). Used by
        list_presets()/refresh_presets(), the only workflow here that reads
        the live device.

        Args:
            adapter: The WiiMAdapter for the currently connected device,
                    or None to clear.
        """
        self._current_adapter = adapter

    @property
    def discovered_devices(self) -> list[DeviceInfo]:
        """Devices found by the most recent discover() call.

        Owned here (not MainWindow) since this is discovery's own result
        cache — device-picker call sites that stayed in MainWindow read it
        via this property instead of a duplicated local copy.
        """
        return self._discovered_devices

    # ------------------------------------------------------------------
    # Workflow: Discovery
    # ------------------------------------------------------------------

    def discover(self) -> None:
        """Trigger device discovery; results arrive via the bridge's discovery signals."""
        assert self._bridge is not None
        assert self._bridge_wrapper is not None
        self._bridge.run_async(self._bridge_wrapper("discovery", self._do_discovery()))

    async def _do_discovery(self) -> None:
        """Run device discovery and emit results via bridge signal.

        Uses progressive discovery — devices appear in the UI as soon as
        they're found rather than waiting for the full scan to complete.
        """
        assert self._bridge is not None
        assert self._discovery_module is not None

        def _on_found(devices: list[DeviceInfo]) -> None:
            """Progressive callback — emit partial results to the UI."""
            device_list = [
                {"name": d.name, "ip": d.ip, "model": d.model}
                for d in devices
            ]
            assert self._bridge is not None
            self._bridge.discovery_progress.emit(device_list)

        devices = await self._discovery_module.discover(on_found=_on_found)
        # Cache raw DeviceInfo objects for device picker dialogs
        self._discovered_devices = devices
        device_list = [
            {"name": d.name, "ip": d.ip, "model": d.model}
            for d in devices
        ]
        self._bridge.discovery_complete.emit(device_list)

    # ------------------------------------------------------------------
    # Workflow: Capability Probing
    # ------------------------------------------------------------------

    def bump_probe_generation(self) -> int:
        """Increment and return the probe-generation counter.

        Called by MainWindow on every device selection, before constructing
        the CapabilityProber for the newly selected device, so the returned
        value can be passed to probe() as the "generation at selection time"
        snapshot _do_probe compares itself against when it resolves.
        """
        self._probe_generation += 1
        return self._probe_generation

    def probe(self, prober: CapabilityProber, generation: int) -> None:
        """Trigger capability probing for a just-selected device.

        Args:
            prober: The CapabilityProber for the device this probe targets.
            generation: Snapshot from bump_probe_generation() at selection
                time, used by _do_probe to discard a stale result.
        """
        assert self._bridge is not None
        assert self._bridge_wrapper is not None
        self._bridge.run_async(
            self._bridge_wrapper("capability_probe", self._do_probe(prober, generation))
        )

    async def _do_probe(self, prober: CapabilityProber, generation: int) -> None:
        """Run capability probing and emit results via bridge signal.

        Calls CapabilityProber.probe() and emits the DeviceCapabilities
        object for flow-type determination and wizard advancement.

        The *prober* instance and *generation* are passed in explicitly
        (rather than read from ``self``) so a probe started for a previously
        selected device can't pick up a different device's prober if the
        user reselects before this one resolves. If *generation* no longer
        matches MainWindow's current probe generation, the result is
        discarded — otherwise a stale probe could advance the wizard for a
        device the user already navigated away from, corrupting the Connect
        step's completed/checkmark state.

        Args:
            prober: The CapabilityProber for the device this probe targets.
            generation: Snapshot of the probe-generation counter at selection time.
        """
        assert self._bridge is not None
        caps = await prober.probe()
        if generation != self._probe_generation:
            logger.debug(
                "Discarding stale capability probe result (generation %d, current %d)",
                generation,
                self._probe_generation,
            )
            return
        self._bridge.capabilities_ready.emit(caps)

    # ------------------------------------------------------------------
    # Workflow: File Import
    # ------------------------------------------------------------------

    def import_file(self, path: str) -> None:
        """Trigger a single-file (stereo) REW import."""
        assert self._bridge is not None
        assert self._bridge_wrapper is not None
        self._bridge.run_async(self._bridge_wrapper("file_import", self._do_file_import(path)))

    async def _do_file_import(self, path: str) -> None:
        """Parse a REW EQ text file and populate filters.

        Calls REWParser.parse_file_with_rows() for full result including
        skipped bands. Stores filters in wizard state, shows warnings if any.

        Args:
            path: Path to the REW text file.
        """
        from src.translator.rew_parser import REWParser

        assert self._bridge is not None
        assert self._wizard_controller is not None

        file_path = Path(path)
        parser = REWParser()
        filters, warnings, rows, notes = parser.parse_file_with_rows(file_path)

        # Store in wizard state — explicitly set Stereo channel mode (smoke #72)
        state = self._wizard_controller.state
        state.current_filters = filters
        state.channel_mode = ChannelMode.STEREO
        state.pending_rows = rows
        state.pending_conversion_notes = notes
        state.filters_origin = f"Imported from REW file: {file_path.name}"

        # Notify FiltersPage of success via peq_ready signal
        self._bridge.peq_ready.emit(filters)

        # If there were skipped/unsupported bands, show info message
        if warnings:
            skip_count = len(warnings)
            self._bridge.progress_update.emit(
                f"{len(filters)} filters loaded, {skip_count} unsupported band(s) skipped"
            )

    def import_file_lr(self, path_l: str, path_r: str) -> None:
        """Trigger an L/R (two-file) REW import."""
        assert self._bridge is not None
        assert self._bridge_wrapper is not None
        self._bridge.run_async(
            self._bridge_wrapper("file_import_lr", self._do_file_import_lr(path_l, path_r))
        )

    async def _do_file_import_lr(self, path_l: str, path_r: str) -> None:
        """Parse two REW EQ text files as L/R channels.

        Parses each file independently, combines into a flat filter list (L+R),
        and sets channel_mode to "L/R" in wizard state.

        Args:
            path_l: Path to the left channel REW text file.
            path_r: Path to the right channel REW text file.
        """
        from src.translator.rew_parser import REWParser

        assert self._bridge is not None
        assert self._wizard_controller is not None

        parser = REWParser()
        filters_l, warnings_l, rows_l, notes_l = parser.parse_file_with_rows(Path(path_l))
        filters_r, warnings_r, rows_r, notes_r = parser.parse_file_with_rows(Path(path_r))

        # Combine L+R into flat list and set L/R channel mode
        filters = filters_l + filters_r
        state = self._wizard_controller.state
        state.current_filters = filters
        state.channel_mode = ChannelMode.LR
        state.pending_rows_l = rows_l
        state.pending_rows_r = rows_r
        state.pending_conversion_notes_l = notes_l
        state.pending_conversion_notes_r = notes_r
        state.filters_origin = (
            f"Imported from REW files: L={Path(path_l).name}, R={Path(path_r).name}"
        )

        # Emit peq_ready with a pseudo-PEQSettings-like object carrying L/R bands
        peq_data = PEQSettings(
            source_name=state.primary_source,
            channel_mode=ChannelMode.LR,
            bands_l=filters_l,
            bands_r=filters_r,
        )
        self._bridge.peq_ready.emit(peq_data)

        total_warnings = len(warnings_l) + len(warnings_r)
        if total_warnings:
            self._bridge.progress_update.emit(
                f"L/R import: Left {len(filters_l)} bands ({len(warnings_l)} skipped), "
                f"Right {len(filters_r)} bands ({len(warnings_r)} skipped)"
            )

    # ------------------------------------------------------------------
    # Workflow: List Device Presets
    # ------------------------------------------------------------------

    def list_presets(self) -> None:
        """Trigger a fire-and-forget presets refresh; results arrive via signals.

        Used by MainWindow's bridge-wrapped dispatch point
        (_load_device_presets). _do_delete_presets, which needs to await
        the refresh inline as part of its own coroutine, calls
        refresh_presets() directly instead — see that method's docstring.
        """
        assert self._bridge is not None
        assert self._bridge_wrapper is not None
        self._bridge.run_async(self._bridge_wrapper("list_presets", self.refresh_presets()))

    async def refresh_presets(self) -> None:
        """Fetch device PEQ preset list and RoomFit profiles, emit as signals.

        The PEQ and RoomFit fetches are fully independent of each other, so
        they run concurrently (#174) instead of one blocking the other —
        each emits its own signal(s) the moment it resolves, rather than
        waiting to combine both into one result (see class docstring).

        Public (no leading underscore) because it's awaited directly from
        two places: list_presets() above (fire-and-forget dispatch) and
        MainWindow._do_delete_presets (which awaits it inline, mid-coroutine,
        to refresh the view after a delete — unwrapped by bridge_wrapper
        there, exactly as before this method moved).
        """
        assert self._current_adapter is not None
        assert self._wizard_controller is not None
        wiim_adapter = self._current_adapter

        source_name = self._wizard_controller.state.primary_source
        from src.gui.views.presets_device_view import PresetItem

        async def _fetch_peq() -> None:
            try:
                if wiim_adapter.capabilities.supports_profile_enumeration:
                    peq_presets = await wiim_adapter.list_peq_profiles(source_name)
                    peq_items = [
                        PresetItem(
                            name=p.get("Name", "Unnamed"),
                            preset_type="PEQ",
                            channel_mode=p.get("channelMode", "Stereo"),
                        )
                        for p in peq_presets
                    ]
                    # read_peq() is a plain, harmless read, unlike
                    # load_peq_profile()/EQv2SourceLoad.
                    active_peq_name = await self._read_active_name_or_default(
                        self._peq_name_for_highlight(source_name),
                        "Failed to read active PEQ preset name",
                    )
                    self.peq_presets_ready.emit(peq_items, active_peq_name)
                else:
                    self.peq_presets_unavailable.emit()
            except Exception:
                logger.warning("Failed to list PEQ presets", exc_info=True)
                self.peq_presets_unavailable.emit()

        async def _fetch_roomfit() -> None:
            try:
                if wiim_adapter.capabilities.supports_roomfit:
                    rf_profiles = await wiim_adapter.list_roomfit_profiles(source_name)
                    rf_items = [
                        PresetItem(
                            name=p.get("Name", "Unnamed"),
                            preset_type="RoomFit",
                            channel_mode=p.get("channelMode", "Stereo"),
                        )
                        for p in rf_profiles
                    ]
                    active_roomfit_name = await self._read_active_name_or_default(
                        self._roomfit_name_for_highlight(),
                        "Failed to read active RoomFit profile name",
                    )
                    self.roomfit_profiles_ready.emit(rf_items, active_roomfit_name)
                else:
                    self.roomfit_profiles_hidden.emit()
            except Exception:
                logger.warning("Failed to list RoomFit profiles", exc_info=True)
                self.roomfit_profiles_hidden.emit()

        await asyncio.gather(_fetch_peq(), _fetch_roomfit())

    async def _read_active_name_or_default(
        self, coro: Coroutine[Any, Any, Any], log_msg: str
    ) -> str:
        """Await a read whose only purpose is an active-item name for
        highlighting (#165c) -- a failure here means no highlight, not a
        failed view, so it degrades to "" rather than propagating."""
        try:
            return str(await coro)
        except Exception:
            logger.warning(log_msg, exc_info=True)
            return ""

    async def _peq_name_for_highlight(self, source_name: str) -> str:
        """The active PEQ preset's name, for #165c highlighting."""
        assert self._current_adapter is not None
        return (await self._current_adapter.read_peq(source_name)).name

    async def _roomfit_name_for_highlight(self) -> str:
        """The active RoomFit profile's name, for #165c highlighting."""
        assert self._current_adapter is not None
        _enabled, active_roomfit_name = await self._current_adapter.get_roomfit_status()
        return active_roomfit_name
