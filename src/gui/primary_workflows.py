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

from src.gui.shared_helpers import extract_filters, is_lr_mode, read_preset_preview
from src.models.channel_mode import ChannelMode
from src.models.peq import PEQSettings
from src.models.profile import build_profile

if TYPE_CHECKING:
    from src.adapters.capability_prober import CapabilityProber
    from src.adapters.rew_http_client import REWHttpApiClient
    from src.adapters.wiim_adapter import WiiMAdapter
    from src.discovery.discovery_module import DiscoveryModule
    from src.gui.async_bridge import AsyncBridge
    from src.gui.wizard_controller import WizardController, WizardState
    from src.models.canonical import CanonicalFilter
    from src.models.capabilities import DeviceInfo
    from src.repository.profile_repository import ProfileRepository

logger = logging.getLogger("wiim_rew_sync.primary_workflows")

# Signature of MainWindow._bridge_wrapper, injected via configure() rather
# than reimplemented here — see configure()'s docstring for why.
BridgeWrapper = Callable[[str, "Coroutine[Any, Any, Any]"], "Coroutine[Any, Any, None]"]


class EmptyPresetFiltersError(Exception):
    """A device preset resolved to zero filters when read for export/save.

    Raised instead of touching a widget directly (this manager has none) so
    it flows through the injected bridge_wrapper's existing error-mapping
    path (see MainWindow._map_error) to reach the status banner.
    """


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

        name_profiles_ready(list, str, bool): RoomFit profile-name list +
            active profile name + whether RoomFit is currently on, mirrors
            NameProfilePage.set_existing_profiles() plus MainWindow's
            _roomfit_enabled attribute. Distinct from roomfit_profiles_ready
            above despite the similar name — that one already feeds
            PresetsDeviceView with a different payload shape (PresetItem
            objects, no enabled flag); reusing it here would misroute data.
        filters_roomfit_profiles_ready(list): RoomFit profile-name list,
            mirrors FiltersPage.set_roomfit_profiles() (no active name or
            enabled flag — that page's dropdown doesn't need either).
        presets_delete_complete(int, int): succeeded/failed counts from a
            delete_presets() batch. delete_presets() is otherwise a normal
            _dispatch()-based entry point, but its two completion paths
            (success, partial-failure) both used to call
            MainWindow._status_banner directly rather than raising an
            exception (partial failure isn't an error condition
            _bridge_wrapper's mapping fits), so it needs a signal instead.
    """

    peq_presets_ready = Signal(list, str)
    peq_presets_unavailable = Signal()
    roomfit_profiles_ready = Signal(list, str)
    roomfit_profiles_hidden = Signal()
    name_profiles_ready = Signal(list, str, bool)
    filters_roomfit_profiles_ready = Signal(list)
    presets_delete_complete = Signal(int, int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bridge: AsyncBridge | None = None
        self._discovery_module: DiscoveryModule | None = None
        self._wizard_controller: WizardController | None = None
        self._bridge_wrapper: BridgeWrapper | None = None
        self._rew_client: REWHttpApiClient | None = None
        self._profile_repository: ProfileRepository | None = None
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
        rew_client: REWHttpApiClient,
        profile_repository: ProfileRepository,
    ) -> None:
        """Inject dependencies for workflow execution.

        Called eagerly from MainWindow.__init__, right after the wizard
        controller is constructed — unlike SecondaryWorkflowManager, these
        dependencies are all available before a device is selected; the
        (smaller) set of methods that additionally need a live device
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
            rew_client: Shared REWHttpApiClient instance, for REW measurement
                listing/filter reads.
            profile_repository: Shared ProfileRepository instance, for saving
                device presets into local storage.
        """
        self._bridge = bridge
        self._discovery_module = discovery_module
        self._wizard_controller = wizard_controller
        self._bridge_wrapper = bridge_wrapper
        self._rew_client = rew_client
        self._profile_repository = profile_repository
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

    def _require_rew_client(self) -> REWHttpApiClient:
        """Return the REW HTTP API client, asserting it's configured.

        Shared by the three REW-workflow methods below — each used to
        repeat this same assert.
        """
        assert self._rew_client is not None
        return self._rew_client

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

    # ------------------------------------------------------------------
    # Workflow: REW Measurements (Phase 3)
    # ------------------------------------------------------------------

    def list_rew_measurements(self) -> None:
        """Trigger a REW measurement list fetch; results arrive via signals."""
        self._dispatch("rew_list", self._do_rew_list_measurements())

    async def _do_rew_list_measurements(self) -> None:
        """List available measurements from REW API.

        Calls REWHttpApiClient.list_measurements() and emits the result.
        If empty, emits an info message instead of the measurement list.
        """
        assert self._bridge is not None
        rew_client = self._require_rew_client()

        measurements = await rew_client.list_measurements()

        if not measurements:
            self._bridge.progress_update.emit(
                "__info__No measurements found in REW. "
                "Load or import measurement(s) in REW's Measurements pane, then try again."
            )
            return

        # Emit measurement list for the picker dialog
        self._bridge.rew_measurements_ready.emit(measurements)

    def get_rew_filters(self, uuid: str, measurement_name: str = "") -> None:
        """Trigger a REW filter fetch for one measurement; result arrives via signal."""
        self._dispatch("rew_filters", self._do_rew_get_filters(uuid, measurement_name))

    async def _do_rew_get_filters(self, uuid: str, measurement_name: str = "") -> None:
        """Fetch filters for a specific REW measurement.

        Calls REWHttpApiClient.get_filters(uuid), stores in wizard state,
        and emits result signal.

        Args:
            uuid: The measurement UUID selected by the user.
            measurement_name: Display name of the measurement, for the
                Filters step tooltip (#162d) -- referenced by UUID for the
                actual fetch since names aren't stable identifiers.
        """
        assert self._bridge is not None
        rew_client = self._require_rew_client()
        state = self._require_wizard_state()

        filters, rows, notes = await rew_client.get_filters_with_rows(uuid)

        # Store in wizard state
        state.current_filters = filters
        state.channel_mode = ChannelMode.STEREO
        state.pending_rows = rows
        state.pending_conversion_notes = notes
        state.filters_origin = f"Pulled from REW measurement: {measurement_name}"

        # Emit result signal
        self._bridge.rew_filters_ready.emit(filters)

    def get_rew_filters_lr(
        self,
        uuid_l: str,
        uuid_r: str,
        measurement_name_l: str = "",
        measurement_name_r: str = "",
    ) -> None:
        """Trigger a REW filter fetch for L/R measurements; result arrives via signal."""
        self._dispatch(
            "rew_filters_lr",
            self._do_rew_get_filters_lr(uuid_l, uuid_r, measurement_name_l, measurement_name_r),
        )

    async def _do_rew_get_filters_lr(
        self,
        uuid_l: str,
        uuid_r: str,
        measurement_name_l: str = "",
        measurement_name_r: str = "",
    ) -> None:
        """Fetch filters for Left and Right REW measurements.

        Calls get_filters for each UUID, combines into L+R format,
        and emits peq_ready with the combined result.

        Args:
            uuid_l: UUID of the Left channel measurement.
            uuid_r: UUID of the Right channel measurement.
            measurement_name_l: Display name of the Left measurement, for
                the Filters step tooltip (#162d).
            measurement_name_r: Display name of the Right measurement.
        """
        from src.translator._warnings import SkippedBand

        assert self._bridge is not None
        rew_client = self._require_rew_client()
        state = self._require_wizard_state()

        filters_l, rows_l, notes_l = await rew_client.get_filters_with_rows(uuid_l)
        filters_r, rows_r, notes_r = await rew_client.get_filters_with_rows(uuid_r)

        # Combine L+R into flat list and set L/R channel mode
        filters = filters_l + filters_r
        state.current_filters = filters
        state.channel_mode = ChannelMode.LR
        state.pending_rows_l = rows_l
        state.pending_rows_r = rows_r
        state.pending_conversion_notes_l = notes_l
        state.pending_conversion_notes_r = notes_r
        state.filters_origin = (
            f"Pulled from REW measurements: L={measurement_name_l}, R={measurement_name_r}"
        )

        # Emit peq_ready with a PEQSettings carrying L/R bands
        peq_data = PEQSettings(
            source_name=state.primary_source,
            channel_mode=ChannelMode.LR,
            bands_l=filters_l,
            bands_r=filters_r,
        )
        self._bridge.peq_ready.emit(peq_data)

        skipped_l = sum(1 for r in rows_l if isinstance(r, SkippedBand))
        skipped_r = sum(1 for r in rows_r if isinstance(r, SkippedBand))
        if skipped_l or skipped_r:
            self._bridge.progress_update.emit(
                f"L/R import: Left {len(filters_l)} bands ({skipped_l} skipped), "
                f"Right {len(filters_r)} bands ({skipped_r} skipped)"
            )

    # ------------------------------------------------------------------
    # Workflow: Preset Export/Save (Phase 3)
    # ------------------------------------------------------------------

    def export_preset(self, preset_name: str, preset_type: str, path: str) -> None:
        """Trigger a device preset export to file; progress arrives via progress_update."""
        self._dispatch(
            "preset_export", self._do_preset_export(preset_name, preset_type, path)
        )

    async def _do_preset_export(
        self, preset_name: str, preset_type: str, path: str
    ) -> None:
        """Read a preset from device and export as REW file.

        For L/R mode, generates two files (_L.txt and _R.txt) from the base path.

        Args:
            preset_name: Name of the preset to export.
            preset_type: "PEQ" or "RoomFit".
            path: Destination file path.

        Raises:
            EmptyPresetFiltersError: if the preset resolves to zero filters
                (mapped to a status-banner error by MainWindow._map_error).
        """
        from src.translator.rew_generator import REWGenerator

        assert self._bridge is not None
        wiim_adapter = self._require_adapter()
        state = self._require_wizard_state()
        source_name = state.primary_source

        # Read preset filters from device (previewing + restoring -- the
        # confirmation dialog in _on_preset_export_requested already warned
        # the user this briefly changes what's playing, see #166)
        peq_settings = await read_preset_preview(
            wiim_adapter, preset_type, source_name, preset_name
        )

        generator = REWGenerator()
        file_path = Path(path)

        # Ensure .txt extension
        if file_path.suffix.lower() != ".txt":
            file_path = file_path.with_suffix(".txt")

        if is_lr_mode(peq_settings.channel_mode):
            # L/R mode: generate two files
            filters_l = peq_settings.bands_l or []
            filters_r = peq_settings.bands_r or []

            if not filters_l and not filters_r:
                raise EmptyPresetFiltersError(
                    f"Preset '{preset_name}' has no filters to export"
                )

            left_path = file_path.with_stem(file_path.stem + "_L")
            right_path = file_path.with_stem(file_path.stem + "_R")
            warnings_l = generator.generate_file(filters_l, left_path)
            warnings_r = generator.generate_file(filters_r, right_path)
            total_warnings = len(warnings_l) + len(warnings_r)

            if total_warnings:
                self._bridge.progress_update.emit(
                    f"Exported '{preset_name}' L/R ({total_warnings} band(s) skipped)"
                )
            else:
                self._bridge.progress_update.emit(
                    f"Exported '{preset_name}' as {left_path.name} and {right_path.name}"
                )
        else:
            # Stereo mode: single file
            filters = peq_settings.bands
            if not filters:
                raise EmptyPresetFiltersError(
                    f"Preset '{preset_name}' has no filters to export"
                )

            warnings = generator.generate_file(filters, file_path)
            if warnings:
                self._bridge.progress_update.emit(
                    f"Exported '{preset_name}' ({len(warnings)} band(s) skipped)"
                )
            else:
                self._bridge.progress_update.emit(
                    f"Exported '{preset_name}' to {file_path.name}"
                )

    def save_preset(self, preset_name: str, preset_type: str, saved_name: str) -> None:
        """Trigger a device preset save to local storage; progress arrives via progress_update."""
        self._dispatch(
            "preset_save", self._do_preset_save(preset_name, preset_type, saved_name)
        )

    async def _do_preset_save(
        self, preset_name: str, preset_type: str, saved_name: str
    ) -> None:
        """Read a preset from device and save to local profile repository.

        Uses build_profile helper for consistent Profile construction.
        Note: the helper is safe to call here because AsyncBridge signals
        are delivered via QueuedConnection (thread-safe).

        Args:
            preset_name: Name of the preset to read from the device --
                the exact on-device identifier, never prefixed.
            preset_type: "PEQ" or "RoomFit".
            saved_name: Name for the resulting local Profile (device-name
                prefixed by the caller); independent of preset_name so the
                device read always uses the real on-device preset name.

        Raises:
            EmptyPresetFiltersError: if the preset resolves to zero filters
                (mapped to a status-banner error by MainWindow._map_error).
        """
        assert self._bridge is not None
        assert self._profile_repository is not None
        wiim_adapter = self._require_adapter()
        state = self._require_wizard_state()
        source_name = state.primary_source

        # Read preset filters from device (previewing + restoring -- the
        # confirmation dialog in _on_preset_save_requested already warned the
        # user this briefly changes what's playing, see #166)
        peq_settings = await read_preset_preview(
            wiim_adapter, preset_type, source_name, preset_name
        )

        # Determine channel mode and filter list
        filters, channel_mode = extract_filters(peq_settings)

        if not filters:
            raise EmptyPresetFiltersError(
                f"Preset '{preset_name}' has no filters to save"
            )

        # Save directly (Profile construction + file write is thread-safe)
        # For L/R, pass explicit channel lists from peq_settings
        profile = build_profile(
            saved_name, filters, channel_mode,
            filters_l=peq_settings.bands_l,
            filters_r=peq_settings.bands_r,
        )

        self._profile_repository.save(profile)
        # UI updates via progress_update signal (thread-safe)
        self._bridge.progress_update.emit(
            f"Saved '{profile.name}' to My Presets"
        )

    # ------------------------------------------------------------------
    # Workflow: RoomFit Dropdown Population (Phase 4)
    # ------------------------------------------------------------------

    def populate_name_profiles(self) -> None:
        """Trigger a NameProfilePage profile-list refresh; result arrives via signal."""
        self._dispatch("list_roomfit_for_naming", self._do_populate_name_profiles())

    async def _do_populate_name_profiles(self) -> None:
        """Fetch RoomFit profiles and emit name_profiles_ready for NameProfilePage."""
        assert self._bridge is not None
        wiim_adapter = self._require_adapter()
        state = self._require_wizard_state()
        source_name = state.primary_source

        try:
            if wiim_adapter.capabilities.supports_roomfit:
                profiles = await wiim_adapter.list_roomfit_profiles(source_name)
                profile_names = [p.get("Name", "") for p in profiles if p.get("Name")]
                try:
                    roomfit_enabled, active_profile = await wiim_adapter.get_roomfit_status()
                except Exception:
                    roomfit_enabled, active_profile = False, ""
                    logger.warning(
                        "Failed to read RoomFit active-profile status", exc_info=True
                    )
                self.name_profiles_ready.emit(profile_names, active_profile, roomfit_enabled)
            else:
                self.name_profiles_ready.emit([], "", False)
        except Exception:
            logger.warning("Failed to list RoomFit profiles for naming", exc_info=True)
            self.name_profiles_ready.emit([], "", False)

    def refresh_roomfit_dropdown(self) -> None:
        """Trigger a FiltersPage RoomFit-dropdown refresh; result arrives via signal."""
        self._dispatch("list_roomfit", self._do_list_roomfit_profiles())

    async def _do_list_roomfit_profiles(self) -> None:
        """Fetch RoomFit profile names and emit filters_roomfit_profiles_ready
        for FiltersPage."""
        assert self._bridge is not None
        wiim_adapter = self._require_adapter()
        state = self._require_wizard_state()
        source_name = state.primary_source

        try:
            if wiim_adapter.capabilities.supports_roomfit:
                profiles = await wiim_adapter.list_roomfit_profiles(source_name)
                profile_names = [p.get("Name", "") for p in profiles if p.get("Name")]
                self.filters_roomfit_profiles_ready.emit(profile_names)
            else:
                self.filters_roomfit_profiles_ready.emit([])
        except Exception:
            logger.warning("Failed to list RoomFit profiles for dropdown", exc_info=True)
            self.filters_roomfit_profiles_ready.emit([])

    # ------------------------------------------------------------------
    # Workflow: Delete Presets (Phase 5)
    # ------------------------------------------------------------------

    def delete_presets(self, items: list[Any]) -> None:
        """Trigger a device preset batch delete; result arrives via signal."""
        self._dispatch("delete_presets", self._do_delete_presets(items))

    async def _do_delete_presets(self, items: list[Any]) -> None:
        """Delete selected PEQ presets / RoomFit profiles from the device.

        Dispatches per item on preset_type to delete_peq_profile or
        delete_roomfit_profile. One item's failure doesn't abort the rest;
        the view is refreshed afterward regardless of partial failure.

        Args:
            items: List of PresetItem objects to delete.
        """
        assert self._bridge is not None
        wiim_adapter = self._require_adapter()
        succeeded = 0
        failed = 0

        for item in items:
            name = getattr(item, "name", "")
            preset_type = getattr(item, "preset_type", "PEQ")
            if not name:
                continue
            try:
                if preset_type == "RoomFit":
                    await wiim_adapter.delete_roomfit_profile(name)
                else:
                    await wiim_adapter.delete_peq_profile(name)
                succeeded += 1
            except Exception:
                logger.exception("Delete preset '%s' (%s) failed", name, preset_type)
                failed += 1

        await self.refresh_presets()
        self.presets_delete_complete.emit(succeeded, failed)
