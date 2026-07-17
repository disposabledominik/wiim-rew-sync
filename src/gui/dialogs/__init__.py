"""GUI dialogs sub-package.

Modal dialogs for push confirmation, onboarding, crash reporting,
unsaved changes, and picker dialogs.
"""

from __future__ import annotations

from src.gui.dialogs.crash_dialog import CrashDialog
from src.gui.dialogs.device_picker import DevicePickerDialog
from src.gui.dialogs.export_dialog import ExportDialog
from src.gui.dialogs.onboarding_overlay import OnboardingOverlay
from src.gui.dialogs.unsaved_changes_dialog import UnsavedChangesDialog

__all__ = [
    "CrashDialog",
    "DevicePickerDialog",
    "ExportDialog",
    "OnboardingOverlay",
    "UnsavedChangesDialog",
]
