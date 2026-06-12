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

Requirements: 1.1, 1.6, 4.1, 4.2, 4.3, 12.1, 12.2, 12.3, 6.7, 6.8
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from src.adapters.capability_prober import CapabilityProber
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
)
from src.models.peq import PEQSettings
from src.translator import TranslationEngine

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
            band.type,
            f"{band.frequency_hz:.2f}",
            f"{band.gain_db:.2f}",
            f"{band.q:.3f}",
        ]
        for index, band in enumerate(bands, start=1)
    ]


def _select_bands(settings: PEQSettings, channel: str) -> list[CanonicalFilter]:
    """Return the band list matching the requested *channel*."""
    if channel == "left":
        return settings.bands_l
    if channel == "right":
        return settings.bands_r
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

    Resolves the source name to *source* when provided, otherwise the device's
    first advertised input (falling back to ``wifi``).
    """
    client = WiiMHttpClient(device, timeout=timeout)
    try:
        capabilities = await CapabilityProber(client).probe()
        resolved_source = source or (
            capabilities.source_names[0]
            if capabilities.source_names
            else _DEFAULT_SOURCE
        )
        adapter = WiiMAdapter(client, capabilities)
        return await adapter.read_peq(resolved_source)
    finally:
        await client.close()


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


def cmd_get_filters(
    device: str, source: str | None, channel: str, timeout: float
) -> int:
    """Read and print PEQ filters for a device. Exit 0 on success, 1 on error."""
    try:
        settings = asyncio.run(_read_filters(device, source, timeout))
    except (WiiMConnectionError, WiiMResponseError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

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

    get_filters = subparsers.add_parser(
        "get-filters",
        help="Read PEQ filters from a device.",
    )
    get_filters.add_argument("--device", required=True, help="Device IP address.")
    get_filters.add_argument(
        "--source",
        default=None,
        help="Audio input source name (default: device's first input).",
    )
    get_filters.add_argument(
        "--channel",
        choices=["stereo", "left", "right"],
        default="stereo",
        help="Channel to display (default: stereo).",
    )

    dry_run = subparsers.add_parser(
        "dry-run-import",
        help="Parse a REW file and preview the translation result.",
    )
    dry_run.add_argument("--file", required=True, help="Path to a REW EQ text file.")

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
    if args.command == "get-filters":
        return cmd_get_filters(args.device, args.source, args.channel, args.timeout)
    if args.command == "dry-run-import":
        return cmd_dry_run_import(args.file)

    # argparse enforces a valid subcommand, so this is unreachable.
    parser.error(f"Unknown command: {args.command}")
    return 2  # pragma: no cover


def main(argv: list[str] | None = None) -> None:
    """Console-script entry point. Exits the process with the command's code."""
    sys.exit(run(argv))


if __name__ == "__main__":
    main()
