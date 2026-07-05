"""Tests for the CLI proof-of-concept commands (src/cli/main.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adapters.safe_write import WriteResult
from src.cli import main as cli
from src.models.canonical import CanonicalFilter
from src.models.capabilities import DeviceCapabilities, DeviceInfo
from src.models.channel_mode import ChannelMode
from src.models.errors import WiiMConnectionError
from src.models.peq import PEQSettings

# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------


def _make_device(name: str = "Living Room", ip: str = "192.168.1.50") -> DeviceInfo:
    return DeviceInfo(
        ip=ip,
        name=name,
        model="WiiM_Pro",
        firmware="4.8.123",
        role="solo",
    )


def _make_caps(source_names: list[str] | None = None) -> DeviceCapabilities:
    return DeviceCapabilities(
        supports_peq=True,
        max_filters=10,
        source_names=source_names if source_names is not None else ["wifi"],
    )


def _make_settings(channel_mode: str = "stereo") -> PEQSettings:
    bands = [
        CanonicalFilter(
            type="PEAK",
            frequency_hz=100.0 * (i + 1),
            gain_db=1.5,
            q=1.0,
        )
        for i in range(10)
    ]
    if channel_mode == "lr":
        return PEQSettings(
            source_name="wifi",
            channel_mode="lr",
            bands_l=bands,
            bands_r=bands,
        )
    return PEQSettings(source_name="wifi", channel_mode="stereo", bands=bands)


def _patch_discovery(monkeypatch: pytest.MonkeyPatch, devices: list[DeviceInfo]) -> None:
    module_instance = MagicMock()
    module_instance.discover = AsyncMock(return_value=devices)
    monkeypatch.setattr(cli, "DiscoveryModule", MagicMock(return_value=module_instance))


def _patch_read_stack(
    monkeypatch: pytest.MonkeyPatch,
    *,
    caps: DeviceCapabilities,
    read_peq: AsyncMock,
) -> None:
    client_instance = MagicMock()
    client_instance.close = AsyncMock()
    monkeypatch.setattr(cli, "WiiMHttpClient", MagicMock(return_value=client_instance))

    prober_instance = MagicMock()
    prober_instance.probe = AsyncMock(return_value=caps)
    monkeypatch.setattr(cli, "CapabilityProber", MagicMock(return_value=prober_instance))

    adapter_instance = MagicMock()
    adapter_instance.read_peq = read_peq
    monkeypatch.setattr(cli, "WiiMAdapter", MagicMock(return_value=adapter_instance))


# ---------------------------------------------------------------------------
# list-devices
# ---------------------------------------------------------------------------


def test_list_devices_with_results(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_discovery(monkeypatch, [_make_device()])

    code = cli.cmd_list_devices(timeout=5.0)

    out = capsys.readouterr().out
    assert code == 0
    assert "Living Room" in out
    assert "192.168.1.50" in out
    assert "WiiM_Pro" in out
    assert "Role" in out  # header present
    assert "No devices found." not in out


def test_list_devices_empty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_discovery(monkeypatch, [])

    code = cli.cmd_list_devices(timeout=5.0)

    out = capsys.readouterr().out
    assert code == 0
    assert out.strip() == "No devices found."


def test_list_devices_via_main_exits_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_discovery(monkeypatch, [])

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["list-devices"])

    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# get-filters
# ---------------------------------------------------------------------------


def test_get_filters_success(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_read_stack(
        monkeypatch,
        caps=_make_caps(),
        read_peq=AsyncMock(return_value=_make_settings("stereo")),
    )

    code = cli.cmd_get_filters(
        device="192.168.1.50", source=None, channel="stereo", timeout=5.0
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "Band" in out
    assert "Frequency (Hz)" in out
    # 10 bands -> band numbers 1..10 present
    assert "10" in out
    assert "PEAK" in out


def test_get_filters_channel_selects_right(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_read_stack(
        monkeypatch,
        caps=_make_caps(),
        read_peq=AsyncMock(return_value=_make_settings("lr")),
    )

    code = cli.cmd_get_filters(
        device="192.168.1.50", source="wifi", channel="right", timeout=5.0
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "PEAK" in out


def test_get_filters_connection_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _patch_read_stack(
        monkeypatch,
        caps=_make_caps(),
        read_peq=AsyncMock(side_effect=WiiMConnectionError("device offline")),
    )

    code = cli.cmd_get_filters(
        device="192.168.1.99", source=None, channel="stereo", timeout=5.0
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "device offline" in captured.err
    assert captured.out == ""


def test_get_filters_via_main_exits_one_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_read_stack(
        monkeypatch,
        caps=_make_caps(),
        read_peq=AsyncMock(side_effect=WiiMConnectionError("boom")),
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["get-filters", "--device", "192.168.1.99"])

    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# dry-run-import
# ---------------------------------------------------------------------------


_VALID_REW = """Equaliser: Parametric EQ
Filter  1: ON  PK Fc 100.0 Hz  Gain 3.0 dB  Q 2.0
Filter  2: ON  PK Fc 1000.0 Hz  Gain -4.0 dB  Q 1.5
"""

# Gain 18 dB exceeds WiiM's +12 dB limit -> should surface a clamping warning.
_OUT_OF_RANGE_REW = """Equaliser: Parametric EQ
Filter  1: ON  PK Fc 100.0 Hz  Gain 18.0 dB  Q 2.0
"""

_INVALID_HEADER_REW = """Not A REW File
Filter  1: ON  PK Fc 100.0 Hz  Gain 3.0 dB  Q 2.0
"""


def test_dry_run_import_valid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rew_file = tmp_path / "filters.txt"
    rew_file.write_text(_VALID_REW, encoding="utf-8")

    code = cli.cmd_dry_run_import(str(rew_file))

    out = capsys.readouterr().out
    assert code == 0
    assert "Band" in out
    assert "PEAK" in out
    assert "100.00" in out


def test_dry_run_import_surfaces_range_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rew_file = tmp_path / "hot.txt"
    rew_file.write_text(_OUT_OF_RANGE_REW, encoding="utf-8")

    code = cli.cmd_dry_run_import(str(rew_file))

    out = capsys.readouterr().out
    assert code == 0
    assert "WiiM range warnings:" in out
    assert "clamped to +12.0 dB" in out


def test_dry_run_import_invalid_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rew_file = tmp_path / "bad.txt"
    rew_file.write_text(_INVALID_HEADER_REW, encoding="utf-8")

    code = cli.cmd_dry_run_import(str(rew_file))

    captured = capsys.readouterr()
    assert code == 1
    assert "Error" in captured.err


def test_dry_run_import_missing_file(capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.cmd_dry_run_import("/nonexistent/path/to/file.txt")

    captured = capsys.readouterr()
    assert code == 1
    assert "Error" in captured.err


def test_dry_run_import_via_main_exits_zero(tmp_path: Path) -> None:
    rew_file = tmp_path / "filters.txt"
    rew_file.write_text(_VALID_REW, encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["dry-run-import", "--file", str(rew_file)])

    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# argument parsing
# ---------------------------------------------------------------------------


def test_missing_command_errors() -> None:
    with pytest.raises(SystemExit):
        cli.main([])


def test_global_timeout_option(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_timeout: dict[str, float] = {}

    def fake_list(timeout: float) -> int:
        captured_timeout["timeout"] = timeout
        return 0

    monkeypatch.setattr(cli, "cmd_list_devices", fake_list)

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["--timeout", "2.5", "list-devices"])

    assert exc_info.value.code == 0
    assert captured_timeout["timeout"] == 2.5


# ---------------------------------------------------------------------------
# set-filters
# ---------------------------------------------------------------------------


_VALID_REW_FOR_SET = """Equaliser: Parametric EQ
Filter  1: ON  PK Fc 100.0 Hz  Gain 3.0 dB  Q 2.0
Filter  2: ON  PK Fc 1000.0 Hz  Gain -4.0 dB  Q 1.5
"""


def _patch_set_filters_stack(
    monkeypatch: pytest.MonkeyPatch,
    *,
    caps: DeviceCapabilities | None = None,
    execute_result: WriteResult | None = None,
    execute_side_effect: Exception | None = None,
) -> None:
    """Patch the full write stack for set-filters tests."""
    if caps is None:
        caps = _make_caps()

    client_instance = MagicMock()
    client_instance.close = AsyncMock()
    monkeypatch.setattr(cli, "WiiMHttpClient", MagicMock(return_value=client_instance))

    prober_instance = MagicMock()
    prober_instance.probe = AsyncMock(return_value=caps)
    monkeypatch.setattr(cli, "CapabilityProber", MagicMock(return_value=prober_instance))

    adapter_instance = MagicMock()
    monkeypatch.setattr(cli, "WiiMAdapter", MagicMock(return_value=adapter_instance))

    monkeypatch.setattr(cli, "BackupManager", MagicMock())
    monkeypatch.setattr(cli, "get_app_data_dir", MagicMock(return_value=Path("/tmp/test")))

    safe_write_instance = MagicMock()
    if execute_side_effect:
        safe_write_instance.execute = AsyncMock(side_effect=execute_side_effect)
    else:
        safe_write_instance.execute = AsyncMock(return_value=execute_result)
    monkeypatch.setattr(cli, "SafeWrite", MagicMock(return_value=safe_write_instance))

    # Patch WiiMCommandQueue to avoid real queue operations
    queue_instance = MagicMock()
    queue_instance.start = AsyncMock()
    queue_instance.drain_and_stop = AsyncMock()
    monkeypatch.setattr(cli, "WiiMCommandQueue", MagicMock(return_value=queue_instance))


def test_set_filters_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rew_file = tmp_path / "filters.txt"
    rew_file.write_text(_VALID_REW_FOR_SET, encoding="utf-8")

    _patch_set_filters_stack(
        monkeypatch,
        execute_result=WriteResult(success=True, backup_path=tmp_path / "backup.json"),
    )

    code = cli.cmd_set_filters(
        device="192.168.1.50",
        source=None,
        file=str(rew_file),
        channel="stereo",
        timeout=5.0,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "Verified successfully." in out
    assert "Done!" in out


def test_set_filters_rollback_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rew_file = tmp_path / "filters.txt"
    rew_file.write_text(_VALID_REW_FOR_SET, encoding="utf-8")

    _patch_set_filters_stack(
        monkeypatch,
        execute_result=WriteResult(
            success=False,
            rollback_success=True,
            backup_path=tmp_path / "backup.json",
            error_message="Write verification failed.",
        ),
    )

    code = cli.cmd_set_filters(
        device="192.168.1.50",
        source=None,
        file=str(rew_file),
        channel="stereo",
        timeout=5.0,
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "Verification FAILED. Rolled back to previous state." in captured.out
    assert "ROLLBACK" in captured.out


def test_set_filters_critical_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rew_file = tmp_path / "filters.txt"
    rew_file.write_text(_VALID_REW_FOR_SET, encoding="utf-8")

    backup_path = tmp_path / "backup.json"
    _patch_set_filters_stack(
        monkeypatch,
        execute_result=WriteResult(
            success=False,
            rollback_success=False,
            backup_path=backup_path,
            error_message="Both failed.",
        ),
    )

    code = cli.cmd_set_filters(
        device="192.168.1.50",
        source=None,
        file=str(rew_file),
        channel="stereo",
        timeout=5.0,
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "CRITICAL" in captured.err
    assert str(backup_path) in captured.err


def test_set_filters_connection_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rew_file = tmp_path / "filters.txt"
    rew_file.write_text(_VALID_REW_FOR_SET, encoding="utf-8")

    _patch_set_filters_stack(
        monkeypatch,
        execute_side_effect=WiiMConnectionError("device unreachable"),
    )

    code = cli.cmd_set_filters(
        device="192.168.1.99",
        source=None,
        file=str(rew_file),
        channel="stereo",
        timeout=5.0,
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "device unreachable" in captured.err


def test_set_filters_invalid_rew_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rew_file = tmp_path / "bad.txt"
    rew_file.write_text("Not a REW file\nGarbage data\n", encoding="utf-8")

    code = cli.cmd_set_filters(
        device="192.168.1.50",
        source=None,
        file=str(rew_file),
        channel="stereo",
        timeout=5.0,
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "Error" in captured.err


def test_set_filters_via_main_exits_zero_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rew_file = tmp_path / "filters.txt"
    rew_file.write_text(_VALID_REW_FOR_SET, encoding="utf-8")

    _patch_set_filters_stack(
        monkeypatch,
        execute_result=WriteResult(success=True, backup_path=tmp_path / "backup.json"),
    )

    with pytest.raises(SystemExit) as exc_info:
        cli.main(["set-filters", "--file", str(rew_file), "--device", "192.168.1.50"])

    assert exc_info.value.code == 0


# ---------------------------------------------------------------------------
# get-filters L/R auto-detection (hardware validation findings)
# ---------------------------------------------------------------------------


def test_get_filters_lr_mode_shows_both_channels(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """When device returns L/R mode and user doesn't specify --channel, both channels print."""
    lr_settings = _make_settings("lr")

    # Patch _read_filters to return L/R mode settings directly
    monkeypatch.setattr(
        cli,
        "_read_filters",
        AsyncMock(return_value=lr_settings),
    )

    code = cli.cmd_get_filters(
        device="192.168.1.50", source="wifi", channel="stereo", timeout=5.0
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "Left channel:" in out
    assert "Right channel:" in out


# ---------------------------------------------------------------------------
# list-sources (hardware validation findings)
# ---------------------------------------------------------------------------


def test_list_sources_shows_available_sources(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Mock the probe to return valid sources, verify table output."""
    mock_sources = [
        ("wifi", "Stereo", True),
        ("bluetooth", "L/R", False),
        ("optical", "Stereo", True),
    ]

    monkeypatch.setattr(
        cli,
        "_probe_sources",
        AsyncMock(return_value=mock_sources),
    )

    code = cli.cmd_list_sources(device="192.168.1.50", timeout=5.0)

    out = capsys.readouterr().out
    assert code == 0
    assert "Source" in out
    assert "Channel Mode" in out
    assert "Has Custom EQ" in out
    assert "wifi" in out
    assert "bluetooth" in out
    assert "optical" in out
    assert "Stereo" in out
    assert "L/R" in out


# ---------------------------------------------------------------------------
# list-peq-profiles
# ---------------------------------------------------------------------------


def test_list_peq_profiles_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """list-peq-profiles shows table output with profile names and channel modes."""
    mock_profiles = [
        {"Name": "My Profile", "channelMode": "Stereo", "Type": "Custom"},
        {"Name": "Bass Boost", "channelMode": "L/R", "Type": "Custom"},
    ]

    monkeypatch.setattr(
        cli,
        "_list_peq_profiles",
        AsyncMock(return_value=mock_profiles),
    )

    code = cli.cmd_list_peq_profiles(device="192.168.1.50", timeout=5.0)

    out = capsys.readouterr().out
    assert code == 0
    assert "Name" in out
    assert "Channel Mode" in out
    assert "My Profile" in out
    assert "Bass Boost" in out
    assert "Stereo" in out
    assert "L/R" in out


def test_list_peq_profiles_empty(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """list-peq-profiles prints message when no profiles found."""
    monkeypatch.setattr(
        cli,
        "_list_peq_profiles",
        AsyncMock(return_value=[]),
    )

    code = cli.cmd_list_peq_profiles(device="192.168.1.50", timeout=5.0)

    out = capsys.readouterr().out
    assert code == 0
    assert "No PEQ profiles found" in out


def test_list_peq_profiles_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """list-peq-profiles returns 1 on connection error."""
    from src.models.errors import WiiMResponseError

    monkeypatch.setattr(
        cli,
        "_list_peq_profiles",
        AsyncMock(side_effect=WiiMResponseError("not supported")),
    )

    code = cli.cmd_list_peq_profiles(device="192.168.1.50", timeout=5.0)

    captured = capsys.readouterr()
    assert code == 1
    assert "not supported" in captured.err


# ---------------------------------------------------------------------------
# set-filters --save-as
# ---------------------------------------------------------------------------


def test_set_filters_with_save_as(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """set-filters --save-as calls save_peq_profile after successful write."""
    rew_file = tmp_path / "filters.txt"
    rew_file.write_text(_VALID_REW_FOR_SET, encoding="utf-8")

    # Track save_peq_profile calls
    save_calls: list[tuple[str, str]] = []

    client_instance = MagicMock()
    client_instance.close = AsyncMock()
    monkeypatch.setattr(cli, "WiiMHttpClient", MagicMock(return_value=client_instance))

    caps = _make_caps()
    prober_instance = MagicMock()
    prober_instance.probe = AsyncMock(return_value=caps)
    monkeypatch.setattr(cli, "CapabilityProber", MagicMock(return_value=prober_instance))

    adapter_instance = MagicMock()
    adapter_instance.save_peq_profile = AsyncMock(
        side_effect=lambda src, name: save_calls.append((src, name))
    )
    monkeypatch.setattr(cli, "WiiMAdapter", MagicMock(return_value=adapter_instance))

    monkeypatch.setattr(cli, "BackupManager", MagicMock())
    monkeypatch.setattr(cli, "get_app_data_dir", MagicMock(return_value=tmp_path))

    safe_write_instance = MagicMock()
    safe_write_instance.execute = AsyncMock(
        return_value=WriteResult(success=True, backup_path=tmp_path / "backup.json")
    )
    monkeypatch.setattr(cli, "SafeWrite", MagicMock(return_value=safe_write_instance))

    queue_instance = MagicMock()
    queue_instance.start = AsyncMock()
    queue_instance.drain_and_stop = AsyncMock()
    monkeypatch.setattr(cli, "WiiMCommandQueue", MagicMock(return_value=queue_instance))

    code = cli.cmd_set_filters(
        device="192.168.1.50",
        source="wifi",
        file=str(rew_file),
        channel="stereo",
        timeout=5.0,
        save_as="REW Correction",
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "Saved as device preset: REW Correction" in out
    assert len(save_calls) == 1
    assert save_calls[0] == ("wifi", "REW Correction")


def test_set_filters_save_as_not_called_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """set-filters --save-as does NOT call save_peq_profile when write fails."""
    rew_file = tmp_path / "filters.txt"
    rew_file.write_text(_VALID_REW_FOR_SET, encoding="utf-8")

    client_instance = MagicMock()
    client_instance.close = AsyncMock()
    monkeypatch.setattr(cli, "WiiMHttpClient", MagicMock(return_value=client_instance))

    caps = _make_caps()
    prober_instance = MagicMock()
    prober_instance.probe = AsyncMock(return_value=caps)
    monkeypatch.setattr(cli, "CapabilityProber", MagicMock(return_value=prober_instance))

    adapter_instance = MagicMock()
    adapter_instance.save_peq_profile = AsyncMock()
    monkeypatch.setattr(cli, "WiiMAdapter", MagicMock(return_value=adapter_instance))

    monkeypatch.setattr(cli, "BackupManager", MagicMock())
    monkeypatch.setattr(cli, "get_app_data_dir", MagicMock(return_value=tmp_path))

    safe_write_instance = MagicMock()
    safe_write_instance.execute = AsyncMock(
        return_value=WriteResult(
            success=False,
            rollback_success=True,
            backup_path=tmp_path / "backup.json",
            error_message="Verification failed.",
        )
    )
    monkeypatch.setattr(cli, "SafeWrite", MagicMock(return_value=safe_write_instance))

    queue_instance = MagicMock()
    queue_instance.start = AsyncMock()
    queue_instance.drain_and_stop = AsyncMock()
    monkeypatch.setattr(cli, "WiiMCommandQueue", MagicMock(return_value=queue_instance))

    code = cli.cmd_set_filters(
        device="192.168.1.50",
        source="wifi",
        file=str(rew_file),
        channel="stereo",
        timeout=5.0,
        save_as="REW Correction",
    )

    assert code == 1
    # save_peq_profile should NOT have been called
    adapter_instance.save_peq_profile.assert_not_called()


# ---------------------------------------------------------------------------
# get-roomfit-filters (hardware testing regression)
# ---------------------------------------------------------------------------


def test_get_roomfit_filters_stereo(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """get-roomfit-filters with stereo PEQ displays a band table."""
    stereo_settings = _make_settings("stereo")

    monkeypatch.setattr(
        cli,
        "_get_roomfit_filters",
        AsyncMock(return_value=stereo_settings),
    )

    code = cli.cmd_get_roomfit_filters(
        device="192.168.1.50", source="wifi", profile_name="My RoomFit", timeout=5.0
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "Band" in out
    assert "Frequency (Hz)" in out
    assert "PEAK" in out


def test_get_roomfit_filters_lr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """get-roomfit-filters with L/R PEQ displays both channel headers."""
    lr_settings = _make_settings("lr")

    monkeypatch.setattr(
        cli,
        "_get_roomfit_filters",
        AsyncMock(return_value=lr_settings),
    )

    code = cli.cmd_get_roomfit_filters(
        device="192.168.1.50", source="wifi", profile_name="My RoomFit", timeout=5.0
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "Left channel:" in out
    assert "Right channel:" in out


async def test_get_roomfit_filters_uses_preview_not_raw_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#178: get-roomfit-filters must go through read_roomfit_preset_preview(),
    not read_roomfit() directly -- a raw read requires EQv2SourceLoad-ing the
    named profile first, which makes it the device's active/selected profile
    as a side effect. Running this read-only CLI command must not silently
    change what's active on the user's device."""
    client_instance = MagicMock()
    client_instance.close = AsyncMock()
    monkeypatch.setattr(cli, "WiiMHttpClient", MagicMock(return_value=client_instance))

    prober_instance = MagicMock()
    prober_instance.probe = AsyncMock(return_value=DeviceCapabilities(roomfit_level=4))
    monkeypatch.setattr(cli, "CapabilityProber", MagicMock(return_value=prober_instance))

    adapter_instance = MagicMock()
    adapter_instance.read_roomfit_preset_preview = AsyncMock(
        return_value=_make_settings("stereo")
    )
    adapter_instance.read_roomfit = AsyncMock(
        side_effect=AssertionError("read_roomfit() must not be called directly")
    )
    monkeypatch.setattr(cli, "WiiMAdapter", MagicMock(return_value=adapter_instance))

    await cli._get_roomfit_filters(
        device="192.168.1.50", source="wifi", profile_name="My RoomFit", timeout=5.0
    )

    adapter_instance.read_roomfit_preset_preview.assert_called_once_with(
        "wifi", "My RoomFit"
    )
    adapter_instance.read_roomfit.assert_not_called()


def test_set_roomfit_filters_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """set-roomfit-filters exits 0 and prints 'saved successfully' on success."""
    rew_file = tmp_path / "filters.txt"
    rew_file.write_text(
        "Equaliser: Parametric EQ\nFilter  1: ON  PK Fc 100.0 Hz  Gain 3.0 dB  Q 2.0\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "_set_roomfit_filters",
        AsyncMock(return_value=WriteResult(success=True)),
    )

    code = cli.cmd_set_roomfit_filters(
        device="192.168.1.50",
        source="wifi",
        profile_name="REW Export",
        file=str(rew_file),
        timeout=5.0,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert "saved successfully" in out


def test_set_roomfit_filters_verification_failure_exits_nonzero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """set-roomfit-filters must exit 1 -- not print "saved successfully" --
    when RoomFitSafeWrite reports a verification failure (smoke #153:
    set-roomfit-filters used to call write_roomfit() directly with no
    verification at all, so a failed write was indistinguishable from a
    successful one)."""
    rew_file = tmp_path / "filters.txt"
    rew_file.write_text(
        "Equaliser: Parametric EQ\nFilter  1: ON  PK Fc 100.0 Hz  Gain 3.0 dB  Q 2.0\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "_set_roomfit_filters",
        AsyncMock(
            return_value=WriteResult(
                success=False,
                rollback_success=True,
                error_message="RoomFit profile verification failed; original profile restored.",
            )
        ),
    )

    code = cli.cmd_set_roomfit_filters(
        device="192.168.1.50",
        source="wifi",
        profile_name="REW Export",
        file=str(rew_file),
        timeout=5.0,
    )

    out = capsys.readouterr()
    assert code == 1
    assert "saved successfully" not in out.out
    assert "was not saved" in out.err


def test_set_roomfit_filters_level_too_low(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """set-roomfit-filters shows specific error when device lacks roomfit_level
    >= 2 (relaxed from >= 4, #191 -- a device at level 3 now gets a real write
    attempt instead of being rejected outright; only < 2 is rejected)."""
    from src.models.errors import WiiMResponseError

    rew_file = tmp_path / "filters.txt"
    rew_file.write_text(
        "Equaliser: Parametric EQ\nFilter  1: ON  PK Fc 100.0 Hz  Gain 3.0 dB  Q 2.0\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        cli,
        "_set_roomfit_filters",
        AsyncMock(
            side_effect=WiiMResponseError(
                "RoomFit write requires roomfit_level >= 2, device has level 0"
            )
        ),
    )

    code = cli.cmd_set_roomfit_filters(
        device="192.168.1.50",
        source="wifi",
        profile_name="REW Export",
        file=str(rew_file),
        timeout=5.0,
    )

    captured = capsys.readouterr()
    assert code == 1
    assert "not available" in captured.err


# ---------------------------------------------------------------------------
# set-filters --file-right (hardware testing regression)
# ---------------------------------------------------------------------------


_VALID_REW_LEFT = """Equaliser: Parametric EQ
Filter  1: ON  PK Fc 100.0 Hz  Gain 3.0 dB  Q 2.0
Filter  2: ON  PK Fc 500.0 Hz  Gain -2.0 dB  Q 1.5
"""

_VALID_REW_RIGHT = """Equaliser: Parametric EQ
Filter  1: ON  PK Fc 200.0 Hz  Gain 1.5 dB  Q 1.0
Filter  2: ON  PK Fc 1000.0 Hz  Gain -3.0 dB  Q 2.5
"""


def test_set_filters_file_right_parses_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--file-right provides L/R mode with both files parsed."""
    left_file = tmp_path / "left.txt"
    left_file.write_text(_VALID_REW_LEFT, encoding="utf-8")
    right_file = tmp_path / "right.txt"
    right_file.write_text(_VALID_REW_RIGHT, encoding="utf-8")

    # Track the settings passed to _set_filters
    captured_settings: list[PEQSettings] = []

    async def mock_set_filters(
        device: str,
        source: str | None,
        file: str,
        channel: str,
        timeout: float,
        save_as: str | None = None,
        file_right: str | None = None,
    ) -> WriteResult:
        # Parse the files to check our assertion
        from src.translator import TranslationEngine

        filters_l = TranslationEngine.parse_rew_file(Path(file))
        settings: PEQSettings
        if file_right is not None:
            filters_r = TranslationEngine.parse_rew_file(Path(file_right))
            settings = PEQSettings(
                source_name=source or "wifi",
                channel_mode="lr",
                bands_l=filters_l,
                bands_r=filters_r,
            )
        else:
            settings = PEQSettings(
                source_name=source or "wifi",
                channel_mode="stereo",
                bands=filters_l,
            )
        captured_settings.append(settings)
        return WriteResult(success=True, backup_path=tmp_path / "backup.json")

    monkeypatch.setattr(cli, "_set_filters", mock_set_filters)

    code = cli.cmd_set_filters(
        device="192.168.1.50",
        source="wifi",
        file=str(left_file),
        channel="stereo",
        timeout=5.0,
        file_right=str(right_file),
    )

    assert code == 0
    assert len(captured_settings) == 1
    settings = captured_settings[0]
    assert settings.channel_mode == ChannelMode.LR
    assert len(settings.bands_l) == 2
    assert len(settings.bands_r) == 2
    # Left channel first filter at 100 Hz
    assert settings.bands_l[0].frequency_hz == 100.0
    # Right channel first filter at 200 Hz
    assert settings.bands_r[0].frequency_hz == 200.0


# ---------------------------------------------------------------------------
# load-preset
# ---------------------------------------------------------------------------


def _patch_load_preset_stack(
    monkeypatch: pytest.MonkeyPatch,
    *,
    caps: DeviceCapabilities | None = None,
    load_side_effects: dict[str, Exception | None] | None = None,
) -> MagicMock:
    """Patch the stack for load-preset tests. Returns the adapter mock."""
    if caps is None:
        caps = _make_caps()

    client_instance = MagicMock()
    client_instance.close = AsyncMock()
    monkeypatch.setattr(cli, "WiiMHttpClient", MagicMock(return_value=client_instance))

    prober_instance = MagicMock()
    prober_instance.probe = AsyncMock(return_value=caps)
    monkeypatch.setattr(cli, "CapabilityProber", MagicMock(return_value=prober_instance))

    adapter_instance = MagicMock()

    if load_side_effects is not None:
        async def load_peq_profile(source: str, preset: str) -> None:
            effect = load_side_effects.get(source)
            if effect is not None:
                raise effect
        adapter_instance.load_peq_profile = AsyncMock(side_effect=load_peq_profile)
    else:
        adapter_instance.load_peq_profile = AsyncMock(return_value=None)

    monkeypatch.setattr(cli, "WiiMAdapter", MagicMock(return_value=adapter_instance))
    return adapter_instance


class TestLoadPreset:
    """Tests for the load-preset CLI command."""

    def test_load_preset_all_sources_succeed(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """load-preset returns 0 and prints checkmarks when all sources succeed."""
        adapter = _patch_load_preset_stack(monkeypatch)

        code = cli.cmd_load_preset(
            device="192.168.1.50",
            preset="Living Room EQ",
            sources=["wifi", "optical", "HDMI"],
            timeout=5.0,
        )

        out = capsys.readouterr().out
        assert code == 0
        assert "Living Room EQ" in out
        assert "wifi \u2713" in out
        assert "optical \u2713" in out
        assert "HDMI \u2713" in out
        # Verify each source had load_peq_profile called
        assert adapter.load_peq_profile.call_count == 3

    def test_load_preset_partial_failure(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """load-preset returns 1 when some sources fail, but all are attempted."""
        from src.models.errors import WiiMResponseError

        _patch_load_preset_stack(
            monkeypatch,
            load_side_effects={
                "wifi": None,
                "optical": WiiMResponseError("source not found"),
                "HDMI": None,
            },
        )

        code = cli.cmd_load_preset(
            device="192.168.1.50",
            preset="Bass Boost",
            sources=["wifi", "optical", "HDMI"],
            timeout=5.0,
        )

        out = capsys.readouterr().out
        assert code == 1
        assert "wifi \u2713" in out
        assert "optical \u2717" in out
        assert "HDMI \u2713" in out

    def test_load_preset_all_fail(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """load-preset returns 1 when all sources fail."""
        _patch_load_preset_stack(
            monkeypatch,
            load_side_effects={
                "wifi": WiiMConnectionError("timeout"),
                "optical": WiiMConnectionError("timeout"),
            },
        )

        code = cli.cmd_load_preset(
            device="192.168.1.50",
            preset="Test",
            sources=["wifi", "optical"],
            timeout=5.0,
        )

        out = capsys.readouterr().out
        assert code == 1
        assert "wifi \u2717" in out
        assert "optical \u2717" in out

    def test_load_preset_each_source_gets_load_peq_profile_called(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Each specified source receives a load_peq_profile call with correct args."""
        adapter = _patch_load_preset_stack(monkeypatch)

        cli.cmd_load_preset(
            device="192.168.1.50",
            preset="My Preset",
            sources=["wifi", "bluetooth", "line-in"],
            timeout=5.0,
        )

        calls = adapter.load_peq_profile.call_args_list
        assert len(calls) == 3
        assert calls[0].args == ("wifi", "My Preset")
        assert calls[1].args == ("bluetooth", "My Preset")
        assert calls[2].args == ("line-in", "My Preset")

    def test_load_preset_single_source(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """load-preset works with a single source."""
        adapter = _patch_load_preset_stack(monkeypatch)

        code = cli.cmd_load_preset(
            device="192.168.1.50",
            preset="Night Mode",
            sources=["wifi"],
            timeout=5.0,
        )

        out = capsys.readouterr().out
        assert code == 0
        assert "Night Mode" in out
        assert "wifi \u2713" in out
        adapter.load_peq_profile.assert_called_once_with("wifi", "Night Mode")

    def test_load_preset_via_main_parses_comma_separated_sources(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """load-preset --source wifi,optical,HDMI is parsed into a list."""
        _patch_load_preset_stack(monkeypatch)

        with pytest.raises(SystemExit) as exc_info:
            cli.main([
                "load-preset",
                "--device", "192.168.1.50",
                "--preset", "My EQ",
                "--source", "wifi,optical,HDMI",
            ])

        assert exc_info.value.code == 0
