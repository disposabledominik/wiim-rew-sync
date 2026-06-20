"""Property-based tests for SecondaryWorkflowManager fault isolation.

Feature: gui-bridge-integration, Property 3: Copy-to-sources fault isolation
Feature: gui-bridge-integration, Property 4: Multi-device push fault isolation

Validates: Requirements 9.3, 9.6, 9.7, 10.3, 10.6, 10.7

Tests two universal correctness properties:
1. Copy-to-sources: every source is attempted regardless of prior failures,
   exactly one SourceCopyResult per source, success field accurate.
2. Multi-device push: every device is attempted regardless of prior failures,
   exactly one DevicePushResult per device, success field accurate.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.gui.secondary_workflows import (
    DevicePushResult,
    MultiDeviceRequest,
    SecondaryWorkflowManager,
    SourceCopyResult,
)
from src.models.canonical import CanonicalFilter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_filters() -> list[CanonicalFilter]:
    """Create a minimal valid filter list for test purposes."""
    return [CanonicalFilter(type="PEAK", frequency_hz=1000.0, gain_db=0.0, q=1.0)]


def _make_configurable_safe_write(sources_or_devices: list[str], failure_mask: list[bool]):
    """Create a mock SafeWrite whose execute() raises for flagged items.

    The failure_mask is padded/trimmed to match the length of the items list.
    The mock tracks which source_name it was called with and raises RuntimeError
    for items where failure_mask[i] is True.
    """
    # Pad or trim failure_mask to match items length
    mask = list(failure_mask)
    while len(mask) < len(sources_or_devices):
        mask.append(False)
    mask = mask[: len(sources_or_devices)]

    # Build a mapping: item_name -> should_fail
    fail_map = {name: mask[i] for i, name in enumerate(sources_or_devices)}

    mock_sw = AsyncMock()

    async def execute_side_effect(source_name, settings):
        if fail_map.get(source_name, False):
            raise RuntimeError(f"Simulated failure for {source_name}")
        return None

    mock_sw.execute = AsyncMock(side_effect=execute_side_effect)
    return mock_sw, mask


# ---------------------------------------------------------------------------
# Property 3: Copy-to-sources fault isolation
# ---------------------------------------------------------------------------


@given(
    sources=st.lists(
        st.text(
            min_size=1,
            max_size=20,
            alphabet=st.characters(whitelist_categories=("L", "N")),
        ),
        min_size=1,
        max_size=10,
        unique=True,
    ),
    failure_mask=st.lists(st.booleans(), min_size=1, max_size=10),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_copy_to_sources_fault_isolation(
    sources: list[str], failure_mask: list[bool]
) -> None:
    """**Validates: Requirements 9.3, 9.6, 9.7**

    For any non-empty list of target sources and any failure bitmap:
    - Every source is attempted (SafeWrite.execute called for each)
    - Exactly one SourceCopyResult per source in the results
    - Each result's success field accurately reflects the outcome
    """
    # Pad/trim failure_mask to match sources length
    mask = list(failure_mask)
    while len(mask) < len(sources):
        mask.append(False)
    mask = mask[: len(sources)]

    # Create manager
    manager = SecondaryWorkflowManager()

    # Create configurable mock SafeWrite
    mock_sw, effective_mask = _make_configurable_safe_write(sources, failure_mask)

    # Mock adapter (needed for _current_adapter assertion)
    mock_adapter = MagicMock()
    manager._current_adapter = mock_adapter

    # Mock safe_write_factory to return our configurable mock
    manager._safe_write_factory = MagicMock(return_value=mock_sw)

    # Capture emitted results
    emitted_results: list[list[SourceCopyResult]] = []
    manager.copy_to_sources_complete.connect(lambda r: emitted_results.append(r))

    # Execute the async method directly
    filters = _make_filters()
    await manager._do_copy_to_sources(filters, sources)

    # Assertions
    assert len(emitted_results) == 1, "copy_to_sources_complete should be emitted exactly once"

    results = emitted_results[0]

    # (a) Exactly one SourceCopyResult per source
    assert len(results) == len(sources), (
        f"Expected {len(sources)} results, got {len(results)}"
    )

    # (b) Every source appears exactly once
    result_source_names = [r.source_name for r in results]
    assert result_source_names == sources, (
        f"Results order/contents don't match sources: {result_source_names} vs {sources}"
    )

    # (c) Success field accurately reflects the failure mask
    for i, result in enumerate(results):
        expected_success = not effective_mask[i]
        assert result.success == expected_success, (
            f"Source '{sources[i]}': expected success={expected_success}, "
            f"got success={result.success}"
        )


# ---------------------------------------------------------------------------
# Property 4: Multi-device push fault isolation
# ---------------------------------------------------------------------------


@given(
    device_ips=st.lists(
        st.from_regex(r"192\.168\.\d{1,3}\.\d{1,3}", fullmatch=True),
        min_size=1,
        max_size=5,
        unique=True,
    ),
    failure_mask=st.lists(st.booleans(), min_size=1, max_size=5),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@pytest.mark.asyncio
async def test_multi_device_fault_isolation(
    device_ips: list[str], failure_mask: list[bool]
) -> None:
    """**Validates: Requirements 10.3, 10.6, 10.7**

    For any non-empty list of target devices and any failure bitmap:
    - Every device is attempted regardless of prior failures
    - Exactly one DevicePushResult per device in the results
    - Each result's success field accurately reflects the outcome
    """
    # Pad/trim failure_mask to match device_ips length
    mask = list(failure_mask)
    while len(mask) < len(device_ips):
        mask.append(False)
    mask = mask[: len(device_ips)]

    # Build a MultiDeviceRequest with one source per device
    source_name = "wifi"
    device_source_map = {ip: [source_name] for ip in device_ips}
    device_names = {ip: f"Device_{i}" for i, ip in enumerate(device_ips)}
    request = MultiDeviceRequest(
        device_source_map=device_source_map,
        device_names=device_names,
    )

    # Build fail_map: device_ip -> should_fail
    fail_map = {ip: mask[i] for i, ip in enumerate(device_ips)}

    # Create manager
    manager = SecondaryWorkflowManager()

    # Create per-device mock adapters and safe_writes
    def adapter_factory(ip: str):
        adapter = MagicMock()
        adapter.ip = ip
        return adapter

    def safe_write_factory(adapter):
        mock_sw = AsyncMock()
        ip = adapter.ip

        async def execute_side_effect(source_name, settings):
            if fail_map.get(ip, False):
                raise RuntimeError(f"Simulated failure for {ip}")
            return None

        mock_sw.execute = AsyncMock(side_effect=execute_side_effect)
        return mock_sw

    manager._wiim_adapter_factory = MagicMock(side_effect=adapter_factory)
    manager._safe_write_factory = MagicMock(side_effect=safe_write_factory)

    # Capture emitted results
    emitted_results: list[list[DevicePushResult]] = []
    manager.multi_device_complete.connect(lambda r: emitted_results.append(r))

    # Execute the async method directly
    filters = _make_filters()
    await manager._do_apply_to_devices(filters, request)

    # Assertions
    assert len(emitted_results) == 1, "multi_device_complete should be emitted exactly once"

    results = emitted_results[0]

    # (a) Exactly one DevicePushResult per device
    assert len(results) == len(device_ips), (
        f"Expected {len(device_ips)} results, got {len(results)}"
    )

    # (b) Every device appears exactly once in results
    result_ips = [r.device_ip for r in results]
    assert result_ips == device_ips, (
        f"Results order/contents don't match devices: {result_ips} vs {device_ips}"
    )

    # (c) Success field accurately reflects the failure mask
    for i, result in enumerate(results):
        expected_success = not mask[i]
        assert result.success == expected_success, (
            f"Device '{device_ips[i]}': expected success={expected_success}, "
            f"got success={result.success}"
        )
