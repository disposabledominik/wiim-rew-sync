"""Unit tests for the discovery module.

Tests cover DiscoveryModule orchestration, SubnetScanner filtering,
and ZeroconfDiscover graceful handling of empty/error responses.

Uses unittest.mock.AsyncMock to patch network calls.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.discovery.discovery_module import DiscoveryModule
from src.discovery.subnet_scanner import SubnetScanner
from src.discovery.zeroconf_discover import ZeroconfDiscover
from src.models.capabilities import DeviceInfo
from src.utils.device_identity import is_wiim_device

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _make_device(ip: str = "192.168.1.50", name: str = "Living Room") -> DeviceInfo:
    """Create a sample DeviceInfo for tests."""
    return DeviceInfo(
        ip=ip,
        name=name,
        model="WiiM_Pro_Plus",
        firmware="4.8.5",
        uuid="test-uuid-001",
    )


def _make_status_response(
    project: str = "WiiM_Pro_Plus",
    name: str = "Living Room",
) -> dict[str, str]:
    """Create a getStatusEx-style response dict."""
    return {
        "project": project,
        "DeviceName": name,
        "Release": "4.8.5",
        "uuid": "uuid-scan-001",
    }


# --------------------------------------------------------------------------
# DiscoveryModule — mDNS success path
# --------------------------------------------------------------------------


async def test_discover_returns_devices_when_mdns_succeeds() -> None:
    """DiscoveryModule.discover() returns devices from mDNS when available."""
    expected = [_make_device()]

    module = DiscoveryModule(timeout=1.0)

    with patch.object(module._zeroconf, "discover", new_callable=AsyncMock) as mock_mdns:
        mock_mdns.return_value = expected

        result = await module.discover()

    assert result == expected
    assert len(result) == 1
    assert result[0].ip == "192.168.1.50"


# --------------------------------------------------------------------------
# DiscoveryModule — fallback to subnet scan
# --------------------------------------------------------------------------


async def test_discover_falls_back_to_subnet_scan_when_mdns_empty() -> None:
    """When mDNS returns empty, DiscoveryModule falls back to subnet scan."""
    subnet_device = _make_device(ip="192.168.1.101", name="Bedroom")

    module = DiscoveryModule(timeout=1.0)

    with (
        patch.object(
            module._zeroconf, "discover", new_callable=AsyncMock
        ) as mock_mdns,
        patch.object(
            module._scanner, "scan", new_callable=AsyncMock
        ) as mock_scan,
    ):
        mock_mdns.return_value = []
        mock_scan.return_value = [subnet_device]

        result = await module.discover()

    assert result == [subnet_device]
    mock_mdns.assert_awaited_once()
    mock_scan.assert_awaited_once()


async def test_discover_warns_when_mdns_empty_but_subnet_scan_succeeds(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A WARNING is logged hinting at the Windows network-profile/firewall
    cause when mDNS contributes zero devices but the subnet scan finds some
    -- this is the common symptom of Windows blocking inbound mDNS replies
    on networks classified "Public" rather than "Private".
    """
    subnet_device = _make_device(ip="192.168.1.101", name="Bedroom")

    module = DiscoveryModule(timeout=1.0)

    logger = logging.getLogger("wiim_rew_sync.discovery")
    logger.propagate = True
    try:
        with (
            patch.object(
                module._zeroconf, "discover", new_callable=AsyncMock
            ) as mock_mdns,
            patch.object(
                module._scanner, "scan", new_callable=AsyncMock
            ) as mock_scan,
            caplog.at_level(logging.WARNING, logger="wiim_rew_sync.discovery"),
        ):
            mock_mdns.return_value = []
            mock_scan.return_value = [subnet_device]

            result = await module.discover()
    finally:
        logger.propagate = False

    assert result == [subnet_device]
    assert "Network profile" in caplog.text


# --------------------------------------------------------------------------
# DiscoveryModule — total failure returns empty (no crash)
# --------------------------------------------------------------------------


async def test_discover_returns_empty_on_total_failure() -> None:
    """On unexpected exceptions, discover() returns [] without raising."""
    module = DiscoveryModule(timeout=1.0)

    with patch.object(
        module._zeroconf, "discover", new_callable=AsyncMock
    ) as mock_mdns:
        mock_mdns.side_effect = RuntimeError("network exploded")

        result = await module.discover()

    assert result == []


async def test_discover_returns_empty_when_both_sources_empty() -> None:
    """When both mDNS and subnet scan find nothing, returns empty list."""
    module = DiscoveryModule(timeout=1.0)

    with (
        patch.object(
            module._zeroconf, "discover", new_callable=AsyncMock
        ) as mock_mdns,
        patch.object(
            module._scanner, "scan", new_callable=AsyncMock
        ) as mock_scan,
    ):
        mock_mdns.return_value = []
        mock_scan.return_value = []

        result = await module.discover()

    assert result == []


# --------------------------------------------------------------------------
# DiscoveryModule — refresh clears and re-discovers
# --------------------------------------------------------------------------


async def test_refresh_clears_previous_results_and_rediscovers() -> None:
    """refresh() clears cached devices and runs discover() again."""
    first_device = _make_device(ip="192.168.1.50", name="First")
    second_device = _make_device(ip="192.168.1.60", name="Second")

    module = DiscoveryModule(timeout=1.0)

    with patch.object(module._zeroconf, "discover", new_callable=AsyncMock) as mock_mdns:
        # First discovery
        mock_mdns.return_value = [first_device]
        await module.discover()
        assert module.devices == [first_device]

        # Now refresh — should clear and re-run
        mock_mdns.return_value = [second_device]
        result = await module.refresh()

    assert result == [second_device]
    assert module.devices == [second_device]
    # Verify discover was called twice (once for discover, once for refresh)
    assert mock_mdns.await_count == 2


# --------------------------------------------------------------------------
# SubnetScanner — project field filtering
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "project,expected",
    [
        ("WiiM_Pro_Plus", True),
        ("WiiM_Ultra", True),
        ("WiiM_Amp", True),
        ("WiiM_Mini", True),
        ("WiiM_Sound_Lite", True),
        ("WiiM Pro Plus", True),
        ("WiiM Ultra", True),
        # Forward-compatible: any "WiiM" prefix accepted
        ("WiiM_Future_Model", True),
        ("wiim_pro", True),
        # Non-WiiM devices rejected
        ("LinkPlay_A31", False),
        ("Arylic_Up2Stream", False),
        ("", False),
        ("SomeOtherDevice", False),
    ],
)
def test_is_recognised_project(project: str, expected: bool) -> None:
    """is_wiim_device accepts WiiM devices and rejects others."""
    assert is_wiim_device(project) is expected


async def test_subnet_scanner_accepts_wiim_project() -> None:
    """SubnetScanner includes hosts with recognised WiiM project field."""
    mock_client = AsyncMock()
    mock_client.command = AsyncMock(return_value=_make_status_response("WiiM_Pro_Plus"))
    mock_client.close = AsyncMock()

    scanner = SubnetScanner(
        timeout=1.0,
        http_client_factory=lambda ip: mock_client,
    )

    with patch(
        "src.discovery.subnet_scanner._get_local_ip", return_value="192.168.1.10"
    ):
        devices = await scanner.scan()

    # Should find at least one device (from the 253 hosts scanned)
    assert len(devices) > 0
    assert all(d.model == "WiiM_Pro_Plus" for d in devices)


async def test_subnet_scanner_rejects_non_wiim_project() -> None:
    """SubnetScanner excludes hosts with unrecognised project fields."""
    mock_client = AsyncMock()
    mock_client.command = AsyncMock(
        return_value=_make_status_response("LinkPlay_Generic")
    )
    mock_client.close = AsyncMock()

    scanner = SubnetScanner(
        timeout=1.0,
        http_client_factory=lambda ip: mock_client,
    )

    with patch(
        "src.discovery.subnet_scanner._get_local_ip", return_value="192.168.1.10"
    ):
        devices = await scanner.scan()

    assert devices == []


# --------------------------------------------------------------------------
# ZeroconfDiscover — empty/no-response handling
# --------------------------------------------------------------------------


async def test_zeroconf_handles_no_services_gracefully() -> None:
    """ZeroconfDiscover returns empty list when no mDNS services respond."""
    zc = ZeroconfDiscover(timeout=0.1)

    with patch(
        "src.discovery.zeroconf_discover.AsyncZeroconf"
    ) as mock_azc_cls:
        # Mock the AsyncZeroconf instance
        mock_azc = MagicMock()
        mock_azc.zeroconf = MagicMock()
        mock_azc.async_close = AsyncMock()
        mock_azc_cls.return_value = mock_azc

        # Mock the browser — it never fires an event (no services found)
        with patch(
            "src.discovery.zeroconf_discover.AsyncServiceBrowser"
        ) as mock_browser_cls:
            mock_browser = MagicMock()
            mock_browser.async_cancel = AsyncMock()
            mock_browser_cls.return_value = mock_browser

            result = await zc.discover()

    assert result == []


async def test_zeroconf_exception_propagates_to_discovery_module() -> None:
    """When ZeroconfDiscover raises, DiscoveryModule catches it and returns []."""
    module = DiscoveryModule(timeout=0.1)

    with patch(
        "src.discovery.zeroconf_discover.AsyncZeroconf"
    ) as mock_azc_cls:
        mock_azc_cls.side_effect = OSError("Network interface unavailable")

        # DiscoveryModule.discover() catches all exceptions gracefully
        result = await module.discover()

    assert result == []


async def test_zeroconf_returns_empty_when_service_has_no_addresses() -> None:
    """ZeroconfDiscover skips services that have no resolved addresses."""
    zc = ZeroconfDiscover(timeout=0.1)

    with patch(
        "src.discovery.zeroconf_discover.AsyncZeroconf"
    ) as mock_azc_cls:
        mock_azc = MagicMock()
        mock_azc.zeroconf = MagicMock()
        mock_azc.async_close = AsyncMock()
        mock_azc_cls.return_value = mock_azc

        with patch(
            "src.discovery.zeroconf_discover.AsyncServiceBrowser"
        ) as mock_browser_cls:
            mock_browser = MagicMock()
            mock_browser.async_cancel = AsyncMock()
            mock_browser_cls.return_value = mock_browser

            # Simulate a service being found but with no resolvable address
            with patch(
                "src.discovery.zeroconf_discover.AsyncServiceInfo"
            ) as mock_info_cls:
                mock_info = MagicMock()
                mock_info.parsed_scoped_addresses.return_value = []
                mock_info.async_request = AsyncMock()
                mock_info_cls.return_value = mock_info

                # We need the browser handler to fire — simulate by calling
                # the handler directly with a found service
                def capture_handler(*args, **kwargs):
                    # The handler is the first positional after zeroconf and service_type
                    handler = kwargs.get("handlers", args[2] if len(args) > 2 else None)
                    if handler and isinstance(handler, list):
                        from zeroconf import ServiceStateChange

                        handler[0](
                            mock_azc.zeroconf,
                            "_wiim._tcp.local.",
                            "TestDevice._wiim._tcp.local.",
                            ServiceStateChange.Added,
                        )
                    return mock_browser

                mock_browser_cls.side_effect = capture_handler

                result = await zc.discover()

    # Device with no addresses is skipped
    assert result == []


async def test_zeroconf_probes_both_service_types_concurrently() -> None:
    """A device that only answers `_linkplay._tcp.local.` (never
    `_wiim._tcp.local.`) must still be found within a single timeout window,
    not after waiting out a full timeout on the WiiM-specific type first.

    Regression test: ZeroconfDiscover used to probe service types
    sequentially, each waiting the full timeout before moving on. A device
    that never answers the first type (e.g. older LinkPlay-only hardware)
    would starve the working probe of its share of the time budget.
    """
    import time

    timeout = 0.2
    zc = ZeroconfDiscover(timeout=timeout)

    with patch("src.discovery.zeroconf_discover.AsyncZeroconf") as mock_azc_cls:
        mock_azc = MagicMock()
        mock_azc.zeroconf = MagicMock()
        mock_azc.async_close = AsyncMock()
        mock_azc_cls.return_value = mock_azc

        with patch(
            "src.discovery.zeroconf_discover.AsyncServiceBrowser"
        ) as mock_browser_cls:
            mock_browser = MagicMock()
            mock_browser.async_cancel = AsyncMock()

            def capture_handler(zeroconf, service_types, handlers):
                # Confirm both service types are browsed in a single call.
                assert service_types == [
                    "_wiim._tcp.local.",
                    "_linkplay._tcp.local.",
                ]
                from zeroconf import ServiceStateChange

                handlers[0](
                    mock_azc.zeroconf,
                    "_linkplay._tcp.local.",
                    "TestDevice._linkplay._tcp.local.",
                    ServiceStateChange.Added,
                )
                return mock_browser

            mock_browser_cls.side_effect = capture_handler

            with patch(
                "src.discovery.zeroconf_discover.AsyncServiceInfo"
            ) as mock_info_cls:
                mock_info = MagicMock()
                mock_info.parsed_scoped_addresses.return_value = ["192.168.1.77"]
                mock_info.properties = {}
                mock_info.server = "TestDevice.local."
                mock_info.async_request = AsyncMock()
                mock_info_cls.return_value = mock_info

                start = time.monotonic()
                result = await zc.discover()
                elapsed = time.monotonic() - start

    assert len(result) == 1
    assert result[0].ip == "192.168.1.77"
    # Found via the second service type, but must not have cost a second
    # full timeout — total time should stay well under 2x timeout.
    assert elapsed < timeout * 2


# --------------------------------------------------------------------------
# Property-Based Test: discovery result field completeness
# --------------------------------------------------------------------------

# Strategy: generate valid getStatusEx response dicts with recognised WiiM projects
_WIIM_PROJECTS = st.sampled_from(["WiiM_Pro", "WiiM_Mini", "WiiM_Amp", "WiiM_Ultra"])


@given(
    project=_WIIM_PROJECTS,
    device_name=st.text(min_size=1),
    release=st.text(min_size=1),
    uuid=st.text(),
    ip=st.from_regex(
        r"192\.168\.\d{1,3}\.\d{1,3}", fullmatch=True
    ),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_pbt_discovery_result_field_completeness(
    project: str,
    device_name: str,
    release: str,
    uuid: str,
    ip: str,
) -> None:
    """For any valid WiiM getStatusEx response, SubnetScanner must produce a
    DeviceInfo with non-empty ip, name, model, and firmware.

    **Validates: Requirements 1.5, 1.8**
    """
    response: dict[str, str] = {
        "project": project,
        "DeviceName": device_name,
        "Release": release,
        "uuid": uuid,
    }

    scanner = SubnetScanner(timeout=1.0)
    result = scanner._parse_status_response(ip, response)

    # A recognised WiiM project must always produce a DeviceInfo
    assert result is not None, f"Expected DeviceInfo for project={project}, got None"
    assert isinstance(result, DeviceInfo)

    # All key fields must be non-empty
    assert result.ip, "DeviceInfo.ip must be non-empty"
    assert result.name, "DeviceInfo.name must be non-empty"
    assert result.model, "DeviceInfo.model must be non-empty"
    assert result.firmware, "DeviceInfo.firmware must be non-empty"


# --------------------------------------------------------------------------
# mDNS enrichment — hardware validation findings
# --------------------------------------------------------------------------


async def test_mdns_enrichment_populates_model_firmware() -> None:
    """After mDNS enrichment, model and firmware should be populated from getStatusEx."""
    # Device discovered via mDNS with empty model/firmware
    bare_device = DeviceInfo(
        ip="192.168.1.77",
        name="Bedroom Speaker",
        model="",
        firmware="",
        uuid="",
    )

    status_response = {
        "project": "WiiM_Pro",
        "DeviceName": "Bedroom Speaker",
        "Release": "6.1.0.5",
        "uuid": "enriched-uuid-001",
    }

    with patch(
        "src.adapters.wiim_http.WiiMHttpClient"
    ) as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.command = AsyncMock(return_value=status_response)
        mock_client.close = AsyncMock()
        mock_client_cls.return_value = mock_client

        from src.discovery.discovery_module import _enrich_device

        enriched = await _enrich_device(bare_device, timeout=5.0)

    assert enriched.model == "WiiM_Pro"
    assert enriched.firmware == "6.1.0.5"
    assert enriched.name == "Bedroom Speaker"
    assert enriched.ip == "192.168.1.77"


async def test_enrich_device_uses_injected_http_client_factory() -> None:
    """_enrich_device() must honor an injected http_client_factory instead
    of always constructing a real WiiMHttpClient directly -- matching the
    same DI contract SubnetScanner already honors, so a caller (e.g.
    DiscoveryModule) that injects a factory for testing/DI purposes actually
    has it reach this function too."""
    from src.discovery.discovery_module import _enrich_device

    bare_device = DeviceInfo(ip="192.168.1.77", name="Bedroom Speaker", model="", firmware="")

    mock_client = AsyncMock()
    mock_client.command = AsyncMock(
        return_value={"project": "WiiM_Pro", "Release": "6.1.0.5", "uuid": "abc"}
    )
    mock_client.close = AsyncMock()
    factory = MagicMock(return_value=mock_client)

    enriched = await _enrich_device(bare_device, timeout=5.0, http_client_factory=factory)

    factory.assert_called_once_with("192.168.1.77")
    assert enriched.model == "WiiM_Pro"


async def test_discovery_module_passes_its_factory_through_to_enrich_device() -> None:
    """DiscoveryModule's own injected http_client_factory must reach
    _enrich_device via _enrich_mdns_devices, not just SubnetScanner -- the
    factory was previously stored on self._http_client_factory but only
    ever read when constructing SubnetScanner, never passed to
    _enrich_device."""
    mock_client = AsyncMock()
    mock_client.command = AsyncMock(
        return_value={"project": "WiiM_Pro", "Release": "6.1.0.5", "uuid": "abc"}
    )
    mock_client.close = AsyncMock()
    factory = MagicMock(return_value=mock_client)

    module = DiscoveryModule(timeout=5.0, http_client_factory=factory)
    bare_device = DeviceInfo(ip="192.168.1.77", name="Bedroom Speaker", model="", firmware="")

    enriched = await module._enrich_mdns_devices([bare_device])

    factory.assert_called_once_with("192.168.1.77")
    assert enriched[0].model == "WiiM_Pro"
