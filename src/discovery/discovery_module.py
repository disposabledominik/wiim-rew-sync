"""
Discovery orchestrator — combines mDNS and subnet scan strategies.

Implements the full discovery sequence:
  1. mDNS `_wiim._tcp.local.`
  2. Fallback mDNS `_linkplay._tcp.local.`
  3. Fallback subnet scan with `getStatusEx` probe

Returns an empty list (no exception) if nothing is found.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from src.discovery.subnet_scanner import SubnetScanner
from src.discovery.zeroconf_discover import ZeroconfDiscover
from src.models.capabilities import DeviceInfo

if TYPE_CHECKING:
    from src.adapters.wiim_http import WiiMHttpClient

logger = logging.getLogger("wiim_rew_sync.discovery")


async def _enrich_device(device: DeviceInfo, timeout: float) -> DeviceInfo:
    """Enrich a DeviceInfo by calling getStatusEx if model/firmware are empty.

    Falls back to the original device info if the probe fails.
    """
    if device.model and device.firmware:
        return device  # Already populated (e.g. from TXT records)

    from src.adapters.wiim_http import WiiMHttpClient

    client = WiiMHttpClient(device.ip, timeout=timeout)
    try:
        resp = await client.command("getStatusEx")
    except Exception:
        logger.debug("getStatusEx enrichment failed for %s", device.ip)
        return device
    finally:
        await client.close()

    if not isinstance(resp, dict):
        return device

    return DeviceInfo(
        ip=device.ip,
        name=str(resp.get("DeviceName", device.name)) or device.name,
        model=str(resp.get("project", device.model)) or device.model,
        firmware=str(resp.get("Release", device.firmware)) or device.firmware,
        uuid=str(resp.get("uuid", device.uuid)) or device.uuid,
        role=device.role,
    )


class DiscoveryModule:
    """Orchestrates WiiM device discovery using mDNS and subnet scanning.

    Discovery strategy:
      1. Probe `_wiim._tcp.local.` via zeroconf
      2. If empty → probe `_linkplay._tcp.local.` via zeroconf
      3. If still empty → subnet scan with `getStatusEx` probes

    Always returns a list (empty if no devices found). Never raises exceptions
    to the caller.

    Args:
        timeout: Maximum time in seconds for each discovery phase.
        http_client_factory: Optional factory for creating WiiMHttpClient instances.
            Used by the subnet scanner for DI/testing. Accepts an IP string.
    """

    def __init__(
        self,
        timeout: float = 5.0,
        http_client_factory: Callable[[str], WiiMHttpClient] | None = None,
    ) -> None:
        self._timeout = timeout
        self._http_client_factory = http_client_factory
        self._devices: list[DeviceInfo] = []
        self._zeroconf = ZeroconfDiscover(timeout=timeout)
        self._scanner = SubnetScanner(
            timeout=min(timeout, 2.0),
            http_client_factory=http_client_factory,
        )

    async def discover(self) -> list[DeviceInfo]:
        """Run the full discovery sequence.

        Tries mDNS first (`_wiim._tcp.local.`, then `_linkplay._tcp.local.`),
        falling back to subnet scan if mDNS yields no results.

        Returns:
            List of discovered DeviceInfo objects. Empty list if nothing found.
            Never raises exceptions.
        """
        try:
            devices = await self._zeroconf.discover()
            if devices:
                # Enrich devices with model/firmware from getStatusEx
                import asyncio

                enriched = await asyncio.gather(
                    *[_enrich_device(d, self._timeout) for d in devices]
                )
                self._devices = list(enriched)
                logger.info("mDNS discovery found %d device(s)", len(self._devices))
                return self._devices

            # Fallback to subnet scan
            logger.info("mDNS found no devices; falling back to subnet scan")
            devices = await self._scanner.scan()
            self._devices = devices
            if devices:
                logger.info("Subnet scan found %d device(s)", len(devices))
            else:
                logger.info("No WiiM devices found on network")
            return self._devices

        except Exception:
            logger.exception("Unexpected error during discovery")
            return []

    async def refresh(self) -> list[DeviceInfo]:
        """Re-run the full discovery sequence and return updated results.

        Clears previous results before re-running discovery.

        Returns:
            Updated list of discovered DeviceInfo objects. Empty list if nothing found.
        """
        self._devices = []
        return await self.discover()

    @property
    def devices(self) -> list[DeviceInfo]:
        """Return the most recently discovered device list."""
        return self._devices
