"""Tests for the CLI proof-of-concept commands (src/cli/main.py)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.adapters.safe_write import WriteResult
from src.cli import main as cli
from src.models.canonical import CanonicalFilter
from src.models.capabilities import DeviceCapabilities, DeviceInfo
from src.models.errors import WiiMConnectionError, WiiMSlaveTargetError
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


def test_set_filters_slave_target_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    rew_file = tmp_path / "filters.txt"
    rew_file.write_text(_VALID_REW_FOR_SET, encoding="utf-8")

    _patch_set_filters_stack(
        monkeypatch,
        execute_side_effect=WiiMSlaveTargetError("Cannot write to slave"),
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
    assert "slave device" in captured.err
