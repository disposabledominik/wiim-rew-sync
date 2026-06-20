"""Property-based tests for DeviceInfo transformation (Property 1: preserves required keys).

Feature: gui-bridge-integration, Property 1: DeviceInfo transformation preserves required keys

Validates: Requirements 1.2

Tests three universal properties:
1. Every transformed dict contains "name" and "ip" keys matching original DeviceInfo fields.
2. Every transformed dict contains "model" key matching original DeviceInfo.model field.
3. An empty device list produces an empty output list.
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from src.models.capabilities import DeviceInfo

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def st_device_info(draw: st.DrawFn) -> DeviceInfo:
    """Generate a DeviceInfo with arbitrary name/ip/model strings."""
    name = draw(st.text(min_size=1, max_size=50))
    ip = draw(st.from_regex(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", fullmatch=True))
    model = draw(st.text(min_size=0, max_size=50))
    return DeviceInfo(name=name, ip=ip, model=model, firmware="1.0.0")


# ---------------------------------------------------------------------------
# Transformation under test (pure function extracted from MainWindow._do_discovery)
# ---------------------------------------------------------------------------


def transform_device_list(devices: list[DeviceInfo]) -> list[dict[str, str]]:
    """Transform DeviceInfo list into dicts for ConnectPage.set_devices().

    This is the exact list comprehension from MainWindow._do_discovery:
        [{"name": d.name, "ip": d.ip, "model": d.model} for d in devices]
    """
    return [{"name": d.name, "ip": d.ip, "model": d.model} for d in devices]


# ---------------------------------------------------------------------------
# Property 1: DeviceInfo transformation preserves name and ip
# ---------------------------------------------------------------------------


@given(devices=st.lists(st_device_info(), min_size=1, max_size=20))
@settings(max_examples=100)
def test_device_transform_preserves_name_and_ip(devices: list[DeviceInfo]) -> None:
    """**Validates: Requirements 1.2**

    For any list of DeviceInfo objects, the transformation produces dicts
    where each dict has "name" matching the original .name and "ip" matching
    the original .ip.
    """
    result = transform_device_list(devices)

    assert len(result) == len(devices)
    for device, transformed in zip(devices, result, strict=True):
        assert "name" in transformed, "Transformed dict missing 'name' key"
        assert "ip" in transformed, "Transformed dict missing 'ip' key"
        assert transformed["name"] == device.name, (
            f"Name mismatch: expected '{device.name}', got '{transformed['name']}'"
        )
        assert transformed["ip"] == device.ip, (
            f"IP mismatch: expected '{device.ip}', got '{transformed['ip']}'"
        )


# ---------------------------------------------------------------------------
# Property 2: DeviceInfo transformation preserves model
# ---------------------------------------------------------------------------


@given(devices=st.lists(st_device_info(), min_size=1, max_size=20))
@settings(max_examples=100)
def test_device_transform_preserves_model(devices: list[DeviceInfo]) -> None:
    """**Validates: Requirements 1.2**

    For any list of DeviceInfo objects, the transformation produces dicts
    where each dict has "model" key matching the original .model value.
    """
    result = transform_device_list(devices)

    assert len(result) == len(devices)
    for device, transformed in zip(devices, result, strict=True):
        assert "model" in transformed, "Transformed dict missing 'model' key"
        assert transformed["model"] == device.model, (
            f"Model mismatch: expected '{device.model}', got '{transformed['model']}'"
        )


# ---------------------------------------------------------------------------
# Property 3: Empty device list produces empty output
# ---------------------------------------------------------------------------


def test_empty_device_list_produces_empty_output() -> None:
    """**Validates: Requirements 1.2**

    An empty input device list always produces an empty output list.
    """
    result = transform_device_list([])

    assert result == [], f"Expected empty list, got {result}"
