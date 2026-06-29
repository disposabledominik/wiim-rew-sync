"""
mDNS discovery for WiiM devices using zeroconf.

Probes `_wiim._tcp.local.` and `_linkplay._tcp.local.` concurrently in a single
browse window, since not all devices advertise both service types (older
LinkPlay-based devices only advertise the latter). Returns a list of
DeviceInfo for each device found.

Requirements: 1.1, 1.2
"""

from __future__ import annotations

import asyncio
import logging

from zeroconf import ServiceStateChange, Zeroconf
from zeroconf.asyncio import AsyncServiceBrowser, AsyncServiceInfo, AsyncZeroconf

from src.models.capabilities import DeviceInfo

logger = logging.getLogger("wiim_rew_sync.discovery")

# mDNS service types in priority order
WIIM_SERVICE_TYPE = "_wiim._tcp.local."
LINKPLAY_SERVICE_TYPE = "_linkplay._tcp.local."


class ZeroconfDiscover:
    """Discover WiiM devices via mDNS service browsing.

    Browses `_wiim._tcp.local.` and `_linkplay._tcp.local.` concurrently in a
    single timeout window, so a device that only advertises one of the two
    types doesn't have its discovery starved by waiting out a full timeout on
    the other type first.

    Args:
        timeout: Maximum time in seconds to wait for mDNS responses.
    """

    def __init__(self, timeout: float = 3.0) -> None:
        self._timeout = timeout

    async def discover(self) -> list[DeviceInfo]:
        """Run mDNS discovery across all known WiiM/LinkPlay service types.

        Returns:
            List of discovered DeviceInfo objects. Empty list if nothing found.
        """
        return await self._probe_services([WIIM_SERVICE_TYPE, LINKPLAY_SERVICE_TYPE])

    async def _probe_services(self, service_types: list[str]) -> list[DeviceInfo]:
        """Probe multiple mDNS service types concurrently and return discovered devices.

        Args:
            service_types: The mDNS service type strings to browse (e.g.
                "_wiim._tcp.local.").

        Returns:
            List of DeviceInfo for devices found under any of the given service types.
        """
        discovered: list[DeviceInfo] = []
        found: list[tuple[str, str]] = []
        event = asyncio.Event()

        def on_service_state_change(
            zeroconf: Zeroconf,
            service_type: str,
            name: str,
            state_change: ServiceStateChange,
        ) -> None:
            if state_change == ServiceStateChange.Added:
                found.append((service_type, name))
                event.set()

        azc = AsyncZeroconf()
        try:
            browser = AsyncServiceBrowser(
                azc.zeroconf,
                service_types,
                handlers=[on_service_state_change],
            )

            # Wait for timeout or until at least one service is found
            try:
                await asyncio.wait_for(event.wait(), timeout=self._timeout)
            except TimeoutError:
                pass

            # Give a brief additional window for more services after first discovery
            if found:
                await asyncio.sleep(min(0.5, self._timeout / 4))

            # Resolve each found service
            for service_type, name in found:
                info = AsyncServiceInfo(service_type, name)
                await info.async_request(azc.zeroconf, timeout=int(self._timeout * 1000))

                device = self._parse_service_info(info)
                if device is not None:
                    discovered.append(device)

            await browser.async_cancel()
        finally:
            await azc.async_close()

        return discovered

    def _parse_service_info(self, info: AsyncServiceInfo) -> DeviceInfo | None:
        """Extract DeviceInfo from a resolved ServiceInfo object.

        Args:
            info: The resolved AsyncServiceInfo.

        Returns:
            DeviceInfo if the service info contains sufficient data, else None.
        """
        addresses = info.parsed_scoped_addresses()
        if not addresses:
            return None

        ip = addresses[0]

        # Extract properties from TXT records
        properties = info.properties or {}

        def _decode(key: bytes | str, default: str = "") -> str:
            """Decode a TXT record value."""
            raw = properties.get(
                key if isinstance(key, bytes) else key.encode(),
                b"",
            )
            if isinstance(raw, bytes):
                return raw.decode("utf-8", errors="replace") or default
            return str(raw) or default

        name = _decode(b"DeviceName") or _decode(b"name") or info.server or ""
        model = _decode(b"project") or _decode(b"model") or ""
        firmware = _decode(b"Release") or _decode(b"firmware") or ""
        uuid = _decode(b"uuid") or ""

        # Strip trailing dot from server name if used as device name
        if name.endswith("."):
            name = name[:-1]

        return DeviceInfo(
            ip=ip,
            name=name,
            model=model,
            firmware=firmware,
            uuid=uuid,
        )
