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
import json
import logging
from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from PySide6.QtCore import QObject, Signal

from src.adapters.safe_write import WriteResult, restore_entries
from src.gui.wizard_controller import FlowType
from src.models.channel_mode import (
    ChannelMode,
    is_lr_mode,
    require_lr_filters,
    resolve_roomfit_channel_kwargs,
)
from src.models.errors import BackupError, WiiMConnectionError, WiiMResponseError
from src.models.peq import PEQSettings, build_peq_settings, extract_filters
from src.models.profile import build_profile
from src.repository.backup_manager import encode_multi_source_backup_paths
from src.utils.paths import ensure_suffix

if TYPE_CHECKING:
    from src.adapters.capability_prober import CapabilityProber
    from src.adapters.rew_http_client import REWHttpApiClient
    from src.adapters.safe_write import RoomFitSafeWrite, SafeWrite
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


class _AbandonGuard:
    """Tracks whether a cancellable ``_do_*`` coroutine reached its own
    success emit, and fires *on_abandoned* in a ``finally`` if not --
    unless a genuine (non-cancellation) exception is propagating, since
    that's already reported through ``_bridge_wrapper``'s ``operation_error``
    emit.

    Every cancellable workflow that leaves some UI element in a "waiting"
    state (a pulsing device card, a scanning spinner, an embedded picker
    showing "Connecting...") needs this: cancellation (``asyncio.CancelledError``)
    and, for probe(), the pre-existing stale-generation-discard path both
    exit without reaching the workflow's own success emit -- and neither is
    caught by ``_bridge_wrapper``'s ``except Exception`` (``CancelledError``
    is a ``BaseException``, not caught there). Without an explicit
    abandonment signal, nothing would ever reset that UI element.

    A genuine ``Exception`` is deliberately excluded from firing
    *on_abandoned*: it's about to be turned into an ``operation_error``
    emit by ``_bridge_wrapper``, which already carries the real failure
    message. Firing *on_abandoned* too let its handler's "cancelled" /
    empty-state framing run first and clobber that real message (e.g.
    the embedded REW measurement picker showing "Measurement fetch
    cancelled." for what was actually a connection failure, because the
    abandonment handler cleared the picker reference the error handler
    needed). Any UI cleanup that must happen on error too (not just on
    cancellation) belongs in the operation_error handler itself, not here.

    Usage::

        async def _do_thing(self) -> None:
            with _AbandonGuard(self._bridge.thing_abandoned.emit) as guard:
                result = await ...
                self._bridge.thing_ready.emit(result)
                guard.succeeded = True
    """

    def __init__(self, on_abandoned: Callable[[], None]) -> None:
        self._on_abandoned = on_abandoned
        self.succeeded = False

    def __enter__(self) -> _AbandonGuard:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        if self.succeeded:
            return
        if exc_type is not None and issubclass(exc_type, Exception):
            return
        self._on_abandoned()


def _extract_profile_names(profiles: list[dict[str, Any]]) -> list[str]:
    """Extract non-empty "Name" values from a list_roomfit_profiles() result.

    Used by _do_populate_name_profiles, which needs the "Name" key with an
    empty-string skip for its downstream signal (round-4 review finding #9,
    2026-07-19).
    """
    return [p.get("Name", "") for p in profiles if p.get("Name")]


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
    declares four signals of its own (see below), each forwarded by
    MainWindow to both PresetsDeviceView and FiltersPage's merged Device
    panel, which share the same PresetItem-shaped data.

    Signals:
        peq_presets_ready(list, object, str, bool, str, bool): PEQ PresetItem list +
            active preset name + active preset's channel mode + whether PEQ
            (EQStat) is actually switched on for this source + the source
            name the list/active state was fetched for, mirrors
            PresetsDeviceView.set_peq_presets() and
            FiltersPage.set_peq_presets(). The channel mode and enabled flag
            travel alongside the name (rather than needing their own reads)
            because all three come from the same read_peq() call. The name
            is used to label the synthetic "Custom" row shown when it's ""
            (see presets_device_view.build_custom_peq_item); the enabled
            flag is used to qualify the active row's badge as
            "(active, PEQ off)" instead of plain "(active)" when a
            name/custom config is selected but PEQ itself is toggled off for
            that source (build_preset_list_item). The active name is
            `object`, not `str`, because it must carry `None` through the
            signal when the live-config read itself failed -- "unknown" is
            not the same thing as "" (confirmed no active preset), and only
            `object`-typed Qt signal args can carry None. The trailing
            source_name exists so both views can show which source's live
            state "Custom"/"(active)" reflects -- unlike RoomFit, PEQ is
            scoped per-source (`state.primary_source`), and neither view
            otherwise has a source picker of its own to make that scope
            visible (smoke test issue: Filters/Presets-on-Device "Custom"
            row looked like it reflected the device's active input rather
            than the wizard's selected source). The final bool is
            DeviceCapabilities.supports_profile_enumeration for this
            device -- when False, `peq_items` is always empty (there's no
            way to list saved presets at all) and build_peq_rows must
            surface the live config unconditionally (real name or
            "Custom") rather than only when active_name == "" (smoke test
            issue: a device with a *named* live config and no enumeration
            support showed an empty list, since "" was the only condition
            that ever produced a row).
        peq_presets_unavailable(): mirrors set_peq_unavailable(). Emitted
            when the device has no PEQ support at all, or the live-config
            read needed to confirm PEQ state failed outright (see
            _fetch_peq() below) -- never emitted just because named-preset
            enumeration is unsupported, since the live config can still be
            shown as a synthetic "Custom" row without it.
        roomfit_profiles_ready(list, str, bool): RoomFit PresetItem list +
            active profile name + whether RoomFit is actually switched on,
            mirrors set_roomfit_profiles() on both views. Same "(active,
            RoomFit off)" qualifier rationale as peq_presets_ready's enabled
            flag, above.
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
            above despite the similar name and now-shared enabled flag —
            that one feeds PresetsDeviceView/FiltersPage with a different
            payload shape (PresetItem objects, for the merged preset list)
            than this one's plain profile-name list (for the Name Your
            Profile step); reusing it here would misroute data.
        presets_delete_complete(int, int): succeeded/failed counts from a
            delete_presets() batch. delete_presets() is otherwise a normal
            _dispatch()-based entry point, but its two completion paths
            (success, partial-failure) both used to call
            MainWindow._status_banner directly rather than raising an
            exception (partial failure isn't an error condition
            _bridge_wrapper's mapping fits), so it needs a signal instead.
        presets_export_complete(int, int) / presets_save_complete(int, int):
            same succeeded/failed-counts pattern as presets_delete_complete,
            for export_presets()/save_presets() batches. A single preset's
            EmptyPresetFiltersError (or any other read failure) inside the
            batch loop is caught and counted as one failure rather than
            propagated -- matching presets_delete_complete's existing
            partial-failure handling, deliberately, even for a batch of one
            (see _do_export_presets/_do_save_presets docstrings).
    """

    peq_presets_ready = Signal(list, object, str, bool, str, bool)
    peq_presets_unavailable = Signal()
    roomfit_profiles_ready = Signal(list, str, bool)
    roomfit_profiles_hidden = Signal()
    name_profiles_ready = Signal(list, str, bool)
    presets_delete_complete = Signal(int, int)
    presets_export_complete = Signal(int, int)
    presets_save_complete = Signal(int, int)

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
        self._safe_write_factory: Callable[[WiiMAdapter], SafeWrite] | None = None
        self._roomfit_safe_write_factory: Callable[[WiiMAdapter], RoomFitSafeWrite] | None = None
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
        safe_write_factory: Callable[[WiiMAdapter], SafeWrite],
        roomfit_safe_write_factory: Callable[[WiiMAdapter], RoomFitSafeWrite],
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
            safe_write_factory: Factory creating a SafeWrite from a
                WiiMAdapter, for push()'s PEQ path — same shape as
                SecondaryWorkflowManager's factory of the same name, so
                both managers inject this dependency the same way.
            roomfit_safe_write_factory: Factory creating a RoomFitSafeWrite
                from a WiiMAdapter, for push()'s RoomFit path.
        """
        self._bridge = bridge
        self._discovery_module = discovery_module
        self._wizard_controller = wizard_controller
        self._bridge_wrapper = bridge_wrapper
        self._rew_client = rew_client
        self._profile_repository = profile_repository
        self._safe_write_factory = safe_write_factory
        self._roomfit_safe_write_factory = roomfit_safe_write_factory
        logger.info("PrimaryWorkflowManager configured")

    def set_current_adapter(self, adapter: WiiMAdapter | None) -> None:
        """Set the current device adapter for same-device workflows.

        Called from MainWindow whenever the active device changes (mirrors
        SecondaryWorkflowManager.set_current_adapter). Used by every
        workflow here that reads the live device: pull_device, pull_roomfit,
        load_peq_preset, list_presets/refresh_presets, and push.

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

    def _dispatch(
        self, operation_name: str, coro: Coroutine[Any, Any, Any], *, cancellable: bool = False
    ) -> None:
        """Run a coroutine on the bridge, wrapped for error mapping.

        Shared by every fire-and-forget entry point below — each one used to
        repeat this same assert/assert/run_async line; consolidated here
        once enough of them existed to justify it.

        Args:
            operation_name: Log-context label for _bridge_wrapper.
            coro: The awaitable adapter coroutine to execute.
            cancellable: Whether the user can cancel this operation via
                Escape or the Cancel button. Defaults to False (the safe
                direction) -- only pass True for confirmed pure reads with
                no device-write/SafeWrite side effect a cancellation could
                leave half-done.
        """
        assert self._bridge is not None
        assert self._bridge_wrapper is not None
        self._bridge.run_async(
            self._bridge_wrapper(operation_name, coro), cancellable=cancellable
        )

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
        self._dispatch("discovery", self._do_discovery(), cancellable=True)

    async def _do_discovery(self) -> None:
        """Run device discovery and emit results via bridge signal.

        Uses progressive discovery — devices appear in the UI as soon as
        they're found rather than waiting for the full scan to complete.

        discover() is dispatched as cancellable, but a cancelled scan still
        needs to clear ConnectPage's scanning indicator -- see
        _AbandonGuard's docstring for why a plain `finally` isn't enough on
        its own. A genuine discovery error is handled separately, by
        MainWindow._on_operation_error, not by this guard.
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

        with _AbandonGuard(self._bridge.discovery_abandoned.emit) as guard:
            devices = await self._discovery_module.discover(on_found=_on_found)
            # Cache raw DeviceInfo objects for device picker dialogs
            self._discovered_devices = devices
            device_list = [
                {"name": d.name, "ip": d.ip, "model": d.model}
                for d in devices
            ]
            self._bridge.discovery_complete.emit(device_list)
            guard.succeeded = True

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

    def probe(self, prober: CapabilityProber, generation: int, device_ip: str) -> None:
        """Trigger capability probing for a just-selected device.

        Args:
            prober: The CapabilityProber for the device this probe targets.
            generation: Snapshot from bump_probe_generation() at selection
                time, used by _do_probe to discard a stale result.
            device_ip: IP of the device this probe targets, so _do_probe can
                report back exactly which device's card to reset if the
                probe never produces a result.
        """
        self._dispatch(
            "capability_probe", self._do_probe(prober, generation, device_ip), cancellable=True
        )

    async def _do_probe(
        self, prober: CapabilityProber, generation: int, device_ip: str
    ) -> None:
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

        Either way -- discarded as stale, or cancelled outright via
        Escape/Cancel while the probe is cancellable -- ConnectPage's card
        for *device_ip* was already left pulsing "connecting" by whoever
        dispatched this probe, with nothing else to revert it. _AbandonGuard
        emits `probe_abandoned` for exactly that device when this coroutine
        exits stale/cancelled without reaching `capabilities_ready`, so the
        card for a superseded/cancelled probe doesn't pulse forever. A
        genuine probe error is handled separately, by
        MainWindow._on_operation_error, not by this guard.

        Args:
            prober: The CapabilityProber for the device this probe targets.
            generation: Snapshot of the probe-generation counter at selection time.
            device_ip: IP of the device this probe targets.
        """
        bridge = self._bridge
        assert bridge is not None
        with _AbandonGuard(lambda: bridge.probe_abandoned.emit(device_ip)) as guard:
            caps = await prober.probe()
            if generation != self._probe_generation:
                logger.debug(
                    "Discarding stale capability probe result (generation %d, current %d)",
                    generation,
                    self._probe_generation,
                )
                return
            bridge.capabilities_ready.emit(caps)
            guard.succeeded = True

    # ------------------------------------------------------------------
    # Workflow: File Import
    # ------------------------------------------------------------------

    def import_file(self, path: str) -> None:
        """Trigger a single-file (stereo) REW import."""
        # cancellable=False: _do_file_import has no await point (REWParser.
        # parse_file_with_rows() is fully synchronous), so a mid-flight
        # cancel could never actually interrupt it -- showing a Cancel
        # button that silently does nothing would be misleading.
        self._dispatch("file_import", self._do_file_import(path), cancellable=False)

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
        # cancellable=False: see import_file()'s comment -- _do_file_import_lr
        # is also fully synchronous, no await point to cancel at.
        self._dispatch(
            "file_import_lr", self._do_file_import_lr(path_l, path_r), cancellable=False
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

        Used by MainWindow's bridge-wrapped dispatch points
        (_load_device_presets, _on_device_presets_requested). _do_delete_presets,
        which needs to await the refresh inline as part of its own coroutine,
        calls refresh_presets() directly instead — see that method's docstring.
        """
        self._dispatch("list_presets", self.refresh_presets(), cancellable=True)

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

        def _to_preset_items(
            raw_items: list[dict[str, Any]], preset_type: Literal["PEQ", "RoomFit"]
        ) -> list[PresetItem]:
            return [
                PresetItem(
                    name=item.get("Name", "Unnamed"),
                    preset_type=preset_type,
                    channel_mode=item.get("channelMode", "Stereo"),
                )
                for item in raw_items
            ]

        async def _fetch_peq() -> None:
            if not wiim_adapter.capabilities.supports_peq:
                self.peq_presets_unavailable.emit()
                return

            peq_items: list[PresetItem] = []
            if wiim_adapter.capabilities.supports_profile_enumeration:
                try:
                    peq_presets = await wiim_adapter.list_peq_profiles(source_name)
                    peq_items = _to_preset_items(peq_presets, "PEQ")
                except Exception:
                    logger.warning("Failed to list PEQ presets", exc_info=True)
                    self.peq_presets_unavailable.emit()
                    return

            # read_peq() is a plain, harmless read, unlike
            # load_peq_profile()/EQv2SourceLoad. This is the *only* PEQ
            # signal on a device without profile enumeration -- it backs
            # the synthetic "Custom" row (see build_custom_peq_item) that
            # replaces the old dedicated "Current configuration on device"
            # button for such devices.
            active_peq_name, active_peq_channel_mode, active_peq_enabled = (
                await self._peq_active_info_or_default(source_name)
            )
            if active_peq_name is None and not peq_items:
                # Nothing confirmed: no named presets (unsupported or none
                # saved) and the live-config read that would back a
                # synthetic "Custom" row also failed -- same outcome as
                # peq_presets_unavailable, not a preset list with an
                # unearned "Custom" entry.
                self.peq_presets_unavailable.emit()
                return
            self.peq_presets_ready.emit(
                peq_items,
                active_peq_name,
                active_peq_channel_mode,
                active_peq_enabled,
                source_name,
                wiim_adapter.capabilities.supports_profile_enumeration,
            )

        async def _fetch_roomfit() -> None:
            try:
                if wiim_adapter.capabilities.supports_roomfit:
                    rf_profiles = await wiim_adapter.list_roomfit_profiles(source_name)
                    rf_items = _to_preset_items(rf_profiles, "RoomFit")
                    active_roomfit_name, active_roomfit_enabled = (
                        await self._roomfit_active_info_or_default()
                    )
                    self.roomfit_profiles_ready.emit(
                        rf_items, active_roomfit_name, active_roomfit_enabled
                    )
                else:
                    self.roomfit_profiles_hidden.emit()
            except Exception:
                logger.warning("Failed to list RoomFit profiles", exc_info=True)
                self.roomfit_profiles_hidden.emit()

        await asyncio.gather(_fetch_peq(), _fetch_roomfit())

    async def _peq_active_info_or_default(
        self, source_name: str
    ) -> tuple[str | None, str, bool]:
        """The active PEQ config's (name, channel_mode, enabled), for #165c
        highlighting and the merged Device list's synthetic "Custom" row.

        A single read_peq() call serves all three -- channel_mode and the
        EQStat-derived enabled flag come along for free rather than needing
        their own requests. `enabled` backs the "(active, PEQ off)" qualifier
        (build_preset_list_item) -- a source can have a name/custom config
        selected while PEQ itself is toggled off for that source, and
        "(active)" alone would misleadingly claim it's actually being
        applied to audio right now.

        Degrades to (None, "Stereo", True) on failure -- deliberately *not*
        ("", "Stereo", True): "" is the hardware-confirmed signal that the
        live config doesn't match any saved preset (show "Custom"), while a
        read failure means the active state is simply unknown (no
        highlight, no "Custom" row, same as never having fetched at all).
        Collapsing those two into one value would render a "Custom" row
        nothing actually confirmed. `enabled`'s default is moot in this
        branch since no row ever renders off a None name.
        """
        try:
            settings = await self._require_adapter().read_peq(source_name)
            return settings.name, settings.channel_mode.display_value, settings.enabled
        except Exception:
            logger.warning("Failed to read active PEQ preset name", exc_info=True)
            return None, "Stereo", True

    async def _roomfit_active_info_or_default(self) -> tuple[str, bool]:
        """The active RoomFit profile's (name, enabled), for #165c
        highlighting and the "(active, RoomFit off)" qualifier.

        Degrades to ("", True) on failure -- a failure here means no
        highlight, not a failed view (same rationale as
        _peq_active_info_or_default), and RoomFit has no "Custom" row
        concept so "" carries no special meaning here the way it does for
        PEQ.
        """
        try:
            enabled, active_roomfit_name = await self._require_adapter().get_roomfit_status()
            return active_roomfit_name, enabled
        except Exception:
            logger.warning("Failed to read active RoomFit profile name", exc_info=True)
            return "", True

    # ------------------------------------------------------------------
    # Workflow: Device / Preset Reads (Phase 2)
    # ------------------------------------------------------------------

    def pull_device(self) -> None:
        """Trigger a pull-from-device; result arrives via peq_ready."""
        self._dispatch("device_pull", self._do_device_pull(), cancellable=True)

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
        state.filters_origin = f"Pulled from device (source: {source_name})"

        # Emit result signal
        self._bridge.peq_ready.emit(peq_settings)

    def pull_roomfit(self, profile_name: str, operation_name: str = "roomfit_pull") -> None:
        """Trigger a RoomFit profile pull; result arrives via peq_ready.

        Args:
            profile_name: Name of the RoomFit profile to read.
            operation_name: Log-context label for _bridge_wrapper.
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
        confirmation dialog in _on_device_item_selected already warned the
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

        # Extract filters and channel_mode from the device data, and update
        # wizard state (avoids stale L/R state from a previous load, smoke #111)
        filters, channel_mode = extract_filters(peq_settings)
        state.channel_mode = channel_mode

        # Store in wizard state
        state.current_filters = filters
        state.filters_origin = f"PEQ preset: {preset_name}"

        # Emit result signal
        self._bridge.peq_ready.emit(peq_settings)

    # ------------------------------------------------------------------
    # Workflow: Export to File (Phase 2)
    # ------------------------------------------------------------------

    def export_file(self, filters: list[CanonicalFilter], path: str) -> None:
        """Trigger a stereo REW file export; progress arrives via progress_update."""
        # cancellable=False: _do_export has no await point (REWGenerator.
        # generate_file() is fully synchronous) -- see import_file()'s comment.
        self._dispatch("export", self._do_export(filters, path), cancellable=False)

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
        # cancellable=False: _do_export_lr is also fully synchronous -- see
        # import_file()'s comment.
        self._dispatch(
            "export_lr",
            self._do_export_lr(filters_l, filters_r, path_l, path_r),
            cancellable=False,
        )

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
        self._dispatch("rew_list", self._do_rew_list_measurements(), cancellable=True)

    async def _do_rew_list_measurements(self) -> None:
        """List available measurements from REW API.

        Calls REWHttpApiClient.list_measurements() and emits the result.
        If empty, emits an info message instead of the measurement list.

        list_rew_measurements() is dispatched as cancellable, but nothing
        else clears the embedded RewPullView's "Connecting..." state for a
        cancelled fetch -- _AbandonGuard emits `rew_list_abandoned` when
        this coroutine is cancelled without reaching one of its two terminal
        emits below, so the picker doesn't stay stuck showing
        "Connecting..." forever after Escape/Cancel. A genuine fetch error
        is handled separately, by MainWindow._on_operation_error (which
        shows the real error in the still-active RewPullView), not by this
        guard.
        """
        bridge = self._bridge
        assert bridge is not None
        rew_client = self._require_rew_client()

        with _AbandonGuard(bridge.rew_list_abandoned.emit) as guard:
            measurements = await rew_client.list_measurements()

            if not measurements:
                bridge.progress_update.emit(
                    "__info__No measurements found in REW. "
                    "Load or import measurement(s) in REW's Measurements pane, then try again."
                )
                guard.succeeded = True
                return

            # Emit measurement list for the picker dialog
            bridge.rew_measurements_ready.emit(measurements)
            guard.succeeded = True

    def get_rew_filters(self, uuid: str, measurement_name: str = "") -> None:
        """Trigger a REW filter fetch for one measurement; result arrives via signal."""
        self._dispatch(
            "rew_filters", self._do_rew_get_filters(uuid, measurement_name), cancellable=True
        )

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
            cancellable=True,
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

        # Independent fetches -- run concurrently rather than one blocking
        # the other, matching refresh_presets()'s PEQ/RoomFit concurrency.
        (filters_l, rows_l, notes_l), (filters_r, rows_r, notes_r) = await asyncio.gather(
            rew_client.get_filters_with_rows(uuid_l),
            rew_client.get_filters_with_rows(uuid_r),
        )

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

    def export_presets(
        self, requests: list[tuple[str, str, str, bool]]
    ) -> None:
        """Trigger a batch device-preset export to file(s); result via
        presets_export_complete.

        Args:
            requests: (preset_name, preset_type, path, is_custom) tuples,
                one per preset to export -- built by MainWindow from however
                many items are selected (one or many, no special-casing
                needed here; see _do_export_presets).
        """
        self._dispatch("preset_export_batch", self._do_export_presets(requests))

    async def _do_export_presets(
        self, requests: list[tuple[str, str, str, bool]]
    ) -> None:
        """Sequentially read+export each preset in `requests`.

        Sequential, not concurrent: reading a named preset briefly loads it
        onto the device's live DSP (see #166) -- running several of these
        concurrently would race on that same shared device state, same
        reasoning as _do_save_presets/_do_delete_presets/
        _do_copy_presets_batch_multi (secondary_workflows.py).

        One preset's failure (including EmptyPresetFiltersError) doesn't
        abort the rest -- it's counted as a failure in the emitted totals
        instead of propagating, matching _do_delete_presets's existing
        partial-failure handling. This applies even to a "batch" of one: a
        single preset with no filters to export now reports as "0
        exported, 1 failed" rather than a specific EmptyPresetFiltersError
        message, a deliberate consistency trade-off (#165c follow-up) with
        every other batch action in this codebase.
        """
        succeeded, failed = await self._run_batch_preset_requests(
            requests, self._do_preset_export, "Export"
        )
        self.presets_export_complete.emit(succeeded, failed)

    async def _run_batch_preset_requests(
        self,
        requests: list[tuple[str, str, str, bool]],
        worker: Callable[..., Awaitable[None]],
        action: str,
    ) -> tuple[int, int]:
        """Sequentially run `worker(preset_name, preset_type, target, is_custom=...)`
        over every (preset_name, preset_type, target, is_custom) request,
        tolerating per-item failure. Shared by _do_export_presets and
        _do_save_presets -- both loop over the identical request shape and
        only differ in which per-item worker they call and the log/signal
        labels, so the loop itself lives here once (see _do_export_presets's
        docstring for why sequential, not concurrent, and why a failure
        doesn't abort the rest).

        Args:
            requests: (preset_name, preset_type, target, is_custom) tuples.
            worker: Async per-item callable, e.g. self._do_preset_export.
            action: Verb used in the per-item failure log line ("Export"/"Save").

        Returns:
            (succeeded, failed) counts for the caller to emit on its own signal.
        """
        succeeded = 0
        failed = 0
        for preset_name, preset_type, target, is_custom in requests:
            try:
                await worker(preset_name, preset_type, target, is_custom=is_custom)
                succeeded += 1
            except Exception:
                logger.exception("%s preset '%s' failed", action, preset_name)
                failed += 1
        return succeeded, failed

    async def _do_preset_export(
        self, preset_name: str, preset_type: str, path: str, *, is_custom: bool = False
    ) -> None:
        """Read a preset from device and export as REW file.

        For L/R mode, generates two files (_L.txt and _R.txt) from the base path.

        Args:
            preset_name: Name of the preset to export.
            preset_type: "PEQ" or "RoomFit".
            path: Destination file path.
            is_custom: True for the synthetic "Custom" row (#165c) -- reads
                the live PEQ config directly instead of a named preset.

        Raises:
            EmptyPresetFiltersError: if the preset resolves to zero filters
                (mapped to a status-banner error by MainWindow._map_error).
        """
        from src.translator.rew_generator import REWGenerator

        assert self._bridge is not None
        wiim_adapter = self._require_adapter()
        state = self._require_wizard_state()
        source_name = state.primary_source

        # Read preset filters from device -- a named preset previews+restores
        # (the confirmation dialog in _on_preset_export_requested already
        # warned the user this briefly changes what's playing, see #166);
        # "Custom" is already live, so it's a plain read instead (#165c).
        peq_settings = await wiim_adapter.read_preset_preview_or_live(
            preset_type, source_name, preset_name, is_custom=is_custom
        )

        generator = REWGenerator()
        file_path = ensure_suffix(Path(path), ".txt")

        if is_lr_mode(peq_settings.channel_mode):
            # L/R mode: generate two files
            filters_l = peq_settings.bands_l or []
            filters_r = peq_settings.bands_r or []

            if not filters_l and not filters_r:
                raise EmptyPresetFiltersError(
                    f"Preset '{preset_name}' has no filters to export"
                )

            left_path, right_path, lr_warnings = generator.generate_lr_files(
                filters_l, filters_r, file_path
            )
            total_warnings = len(lr_warnings)

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

    def save_presets(
        self, requests: list[tuple[str, str, str, bool]]
    ) -> None:
        """Trigger a batch device-preset save to local storage; result via
        presets_save_complete.

        Args:
            requests: (preset_name, preset_type, saved_name, is_custom)
                tuples, one per preset to save.
        """
        self._dispatch("preset_save_batch", self._do_save_presets(requests))

    async def _do_save_presets(
        self, requests: list[tuple[str, str, str, bool]]
    ) -> None:
        """Sequentially read+save each preset in `requests`.

        Sequential, not concurrent -- and one preset's failure doesn't abort
        the rest, even a "batch" of one -- for the same reasons as
        _do_export_presets above.
        """
        succeeded, failed = await self._run_batch_preset_requests(
            requests, self._do_preset_save, "Save"
        )
        self.presets_save_complete.emit(succeeded, failed)

    async def _do_preset_save(
        self, preset_name: str, preset_type: str, saved_name: str, *, is_custom: bool = False
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
            is_custom: True for the synthetic "Custom" row (#165c) -- reads
                the live PEQ config directly instead of a named preset.

        Raises:
            EmptyPresetFiltersError: if the preset resolves to zero filters
                (mapped to a status-banner error by MainWindow._map_error).
        """
        assert self._bridge is not None
        assert self._profile_repository is not None
        wiim_adapter = self._require_adapter()
        state = self._require_wizard_state()
        source_name = state.primary_source

        # Read preset filters from device -- a named preset previews+restores
        # (the confirmation dialog in _on_preset_save_requested already
        # warned the user this briefly changes what's playing, see #166);
        # "Custom" is already live, so it's a plain read instead (#165c).
        peq_settings = await wiim_adapter.read_preset_preview_or_live(
            preset_type, source_name, preset_name, is_custom=is_custom
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
        self._dispatch(
            "list_roomfit_for_naming", self._do_populate_name_profiles(), cancellable=True
        )

    async def _do_populate_name_profiles(self) -> None:
        """Fetch RoomFit profiles and emit name_profiles_ready for NameProfilePage."""
        assert self._bridge is not None
        wiim_adapter = self._require_adapter()
        state = self._require_wizard_state()
        source_name = state.primary_source

        try:
            if wiim_adapter.capabilities.supports_roomfit:
                profiles = await wiim_adapter.list_roomfit_profiles(source_name)
                profile_names = _extract_profile_names(profiles)
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

    # ------------------------------------------------------------------
    # Workflow: Push (the safety-critical core write path)
    # ------------------------------------------------------------------

    def push(self) -> None:
        """Trigger a push to the connected device; result arrives via signal."""
        self._dispatch("push", self._do_push())

    async def _do_push(self) -> None:
        """Execute push to device — PEQ via SafeWrite, or RoomFit via write_roomfit.

        For PEQ flow: constructs PEQSettings and uses SafeWrite protocol.
        Pushes to ALL selected sources (state.selected_sources).
        For RoomFit flow: uses write_roomfit with the named profile.

        Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7
        """
        assert self._bridge is not None
        state = self._require_wizard_state()

        # Safety net: never write to device in dry-run mode
        if state.dry_run:
            logger.warning("_do_push called in dry-run mode - aborting write")
            return

        wiim_adapter = self._require_adapter()
        assert self._safe_write_factory is not None
        assert self._roomfit_safe_write_factory is not None

        assert self._wizard_controller is not None
        filters = state.current_filters
        channel_mode = state.channel_mode
        flow_type = self._wizard_controller.flow_type

        # The push flow is the one deliberately multi-source operation:
        # one write per selected source. Empty selection falls back to the
        # single default source (#194).
        source_list = state.selected_sources or [state.primary_source]

        logger.info(
            "Push initiated: flow=%s, channel=%s, filters=%d, sources=%s",
            flow_type.value, channel_mode.value, len(filters), source_list,
        )

        on_stage = self._bridge.stage_changed.emit

        if flow_type == FlowType.ROOMFIT:
            # RoomFit: write as named profile via write_roomfit
            # RoomFit is device-global, so source doesn't matter — use first
            source_name = source_list[0]
            profile_name = state.roomfit_profile_name
            if not profile_name:
                result = WriteResult(
                    success=False, error_message="No profile name specified", backup_path=None
                )
                self._bridge.write_complete.emit(result)
                return

            roomfit_safe_write = self._roomfit_safe_write_factory(wiim_adapter)
            try:
                self._bridge.progress_update.emit(
                    f"Writing RoomFit profile '{profile_name}'..."
                )
                # Never derive filters_l/filters_r by splitting the combined
                # `filters` list -- resolve_roomfit_channel_kwargs() requires
                # them explicitly already-separate (round-4 review finding
                # #8, 2026-07-19: shared with secondary_workflows.
                # _write_preset_to_adapter, which hand-rolled this same
                # branch independently before).
                roomfit_filters_l, roomfit_filters_r = resolve_roomfit_channel_kwargs(
                    channel_mode, state.filters_l, state.filters_r
                )
                result = await roomfit_safe_write.execute(
                    source_name,
                    profile_name,
                    filters,
                    channel_mode=channel_mode,
                    filters_l=roomfit_filters_l,
                    filters_r=roomfit_filters_r,
                    on_stage=on_stage,
                )

                if result.success:
                    self._bridge.progress_update.emit(
                        f"RoomFit profile '{profile_name}' saved"
                    )
                self._bridge.write_complete.emit(result)
            except Exception as exc:
                result = WriteResult(success=False, error_message=str(exc), backup_path=None)
                self._bridge.write_complete.emit(result)
        else:
            # PEQ: use SafeWrite protocol — push to ALL selected sources
            safe_write = self._safe_write_factory(wiim_adapter)

            # Validate the L/R split up front -- channel_mode/state.filters_l/
            # state.filters_r don't vary per source, so if this is going to
            # raise it raises identically on every iteration below. Catching
            # it here (matching the RoomFit branch's own try/except a few
            # lines up) means a bad split fails cleanly via write_complete,
            # same as every other push failure, instead of the raw
            # ValueError propagating past this method to _bridge_wrapper's
            # generic operation_error handler, which never touches PushPage
            # (round-4 review finding #4, 2026-07-19).
            if channel_mode.is_lr:
                try:
                    require_lr_filters(state.filters_l, state.filters_r)
                except ValueError as exc:
                    result = WriteResult(
                        success=False, error_message=str(exc), backup_path=None
                    )
                    self._bridge.write_complete.emit(result)
                    return

            last_result = None
            backup_paths: list[tuple[str, str]] = []
            for i, source_name in enumerate(source_list):
                if len(source_list) > 1:
                    self._bridge.progress_update.emit(
                        f"Pushing to {source_name} ({i + 1}/{len(source_list)})..."
                    )
                    self._bridge.push_round_changed.emit(
                        source_name, i + 1, len(source_list)
                    )

                settings = build_peq_settings(
                    source_name, filters, channel_mode,
                    filters_l=state.filters_l,
                    filters_r=state.filters_r,
                )
                try:
                    result = await safe_write.execute(source_name, settings, on_stage=on_stage)
                except (WiiMConnectionError, WiiMResponseError, BackupError) as exc:
                    # A connection/response/backup error aborted this
                    # source's write before SafeWrite.execute() could return
                    # a result at all -- e.g. a connection drop mid-write
                    # (docs/backlog.md item 9). Distinct from a *returned*
                    # failed WriteResult (below): here nothing was verified,
                    # so backup_path stays None (no backup exists to point
                    # recovery at) and verified=False tells PushPage not to
                    # claim the device was safely restored, since that was
                    # never confirmed.
                    logger.exception("Push to source '%s' failed", source_name)
                    result = WriteResult(
                        success=False, error_message=str(exc), backup_path=None,
                        verified=False,
                    )
                    await self._finalize_push_failure(result, backup_paths, safe_write)
                    return
                last_result = result

                if not result.success:
                    # Abort on first failure. Source i itself already rolled
                    # back via its own SafeWrite.execute() call, so its
                    # backup is excluded from backup_paths below -- nothing
                    # to undo there. Sources 0..i-1 (already in backup_paths)
                    # succeeded and are handled by _finalize_push_failure()
                    # (docs/backlog.md item 3).
                    await self._finalize_push_failure(result, backup_paths, safe_write)
                    return

                # Collect backup path for undo only for sources that
                # actually succeeded (smoke #77, refined for #242 above --
                # a failed source's own backup is excluded, see comment above).
                bp_path = result.backup_path
                if bp_path:
                    backup_paths.append((source_name, str(bp_path)))

            # All sources succeeded — store all backup paths for undo
            if last_result and last_result.success:
                combined_backup = (
                    encode_multi_source_backup_paths(backup_paths) if backup_paths else None
                )
                result = WriteResult(
                    success=True,
                    backup_path=combined_backup,
                    # Same filters/channel_mode were pushed to every source
                    # in this loop, so the last source's read-back is
                    # representative of what's now on every one of them.
                    read_back=last_result.read_back,
                )
                self._bridge.write_complete.emit(result)

    async def _finalize_push_failure(
        self,
        result: WriteResult,
        backup_paths: list[tuple[str, str]],
        safe_write: SafeWrite,
    ) -> None:
        """Auto-roll-back already-succeeded sources on a mid-loop push
        failure, populate `result` with the outcome, and emit it.

        The one place this logic lives, called both when SafeWrite.execute()
        returns a failed WriteResult and when it raises a connection/
        response/backup error (see _do_push()'s PEQ loop above) -- so the
        two failure origins can't drift apart (docs/backlog.md items 3, 9).

        Args:
            result: The failing source's own WriteResult (already built,
                either returned by SafeWrite.execute() or constructed from a
                caught exception). Mutated in place with auto-rollback
                outcome fields, then emitted -- every other field (backup_
                path, error_message, verified) stays exactly as the caller
                set it.
            backup_paths: (source_name, backup_path) pairs for the sources
                that already succeeded before this failure, in push order.
                Empty if this is the first source, or a single-source push.
            safe_write: The SafeWrite instance _do_push() is already using
                for this run, reused here (not rebuilt) to restore each
                entry.
        """
        assert self._bridge is not None
        if backup_paths:
            self._bridge.rollback_state_changed.emit(True)
            try:
                # succeeded count is intentionally not read here -- it's
                # always derivable as auto_rollback_attempted - partial_sources
                # (see WriteResult's docstring), so no separate field for it.
                _, failed, failed_entries = await restore_entries(
                    safe_write, backup_paths,
                    on_stage=self._bridge.stage_changed.emit,
                    on_round=self._on_rollback_round,
                )
            finally:
                self._bridge.rollback_state_changed.emit(False)
            result.auto_rollback_attempted = len(backup_paths)
            result.partial_sources = failed
            result.partial_backup_paths = (
                encode_multi_source_backup_paths(failed_entries) if failed_entries else None
            )
        self._bridge.write_complete.emit(result)

    def _on_rollback_round(self, source_name: str, index: int, total: int) -> None:
        """Progress callback for restore_entries() during auto-rollback.

        Mirrors the forward-push loop's own progress_update/push_round_changed
        pairing a few lines up in _do_push(), with "Rolling back" wording so
        it reads distinctly from a manual Undo's "Restoring" (see PushPage
        .set_push_round()'s _rollback_mode flag).
        """
        assert self._bridge is not None
        self._bridge.progress_update.emit(
            f"Rolling back {source_name} ({index} of {total})..."
        )
        self._bridge.push_round_changed.emit(source_name, index, total)

    # ------------------------------------------------------------------
    # Workflow: Raw Command (Diagnostics panel)
    # ------------------------------------------------------------------

    def raw_command(self, command: str) -> None:
        """Trigger a raw httpapi command against the connected device."""
        self._dispatch("raw_command", self._do_raw_command(command))

    async def _do_raw_command(self, command: str) -> None:
        """Execute a raw httpapi command against the connected device.

        Catches its own exceptions (rather than letting bridge_wrapper's
        usual error-mapping handle them) since the diagnostics panel wants
        the error text displayed as a formatted response, not routed
        through the status-banner error path.

        Args:
            command: The command string (e.g. "getStatusEx").
        """
        assert self._bridge is not None
        wiim_adapter = self._require_adapter()

        try:
            response = await wiim_adapter.raw_command(command)
            # Format the response as JSON if possible
            if isinstance(response, dict):
                formatted = json.dumps(response, indent=2, ensure_ascii=False)
            else:
                formatted = str(response)
            # Emit via signal to avoid cross-thread GUI access (smoke #85 segfault fix)
            self._bridge.progress_update.emit(f"__raw_response__{formatted}")
        except Exception as exc:
            self._bridge.progress_update.emit(f"__raw_response__Error: {exc}")
