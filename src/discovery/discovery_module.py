"""
Discovery orchestrator — combines mDNS and subnet scan strategies.

Implements a parallel discovery strategy for fast, responsive device detection:
  1. Start mDNS probe (`_wiim._tcp.local.` and `_linkplay._tcp.local.` concurrently)
  2. After a short grace period, start subnet scan in parallel
  3. Emit results progressively as devices are found (via on_found callback)
  4. Deduplicate by IP across both strategies

Returns an empty list (no exception) if nothing is found.

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

from src.discovery.subnet_scanner import SubnetScanner
from src.discovery.zeroconf_discover import ZeroconfDiscover
from src.models.capabilities import DeviceInfo

if TYPE_CHECKING:
    from src.adapters.wiim_http import WiiMHttpClient

logger = logging.getLogger("wiim_rew_sync.discovery")

# Grace period (seconds) — how long to wait for mDNS results before
# launching the subnet scan in parallel. Short enough to feel responsive,
# long enough for mDNS to win on healthy networks.
_MDNS_GRACE_PERIOD: float = 1.5


async def _enrich_device(device: DeviceInfo, timeout: float) -> DeviceInfo:
    """Enrich a DeviceInfo by calling getStatusEx if model/firmware are empty.

    Only needed for mDNS-discovered devices whose TXT records may be sparse.
    Subnet-scanned devices already have full info from getStatusEx.

    Falls back to the original device info if the probe fails.
    """
    if device.model and device.firmware:
        return device  # Already populated (e.g. from TXT records or subnet scan)

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

    Discovery strategy (parallel with short-circuit):
      1. Start mDNS probe (browses _wiim._tcp.local. and _linkplay._tcp.local. concurrently)
      2. After 1.5s grace period: if mDNS already found devices, skip subnet scan
      3. Otherwise, start subnet scan in parallel with remaining mDNS time
      4. Deduplicate results by IP address
      5. Emit results progressively via on_found callback (if provided)

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

    async def discover(
        self,
        on_found: Callable[[list[DeviceInfo]], None] | None = None,
    ) -> list[DeviceInfo]:
        """Run the parallel discovery sequence.

        Args:
            on_found: Optional callback invoked each time new devices are
                discovered. Receives the cumulative list of all devices found
                so far (deduplicated by IP). Called from the async worker thread.

        Returns:
            Final list of discovered DeviceInfo objects. Empty list if nothing found.
            Never raises exceptions.
        """
        try:
            return await self._discover_parallel(on_found)
        except Exception:
            logger.exception("Unexpected error during discovery")
            return []

    async def _discover_parallel(
        self,
        on_found: Callable[[list[DeviceInfo]], None] | None,
    ) -> list[DeviceInfo]:
        """Core parallel discovery logic."""
        seen_ips: set[str] = set()
        all_devices: list[DeviceInfo] = []

        def _add_devices(new_devices: list[DeviceInfo]) -> bool:
            """Add devices to the result set, deduplicating by IP.

            Returns True if any new devices were added.
            """
            added = False
            for d in new_devices:
                if d.ip not in seen_ips:
                    seen_ips.add(d.ip)
                    all_devices.append(d)
                    added = True
            return added

        # Phase 1: Start mDNS probe
        mdns_task = asyncio.create_task(self._zeroconf.discover())

        # Wait for the grace period — give mDNS a head start
        grace = min(_MDNS_GRACE_PERIOD, self._timeout)
        await asyncio.sleep(grace)

        # Check if mDNS already found devices during the grace period
        if mdns_task.done():
            mdns_devices = mdns_task.result()
            if mdns_devices:
                enriched = await self._enrich_mdns_devices(mdns_devices)
                _add_devices(enriched)
                self._devices = list(all_devices)
                if on_found:
                    on_found(list(all_devices))
                logger.info(
                    "mDNS discovery found %d device(s) within grace period",
                    len(all_devices),
                )
                return self._devices

        # Phase 2: mDNS hasn't delivered yet — start subnet scan in parallel
        logger.info("mDNS grace period elapsed; starting subnet scan in parallel")
        scan_task = asyncio.create_task(self._scanner.scan())

        # Wait for mDNS to complete (remaining time)
        remaining = max(0.0, self._timeout - grace)
        if not mdns_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(mdns_task), timeout=remaining)
            except TimeoutError:
                logger.debug("mDNS timed out after %.1fs total", self._timeout)

        # Collect mDNS results (if any)
        if mdns_task.done() and not mdns_task.cancelled():
            try:
                mdns_devices = mdns_task.result()
                if mdns_devices:
                    enriched = await self._enrich_mdns_devices(mdns_devices)
                    if _add_devices(enriched):
                        if on_found:
                            on_found(list(all_devices))
                        logger.info(
                            "mDNS found %d device(s) after grace period",
                            len(mdns_devices),
                        )
            except Exception:
                logger.debug("mDNS task raised an exception", exc_info=True)

        # If mDNS found devices, we can cancel the subnet scan (it's redundant)
        if all_devices:
            scan_task.cancel()
            try:
                await scan_task
            except asyncio.CancelledError:
                pass
            self._devices = list(all_devices)
            return self._devices

        # Phase 3: Wait for subnet scan results
        try:
            scan_devices = await scan_task
        except asyncio.CancelledError:
            scan_devices = []
        except Exception:
            logger.exception("Subnet scan failed")
            scan_devices = []

        # Subnet-scanned devices already have full info from getStatusEx —
        # no enrichment needed (they come from _parse_status_response which
        # extracts name, model, firmware, uuid directly).
        if scan_devices:
            _add_devices(scan_devices)
            if on_found:
                on_found(list(all_devices))
            logger.info("Subnet scan found %d device(s)", len(scan_devices))
            # Reaching this point means mDNS contributed zero devices over the
            # full timeout (the all_devices-cancels-scan_task short-circuit
            # above only fires when mDNS found something). On Windows this is
            # most commonly the active network being classified "Public"
            # rather than "Private", which blocks inbound mDNS replies to the
            # app regardless of how fast the probe itself is.
            logger.warning(
                "mDNS found no devices even though the subnet scan succeeded "
                "-- on Windows, check whether the active network is "
                "classified 'Private' (Settings > Network & Internet > "
                "Wi-Fi > Network profile); 'Public' blocks inbound mDNS "
                "replies. See the in-app Troubleshooting guide for details."
            )
        else:
            logger.info("No WiiM devices found on network")

        self._devices = list(all_devices)
        return self._devices

    async def _enrich_mdns_devices(
        self, devices: list[DeviceInfo]
    ) -> list[DeviceInfo]:
        """Enrich mDNS-discovered devices that lack model/firmware info.

        Only calls getStatusEx for devices whose TXT records didn't provide
        the model and firmware fields. Runs enrichment in parallel.
        """
        enriched = await asyncio.gather(
            *[_enrich_device(d, self._timeout) for d in devices]
        )
        return list(enriched)

    async def refresh(
        self,
        on_found: Callable[[list[DeviceInfo]], None] | None = None,
    ) -> list[DeviceInfo]:
        """Re-run the full discovery sequence and return updated results.

        Clears previous results before re-running discovery.

        Args:
            on_found: Optional progressive callback (same as discover()).

        Returns:
            Updated list of discovered DeviceInfo objects. Empty list if nothing found.
        """
        self._devices = []
        return await self.discover(on_found=on_found)

    @property
    def devices(self) -> list[DeviceInfo]:
        """Return the most recently discovered device list."""
        return self._devices
