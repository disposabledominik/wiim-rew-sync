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
from src.adapters.safe_write import SafeWrite, WriteResult
from src.adapters.wiim_adapter import WiiMAdapter
from src.adapters.wiim_http import WiiMHttpClient
from src.discovery.discovery_module import DiscoveryModule
from src.models.canonical import CanonicalFilter
from src.models.capabilities import DeviceInfo
from src.models.errors import (
    ParseError,
    ValidationError,
    WiiMConnectionError,
    WiiMResponseError,
    WiiMSlaveTargetError,
)
from src.models.peq import PEQSettings
from src.repository.backup_manager import BackupManager
from src.translator import TranslationEngine
from src.utils.app_dirs import get_app_data_dir

logger = logging.getLogger("wiim_rew_sync.app")

# Default source used when the device exposes no input list and the user did
# not pass --source.
# ASSUMPTION: "wifi" is always a valid WiiM input source name (confirmed by the
# WiiM HTTP API InputList examples in docs/wiim_api_notes.md).
_DEFAULT_SOURCE = "wifi"

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
    if settings.channel_mode == "lr" and not settings.bands:
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
        resolved_source = source or _DEFAULT_SOURCE
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
    import json
    from urllib.parse import quote

    client = WiiMHttpClient(device, timeout=timeout)
    results: list[tuple[str, str, bool]] = []
    try:
        for source in _CANONICAL_SOURCES:
            payload = json.dumps({
                "source_name": source,
                "pluginURI": "http://moddevices.com/plugins/caps/EqNp",
            })
            try:
                resp = await client.command(f"EQGetLV2SourceBandEx:{quote(payload)}")
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


def _has_custom_data(bands: list[dict[str, object]]) -> bool:
    """Check if band data contains any non-default values.

    Default = all modes are PEAK (1) or OFF (-1), all gains are 0.0.
    """
    for entry in bands:
        param_name = str(entry.get("param_name", ""))
        value = float(str(entry.get("value", 0.0)))
        if param_name.endswith("_gain") and abs(value) > 0.001:
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
        [device.name, device.ip, device.model, device.firmware, device.role]
        for device in devices
    ]
    print(_format_table(["Name", "IP", "Model", "Firmware", "Role"], rows))
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

    print(f"Source: {settings.source_name} | Mode: {settings.channel_mode}")
    print()

    if settings.channel_mode == "lr" and channel == "stereo":
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
    device: str, source: str | None, file: str, channel: str, timeout: float
) -> WriteResult:
    """Parse REW file, probe device, run safe write protocol."""
    path = Path(file)
    filters = TranslationEngine.parse_rew_file(path)

    # Build PEQSettings from parsed filters based on channel mode
    if channel in ("left", "right"):
        settings = PEQSettings(
            source_name=source or _DEFAULT_SOURCE,
            channel_mode="lr",
            bands_l=filters if channel == "left" else [],
            bands_r=filters if channel == "right" else [],
        )
    else:
        settings = PEQSettings(
            source_name=source or _DEFAULT_SOURCE,
            channel_mode="stereo",
            bands=filters,
        )

    client = WiiMHttpClient(device, timeout=timeout)
    try:
        print("Probing device capabilities...")
        capabilities = await CapabilityProber(client).probe()

        resolved_source = source or (
            capabilities.source_names[0]
            if capabilities.source_names
            else _DEFAULT_SOURCE
        )

        adapter = WiiMAdapter(client, capabilities)
        backup_manager = BackupManager(get_app_data_dir())

        # Use command queue for sequential writes if batch is not supported
        queue: WiiMCommandQueue | None = None
        if not capabilities.supports_batch_write:
            queue = WiiMCommandQueue(client)
            await queue.start()

        safe_write = SafeWrite(adapter, backup_manager, queue)

        print("Backing up...")
        print("Writing...")
        result = await safe_write.execute(resolved_source, settings)

        if result.success:
            print("Verifying...")
            print("Done!")
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
    device: str, source: str | None, file: str, channel: str, timeout: float
) -> int:
    """Write REW filters to a device using the safe-write protocol.

    Exit code 0 on verified success, 1 on any failure.
    """
    try:
        result = asyncio.run(_set_filters(device, source, file, channel, timeout))
    except WiiMSlaveTargetError:
        print(
            "Error: target is a slave device; write to the master node instead.",
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
    if args.command == "get-filters":
        return cmd_get_filters(args.device, args.source, args.channel, args.timeout)
    if args.command == "dry-run-import":
        return cmd_dry_run_import(args.file)
    if args.command == "set-filters":
        return cmd_set_filters(
            args.device, args.source, args.file, args.channel, args.timeout
        )

    # argparse enforces a valid subcommand, so this is unreachable.
    parser.error(f"Unknown command: {args.command}")
    return 2  # pragma: no cover


def main(argv: list[str] | None = None) -> None:
    """Console-script entry point. Exits the process with the command's code."""
    sys.exit(run(argv))


if __name__ == "__main__":
    main()
