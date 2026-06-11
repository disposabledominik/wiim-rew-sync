"""
Fallback subnet scanner for WiiM device discovery.

Scans the local subnet issuing `getStatusEx` probes to each host. Only
hosts whose response contains a recognisable `project` field are included.

Requirements: 1.3, 1.8
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from collections.abc import Callable
from typing import TYPE_CHECKING

from src.models.capabilities import DeviceInfo

if TYPE_CHECKING:
    from src.adapters.wiim_http import WiiMHttpClient

logger = logging.getLogger("wiim_rew_sync.discovery")

# Known WiiM project field values — used to filter genuine WiiM devices
# from generic LinkPlay or other httpapi.asp responders.
# Source: docs/wiim_api_notes.md — Capability Nuances table
KNOWN_WIIM_PROJECTS: frozenset[str] = frozenset({
    "WiiM_Ultra",
    "WiiM_Amp_Ultra",
    "WiiM_Amp_Pro",
    "WiiM_Pro",
    "WiiM_Pro_Plus",
    "WiiM_Amp",
    "WiiM_Sound",
    "WiiM_Sound_Lite",
    "WiiM_Mini",
    # Common variations (underscore vs space, case variations)
    "WiiM Ultra",
    "WiiM Amp Ultra",
    "WiiM Amp Pro",
    "WiiM Pro",
    "WiiM Pro Plus",
    "WiiM Amp",
    "WiiM Sound",
    "WiiM Sound Lite",
    "WiiM Mini",
})


def _is_recognised_project(project: str) -> bool:
    """Check if a project field value indicates a WiiM device.

    Performs case-insensitive prefix matching against known WiiM project names.

    Args:
        project: The `project` field value from a getStatusEx response.

    Returns:
        True if the project field indicates a WiiM device.
    """
    if not project:
        return False
    # Check exact match first (case-insensitive)
    normalised = project.lower().replace(" ", "_")
    if normalised in {p.lower().replace(" ", "_") for p in KNOWN_WIIM_PROJECTS}:
        return True
    # Also accept any value starting with "WiiM" (case-insensitive) to be
    # forward-compatible with new WiiM models
    return project.lower().startswith("wiim")


def _get_local_ip() -> str | None:
    """Determine the local machine's IP address on the LAN.

    Returns:
        The local IPv4 address as a string, or None if it cannot be determined.
    """
    try:
        # Connect to a public DNS to determine the default route interface
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


class SubnetScanner:
    """Fallback device discovery via subnet-wide getStatusEx probes.

    Scans all hosts on the local /24 subnet, issuing `getStatusEx` to each.
    Only hosts responding with a recognised `project` field are returned.

    Args:
        timeout: Per-host probe timeout in seconds.
        http_client_factory: Optional factory to create WiiMHttpClient instances.
            Accepts an IP string and returns a WiiMHttpClient. Used for DI/testing.
        max_concurrent: Maximum number of concurrent probe tasks.
    """

    def __init__(
        self,
        timeout: float = 2.0,
        http_client_factory: Callable[[str], WiiMHttpClient] | None = None,
        max_concurrent: int = 50,
    ) -> None:
        self._timeout = timeout
        self._http_client_factory = http_client_factory
        self._max_concurrent = max_concurrent

    async def scan(self) -> list[DeviceInfo]:
        """Scan the local /24 subnet for WiiM devices.

        Returns:
            List of DeviceInfo for confirmed WiiM devices. Empty list on failure.
        """
        local_ip = _get_local_ip()
        if local_ip is None:
            logger.warning("Cannot determine local IP; subnet scan skipped")
            return []

        try:
            network = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)
        except ValueError:
            logger.warning("Cannot determine subnet from IP %s", local_ip)
            return []

        # Build list of IPs to probe (exclude network and broadcast)
        hosts = [str(host) for host in network.hosts() if str(host) != local_ip]

        logger.info(
            "Starting subnet scan: %d hosts on %s (timeout=%.1fs)",
            len(hosts),
            network,
            self._timeout,
        )

        semaphore = asyncio.Semaphore(self._max_concurrent)
        tasks = [self._probe_host(ip, semaphore) for ip in hosts]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        devices: list[DeviceInfo] = []
        for result in results:
            if isinstance(result, DeviceInfo):
                devices.append(result)

        logger.info("Subnet scan complete: found %d WiiM device(s)", len(devices))
        return devices

    async def _probe_host(
        self, ip: str, semaphore: asyncio.Semaphore
    ) -> DeviceInfo | None:
        """Probe a single host with getStatusEx.

        Args:
            ip: The IPv4 address to probe.
            semaphore: Concurrency limiter.

        Returns:
            DeviceInfo if the host is a recognised WiiM device, else None.
        """
        async with semaphore:
            client = self._create_client(ip)
            try:
                response = await asyncio.wait_for(
                    client.command("getStatusEx"),
                    timeout=self._timeout,
                )
            except TimeoutError:
                return None
            except Exception:
                return None
            finally:
                await client.close()

            return self._parse_status_response(ip, response)

    def _create_client(self, ip: str) -> WiiMHttpClient:
        """Create a WiiMHttpClient for the given IP.

        Uses the injected factory if available, otherwise imports and
        creates a default WiiMHttpClient.
        """
        if self._http_client_factory is not None:
            return self._http_client_factory(ip)

        # Lazy import to avoid circular dependency
        from src.adapters.wiim_http import WiiMHttpClient

        return WiiMHttpClient(ip=ip, timeout=self._timeout)

    def _parse_status_response(
        self, ip: str, response: dict | str  # type: ignore[type-arg]
    ) -> DeviceInfo | None:
        """Parse a getStatusEx response into DeviceInfo if it's a WiiM device.

        Args:
            ip: The host IP that produced this response.
            response: The parsed response from getStatusEx.

        Returns:
            DeviceInfo if the response indicates a WiiM device, else None.
        """
        if not isinstance(response, dict):
            return None

        project = response.get("project", "")
        if not _is_recognised_project(project):
            logger.debug("Host %s excluded: unrecognised project '%s'", ip, project)
            return None

        name = response.get("DeviceName", "")
        firmware = response.get("Release", "")
        uuid = response.get("uuid", "")

        return DeviceInfo(
            ip=ip,
            name=name,
            model=project,
            firmware=firmware,
            uuid=uuid,
        )
