"""Shared helper functions for GUI layer operations.

Eliminates duplication across main_window.py and secondary_workflows.py
for channel-mode handling and filter splitting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.models.canonical import CanonicalFilter
from src.models.channel_mode import ChannelMode, require_lr_filters
from src.models.peq import PEQSettings
from src.repository.backup_manager import load_backup_json, parse_backup_filters

if TYPE_CHECKING:
    from src.adapters.wiim_adapter import WiiMAdapter

__all__ = [
    "load_backup_json",
    "parse_backup_filters",
]


def extract_filters(peq_settings: PEQSettings) -> tuple[list[CanonicalFilter], ChannelMode]:
    """Extract combined filter list and channel_mode from PEQSettings.

    Returns:
        Tuple of (combined_filters, channel_mode).
    """
    if is_lr_mode(peq_settings.channel_mode):
        filters = (peq_settings.bands_l or []) + (peq_settings.bands_r or [])
        return filters, ChannelMode.LR
    return list(peq_settings.bands), ChannelMode.STEREO


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


def get_lr_filters(
    state: object,
    combined: list[CanonicalFilter],
) -> tuple[list[CanonicalFilter], list[CanonicalFilter]]:
    """Get L/R filter lists from wizard state.

    Prefers explicit state.filters_l/filters_r (set during validation).

    Args:
        state: WizardState object with filters_l/filters_r fields.
        combined: Unused; retained for call-site compatibility.

    Returns:
        Tuple of (left_filters, right_filters).

    Raises:
        ValueError: if state has no filters_l/filters_r set.
    """
    del combined
    left = getattr(state, "filters_l", None)
    right = getattr(state, "filters_r", None)
    return require_lr_filters(left, right)


def is_lr_mode(channel_mode: str | ChannelMode) -> bool:
    """Check if a channel mode represents L/R (dual-channel) mode.

    Accepts both ChannelMode enum values and legacy string variants.
    Handles all variants: "lr", "l/r", "L/R", "left", "right", ChannelMode.LR.
    """
    if isinstance(channel_mode, ChannelMode):
        return channel_mode.is_lr
    return ChannelMode.from_any(channel_mode).is_lr


# load_backup_json / parse_backup_filters live in src.repository.backup_manager
# (RoomFitSafeWrite.undo(), in src/adapters/, needs them too, and adapters
# must not import from gui) -- re-exported here so existing GUI call sites
# (main_window.py, secondary_workflows.py) need no import-path changes.


