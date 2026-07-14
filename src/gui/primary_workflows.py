"""Primary workflow orchestration: discovery, probing, file import/export,
device/preset reads, and device presets listing.

Phases 1-2 of the MainWindow god-object extraction (docs/backlog.md item 2):
moves `_do_*` methods out of MainWindow into a dedicated QObject manager,
following the pattern established by SecondaryWorkflowManager
(src/gui/secondary_workflows.py) — no direct Qt widget access, dependencies
injected via configure(), workflow results delivered as signals: mostly via
AsyncBridge's existing signals directly (none of these methods declare a new
signal of their own for that), except `list_presets()`/`refresh_presets()`,
which owns four signals of its own (see class docstring) since it used to
write directly to a view widget.

`configure()` is called eagerly from MainWindow.__init__, since discovery/
probing/file-import/export need no live device adapter; the methods that do
(`pull_device`, `pull_roomfit`, `load_peq_preset`, `list_presets`/
`refresh_presets`) instead wait on `set_current_adapter()`, called once a
device is selected and probed — mirroring `SecondaryWorkflowManager`.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Signal

from src.gui.shared_helpers import extract_filters, is_lr_mode
from src.models.channel_mode import ChannelMode
from src.models.peq import PEQSettings

if TYPE_CHECKING:
    from src.adapters.capability_prober import CapabilityProber
    from src.adapters.wiim_adapter import WiiMAdapter
    from src.discovery.discovery_module import DiscoveryModule
    from src.gui.async_bridge import AsyncBridge
    from src.gui.wizard_controller import WizardController, WizardState
    from src.models.canonical import CanonicalFilter
    from src.models.capabilities import DeviceInfo

logger = logging.getLogger("wiim_rew_sync.primary_workflows")

# Signature of MainWindow._bridge_wrapper, injected via configure() rather
# than reimplemented here — see configure()'s docstring for why.
BridgeWrapper = Callable[[str, "Coroutine[Any, Any, Any]"], "Coroutine[Any, Any, None]"]


class PrimaryWorkflowManager(QObject):
    """Orchestrates primary wizard workflows: discovery, probing, file
    import/export, device/preset reads, and device presets listing.

    This manager coordinates most of MainWindow's `_do_*` methods. It does
    NOT perform direct network calls itself for discovery (that's
    DiscoveryModule), file I/O (that's REWParser/REWGenerator), or device
    reads (that's WiiMAdapter); it just relocates the existing orchestration
    bodies verbatim out of MainWindow.

    Results are delivered via AsyncBridge's existing signals
    (discovery_progress, discovery_complete, capabilities_ready, peq_ready,
    progress_update) — this manager declares no new signals of its own for
    those workflows, so MainWindow's existing `_on_*` slot connections need
    no rewiring. list_presets()/refresh_presets() is the exception: it
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
        controller is constructed — unlike SecondaryWorkflowManager, these
        four dependencies are all available before a device is selected;
        the (smaller) set of methods that additionally need a live device
        adapter get it separately via set_current_adapter().

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
        SecondaryWorkflowManager.set_current_adapter). Used by every
        workflow here that reads the live device: pull_device, pull_roomfit,
        load_peq_preset, and list_presets/refresh_presets.

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

    def _dispatch(self, operation_name: str, coro: Coroutine[Any, Any, Any]) -> None:
        """Run a coroutine on the bridge, wrapped for error mapping.

        Shared by every fire-and-forget entry point below — each one used to
        repeat this same assert/assert/run_async line; consolidated here
        once enough of them existed to justify it.
        """
        assert self._bridge is not None
        assert self._bridge_wrapper is not None
        self._bridge.run_async(self._bridge_wrapper(operation_name, coro))

    def _require_adapter(self) -> WiiMAdapter:
        """Return the current device adapter, asserting it's set.

        Shared by every method below that needs a live device — each used
        to repeat this same assert.
        """
        assert self._current_adapter is not None
        return self._current_adapter

    def _require_wizard_state(self) -> WizardState:
        """Return the wizard's mutable state, asserting the controller is set.

        Shared by every method below that reads/writes wizard state — each
        used to repeat this same assert.
        """
        assert self._wizard_controller is not None
        return self._wizard_controller.state

    # ------------------------------------------------------------------
    # Workflow: Discovery
    # ------------------------------------------------------------------

    def discover(self) -> None:
        """Trigger device discovery; results arrive via the bridge's discovery signals."""
        self._dispatch("discovery", self._do_discovery())

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
        self._dispatch("capability_probe", self._do_probe(prober, generation))

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
        self._dispatch("file_import", self._do_file_import(path))

    async def _do_file_import(self, path: str) -> None:
        """Parse a REW EQ text file and populate filters.

        Calls REWParser.parse_file_with_rows() for full result including
        skipped bands. Stores filters in wizard state, shows warnings if any.

        Args:
            path: Path to the REW text file.
        """
        from src.translator.rew_parser import REWParser

        assert self._bridge is not None

        file_path = Path(path)
        parser = REWParser()
        filters, warnings, rows, notes = parser.parse_file_with_rows(file_path)

        # Store in wizard state — explicitly set Stereo channel mode (smoke #72)
        state = self._require_wizard_state()
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
        self._dispatch("file_import_lr", self._do_file_import_lr(path_l, path_r))

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

        parser = REWParser()
        filters_l, warnings_l, rows_l, notes_l = parser.parse_file_with_rows(Path(path_l))
        filters_r, warnings_r, rows_r, notes_r = parser.parse_file_with_rows(Path(path_r))

        # Combine L+R into flat list and set L/R channel mode
        filters = filters_l + filters_r
        state = self._require_wizard_state()
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
        self._dispatch("list_presets", self.refresh_presets())

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
        wiim_adapter = self._require_adapter()
        source_name = self._require_wizard_state().primary_source
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
        return (await self._require_adapter().read_peq(source_name)).name

    async def _roomfit_name_for_highlight(self) -> str:
        """The active RoomFit profile's name, for #165c highlighting."""
        _enabled, active_roomfit_name = await self._require_adapter().get_roomfit_status()
        return active_roomfit_name

    # ------------------------------------------------------------------
    # Workflow: Device / Preset Reads (Phase 2)
    # ------------------------------------------------------------------

    def pull_device(self) -> None:
        """Trigger a pull-from-device; result arrives via peq_ready."""
        self._dispatch("device_pull", self._do_device_pull())

    async def _do_device_pull(self) -> None:
        """Pull PEQ settings from the connected device.

        Reads PEQ bands via WiiMAdapter, converts to CanonicalFilter list,
        stores in wizard state, and emits result signal.
        """
        assert self._bridge is not None
        wiim_adapter = self._require_adapter()
        state = self._require_wizard_state()
        source_name = state.primary_source

        peq_settings = await wiim_adapter.read_peq(source_name)

        # Extract filters based on channel mode
        filters, _ = extract_filters(peq_settings)

        # Store in wizard state
        state.current_filters = filters
        state.device_filters = filters
        state.filters_origin = f"Pulled from device (source: {source_name})"

        # Emit result signal
        self._bridge.peq_ready.emit(peq_settings)

    def pull_roomfit(self, profile_name: str, operation_name: str = "roomfit_pull") -> None:
        """Trigger a RoomFit profile pull; result arrives via peq_ready.

        Args:
            profile_name: Name of the RoomFit profile to read.
            operation_name: Log-context label for _bridge_wrapper — this
                coroutine has two real callers today (selecting a RoomFit
                profile in the Filters step vs. loading a preset from a
                presets list), which want distinct labels in the failure
                log even though the underlying read is identical.
        """
        self._dispatch(operation_name, self._do_roomfit_pull(profile_name))

    async def _do_roomfit_pull(self, profile_name: str) -> None:
        """Pull RoomFit profile filters from the device.

        Reads the named RoomFit profile via WiiMAdapter, stores filters
        in wizard state, and emits peq_ready to advance to Review.

        Args:
            profile_name: Name of the RoomFit profile to read.
        """
        assert self._bridge is not None
        wiim_adapter = self._require_adapter()
        state = self._require_wizard_state()
        source_name = state.primary_source

        peq_settings = await wiim_adapter.read_roomfit_preset_preview(
            source_name, profile_name
        )

        # Extract filters based on channel mode
        filters, _ = extract_filters(peq_settings)

        # Store in wizard state
        state.current_filters = filters
        state.device_filters = filters
        state.filters_origin = f"RoomFit profile: {profile_name}"

        # Emit result signal (triggers _on_peq_ready -> Review page)
        self._bridge.peq_ready.emit(peq_settings)

    def load_peq_preset(self, preset_name: str) -> None:
        """Trigger a named PEQ preset load; result arrives via peq_ready."""
        self._dispatch("load_preset", self._do_load_peq_preset(preset_name))

    async def _do_load_peq_preset(self, preset_name: str) -> None:
        """Load a named PEQ preset from device and emit peq_ready.

        Loads the preset via EQv2SourceLoad then reads the resulting bands,
        then restores the source's original active preset (#166) -- the
        confirmation dialog in _on_preset_load_into_editor already warned the
        user this briefly changes what's playing. Sets channel_mode in wizard
        state from the device response to avoid stale L/R state from a
        previous load (smoke #111).

        Args:
            preset_name: Name of the PEQ preset to load.
        """
        assert self._bridge is not None
        wiim_adapter = self._require_adapter()
        state = self._require_wizard_state()
        source_name = state.primary_source

        peq_settings = await wiim_adapter.read_peq_preset_preview(
            source_name, preset_name
        )

        # Determine channel_mode from the device data and update wizard state
        peq_channel = getattr(peq_settings, "channel_mode", None)
        if is_lr_mode(peq_channel) if peq_channel else False:
            state.channel_mode = ChannelMode.LR
        else:
            state.channel_mode = ChannelMode.STEREO

        # Extract filters
        filters, _ = extract_filters(peq_settings)

        # Store in wizard state
        state.current_filters = filters
        state.device_filters = filters
        state.filters_origin = f"PEQ preset: {preset_name}"

        # Emit result signal
        self._bridge.peq_ready.emit(peq_settings)

    # ------------------------------------------------------------------
    # Workflow: Export to File (Phase 2)
    # ------------------------------------------------------------------

    def export_file(self, filters: list[CanonicalFilter], path: str) -> None:
        """Trigger a stereo REW file export; progress arrives via progress_update."""
        self._dispatch("export", self._do_export(filters, path))

    async def _do_export(self, filters: list[CanonicalFilter], path: str) -> None:
        """Generate a REW EQ text file from current filters.

        Calls REWGenerator.generate_file() and emits progress_update with
        success message. Includes skip count if any bands were skipped.

        Args:
            filters: List of CanonicalFilter objects to export.
            path: Destination file path chosen by the user.
        """
        from src.translator.rew_generator import REWGenerator

        assert self._bridge is not None

        generator = REWGenerator()
        file_path = Path(path)
        warnings = generator.generate_file(filters, file_path)

        if warnings:
            skip_count = len(warnings)
            self._bridge.progress_update.emit(
                f"File exported successfully ({skip_count} unsupported band(s) skipped)"
            )
        else:
            self._bridge.progress_update.emit("File exported successfully")

    def export_file_lr(
        self,
        filters_l: list[CanonicalFilter],
        filters_r: list[CanonicalFilter],
        path_l: Path,
        path_r: Path,
    ) -> None:
        """Trigger an L/R REW file export; progress arrives via progress_update."""
        self._dispatch("export_lr", self._do_export_lr(filters_l, filters_r, path_l, path_r))

    async def _do_export_lr(
        self,
        filters_l: list[CanonicalFilter],
        filters_r: list[CanonicalFilter],
        path_l: Path,
        path_r: Path,
    ) -> None:
        """Generate two REW EQ text files for L/R channel mode (smoke #29).

        Uses REWGenerator.generate_file() for each channel independently.

        Args:
            filters_l: Left channel CanonicalFilter list.
            filters_r: Right channel CanonicalFilter list.
            path_l: Destination path for left channel file.
            path_r: Destination path for right channel file.
        """
        from src.translator.rew_generator import REWGenerator

        assert self._bridge is not None

        generator = REWGenerator()
        warnings_l = generator.generate_file(filters_l, path_l)
        warnings_r = generator.generate_file(filters_r, path_r)

        total_warnings = len(warnings_l) + len(warnings_r)
        if total_warnings:
            self._bridge.progress_update.emit(
                f"L/R files exported ({total_warnings} unsupported band(s) skipped)"
            )
        else:
            self._bridge.progress_update.emit(
                f"L/R files exported: {path_l.name} and {path_r.name}"
            )
