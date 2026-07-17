"""Shared helper functions for GUI layer operations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.models.peq import PEQSettings
from src.repository.backup_manager import load_backup_json, parse_backup_filters

if TYPE_CHECKING:
    from src.adapters.wiim_adapter import WiiMAdapter

__all__ = [
    "load_backup_json",
    "parse_backup_filters",
]


async def read_preset_preview(
    wiim_adapter: WiiMAdapter, preset_type: str, source_name: str, preset_name: str
) -> PEQSettings:
    """Read+preview a preset from the device, dispatching by preset_type.

    Previewing briefly loads the preset onto the device's live DSP and
    restores it after (see #166). Shared by MainWindow's copy flow
    (_read_preset_to_copy) and PrimaryWorkflowManager's export/save flows,
    which otherwise each independently reimplement this dispatch.
    """
    if preset_type == "RoomFit":
        return await wiim_adapter.read_roomfit_preset_preview(source_name, preset_name)
    return await wiim_adapter.read_peq_preset_preview(source_name, preset_name)


# load_backup_json / parse_backup_filters live in src.repository.backup_manager
# (RoomFitSafeWrite.undo(), in src/adapters/, needs them too, and adapters
# must not import from gui) -- re-exported here so existing GUI call sites
# (main_window.py, secondary_workflows.py) need no import-path changes.
