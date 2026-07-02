"""Smoke tests for higher-level integration issues.

Covers smoke test issues: #88 (Discovery), #96 (REW Measurements),
#97 (Filter Parsing), #99 (Device Identity), #120 (REW L/R Bleed).

Each test calls the real production code path the fix landed in (not a
hand-rolled reimplementation of the fix logic), so a regression in the
actual code will fail the test.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

from src.discovery.discovery_module import _MDNS_GRACE_PERIOD, DiscoveryModule
from src.models.capabilities import DeviceInfo
from src.utils.device_identity import is_wiim_device

# ===========================================================================
# ISSUE #88: Discovery (parallel mDNS + subnet scan)
# ===========================================================================


async def test_discovery_module_parallel_scan_grace_period() -> None:
    """#88: mDNS and subnet scan run concurrently, not sequentially.

    Previously discovery ran mDNS-then-subnet-scan sequentially, so a cold
    start could take ~30s. The fix makes DiscoveryModule.discover() start
    the subnet scan in parallel with mDNS once the grace period elapses,
    then await *both* remaining tasks concurrently instead of waiting for
    mDNS to finish before ever starting the subnet scan.

    mDNS is made to run past the grace period (mdns_delay > grace), so the
    "wait for remaining mDNS time" phase and the subnet scan genuinely
    overlap. A sequential implementation would total
    ~= mdns_delay + subnet_delay; the real parallel implementation should
    total ~= max(mdns_delay, grace + subnet_delay).
    """
    grace = _MDNS_GRACE_PERIOD  # 1.5s
    mdns_delay = grace + 0.4  # mDNS resolves shortly after the grace period
    subnet_delay = 0.4

    module = DiscoveryModule(timeout=5.0)

    async def fake_mdns_discover() -> list[DeviceInfo]:
        await asyncio.sleep(mdns_delay)
        return []  # mDNS finds nothing -> forces the subnet-scan path

    async def fake_subnet_scan() -> list[DeviceInfo]:
        await asyncio.sleep(subnet_delay)
        return [
            DeviceInfo(
                ip="192.168.1.50",
                name="Living Room",
                model="WiiM_Pro_Plus",
                firmware="4.8.5",
                uuid="uuid-1",
            )
        ]

    with (
        patch.object(module._zeroconf, "discover", side_effect=fake_mdns_discover),
        patch.object(module._scanner, "scan", side_effect=fake_subnet_scan),
    ):
        start = time.monotonic()
        result = await module.discover()
        elapsed = time.monotonic() - start

    assert len(result) == 1
    assert result[0].ip == "192.168.1.50"

    # Sequential (mDNS fully awaited, *then* subnet scan started) would take
    # >= mdns_delay + subnet_delay. Parallel (subnet scan starts as soon as
    # the grace period elapses, running alongside the remaining mDNS wait)
    # should take roughly max(mdns_delay, grace + subnet_delay), i.e. bounded
    # by mdns_delay here since grace + subnet_delay < mdns_delay.
    sequential_floor = mdns_delay + subnet_delay
    assert elapsed < sequential_floor - 0.2, (
        f"discover() took {elapsed:.2f}s -- expected well under the "
        f"{sequential_floor:.2f}s a sequential mDNS-then-subnet-scan "
        "implementation would take, proving the two scans ran concurrently"
    )
    # Also assert it's close to the parallel expectation (not just "faster
    # than sequential" by luck) -- allow generous scheduling slack.
    assert elapsed < mdns_delay + 0.3


async def test_discovery_module_grace_period_constant() -> None:
    """#88: the grace period constant used to gate the parallel start is 1.5s."""
    assert _MDNS_GRACE_PERIOD == 1.5


# ===========================================================================
# ISSUE #96: REW Measurements (Dict-keyed response)
# ===========================================================================


async def test_rew_http_client_handles_dict_keys() -> None:
    """#96: REW client parses dict-keyed measurements (keys "1", "2")."""
    from src.adapters.rew_http_client import REWHttpApiClient

    response_payload = {
        "1": {"title": "Living Room L", "uuid": "uuid-aaa"},
        "2": {"title": "Living Room R", "uuid": "uuid-bbb"},
    }

    client = REWHttpApiClient()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = response_payload

    try:
        with patch.object(client, "_get", new=AsyncMock(return_value=mock_response)):
            measurements = await client.list_measurements()
    finally:
        await client.close()

    assert len(measurements) == 2
    assert measurements[0].uuid == "uuid-aaa"
    assert measurements[0].name == "Living Room L"
    assert measurements[0].index == 0
    assert measurements[1].uuid == "uuid-bbb"
    assert measurements[1].name == "Living Room R"
    assert measurements[1].index == 1


# ===========================================================================
# ISSUE #97: Filter Parsing (Unknown filter type)
# ===========================================================================


def test_unknown_filter_type_skipped() -> None:
    """#97: REW parser skips unknown/unsupported filter types.

    "Modal" has no WiiM translation (see rew_parser._SKIP_TYPES) and must
    be silently dropped by the real parser, without raising and without
    disturbing the valid PEAK filters around it.
    """
    from src.translator.rew_parser import REWParser

    parser = REWParser()
    settings = [
        {"enabled": True, "type": "PK", "frequency": 1000.0, "gaindB": -3.0, "q": 1.0},
        {"enabled": True, "type": "Modal", "frequency": 500.0, "gaindB": 0.0, "q": 0.5},
        {"enabled": True, "type": "PK", "frequency": 2000.0, "gaindB": 2.0, "q": 2.0},
    ]

    parsed = parser.parse_filter_settings(settings)

    assert len(parsed) == 2
    assert parsed[0].type == "PEAK"
    assert parsed[0].frequency_hz == 1000.0
    assert parsed[1].type == "PEAK"
    assert parsed[1].frequency_hz == 2000.0


# ===========================================================================
# ISSUE #99: Device Identity (Unified logic)
# ===========================================================================


def test_unified_device_identity() -> None:
    """#99: is_wiim_device correctly identifies known WiiM models."""
    assert is_wiim_device("WiiM Pro Plus") is True
    assert is_wiim_device("WiiM Mini") is True
    assert is_wiim_device("Generic Speaker") is False


async def test_capability_prober_delegates_to_device_identity() -> None:
    """#99: CapabilityProber.probe() must classify devices via the single
    shared src.utils.device_identity.is_wiim_device() function, not a
    reimplemented/duplicated device list.

    Monkeypatches the shared function itself so the only way this test can
    pass is if CapabilityProber's real probe() code path actually calls it.
    """
    from src.adapters.capability_prober import CapabilityProber

    mock_client = MagicMock()

    async def fake_command(cmd: str, **_kwargs: object) -> dict[str, object]:
        if cmd == "getStatusEx":
            return {
                "project": "Some_Nonstandard_Name",
                "DeviceName": "Test Device",
                "firmware": "1.0.0",
                "uuid": "uuid-xyz",
            }
        raise RuntimeError(f"unexpected command {cmd}")

    mock_client.command = AsyncMock(side_effect=fake_command)
    mock_client.host = "192.168.1.50"

    prober = CapabilityProber(mock_client)

    with patch(
        "src.adapters.capability_prober.is_wiim_device", return_value=False
    ) as mock_is_wiim:
        caps = await prober.probe()

    mock_is_wiim.assert_called_once_with("Some_Nonstandard_Name")
    # Conservative defaults are applied when is_wiim_device() says "no".
    assert caps.supports_peq is False
    assert caps.max_filters == 0


def test_subnet_scanner_delegates_to_device_identity() -> None:
    """#99: SubnetScanner._parse_status_response() must classify devices via
    the shared src.utils.device_identity.is_wiim_device() function, not a
    reimplemented/duplicated device list.
    """
    from src.discovery.subnet_scanner import SubnetScanner

    scanner = SubnetScanner()

    with patch(
        "src.discovery.subnet_scanner.is_wiim_device", return_value=False
    ) as mock_is_wiim:
        result = scanner._parse_status_response(
            "192.168.1.77", {"project": "Some_Nonstandard_Name", "DeviceName": "X"}
        )

    mock_is_wiim.assert_called_once_with("Some_Nonstandard_Name")
    assert result is None  # Rejected because the shared function said "no"

    with patch(
        "src.discovery.subnet_scanner.is_wiim_device", return_value=True
    ) as mock_is_wiim_true:
        accepted = scanner._parse_status_response(
            "192.168.1.77", {"project": "Some_Nonstandard_Name", "DeviceName": "X"}
        )

    mock_is_wiim_true.assert_called_once_with("Some_Nonstandard_Name")
    assert accepted is not None
    assert accepted.ip == "192.168.1.77"


# ===========================================================================
# ISSUE #120: REW L/R Bleed (Unequal band counts)
# ===========================================================================


async def test_rew_parser_lr_bleed_unequal_bands(qtbot) -> None:
    """#120: an empty (but present) right channel must not fall back to a
    naive 50/50 split that bleeds left-channel data into the right.

    The real bug lived in MainWindow._on_peq_ready(): `bands_l and bands_r`
    was falsy for an empty list, so an explicitly-empty right channel
    (`bands_r == []`, not None) incorrectly fell through to the
    split_lr_filters() 50/50 fallback. The fix changed the check to
    `bands_l is not None and bands_r is not None`, so an empty-but-present
    right channel is honored as "no right-channel filters" instead of being
    guessed via a naive split.
    """
    from unittest.mock import patch as _patch

    from src.gui.app_settings import AppSettings
    from src.gui.main_window import MainWindow
    from src.models.canonical import CanonicalFilter
    from src.models.channel_mode import ChannelMode
    from src.tests.conftest import close_coroutine_tree

    mock_bridge = MagicMock()
    mock_bridge.run_async = MagicMock(side_effect=close_coroutine_tree)
    app_settings = AppSettings(first_run_complete=True)

    with (
        _patch("src.gui.app_settings.AppSettings.load", return_value=app_settings),
        _patch("src.gui.app_settings.AppSettings.save"),
    ):
        window = MainWindow(async_bridge=mock_bridge)
        qtbot.addWidget(window)

    try:
        filters_l = [
            CanonicalFilter(type="PEAK", frequency_hz=100.0, gain_db=-3.0, q=1.0),
            CanonicalFilter(type="PEAK", frequency_hz=200.0, gain_db=1.0, q=2.0),
            CanonicalFilter(type="PEAK", frequency_hz=300.0, gain_db=2.0, q=3.0),
        ]
        state = window._wizard_controller.state
        state.current_filters = list(filters_l)
        state.channel_mode = ChannelMode.LR

        peq_data = MagicMock()
        peq_data.channel_mode = "lr"
        peq_data.bands_l = filters_l
        peq_data.bands_r = []  # Genuinely empty right channel, not None

        with patch.object(window._review_page, "set_lr_filters") as mock_set_lr:
            window._on_peq_ready(peq_data)
            mock_set_lr.assert_called_once()
            called_l, called_r = mock_set_lr.call_args[0][0], mock_set_lr.call_args[0][1]

        # Right stays empty -- no naive 50/50 split fallback was applied.
        assert called_r == []
        # Left keeps all of its own filters, untouched by any split.
        assert len(called_l) == 3
        assert [f.frequency_hz for f in called_l] == [100.0, 200.0, 300.0]
        assert state.filters_r == []
        assert len(state.filters_l) == 3
    finally:
        state.current_filters = []
        window.close()
