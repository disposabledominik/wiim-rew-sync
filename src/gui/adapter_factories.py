"""Default adapter-construction factories for MainWindow.

CLAUDE.md: "Adapters are injected via constructor... never instantiate an
adapter inside business logic." This module is the one place in ``src/gui/``
allowed to call the real adapter constructors directly -- ``MainWindow``
takes these as constructor-injected factory callables (defaulting to the
functions here), so its adapter-construction call sites don't instantiate
concrete classes themselves and stay swappable in tests. Enforced by a
grep-based guard test (``test_gui_adapter_injection.py``), mirroring how
``safe_write.py``/``wiim_adapter.py`` are the sole allowed files for the
direct-write-bypass guard in ``test_safe_write.py``.
"""

from __future__ import annotations

from src.adapters.capability_prober import CapabilityProber
from src.adapters.rew_http_client import REWHttpApiClient
from src.adapters.safe_write import RoomFitSafeWrite, SafeWrite
from src.adapters.wiim_adapter import WiiMAdapter
from src.adapters.wiim_http import WiiMHttpClient
from src.models.capabilities import DeviceCapabilities
from src.repository.backup_manager import BackupManager


def make_rew_client() -> REWHttpApiClient:
    """Construct the REW HTTP API client."""
    return REWHttpApiClient()


def make_wiim_http_client(ip: str) -> WiiMHttpClient:
    """Construct a WiiM HTTP client for the given device IP."""
    return WiiMHttpClient(ip)


def make_capability_prober(client: WiiMHttpClient) -> CapabilityProber:
    """Construct a capability prober for the given WiiM HTTP client."""
    return CapabilityProber(client)


def make_wiim_adapter(client: WiiMHttpClient, caps: DeviceCapabilities) -> WiiMAdapter:
    """Construct a WiiM adapter for the given client and probed capabilities."""
    return WiiMAdapter(client, caps)


def make_safe_write(adapter: WiiMAdapter, backup_manager: BackupManager) -> SafeWrite:
    """Construct the PEQ safe-write protocol wrapper for the given adapter."""
    return SafeWrite(adapter, backup_manager)


def make_roomfit_safe_write(
    adapter: WiiMAdapter, backup_manager: BackupManager
) -> RoomFitSafeWrite:
    """Construct the RoomFit safe-write protocol wrapper for the given adapter."""
    return RoomFitSafeWrite(adapter, backup_manager)
