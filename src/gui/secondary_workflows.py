"""Secondary workflow orchestration for profile recall and undo operations.

Encapsulates the logic for workflows that extend beyond the primary wizard:
- Profile recall from My Saved Presets (Req 17.2)
- Undo last push (Req 18)

These workflows are self-contained operations launched from PushPage or
MyPresetsView. They do NOT create new wizard steps in the StepIndicator —
they are modal sub-flows or inline operations.

Note: "Copy to another source" (Req 20) and "Apply to multiple devices"
(Req 21) were never wired to any UI trigger and have been removed as dead
code (code quality audit, 2026-06-28) — see docs/backlog.md if those
features are revisited. "Copy preset to another device" (Req 15.11, 17.3)
lives here in full, including the batch dispatchers
(copy_presets_to_devices / copy_local_profiles_to_devices — docs/backlog.md
item 2 Phase D).

Requirements referenced: 17.2, 18.1, 18.2, 18.3, 18.4, 18.6.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Signal, Slot

from src.adapters.safe_write import restore_entries, restore_one
from src.gui.async_bridge import emit_round_progress
from src.gui.primary_workflows import EmptyPresetFiltersError
from src.models.canonical import CanonicalFilter
from src.models.channel_mode import (
    ChannelMode,
    coerce_channel_mode,
    resolve_roomfit_channel_kwargs,
)
from src.models.peq import PEQSettings, build_peq_settings, extract_filters
from src.repository.backup_manager import (
    decode_multi_source_backup_paths,
    load_backup_json,
    parse_backup_restore_metadata,
)
from src.translator.wiim_generator import find_unsupported_filter_types

if TYPE_CHECKING:
    from src.adapters.capability_prober import CapabilityProber
    from src.adapters.safe_write import RoomFitSafeWrite, SafeWrite
    from src.adapters.wiim_adapter import WiiMAdapter
    from src.adapters.wiim_http import WiiMHttpClient
    from src.gui.async_bridge import AsyncBridge
    from src.models.capabilities import DeviceCapabilities, DeviceInfo

logger = logging.getLogger("wiim_rew_sync.secondary_workflows")

# Signature of MainWindow._bridge_wrapper, injected via configure() the same
# way PrimaryWorkflowManager does -- see BridgeWrapper in primary_workflows.py.
BridgeWrapper = Callable[[str, Coroutine[Any, Any, Any]], Coroutine[Any, Any, None]]


# ---------------------------------------------------------------------------
# SecondaryWorkflowManager
# ---------------------------------------------------------------------------


class SecondaryWorkflowManager(QObject):
    """Orchestrates secondary workflows: profile recall and undo.

    This manager coordinates multi-step operations that go beyond the primary
    wizard flow. It does NOT perform direct network calls; actual I/O is
    delegated to the AsyncBridge.

    The manager emits progress and completion signals that the MainWindow
    connects to for UI updates (StatusBanner messages, dialogs, etc.).

    Signals:
        profile_recalled(list, str): List of CanonicalFilter loaded from a
            profile, and the profile's name (for the Filters step tooltip,
            #162d).
        undo_complete(bool, str): Success flag and message after undo, for
            the binary-outcome undo paths (_do_undo, _do_undo_roomfit).
        undo_multi_source_complete(int, int, str): succeeded, failed counts
            and message after a multi-source undo. A separate signal from
            undo_complete rather than a shared one -- multi-source undo has
            a genuine 3-way outcome (full success / partial / full failure)
            that a binary success flag can't carry, and the "should the
            pushed-filters snapshot be cleared" decision (succeeded > 0)
            is independent of the "should the banner show success" decision
            (failed == 0). Squeezing this into undo_complete would add a
            parameter that's always redundant with the success flag for the
            other two (binary) undo paths.
        source_slots_ready(list): SourceSlotInfo rows from the current
            device's EQGetSourceModes overview (diagnostic-only).
        source_slots_error(str): Error message when the slot overview
            couldn't be fetched (e.g. device doesn't support the command).
        copy_batch_complete(int, int, int, int, str): n_items, n_devices,
            succeeded, failed counts, and a singular item-kind label
            ("preset"/"profile") from a multi-item/multi-device copy.
            Shared by copy_presets_to_devices (device-to-device, label
            "preset") and copy_local_profiles_to_devices (local-Profile-to-
            device, label "profile") -- both report the same (item count,
            device count, succeeded, failed) shape, one or more items at a
            time; the label lets _on_copy_batch_complete's summary say
            "preset(s)"/"profile(s)" accurately instead of a name borrowed
            from whichever caller was implemented first.
        copy_item_failed(str): One pre-formatted, human-readable line per
            failed copy operation (or per group of operations skipped for
            the same reason -- a source-read failure or a target-connect
            failure skips every affected device/item at once rather than
            emitting one identical line per item). Emitted as failures
            happen during a copy_presets_to_devices/
            copy_local_profiles_to_devices batch, in addition to (not
            instead of) the aggregate counts in copy_batch_complete --
            lets MainWindow show *what* failed and *why* (e.g. "device
            doesn't support RoomFit" vs. "connection lost") instead of
            only a bare "N of M operations failed" tally.
    """

    # --- Signals ---
    profile_recalled = Signal(list, str)
    undo_complete = Signal(bool, str)
    undo_multi_source_complete = Signal(int, int, str)
    source_slots_ready = Signal(list)
    source_slots_error = Signal(str)
    copy_batch_complete = Signal(int, int, int, int, str)
    copy_item_failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._bridge: AsyncBridge | None = None
        self._bridge_wrapper: BridgeWrapper | None = None
        self._safe_write_factory: Callable[[WiiMAdapter], SafeWrite] | None = None
        self._roomfit_safe_write_factory: Callable[[WiiMAdapter], RoomFitSafeWrite] | None = None
        self._current_adapter: WiiMAdapter | None = None
        self._wiim_http_client_factory: Callable[[str], WiiMHttpClient] | None = None
        self._capability_prober_factory: (
            Callable[[WiiMHttpClient], CapabilityProber] | None
        ) = None
        self._target_adapter_factory: (
            Callable[[WiiMHttpClient, DeviceCapabilities], WiiMAdapter] | None
        ) = None
        # Shared by copy_presets_to_devices/copy_local_profiles_to_devices --
        # both feed the same MainWindow-level _copy_batch_failures
        # accumulator, so a second dispatch overlapping the first (there's
        # no synchronous "button already disabled" guarantee: run_async()
        # schedules the coroutine on a background-thread event loop and
        # only emits operation_started -- which disables the Copy buttons --
        # once that coroutine actually starts running there, leaving a
        # window where a fast double-click isn't caught by the UI) would
        # interleave both batches' results into one summary/dialog.
        self._copy_in_progress = False

    # ------------------------------------------------------------------
    # Configuration (adapter injection for async execution)
    # ------------------------------------------------------------------

    def configure(
        self,
        bridge: AsyncBridge,
        bridge_wrapper: BridgeWrapper,
        safe_write_factory: Callable[[WiiMAdapter], SafeWrite],
        roomfit_safe_write_factory: Callable[[WiiMAdapter], RoomFitSafeWrite],
        wiim_http_client_factory: Callable[[str], WiiMHttpClient],
        capability_prober_factory: Callable[[WiiMHttpClient], CapabilityProber],
        target_adapter_factory: Callable[[WiiMHttpClient, DeviceCapabilities], WiiMAdapter],
    ) -> None:
        """Inject adapter dependencies for real async workflow execution.

        Called eagerly from MainWindow._setup_secondary_workflows() (__init__)
        -- every argument is a device-agnostic factory/callable, not tied to
        whichever device the Connect step later probes, so workflows like
        copy_local_profiles_to_devices() must not require a prior connect.

        Args:
            bridge: The AsyncBridge for run_async calls.
            bridge_wrapper: MainWindow._bridge_wrapper, injected the same way
                PrimaryWorkflowManager takes it -- catches any exception,
                logs it, maps it to a user-friendly message, and emits
                operation_error. Used by the fire-and-forget dispatchers
                below (undo_roomfit, undo_multi_source, copy_presets_to_devices,
                copy_local_profiles_to_devices) so an exception that escapes
                their coroutine reaches a status banner instead of being
                silently dropped by run_async's un-awaited Future.
            safe_write_factory: Factory creating a SafeWrite from a WiiMAdapter.
            roomfit_safe_write_factory: Factory creating a RoomFitSafeWrite
                from a WiiMAdapter, for undo_roomfit().
            wiim_http_client_factory: Factory creating a WiiMHttpClient for a
                target device IP, for copy-to-device's target connection.
            capability_prober_factory: Factory creating a CapabilityProber
                for a WiiMHttpClient, to probe an unfamiliar target device
                before connecting to it (async -- the target device's own
                capabilities are unknown until probed, unlike the already-
                connected source device).
            target_adapter_factory: Factory creating a WiiMAdapter from a
                probed target client + capabilities, for copy-to-device's
                target connection.

        Requirements: 8.1.
        """
        self._bridge = bridge
        self._bridge_wrapper = bridge_wrapper
        self._safe_write_factory = safe_write_factory
        self._roomfit_safe_write_factory = roomfit_safe_write_factory
        self._wiim_http_client_factory = wiim_http_client_factory
        self._capability_prober_factory = capability_prober_factory
        self._target_adapter_factory = target_adapter_factory
        logger.info("SecondaryWorkflowManager configured with adapter factories")

    def _dispatch(
        self, operation_name: str, coro: Coroutine[Any, Any, Any], *, cancellable: bool = False
    ) -> None:
        """Run a coroutine on the bridge, wrapped for error mapping.

        Mirrors PrimaryWorkflowManager._dispatch -- shared so an exception
        that escapes a fire-and-forget workflow coroutine reaches a status
        banner instead of vanishing silently in run_async's un-awaited Future.

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

    def set_current_adapter(self, adapter: WiiMAdapter | None) -> None:
        """Set the current device adapter for same-device workflows.

        Called from MainWindow whenever the active device changes (after
        capability probing creates a WiiMAdapter). Used by undo_last_push,
        which operates on the currently connected device.

        Args:
            adapter: The WiiMAdapter for the currently connected device,
                    or None to clear.
        """
        self._current_adapter = adapter

    # ------------------------------------------------------------------
    # Workflow: Profile Recall (Req 17.2)
    # ------------------------------------------------------------------

    @Slot(object)
    def recall_profile(self, profile: object) -> None:
        """Load a saved profile from the local preset library into the Review step.

        Extracts CanonicalFilter data from the profile and emits
        profile_recalled so the wizard can populate the ReviewPage.
        Handles both stereo (profile.filters) and L/R (profile.filters_l + filters_r).

        Args:
            profile: A Profile object from the local preset library.

        Requirement 17.2: Profile Recall & Push flow.
        """
        profile_name: str = getattr(profile, "name", "Unknown")
        channel_mode = coerce_channel_mode(
            getattr(profile, "channel_mode", ChannelMode.STEREO)
        )

        # Extract filters based on channel mode
        if channel_mode.is_lr:
            # L/R profile: combine both channels into flat list
            filters_l: list[CanonicalFilter] = getattr(profile, "filters_l", None) or []
            filters_r: list[CanonicalFilter] = getattr(profile, "filters_r", None) or []
            filters = filters_l + filters_r
            # Store separate L/R lists in wizard state so downstream never re-splits
            self._store_lr_state(filters_l, filters_r)
        else:
            # Stereo profile
            filters = getattr(profile, "filters", None) or []
            # Clear L/R state for stereo profiles
            self._store_lr_state([], [])

        if not filters:
            logger.warning(
                "Profile recall: profile '%s' has no filters",
                profile_name,
            )
            self.profile_recalled.emit([], profile_name)
            return

        logger.info(
            "Profile recall: loaded %d filters from profile '%s' (%s)",
            len(filters),
            profile_name,
            channel_mode,
        )
        self.profile_recalled.emit(filters, profile_name)

    def _store_lr_state(
        self, filters_l: list[CanonicalFilter], filters_r: list[CanonicalFilter]
    ) -> None:
        """Store L/R filter lists in the parent MainWindow's wizard state.

        This avoids the need for naive 50/50 splitting when consumers
        need separate channel lists.

        Reaches through self.parent() rather than an injected dependency
        (unlike every other cross-object access in this class) because this
        method predates the configure()-based injection pattern established
        by the rest of the file. Logs rather than silently no-opping if the
        parent isn't wired up yet, so a construction-order mistake surfaces
        instead of just quietly losing the L/R state.
        """
        parent = self.parent()
        if parent is not None and hasattr(parent, "wizard_controller"):
            state = parent.wizard_controller.state
            state.filters_l = filters_l
            state.filters_r = filters_r
        else:
            logger.warning(
                "_store_lr_state: no parent with wizard_controller -- L/R state not stored"
            )

    # ------------------------------------------------------------------
    # Workflow: Undo Last Push (Req 18)
    # ------------------------------------------------------------------

    @Slot(str, object)
    def undo_last_push(self, source_name: str, backup_path: str | Path = "") -> None:
        """Restore the device's PEQ state from the most recent backup.

        The undo operation follows the same Safe_Write_Protocol as a normal
        push: backup current state → write backup data → verify →
        commit/rollback.

        Args:
            source_name: The source name to restore (needed for SafeWrite).
            backup_path: Path to the pre-write backup file created during
                        the original push operation.

        Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6.
        """
        self._dispatch("undo_last_push", self._do_undo(source_name, backup_path))

    async def _restore_backup(
        self, source_name: str, backup_path: str | Path
    ) -> tuple[bool, str]:
        """Restore a source's PEQ state from backup via restore_one() (file-
        existence check, SafeWrite.undo() call, and exception handling all
        live there -- see its docstring -- shared with restore_entries()'s
        multi-source loop so the two can't drift apart).

        Shared by _do_undo (single-source, wraps this in an undo_complete
        emit) and _do_undo_multi_source (awaits this directly per source so
        its succeeded/failed tally reflects each source's real outcome,
        rather than undo_last_push()'s fire-and-forget scheduling -- branch-
        quality review, 2026-07-18).

        Threads on_stage into SafeWrite.undo() (which forwards it to its
        internal execute() call, same as a normal push) so PushPage's
        existing Backup/Write/Verify stepper reflects real undo progress
        instead of the caller only having a one-line status banner message.

        Returns:
            Tuple of (success, message) -- message is the restored-
            confirmation text on success, or the error text on failure.
        """
        # Check the file first, ahead of the configure()-invariant asserts
        # below -- a missing backup is an ordinary, expected outcome (no
        # configure()/bridge setup required to detect it), not a
        # configuration-invariant violation. restore_one() below does its
        # own equivalent check too (needed for restore_entries()'s
        # multi-source callers, which have no such ordering requirement) --
        # this one short-circuits before it, preserving that a bad path
        # alone should never require configure() to have run.
        path = Path(backup_path) if isinstance(backup_path, str) else backup_path
        if not path or not path.is_file():
            logger.error("Restore requested but backup file not found: %s", path)
            return False, "No backup available"

        # configure()-invariant asserts: a violation is a programmer error,
        # not a runtime undo failure, so it must propagate to
        # _bridge_wrapper's loud crash-log path -- restore_one() itself has
        # no opinion on this, it just takes an already-built SafeWrite.
        assert self._bridge is not None, "configure() must run before undo"
        assert self._safe_write_factory is not None, "configure() must run before undo"
        assert self._current_adapter is not None, "configure() must run before undo"

        safe_write = self._safe_write_factory(self._current_adapter)
        return await restore_one(
            safe_write, source_name, path, on_stage=self._bridge.stage_changed.emit
        )

    async def _do_undo(self, source_name: str, backup_path: str | Path) -> None:
        """Execute undo via _restore_backup() and report the result."""
        success, message = await self._restore_backup(source_name, backup_path)
        self.undo_complete.emit(success, message)

    @Slot(str, str, str)
    def undo_roomfit(self, backup_path: str, source_name: str, profile_name: str) -> None:
        """Restore a RoomFit profile from backup."""
        self._dispatch(
            "undo_roomfit",
            self._do_undo_roomfit(backup_path, source_name, profile_name),
        )

    async def _do_undo_roomfit(
        self, backup_path: str, source_name: str, profile_name: str
    ) -> None:
        """Restore a RoomFit profile from backup — thin pass-through to
        RoomFitSafeWrite.undo(), which owns all orchestration (backup
        parsing, new-vs-overwrite branching, selection/enable-state
        restore to the state before the *original* push). No widget
        access here (moved out of MainWindow, docs/backlog.md item 2 Phase
        D) -- results reported via undo_complete, same signal
        undo_last_push()/_do_undo() above already use.
        """
        path = Path(backup_path) if backup_path else Path(".")
        if not path.exists() or not path.is_file():
            self.undo_complete.emit(False, "No backup available for undo")
            return

        # Outside the try/except below on purpose: a configure()-invariant
        # violation is a programmer error, not a runtime undo failure, so it
        # must propagate to _bridge_wrapper's loud crash-log path instead of
        # being caught and reported as an ordinary "Undo failed" message.
        assert self._bridge is not None, "configure() must run before undo"
        assert self._roomfit_safe_write_factory is not None, "configure() must run before undo"
        assert self._current_adapter is not None, "configure() must run before undo"

        try:
            self._bridge.progress_update.emit(f"Restoring '{profile_name}'...")
            roomfit_safe_write = self._roomfit_safe_write_factory(self._current_adapter)
            result = await roomfit_safe_write.undo(
                path, source_name, profile_name, on_stage=self._bridge.stage_changed.emit
            )
            if not result.success:
                self.undo_complete.emit(
                    False, result.error_message or "RoomFit undo verification failed"
                )
                return
            # was_new_profile determines what undo() actually did: for a
            # brand-new profile it skips the bands-restore entirely (there
            # was nothing to restore) and only re-activates the
            # previously-active profile, leaving the new one on the device.
            # Read the same metadata undo() itself used, so the message
            # matches what happened instead of always claiming a restore.
            _, _, was_new_profile, _ = parse_backup_restore_metadata(
                load_backup_json(path)
            )
            if was_new_profile is True:
                message = (
                    f"Original profile re-activated. Profile '{profile_name}' was "
                    "kept, but deactivated."
                )
            else:
                message = f"Profile '{profile_name}' restored from backup"
            self.undo_complete.emit(True, message)
        except Exception as exc:
            logger.exception("RoomFit undo failed")
            self.undo_complete.emit(False, str(exc))

    @Slot(str)
    def undo_multi_source(self, backup_paths_str: str) -> None:
        """Undo a multi-source push by restoring each source's backup."""
        self._dispatch("undo_multi_source", self._do_undo_multi_source(backup_paths_str))

    async def _do_undo_multi_source(self, backup_paths_str: str) -> None:
        """Undo a multi-source push by restoring each source's backup.

        Args:
            backup_paths_str: Semicolon-separated "source=/path" entries.

        Awaits each source's real restore via restore_entries() (rather than
        undo_last_push(), which only schedules the restore via run_async()
        and returns immediately) so succeeded/failed reflects each source's
        actual outcome, not just scheduling success. Fixed branch-quality
        review, 2026-07-18 -- see docs/corrections.md for the prior
        scheduling-vs-outcome gap this replaces. restore_entries() is the
        same restore-loop logic PrimaryWorkflowManager._do_push()'s
        auto-rollback uses (docs/backlog.md item 3), so the two paths can't
        drift apart in how they restore a source or tally the outcome.

        The on_round callback below emits progress_update/push_round_changed
        per source -- the same signal PrimaryWorkflowManager._do_push uses
        for a multi-source push -- so PushPage's round label
        ("Restoring X (i of N)" in undo mode) tracks real per-source
        progress, on top of restore_entries()'s own stage_changed emits for
        the Backup/Write/Verify stepper.

        Emits undo_multi_source_complete (succeeded, failed, message) rather
        than the shared undo_complete(bool, str) the other two undo paths
        use -- MainWindow needs the succeeded count independently of the
        failed count (clear the pushed-filters snapshot whenever
        succeeded > 0, show a success banner only when failed == 0; these
        are different conditions for a partial multi-source undo, unlike
        the single-source paths where they collapse to the same thing).
        """
        assert self._bridge is not None
        entries = decode_multi_source_backup_paths(backup_paths_str)
        if not entries:
            # No current producer of backup_paths_str can generate a
            # degenerate zero-entry string today (round-4 review finding
            # #6, 2026-07-19, PLAUSIBLE not CONFIRMED) -- but without this
            # guard, restore_entries() below never runs, failed stays 0, and
            # the success branch fires a misleading "All 0 source(s)
            # restored" banner while succeeded==0 also skips clearing the
            # stale pushed-filters snapshot. Defensive, cheap to keep
            # correct.
            logger.error(
                "Undo multi-source: no backup entries decoded from '%s'",
                backup_paths_str,
            )
            self.undo_multi_source_complete.emit(
                0, 1, "No sources to restore -- backup data was empty or malformed"
            )
            return

        def on_round(source_name: str, index: int, total: int) -> None:
            assert self._bridge is not None
            emit_round_progress(self._bridge, "Restoring", source_name, index, total)

        assert self._safe_write_factory is not None, "configure() must run before undo"
        assert self._current_adapter is not None, "configure() must run before undo"
        safe_write = self._safe_write_factory(self._current_adapter)
        succeeded, failed, _failed_entries = await restore_entries(
            safe_write, entries,
            on_stage=self._bridge.stage_changed.emit,
            on_round=on_round,
        )

        if failed == 0:
            self.undo_multi_source_complete.emit(
                succeeded, failed, f"All {succeeded} source(s) restored from backup"
            )
        else:
            self.undo_multi_source_complete.emit(
                succeeded, failed, f"{succeeded} restored, {failed} failed"
            )

    # ------------------------------------------------------------------
    # Workflow: Copy Preset to Device (Req 15.11, 17.3)
    # ------------------------------------------------------------------

    async def _read_preset_to_copy(
        self, source_name: str, preset_name: str, preset_type: str, *, is_custom: bool = False
    ) -> tuple[list[CanonicalFilter], ChannelMode, PEQSettings]:
        """Read a preset from the currently connected (source) device.

        Shared by every preset copied in a batch so the read -- which for a
        named preset briefly loads it onto the source device's live DSP and
        restores it after, see #166 -- happens exactly once per preset, not
        once per target device it's copied to (#171).

        Args:
            is_custom: True for the synthetic "Custom" row (#165c) -- reads
                the live PEQ config directly instead of a named preset, with
                no preview/restore and no live-audio blip.

        Raises:
            EmptyPresetFiltersError: if the preset resolves to zero filters.
                No widget access here (moved out of MainWindow, docs/backlog.md
                item 2 Phase D) -- raising lets the caller's existing
                exception handling treat it like any other read failure.
        """
        assert self._current_adapter is not None

        # Reading (previewing + restoring, for a named preset) -- the
        # confirmation dialog shown before this is triggered already warned
        # the user this briefly changes what's playing, see #166.
        peq_settings = await self._current_adapter.read_preset_preview_or_live(
            preset_type, source_name, preset_name, is_custom=is_custom
        )
        filters, channel_mode = extract_filters(peq_settings)

        if not filters:
            raise EmptyPresetFiltersError(f"Preset '{preset_name}' has no filters to copy")

        return filters, channel_mode, peq_settings

    async def _write_preset_to_adapter(
        self,
        target_adapter: WiiMAdapter,
        preset_name: str,
        preset_type: str,
        target_source: str,
        filters: list[CanonicalFilter],
        channel_mode: ChannelMode,
        peq_settings: PEQSettings,
    ) -> None:
        """Write+verify+save one already-read preset onto an already-connected
        target adapter, as a named preset.

        1. Writes + verifies (SafeWrite/RoomFitSafeWrite)
        2. Saves as a named preset (same name) on the target device

        Split out of `_do_copy_preset_to_device` (branch-quality review,
        2026-07-17) so `_write_preset_copies_to_devices` can connect to each
        target device once and reuse the adapter across every preset copied
        to it, instead of reconnecting + re-probing capabilities on every
        (preset, device) pair -- the connect step doesn't change between
        presets copied seconds apart in the same batch. `_do_copy_preset_to_device`
        itself was later deleted (round-4 review finding #10, 2026-07-19) once
        this method became the sole production write primitive and the older
        one had zero remaining callers.

        No per-item success banner: earlier (pre-Phase-D) code showed a
        StatusBanner success message after every individual (preset,
        device) write. That's intentionally not reproduced here -- with
        this manager, per-item feedback is the existing progress_update
        message ("Copying '{preset}' to {device}...") emitted by the
        caller, and the final result is the batch-level copy_batch_complete
        summary (shared by both copy_presets_to_devices and
        copy_local_profiles_to_devices). A banner per
        item would flicker/spam for a multi-preset, multi-device batch;
        consolidating into one summary is a deliberate UX choice, not a
        dropped feature (branch-quality review, 2026-07-17).

        Args:
            target_adapter: Already-connected WiiMAdapter for the target device.
            preset_name: Name of the preset/profile to copy.
            preset_type: "PEQ" or "RoomFit".
            target_source: Target source name on the remote device.
            filters: Filters read from the source preset (see _read_preset_to_copy).
            channel_mode: Channel mode of the source preset.
            peq_settings: Full PEQSettings read from the source preset (carries
                bands_l/bands_r for L/R mode).
        """
        assert self._safe_write_factory is not None
        assert self._roomfit_safe_write_factory is not None

        # Fail fast on a device-unsupported filter type (e.g. LP/HP on a
        # WiiM Mini) instead of sending it and trusting write+read-back
        # verification to catch the mismatch -- a device that silently
        # mis-stores an unsupported mode value could echo it back unchanged
        # and pass verification without ever applying the intended filter.
        # Applies to both PEQ and RoomFit: RoomFit reuses the exact same LV2
        # PEQ commands as user PEQ, just at EQLevel:2 (docs/wiim_api_notes.md
        # "RoomFit (Room Correction) API") -- same plugin, same filter-type
        # support. `filters` is already the combined stereo/L+R list (see
        # extract_filters()), so one check covers both channel modes.
        unsupported_types = find_unsupported_filter_types(
            filters, target_adapter.capabilities.supported_filter_types
        )
        if unsupported_types:
            raise RuntimeError(
                "Filter type(s) " + ", ".join(sorted(unsupported_types))
                + " not supported on this device"
            )

        if preset_type == "RoomFit":
            # RoomFit: write as RoomFit profile on target (smoke #34, #79),
            # verified and rolled back on mismatch via RoomFitSafeWrite --
            # same protocol as the main Push flow (smoke #153), not a bare
            # write_roomfit() with no verification at all.
            roomfit_safe_write = self._roomfit_safe_write_factory(target_adapter)
            # Use the L/R bands just read from the source preset -- not
            # wizard state, which may be stale or unrelated to this preset
            # (e.g. never populated in this session).
            # resolve_roomfit_channel_kwargs() rejects an incomplete split
            # the same way build_peq_settings() already does for the PEQ
            # branch below (via resolve_channel_split) -- without this, a
            # source preset with one legitimately-empty channel (a valid
            # device read-state, see WiiMAdapter._parse_lr) could be
            # silently copied to a target device with an incomplete L/R
            # split, when the equivalent PEQ copy is already rejected.
            # Shared with primary_workflows._do_push's RoomFit branch,
            # which hand-rolled this same is_lr/require_lr_filters check
            # independently before (round-4 review finding #8, 2026-07-19).
            # Raises ValueError, caught by the per-preset try/except in
            # _write_preset_copies_to_devices's caller loop, same as the
            # RuntimeError below for a verification failure.
            roomfit_filters_l, roomfit_filters_r = resolve_roomfit_channel_kwargs(
                channel_mode, peq_settings.bands_l, peq_settings.bands_r
            )
            result = await roomfit_safe_write.execute(
                target_source, preset_name, filters,
                channel_mode=channel_mode,
                filters_l=roomfit_filters_l,
                filters_r=roomfit_filters_r,
            )
            if not result.success:
                raise RuntimeError(
                    result.error_message or "RoomFit copy verification failed"
                )
        else:
            # PEQ: write filters (verified via SafeWrite, smoke #153), then
            # save as named PEQ preset -- only if the write actually verified.
            settings = build_peq_settings(
                target_source, filters, channel_mode,
                filters_l=peq_settings.bands_l,
                filters_r=peq_settings.bands_r,
            )
            safe_write = self._safe_write_factory(target_adapter)
            result = await safe_write.execute(target_source, settings)
            if not result.success:
                raise RuntimeError(
                    result.error_message or "PEQ copy verification failed"
                )
            await target_adapter.save_peq_profile(
                target_source, preset_name
            )

    async def _close_client_best_effort(
        self, client: WiiMHttpClient, device_ip: str
    ) -> None:
        """Close a target-device HTTP client, swallowing any close() failure.

        A close() failure must not itself escape and abort the rest of a
        copy batch -- that would skip copy_batch_complete for every
        remaining device, leaving MainWindow's _copy_batch_failures
        unresolved and leaking into the next batch's failure dialog,
        defeating _copy_in_progress's whole purpose. Shared by both call
        sites in _write_preset_copies_to_devices below (round-5 review
        finding #3, 2026-08-11).
        """
        try:
            await client.close()
        except Exception:
            logger.exception("Closing connection to %s failed", device_ip)

    async def _write_preset_copies_to_devices(
        self,
        reads: list[tuple[str, str, list[CanonicalFilter], ChannelMode, PEQSettings]],
        target_devices: list[DeviceInfo],
        target_source: str,
    ) -> tuple[int, int]:
        """Write each already-read preset to every target device.

        Shared by `_do_copy_presets_batch_multi` (reads come from the live
        source device) and `_do_copy_local_profiles_to_devices` (reads come
        from locally saved Profiles, no source device involved) -- both
        write via the identical `_write_preset_to_adapter` primitive per
        (read, device) pair, so that loop/exception-handling/progress-emit
        logic lives exactly once.

        Connects to each target device once (outer loop) and reuses that
        connection across every preset copied to it, instead of
        reconnecting + re-probing per (preset, device) pair (branch-quality
        review, 2026-07-17) -- a device that fails to connect/probe counts
        all its presets as failed in one step rather than retrying the
        connection once per preset.

        Args:
            reads: List of (preset_name, preset_type, filters, channel_mode,
                peq_settings) tuples, one per already-read preset.
            target_devices: List of discovered device objects to copy to.
            target_source: Target source name on each remote device.

        Returns:
            Tuple of (succeeded, failed) copy-operation counts.
        """
        assert self._bridge is not None
        assert self._wiim_http_client_factory is not None
        assert self._capability_prober_factory is not None
        assert self._target_adapter_factory is not None

        succeeded = 0
        failed = 0

        for device in target_devices:
            self._bridge.progress_update.emit(f"Connecting to {device.name}...")
            # None until the factory call below succeeds -- may still be
            # None when the except branch runs, if the factory call itself
            # is what raised.
            target_client: WiiMHttpClient | None = None
            try:
                target_client = self._wiim_http_client_factory(device.ip)
                target_caps = await self._capability_prober_factory(target_client).probe()
                target_adapter = self._target_adapter_factory(target_client, target_caps)
            except Exception as exc:
                logger.exception("Connect to %s failed", device.ip)
                # Only worth reporting as a skip if there was anything to
                # skip -- every preset in this batch may have already
                # failed to read from the source, in which case this
                # device was never going to receive anything regardless of
                # whether it was reachable.
                if reads:
                    self.copy_item_failed.emit(
                        f"{device.name}: could not connect ({exc}) -- "
                        f"all item(s) skipped for this device"
                    )
                failed += len(reads)
                if target_client is not None:
                    await self._close_client_best_effort(target_client, device.ip)
                continue

            try:
                for preset_name, preset_type, filters, channel_mode, peq_settings in reads:
                    self._bridge.progress_update.emit(
                        f"Copying '{preset_name}' to {device.name}..."
                    )
                    try:
                        await self._write_preset_to_adapter(
                            target_adapter, preset_name, preset_type, target_source,
                            filters, channel_mode, peq_settings,
                        )
                        succeeded += 1
                    except Exception as exc:
                        logger.exception(
                            "Copy preset '%s' to %s failed", preset_name, device.ip
                        )
                        self.copy_item_failed.emit(
                            f"{device.name} -- '{preset_name}': {exc}"
                        )
                        failed += 1
            finally:
                await self._close_client_best_effort(target_client, device.ip)

        return succeeded, failed

    @asynccontextmanager
    async def _copy_batch_guard(self) -> AsyncIterator[None]:
        """Wrap a copy-batch coroutine body, guaranteeing _copy_in_progress
        clears no matter how the body exits.

        Shared by _do_copy_presets_batch_multi and
        _do_copy_local_profiles_to_devices -- previously each hand-rolled an
        identical try/finally; a future change to this guard (e.g. also
        covering some new exception path) would have had to be applied
        twice by hand (round-5 review finding #3, 2026-08-11).
        """
        try:
            yield
        finally:
            self._copy_in_progress = False

    @Slot(list, list, str, str)
    def copy_presets_to_devices(
        self,
        items: list[Any],
        target_devices: list[DeviceInfo],
        source_name: str,
        target_source: str,
    ) -> None:
        """Copy presets to multiple target devices (smoke #73 fix).

        Ignores a call while another copy batch (from either this method or
        copy_local_profiles_to_devices) is still in flight -- see
        _copy_in_progress's comment in __init__ for why the UI's
        button-disable alone doesn't already prevent this.
        """
        if self._copy_in_progress:
            logger.warning(
                "copy_presets_to_devices ignored -- a copy batch is already in progress"
            )
            return
        self._copy_in_progress = True
        self._dispatch(
            "copy_presets_to_devices",
            self._do_copy_presets_batch_multi(
                items, target_devices, source_name, target_source
            ),
        )

    async def _do_copy_presets_batch_multi(
        self,
        items: list[Any],
        target_devices: list[DeviceInfo],
        source_name: str,
        target_source: str,
    ) -> None:
        """Copy presets to multiple target devices (smoke #73 fix).

        Iterates over all presets, reading (and previewing) each once from the
        source device, then writes that single read to every target device.
        Presets are the outer loop and devices the inner loop specifically so
        the read/preview step -- which briefly flips the source device's live
        audio, see #166 -- happens once per preset rather than once per
        (preset, device) pair (#171). No widget access here (moved out of
        MainWindow, docs/backlog.md item 2 Phase D) -- results reported via
        copy_batch_complete.

        Args:
            items: List of PresetItem objects to copy.
            target_devices: List of discovered device objects to copy to.
            source_name: Source device's own active source, to read the
                presets from (resolved by the caller from wizard state --
                this manager has none of its own).
            target_source: Target source name on each remote device.
        """
        async with self._copy_batch_guard():
            assert self._bridge is not None

            reads: list[tuple[str, str, list[CanonicalFilter], ChannelMode, PEQSettings]] = []
            read_failed = 0
            skipped = 0

            for item in items:
                preset_name = getattr(item, "name", "")
                preset_type = getattr(item, "preset_type", "PEQ")
                is_custom = getattr(item, "is_custom", False)
                if not preset_name:
                    # Never attempted -- not a read failure, so it must not
                    # count toward n_items below either, or the batch-complete
                    # totals (n_items * n_devices vs succeeded + failed) stop
                    # matching (round-4 review finding #5, 2026-07-19).
                    skipped += 1
                    continue

                self._bridge.progress_update.emit(f"Reading '{preset_name}'...")
                try:
                    filters, channel_mode, peq_settings = await self._read_preset_to_copy(
                        source_name, preset_name, preset_type, is_custom=is_custom
                    )
                except Exception as exc:
                    logger.exception("Read preset '%s' for copy failed", preset_name)
                    self._bridge.progress_update.emit(
                        f"Failed to read '{preset_name}' -- skipping"
                    )
                    self.copy_item_failed.emit(
                        f"'{preset_name}': could not read from source device "
                        f"({exc}) -- skipped for all target devices"
                    )
                    read_failed += len(target_devices)
                    continue
                reads.append((preset_name, preset_type, filters, channel_mode, peq_settings))

            succeeded, write_failed = await self._write_preset_copies_to_devices(
                reads, target_devices, target_source
            )
            failed = read_failed + write_failed

            self.copy_batch_complete.emit(
                len(items) - skipped, len(target_devices), succeeded, failed, "preset"
            )

    @Slot(list, str, list, str)
    def copy_local_profiles_to_devices(
        self,
        profiles: list[
            tuple[
                str,
                ChannelMode,
                list[CanonicalFilter] | None,
                list[CanonicalFilter] | None,
                list[CanonicalFilter] | None,
            ]
        ],
        preset_type: str,
        target_devices: list[DeviceInfo],
        target_source: str,
    ) -> None:
        """Copy one or more locally saved Profiles' raw filter fields to devices.

        Takes each Profile's fields as-is (not a pre-built PEQSettings) so the
        build_peq_settings()/extract_filters() normalization -- and its
        ValueError case for an incomplete L/R split -- happens here rather
        than in MainWindow, matching how `_do_copy_presets_batch_multi`
        handles a live-device read failure: reported through
        copy_batch_complete, not a synchronous caller-side try/except.

        Ignores a call while another copy batch (from either this method or
        copy_presets_to_devices) is still in flight -- see
        _copy_in_progress's comment in __init__ for why the UI's
        button-disable alone doesn't already prevent this.
        """
        if self._copy_in_progress:
            logger.warning(
                "copy_local_profiles_to_devices ignored -- a copy batch is "
                "already in progress"
            )
            return
        self._copy_in_progress = True
        self._dispatch(
            "copy_local_profiles_to_devices",
            self._do_copy_local_profiles_to_devices(
                profiles, preset_type, target_devices, target_source,
            ),
        )

    async def _do_copy_local_profiles_to_devices(
        self,
        profiles: list[
            tuple[
                str,
                ChannelMode,
                list[CanonicalFilter] | None,
                list[CanonicalFilter] | None,
                list[CanonicalFilter] | None,
            ]
        ],
        preset_type: str,
        target_devices: list[DeviceInfo],
        target_source: str,
    ) -> None:
        """Copy one or more locally saved profiles' filters to devices.

        Unlike `_do_copy_presets_batch_multi`, there's no source device to
        read from -- the filters already came from local Profiles -- so
        this builds/validates a PEQSettings from each Profile's raw fields
        (the "read" step's equivalent here, one per profile) before the
        `reads` list around the same shared `_write_preset_copies_to_devices`
        write primitive -- same batching shape as
        `_do_copy_presets_batch_multi`'s per-item read-failure handling. No
        widget access here (moved out of MainWindow, docs/backlog.md item 2
        Phase D) -- results reported via copy_batch_complete.

        Args:
            profiles: List of (name, channel_mode, filters, filters_l,
                filters_r) tuples, one per selected local Profile.
            preset_type: "PEQ" or "RoomFit", chosen once via
                PresetTypeDialog and applied to every profile in the batch.
            target_devices: List of discovered device objects to copy to.
            target_source: Target source name on each remote device.
        """
        async with self._copy_batch_guard():
            assert self._bridge is not None

            reads: list[tuple[str, str, list[CanonicalFilter], ChannelMode, PEQSettings]] = []
            build_failed = 0

            for profile_name, channel_mode, filters, filters_l, filters_r in profiles:
                try:
                    peq_settings = build_peq_settings(
                        target_source, filters or [], channel_mode,
                        filters_l=filters_l, filters_r=filters_r,
                    )
                except ValueError as exc:
                    logger.warning(
                        "Build PEQSettings for local profile copy '%s' failed: %s",
                        profile_name, exc,
                    )
                    self._bridge.progress_update.emit(
                        f"Copy failed for '{profile_name}': {exc}"
                    )
                    self.copy_item_failed.emit(
                        f"'{profile_name}': {exc} -- skipped for all target devices"
                    )
                    build_failed += len(target_devices)
                    continue
                resolved_filters, resolved_channel_mode = extract_filters(peq_settings)
                reads.append((
                    profile_name, preset_type, resolved_filters,
                    resolved_channel_mode, peq_settings,
                ))

            # Skip connecting to target devices entirely when every profile in
            # the batch failed to build -- there's nothing to write, and
            # _write_preset_copies_to_devices would otherwise still probe/
            # connect to each target device for no reason.
            if reads:
                succeeded, write_failed = await self._write_preset_copies_to_devices(
                    reads, target_devices, target_source
                )
            else:
                succeeded, write_failed = 0, 0

            self.copy_batch_complete.emit(
                len(profiles), len(target_devices), succeeded,
                build_failed + write_failed, "profile",
            )

    # ------------------------------------------------------------------
    # Workflow: Source-Slot Overview (#194 follow-up diagnostic)
    # ------------------------------------------------------------------

    @Slot()
    def fetch_source_slots(self) -> None:
        """Fetch the current device's live per-source PEQ slot overview.

        Read-only diagnostic (EQGetSourceModes) -- surfaces garbage slots
        left behind by invalid source_name writes. Not a new MainWindow
        `_do_*` method: this orchestration lives here, per backlog #7's
        rule that new orchestration must not grow MainWindow further.

        No `self._bridge is None` guard here (unlike `_dispatch()`'s
        assert): configure() now runs eagerly in MainWindow.__init__, so
        `self._bridge` is never None by the time a user action can reach
        this slot -- "no device connected" is `_do_fetch_source_slots()`'s
        own `self._current_adapter is None` check below, a separate
        per-connect concern configure() doesn't set.
        """
        self._dispatch(
            "fetch_source_slots", self._do_fetch_source_slots(), cancellable=True
        )

    async def _do_fetch_source_slots(self) -> None:
        if self._current_adapter is None:
            self.source_slots_error.emit("No device connected")
            return
        try:
            slots = await self._current_adapter.get_source_slot_overview()
            self.source_slots_ready.emit(slots)
        except Exception as exc:
            logger.warning("Source-slot overview fetch failed: %s", exc)
            self.source_slots_error.emit(str(exc))
