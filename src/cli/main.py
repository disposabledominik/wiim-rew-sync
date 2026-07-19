"""
CLI entry point — argparse-driven proof-of-concept commands.

Exercises the full stack (discovery, capability probing, PEQ read, REW
translation) without a GUI. Invoked via the ``wiim-rew-sync`` console script
defined in ``pyproject.toml`` (``src.cli.main:main``) or with
``python -m src.cli.main``.

Commands:
  list-devices      Discover and list WiiM devices on the LAN.
  get-filters       Read PEQ filters from a device and print them.
  dry-run-import    Parse a REW file and preview the translation (no network).
  set-filters       Write REW filters to a device with safe-write protocol.

Requirements: 1.1, 1.6, 4.1, 4.2, 4.3, 5.1-5.10, 12.1, 12.2, 12.3, 6.7, 6.8
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from src.adapters.capability_prober import CapabilityProber
from src.adapters.command_queue import WiiMCommandQueue
from src.adapters.safe_write import RoomFitSafeWrite, SafeWrite, WriteResult
from src.adapters.wiim_adapter import WiiMAdapter
from src.adapters.wiim_commands import encode_wiim_command
from src.adapters.wiim_http import WiiMHttpClient
from src.discovery.discovery_module import DiscoveryModule
from src.models.canonical import CanonicalFilter
from src.models.capabilities import DeviceInfo
from src.models.channel_mode import ChannelMode
from src.models.constants import DEFAULT_SOURCE
from src.models.errors import (
    ParseError,
    RoomFitUnsupportedError,
    ValidationError,
    WiiMConnectionError,
    WiiMResponseError,
)
from src.models.peq import PEQSettings
from src.repository.backup_manager import BackupManager
from src.translator import TranslationEngine
from src.utils.app_dirs import get_app_data_dir
from src.utils.version import get_app_version

logger = logging.getLogger("wiim_rew_sync.app")

_FILTER_HEADERS = ["Band", "Type", "Frequency (Hz)", "Gain (dB)", "Q"]


# ---------------------------------------------------------------------------
# Table formatting (no external dependency)
# ---------------------------------------------------------------------------


def _format_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render *rows* as a fixed-width text table with a header separator."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    column_sep = " | "
    header_line = column_sep.join(h.ljust(widths[i]) for i, h in enumerate(headers))
    divider = "-+-".join("-" * widths[i] for i in range(len(headers)))

    lines = [header_line, divider]
    lines.extend(
        column_sep.join(cell.ljust(widths[i]) for i, cell in enumerate(row))
        for row in rows
    )
    return "\n".join(lines)


def _filter_rows(bands: list[CanonicalFilter]) -> list[list[str]]:
    """Build table rows (1-based band number) for a list of canonical filters."""
    return [
        [
            str(index),
            f"?{band.raw_mode}" if band.type == "UNKNOWN" else band.type,
            f"{band.frequency_hz:.2f}",
            f"{band.gain_db:.2f}",
            f"{band.q:.3f}",
        ]
        for index, band in enumerate(bands, start=1)
    ]


def _select_bands(settings: PEQSettings, channel: str) -> list[CanonicalFilter]:
    """Return the band list matching the requested *channel*.

    If channel is "stereo" but the device is in L/R mode, auto-select left.
    If channel is "left"/"right", use that directly.
    If no explicit channel and device is in L/R mode, print both channels.
    """
    if channel == "left":
        return settings.bands_l
    if channel == "right":
        return settings.bands_r
    # "stereo" requested (default)
    if settings.channel_mode == ChannelMode.LR and not settings.bands:
        # Device is in L/R mode — fall back to left channel
        return settings.bands_l
    return settings.bands


# ---------------------------------------------------------------------------
# Async stack helpers
# ---------------------------------------------------------------------------


async def _discover(timeout: float) -> list[DeviceInfo]:
    """Run the full discovery sequence and return the device list."""
    module = DiscoveryModule(timeout=timeout)
    return await module.discover()


async def _read_filters(
    device: str, source: str | None, timeout: float
) -> PEQSettings:
    """Probe capabilities and read PEQ settings for *device*.

    Resolves the source name to *source* when provided, otherwise defaults
    to ``wifi`` with a warning.
    """
    client = WiiMHttpClient(device, timeout=timeout)
    try:
        capabilities = await CapabilityProber(client).probe()
        resolved_source = source or DEFAULT_SOURCE
        if source is None:
            print(
                f"Note: No --source specified, defaulting to '{resolved_source}'. "
                f"Use --source to select a specific input "
                f"(e.g. wifi, bluetooth, line-in, optical, hdmi, ethernet).",
                file=sys.stderr,
            )
        adapter = WiiMAdapter(client, capabilities)
        return await adapter.read_peq(resolved_source)
    finally:
        await client.close()


async def _list_peq_profiles(device: str, timeout: float) -> list[dict[str, str]]:
    """Probe device and list PEQ profiles."""
    client = WiiMHttpClient(device, timeout=timeout)
    try:
        capabilities = await CapabilityProber(client).probe()
        if not capabilities.supports_profile_enumeration:
            raise WiiMResponseError(
                "Device does not support profile enumeration."
            )
        adapter = WiiMAdapter(client, capabilities)
        return await adapter.list_peq_profiles(DEFAULT_SOURCE)
    finally:
        await client.close()


# Confirmed source names from hardware testing (2026-06-14).
# These are the actual labels used when the associated source is selected.
# NOTE: The API accepts any name — phantom sources return default data.
_CANONICAL_SOURCES = [
    "wifi", "bluetooth", "line-in", "optical", "HDMI", "auxIn",
]


async def _probe_sources(
    device: str, timeout: float
) -> list[tuple[str, str, bool]]:
    """Probe known source names and return those that exist with non-default data.

    Returns a list of (source_name, channel_mode, has_custom_data) tuples.
    A source is considered to have custom data if any band has non-zero gain
    or a non-PEAK/non-OFF filter type.
    """
    client = WiiMHttpClient(device, timeout=timeout)
    results: list[tuple[str, str, bool]] = []
    try:
        for source in _CANONICAL_SOURCES:
            try:
                resp = await client.command(
                    encode_wiim_command("EQGetLV2SourceBandEx", source_name=source)
                )
                if not isinstance(resp, dict) or "channelMode" not in resp:
                    continue
                mode = str(resp["channelMode"])
                # Check if any band has non-default values
                bands = resp.get("EQBand", resp.get("EQBandL", []))
                has_custom = _has_custom_data(bands)
                results.append((source, mode, has_custom))
            except Exception:
                logger.debug("Source probe failed for %s", source)
                continue
    finally:
        await client.close()
    return results


# Threshold below which a gain is considered indistinguishable from silence
# (i.e. "not customized"), for this diagnostic probe only. Deliberately not
# fp_compare.GAIN_TOLERANCE_DB (0.05 dB) -- that constant answers a different
# question (does a read-back gain match an intended one within the device's
# write/verify precision), and swapping it in here would silently reclassify
# any gain in (0.001, 0.05] dB from "customized" to "default."
_ZERO_GAIN_EPSILON = 0.001


def _has_custom_data(bands: list[dict[str, object]]) -> bool:
    """Check if band data contains any non-default values.

    Default = all modes are PEAK (1) or OFF (-1), all gains are 0.0.
    """
    for entry in bands:
        param_name = str(entry.get("param_name", ""))
        value = float(str(entry.get("value", 0.0)))
        if param_name.endswith("_gain") and abs(value) > _ZERO_GAIN_EPSILON:
            return True
        if param_name.endswith("_mode") and value not in (-1.0, 1.0):
            # Non-default mode (LS, HS, LP, HP)
            return True
    return False


# ---------------------------------------------------------------------------
# Command handlers (each returns an int exit code)
# ---------------------------------------------------------------------------


def cmd_list_devices(timeout: float) -> int:
    """Discover devices and print a table. Exit code 0 regardless of results."""
    devices = asyncio.run(_discover(timeout))

    if not devices:
        print("No devices found.")
        return 0

    rows = [
        [device.name, device.ip, device.model, device.firmware]
        for device in devices
    ]
    print(_format_table(["Name", "IP", "Model", "Firmware"], rows))
    return 0


def cmd_list_peq_profiles(device: str, timeout: float) -> int:
    """List PEQ profiles stored on a device. Exit 0 on success, 1 on error."""
    try:
        profiles = asyncio.run(_list_peq_profiles(device, timeout))
    except (WiiMConnectionError, WiiMResponseError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not profiles:
        print("No PEQ profiles found on device.")
        return 0

    rows = [
        [entry["Name"], entry["channelMode"]]
        for entry in profiles
    ]
    print(_format_table(["Name", "Channel Mode"], rows))
    return 0


def cmd_list_sources(device: str, timeout: float) -> int:
    """Probe and list available PEQ sources for a device. Exit code 0."""
    try:
        sources = asyncio.run(_probe_sources(device, timeout))
    except (WiiMConnectionError, WiiMResponseError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not sources:
        print("No PEQ sources found on device.")
        return 0

    rows = [
        [name, mode, "Yes" if has_custom else "-"]
        for name, mode, has_custom in sources
    ]
    print(_format_table(["Source", "Channel Mode", "Has Custom EQ"], rows))
    return 0


def cmd_get_filters(
    device: str, source: str | None, channel: str, timeout: float
) -> int:
    """Read and print PEQ filters for a device. Exit 0 on success, 1 on error."""
    try:
        settings = asyncio.run(_read_filters(device, source, timeout))
    except (WiiMConnectionError, WiiMResponseError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Source: {settings.source_name} | Mode: {settings.channel_mode.value}")
    print()

    if settings.channel_mode == ChannelMode.LR and channel == "stereo":
        # In L/R mode, show both channels when no explicit channel requested
        print("Left channel:")
        print(_format_table(_FILTER_HEADERS, _filter_rows(settings.bands_l)))
        print()
        print("Right channel:")
        print(_format_table(_FILTER_HEADERS, _filter_rows(settings.bands_r)))
    else:
        bands = _select_bands(settings, channel)
        print(_format_table(_FILTER_HEADERS, _filter_rows(bands)))
    return 0


def cmd_dry_run_import(file: str) -> int:
    """Parse a REW file and preview the translation. No network calls.

    Exit code 0 on a valid file, 1 on parse/validation error.
    """
    path = Path(file)

    try:
        filters = TranslationEngine.parse_rew_file(path)
    except (ParseError, ValidationError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Error: cannot read file '{file}': {exc}", file=sys.stderr)
        return 1

    # Generate the WiiM band array purely to surface clamping warnings; the
    # result array is discarded because no write occurs in dry-run mode.
    _band_array, warnings = TranslationEngine.generate_wiim_band_array(filters)

    print(_format_table(_FILTER_HEADERS, _filter_rows(filters)))

    if warnings:
        print()
        print("WiiM range warnings:")
        for warning in warnings:
            print(f"  - [{warning.field}] {warning.message}")

    return 0


# ---------------------------------------------------------------------------
# set-filters — safe write protocol
# ---------------------------------------------------------------------------


async def _set_filters(
    device: str, source: str | None, file: str, channel: str, timeout: float,
    save_as: str | None = None,
    file_right: str | None = None,
) -> WriteResult:
    """Parse REW file(s), probe device, run safe write protocol."""
    path = Path(file)
    filters = TranslationEngine.parse_rew_file(path)

    # Build PEQSettings from parsed filters based on channel mode
    if file_right is not None:
        # L/R mode: --file is left channel, --file-right is right channel
        filters_r = TranslationEngine.parse_rew_file(Path(file_right))
        settings = PEQSettings(
            source_name=source or DEFAULT_SOURCE,
            channel_mode=ChannelMode.LR,
            bands_l=filters,
            bands_r=filters_r,
        )
    elif channel in ("left", "right"):
        settings = PEQSettings(
            source_name=source or DEFAULT_SOURCE,
            channel_mode=ChannelMode.LR,
            bands_l=filters if channel == "left" else [],
            bands_r=filters if channel == "right" else [],
        )
    else:
        settings = PEQSettings(
            source_name=source or DEFAULT_SOURCE,
            channel_mode=ChannelMode.STEREO,
            bands=filters,
        )

    client = WiiMHttpClient(device, timeout=timeout)
    try:
        print("Probing device capabilities...")
        capabilities = await CapabilityProber(client).probe()

        resolved_source = source or (
            capabilities.source_names[0]
            if capabilities.source_names
            else DEFAULT_SOURCE
        )

        adapter = WiiMAdapter(client, capabilities)
        backup_manager = BackupManager(get_app_data_dir())

        # Use command queue for sequential writes if batch is confirmed
        # unsupported. ``supports_batch_write`` is tri-state (True/False/
        # None="not yet determined" -- there is no connect-time write probe
        # anymore); None must NOT be treated as False, or every first-ever
        # write to a device loses the batch-write attempt WiiMAdapter's
        # write path is designed to make.
        queue: WiiMCommandQueue | None = None
        if capabilities.supports_batch_write is False:
            queue = WiiMCommandQueue(client)
            await queue.start()

        safe_write = SafeWrite(adapter, backup_manager, queue)

        print("Backing up...")
        print("Writing...")
        result = await safe_write.execute(resolved_source, settings)

        if result.success:
            print("Verifying...")
            print("Done!")
            # Save as device preset only after verified write
            if save_as:
                await adapter.save_peq_profile(resolved_source, save_as)
                print(f"Saved as device preset: {save_as}")
        elif result.rollback_success is True:
            print("Verifying...")
            print("ROLLBACK: verification failed, original state restored.")
        else:
            print("Verifying...")
            print("ROLLBACK FAILED: manual recovery required.")

        if queue is not None:
            await queue.drain_and_stop()

        return result
    finally:
        await client.close()


def cmd_set_filters(
    device: str, source: str | None, file: str, channel: str, timeout: float,
    save_as: str | None = None,
    file_right: str | None = None,
) -> int:
    """Write REW filters to a device using the safe-write protocol.

    Exit code 0 on verified success, 1 on any failure.
    """
    try:
        result = asyncio.run(
            _set_filters(
                device, source, file, channel, timeout,
                save_as=save_as, file_right=file_right,
            )
        )
    except (WiiMConnectionError, WiiMResponseError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (ParseError, ValidationError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Error: cannot read file '{file}': {exc}", file=sys.stderr)
        return 1

    if result.success:
        print("Verified successfully.")
        return 0

    if result.rollback_success is True:
        print("Verification FAILED. Rolled back to previous state.")
        return 1

    # Rollback also failed — CRITICAL
    print(
        f"CRITICAL: verification and rollback both failed. "
        f"Manual recovery required. Backup: {result.backup_path}",
        file=sys.stderr,
    )
    return 1


# ---------------------------------------------------------------------------
# list-roomfit-profiles — list RoomFit profiles on device
# ---------------------------------------------------------------------------


async def _list_roomfit_profiles(device: str, timeout: float) -> list[dict[str, str]]:
    """Probe capabilities and list RoomFit profiles."""
    client = WiiMHttpClient(device, timeout=timeout)
    try:
        capabilities = await CapabilityProber(client).probe()
        adapter = WiiMAdapter(client, capabilities)
        return await adapter.list_roomfit_profiles("wifi")
    finally:
        await client.close()


def cmd_list_roomfit_profiles(device: str, timeout: float) -> int:
    """List RoomFit profiles on a device. Exit 0 on success, 1 on error."""
    try:
        profiles = asyncio.run(_list_roomfit_profiles(device, timeout))
    except RoomFitUnsupportedError:
        print(
            "Dedicated RoomFit filters not available on this device "
            "(room correction uses PEQ bands instead).",
            file=sys.stderr,
        )
        return 1
    except (WiiMConnectionError, WiiMResponseError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not profiles:
        print("No RoomFit profiles found.")
        return 0

    rows = [
        [
            p.get("Name", ""),
            p.get("channelMode", ""),
            p.get("Type", ""),
        ]
        for p in profiles
    ]
    print(_format_table(["Name", "Channel Mode", "Type"], rows))
    return 0


# ---------------------------------------------------------------------------
# get-roomfit-filters — read RoomFit bands from a named profile
# ---------------------------------------------------------------------------


async def _get_roomfit_filters(
    device: str, source: str, profile_name: str, timeout: float
) -> PEQSettings:
    """Probe capabilities, load a RoomFit profile, and read its bands.

    Uses read_roomfit_preset_preview(), not read_roomfit() directly --
    reading a named profile requires EQv2SourceLoad-ing it into the buffer
    first, which makes it the device's active/selected profile as a side
    effect (#175/#178). The preview variant restores whatever was active
    beforehand, so running this CLI command doesn't silently change what's
    selected on the user's device.
    """
    client = WiiMHttpClient(device, timeout=timeout)
    try:
        capabilities = await CapabilityProber(client).probe()
        adapter = WiiMAdapter(client, capabilities)
        return await adapter.read_roomfit_preset_preview(source, profile_name)
    finally:
        await client.close()


def cmd_get_roomfit_filters(
    device: str, source: str, profile_name: str, timeout: float
) -> int:
    """Read RoomFit bands for a named profile. Exit 0 on success, 1 on error."""
    try:
        settings = asyncio.run(
            _get_roomfit_filters(device, source, profile_name, timeout)
        )
    except RoomFitUnsupportedError:
        print(
            "Dedicated RoomFit filters not available on this device "
            "(room correction uses PEQ bands instead).",
            file=sys.stderr,
        )
        return 1
    except (WiiMConnectionError, WiiMResponseError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(
        f"RoomFit profile: {profile_name} | Source: {source}"
        f" | Mode: {settings.channel_mode.value}"
    )
    print()

    if settings.channel_mode == ChannelMode.LR:
        print("Left channel:")
        print(_format_table(_FILTER_HEADERS, _filter_rows(settings.bands_l)))
        print()
        print("Right channel:")
        print(_format_table(_FILTER_HEADERS, _filter_rows(settings.bands_r)))
    else:
        print(_format_table(_FILTER_HEADERS, _filter_rows(settings.bands)))
    return 0


# ---------------------------------------------------------------------------
# set-roomfit-filters — write REW filters to a RoomFit profile
# ---------------------------------------------------------------------------


async def _set_roomfit_filters(
    device: str,
    source: str,
    profile_name: str,
    file: str,
    timeout: float,
) -> WriteResult:
    """Parse REW file, probe device, write filters to a RoomFit profile.

    Verified and rolled back on mismatch via RoomFitSafeWrite -- same five-
    step safety protocol as the GUI's RoomFit push and the PEQ CLI command
    above, not a bare write_roomfit() with no verification (smoke #153).
    """
    path = Path(file)
    filters = TranslationEngine.parse_rew_file(path)

    client = WiiMHttpClient(device, timeout=timeout)
    try:
        print("Probing device capabilities...")
        capabilities = await CapabilityProber(client).probe()
        adapter = WiiMAdapter(client, capabilities)
        backup_manager = BackupManager(get_app_data_dir())
        roomfit_safe_write = RoomFitSafeWrite(adapter, backup_manager)

        print(f"Writing to RoomFit profile '{profile_name}'...")
        result = await roomfit_safe_write.execute(
            source, profile_name, filters, channel_mode=ChannelMode.STEREO
        )

        print("Verifying...")
        if result.success:
            print("Done!")
        elif result.rollback_success is True:
            print(f"ROLLBACK: {result.error_message}")
        else:
            print(f"ROLLBACK FAILED: {result.error_message}")

        return result
    finally:
        await client.close()


def cmd_set_roomfit_filters(
    device: str,
    source: str,
    profile_name: str,
    file: str,
    timeout: float,
) -> int:
    """Write REW filters to a RoomFit profile. Exit 0 on success, 1 on error."""
    try:
        result = asyncio.run(
            _set_roomfit_filters(device, source, profile_name, file, timeout)
        )
    except RoomFitUnsupportedError:
        # write_roomfit()'s gate is read-support only (no write-probe exists,
        # 2026-07-10 redesign) -- a device with confirmed read support gets a
        # real write attempt as its own capability test, so this message only
        # fires for devices that never confirmed RoomFit read support at all.
        print(
            "Dedicated RoomFit filters not available on this device "
            "(room correction uses PEQ bands instead).",
            file=sys.stderr,
        )
        return 1
    except (WiiMConnectionError, WiiMResponseError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (ParseError, ValidationError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"Error: cannot read file '{file}': {exc}", file=sys.stderr)
        return 1

    if not result.success:
        print(f"Error: RoomFit profile '{profile_name}' was not saved.", file=sys.stderr)
        return 1

    print(f"RoomFit profile '{profile_name}' saved successfully.")
    return 0


# ---------------------------------------------------------------------------
# peq-toggle — enable or disable PEQ on a source
# ---------------------------------------------------------------------------


async def _peq_toggle(device: str, source: str, state: str, timeout: float) -> None:
    """Enable or disable PEQ on a source."""
    client = WiiMHttpClient(device, timeout=timeout)
    try:
        capabilities = await CapabilityProber(client).probe()
        adapter = WiiMAdapter(client, capabilities)
        if state == "on":
            await adapter.enable_peq(source)
        else:
            await adapter.disable_peq(source)
    finally:
        await client.close()


def cmd_peq_toggle(device: str, source: str, state: str, timeout: float) -> int:
    """Enable or disable PEQ on a source. Exit 0 on success, 1 on error."""
    try:
        asyncio.run(_peq_toggle(device, source, state, timeout))
    except (WiiMConnectionError, WiiMResponseError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if state == "on":
        print(f"PEQ enabled on {source}")
    else:
        print(f"PEQ disabled on {source}")
    return 0


# ---------------------------------------------------------------------------
# load-preset — load a PEQ preset onto one or more sources
# ---------------------------------------------------------------------------


async def _load_preset(
    device: str, preset: str, sources: list[str], timeout: float
) -> dict[str, bool]:
    """Load a PEQ preset onto each source. Returns {source: success} mapping.

    Does NOT use Safe_Write_Protocol — loading a preset is a single atomic API
    call (EQv2SourceLoad), not a raw band write.

    EQv2SourceLoad turns PEQ on for the source if it was off (docs/wiim_api_notes.md
    RoomFit rule 4 -- confirmed for PEQ too, docs/corrections.md #192). This command's
    purpose is to make the preset active, so that is the intended effect here, not a
    side effect to guard against -- unlike read_peq_preset_preview()'s preview/restore
    use of the same underlying command.

    Domain rule: PEQ presets are global and loadable onto any source (rules.md rule 9).
    """
    client = WiiMHttpClient(device, timeout=timeout)
    results: dict[str, bool] = {}
    try:
        capabilities = await CapabilityProber(client).probe()
        adapter = WiiMAdapter(client, capabilities)

        for source in sources:
            try:
                await adapter.load_peq_profile(source, preset)
                results[source] = True
            except (WiiMConnectionError, WiiMResponseError) as exc:
                logger.debug("load_peq_profile failed for source %s: %s", source, exc)
                results[source] = False
    finally:
        await client.close()
    return results


def cmd_load_preset(device: str, preset: str, sources: list[str], timeout: float) -> int:
    """Load a PEQ preset onto one or more sources, enabling PEQ on each if it was off.

    Exit code 0 if all sources succeed, 1 if any fail (but all are attempted).
    """
    try:
        results = asyncio.run(_load_preset(device, preset, sources, timeout))
    except (WiiMConnectionError, WiiMResponseError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    parts: list[str] = []
    for source, success in results.items():
        parts.append(f"{source} \u2713" if success else f"{source} \u2717")

    print(f"Loaded '{preset}' onto {', '.join(parts)}")

    return 0 if all(results.values()) else 1


# ---------------------------------------------------------------------------
# Argument parsing & dispatch
# ---------------------------------------------------------------------------


def _configure_logging(level_name: str) -> None:
    """Configure root logging verbosity from a level name string."""
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(levelname)s | %(name)s | %(message)s",
    )


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argparse parser with global options and subcommands."""
    parser = argparse.ArgumentParser(
        prog="wiim-rew-sync",
        description="WiiM <-> REW PEQ sync CLI (proof of concept).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {get_app_version()}",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Discovery and HTTP timeout in seconds (default: 5.0).",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging verbosity: DEBUG, INFO, WARNING, ERROR (default: INFO).",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "list-devices",
        help="Discover and list all WiiM devices on the LAN.",
    )

    list_sources = subparsers.add_parser(
        "list-sources",
        help="Probe and list available PEQ input sources for a device.",
    )
    list_sources.add_argument("--device", required=True, help="Device IP address.")

    list_peq_profiles = subparsers.add_parser(
        "list-peq-profiles",
        help="List PEQ profiles stored on a device.",
    )
    list_peq_profiles.add_argument("--device", required=True, help="Device IP address.")

    get_filters = subparsers.add_parser(
        "get-filters",
        help="Read PEQ filters from a device.",
    )
    get_filters.add_argument("--device", required=True, help="Device IP address.")
    get_filters.add_argument(
        "--source",
        default=None,
        help=(
            "Audio input source name (default: wifi). "
            "Known sources: wifi, bluetooth, line-in, optical, hdmi, ethernet."
        ),
    )
    get_filters.add_argument(
        "--channel",
        choices=["stereo", "left", "right"],
        default="stereo",
        help="Channel to display (default: stereo, auto-detects L/R mode).",
    )

    dry_run = subparsers.add_parser(
        "dry-run-import",
        help="Parse a REW file and preview the translation result.",
    )
    dry_run.add_argument("--file", required=True, help="Path to a REW EQ text file.")

    set_filters = subparsers.add_parser(
        "set-filters",
        help="Write REW filters to a device using the safe-write protocol.",
    )
    set_filters.add_argument("--file", required=True, help="Path to a REW EQ text file.")
    set_filters.add_argument("--device", required=True, help="Device IP address.")
    set_filters.add_argument(
        "--source",
        default=None,
        help=(
            "Audio input source name (default: wifi). "
            "Known sources: wifi, bluetooth, line-in, optical, hdmi, ethernet."
        ),
    )
    set_filters.add_argument(
        "--channel",
        choices=["stereo", "left", "right"],
        default="stereo",
        help="Channel mode to write (default: stereo).",
    )
    set_filters.add_argument(
        "--save-as",
        default=None,
        dest="save_as",
        help="Save the written filters as a named device preset after successful write.",
    )
    set_filters.add_argument(
        "--file-right",
        default=None,
        dest="file_right",
        help=(
            "Path to a REW EQ text file for the right channel. "
            "When provided, --file is used for the left channel and the device "
            "is switched to L/R mode. Overrides --channel."
        ),
    )

    list_roomfit = subparsers.add_parser(
        "list-roomfit-profiles",
        help="List RoomFit profiles stored on a device.",
    )
    list_roomfit.add_argument("--device", required=True, help="Device IP address.")

    get_roomfit = subparsers.add_parser(
        "get-roomfit-filters",
        help="Read RoomFit bands from a named profile on the device.",
    )
    get_roomfit.add_argument("--device", required=True, help="Device IP address.")
    get_roomfit.add_argument(
        "--source", default="wifi",
        help="Audio input source (default: wifi).",
    )
    get_roomfit.add_argument(
        "--profile", required=True,
        help="Name of the RoomFit profile to read.",
    )

    set_roomfit = subparsers.add_parser(
        "set-roomfit-filters",
        help="Write REW filters to a RoomFit profile on the device.",
    )
    set_roomfit.add_argument("--device", required=True, help="Device IP address.")
    set_roomfit.add_argument(
        "--source", default="wifi",
        help="Audio input source (default: wifi).",
    )
    set_roomfit.add_argument(
        "--profile", required=True,
        help="Name of the RoomFit profile to write to (new or existing).",
    )
    set_roomfit.add_argument(
        "--file", required=True,
        help="Path to a REW EQ text file.",
    )

    peq_toggle = subparsers.add_parser(
        "peq-toggle",
        help="Enable or disable PEQ on a specific source.",
    )
    peq_toggle.add_argument("--device", required=True, help="Device IP address.")
    peq_toggle.add_argument(
        "--source", default="wifi",
        help="Audio input source (default: wifi).",
    )
    peq_toggle.add_argument(
        "--state", required=True, choices=["on", "off"],
        help="Desired PEQ state: 'on' to enable, 'off' to disable.",
    )

    load_preset = subparsers.add_parser(
        "load-preset",
        help="Load a PEQ preset onto one or more sources (enables PEQ on each if it was off).",
    )
    load_preset.add_argument("--device", required=True, help="Device IP address.")
    load_preset.add_argument(
        "--preset", required=True,
        help="Name of the PEQ preset to load.",
    )
    load_preset.add_argument(
        "--source", required=True,
        help="Comma-separated list of source names (e.g. wifi,optical,HDMI).",
    )

    return parser


def run(argv: list[str] | None = None) -> int:
    """Parse arguments and dispatch to the selected command.

    Returns the command's integer exit code.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    _configure_logging(args.log_level)

    if args.command == "list-devices":
        return cmd_list_devices(args.timeout)
    if args.command == "list-sources":
        return cmd_list_sources(args.device, args.timeout)
    if args.command == "list-peq-profiles":
        return cmd_list_peq_profiles(args.device, args.timeout)
    if args.command == "get-filters":
        return cmd_get_filters(args.device, args.source, args.channel, args.timeout)
    if args.command == "dry-run-import":
        return cmd_dry_run_import(args.file)
    if args.command == "set-filters":
        return cmd_set_filters(
            args.device, args.source, args.file, args.channel, args.timeout,
            save_as=args.save_as,
            file_right=args.file_right,
        )
    if args.command == "list-roomfit-profiles":
        return cmd_list_roomfit_profiles(args.device, args.timeout)
    if args.command == "get-roomfit-filters":
        return cmd_get_roomfit_filters(
            args.device, args.source, args.profile, args.timeout
        )
    if args.command == "set-roomfit-filters":
        return cmd_set_roomfit_filters(
            args.device, args.source, args.profile, args.file, args.timeout
        )
    if args.command == "peq-toggle":
        return cmd_peq_toggle(args.device, args.source, args.state, args.timeout)
    if args.command == "load-preset":
        sources = [s.strip() for s in args.source.split(",")]
        return cmd_load_preset(args.device, args.preset, sources, args.timeout)

    # argparse enforces a valid subcommand, so this is unreachable.
    parser.error(f"Unknown command: {args.command}")
    return 2  # pragma: no cover


def main(argv: list[str] | None = None) -> None:
    """Console-script entry point. Exits the process with the command's code."""
    sys.exit(run(argv))


if __name__ == "__main__":
    main()
