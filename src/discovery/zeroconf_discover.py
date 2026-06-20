"""
mDNS discovery for WiiM devices using zeroconf.

Probes for `_wiim._tcp.local.` first, then falls back to `_linkplay._tcp.local.`.
Returns a list of DeviceInfo for each device found.

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

    Probes `_wiim._tcp.local.` first. If no results, probes
    `_linkplay._tcp.local.` as a fallback.

    Args:
        timeout: Maximum time in seconds to wait for mDNS responses.
    """

    def __init__(self, timeout: float = 3.0) -> None:
        self._timeout = timeout

    async def discover(self) -> list[DeviceInfo]:
        """Run mDNS discovery, trying WiiM service type first, then LinkPlay.

        Returns:
            List of discovered DeviceInfo objects. Empty list if nothing found.
        """
        # Try _wiim._tcp.local. first
        devices = await self._probe_service(WIIM_SERVICE_TYPE)
        if devices:
            return devices

        # Fallback to _linkplay._tcp.local.
        devices = await self._probe_service(LINKPLAY_SERVICE_TYPE)
        return devices

    async def _probe_service(self, service_type: str) -> list[DeviceInfo]:
        """Probe a single mDNS service type and return discovered devices.

        Args:
            service_type: The mDNS service type string (e.g. "_wiim._tcp.local.").

        Returns:
            List of DeviceInfo for devices found under this service type.
        """
        discovered: list[DeviceInfo] = []
        found_names: list[str] = []
        event = asyncio.Event()

        def on_service_state_change(
            zeroconf: Zeroconf,
            service_type: str,
            name: str,
            state_change: ServiceStateChange,
        ) -> None:
            if state_change == ServiceStateChange.Added:
                found_names.append(name)
                event.set()

        azc = AsyncZeroconf()
        try:
            browser = AsyncServiceBrowser(
                azc.zeroconf,
                service_type,
                handlers=[on_service_state_change],
            )

            # Wait for timeout or until at least one service is found
            try:
                await asyncio.wait_for(event.wait(), timeout=self._timeout)
            except TimeoutError:
                pass

            # Give a brief additional window for more services after first discovery
            if found_names:
                await asyncio.sleep(min(0.5, self._timeout / 4))

            # Resolve each found service
            for name in found_names:
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
