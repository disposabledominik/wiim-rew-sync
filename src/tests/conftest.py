"""
Shared pytest fixtures and Hypothesis strategies for the WiiM ↔ REW PEQ Sync Tool test suite.

Strategies defined here (used across multiple PBT tasks):
  - st_canonical_filter()           — a single valid CanonicalFilter
  - st_canonical_filter_list()      — a list of valid CanonicalFilters
  - st_float_near_boundary()        — floats near a tolerance boundary
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from hypothesis import strategies as st

from src.models.canonical import CanonicalFilter


def iter_src_python_files() -> list[Path]:
    """Return every .py file under src/, sorted -- shared by grep-based
    architecture-rule guard tests (e.g. test_safe_write.py's
    TestNoDirectWriteBypass, test_gui_adapter_injection.py) so each new rule
    adds its own pattern/allowlist without re-implementing the source-tree
    walk."""
    repo_root = Path(__file__).resolve().parents[2]
    return sorted((repo_root / "src").rglob("*.py"))


def close_coroutine_tree(value: object, seen: set[int] | None = None) -> None:
    """Close a coroutine and any nested coroutine locals it captures.

    GUI handler tests mock ``AsyncBridge.run_async`` so the coroutine passed
    to it never actually runs. An un-awaited, un-closed coroutine triggers a
    "coroutine was never awaited" RuntimeWarning whenever the garbage
    collector eventually reclaims it (often during an unrelated later test).
    Use this as the mock's ``side_effect`` to dispose of the coroutine (and
    any inner coroutine it captured as a local, e.g. ``_bridge_wrapper``
    wrapping ``self._do_push()``) the moment the mock is called.
    """
    if not inspect.iscoroutine(value):
        return

    if seen is None:
        seen = set()

    obj_id = id(value)
    if obj_id in seen:
        return
    seen.add(obj_id)

    frame = value.cr_frame
    if frame is not None:
        for local_value in frame.f_locals.values():
            close_coroutine_tree(local_value, seen)

    value.close()


@pytest.fixture(autouse=True)
def _suppress_unsaved_changes_dialog(monkeypatch):
    """Prevent UnsavedChangesDialog from blocking during test teardown.

    Patches MainWindow._has_unsaved_changes to always return False so that
    closeEvent never opens the modal dialog. This avoids test hangs on WSL2.
    """
    from src.gui.main_window import MainWindow

    monkeypatch.setattr(MainWindow, "_has_unsaved_changes", lambda self: False)


@pytest.fixture(autouse=True)
def _suppress_blocking_message_boxes(monkeypatch):
    """Auto-answer QMessageBox popups instead of letting them block.

    Any code path that reaches QMessageBox.question/warning/critical/
    information without the *individual test* mocking it away would
    otherwise show a real modal dialog and hang the run until a human
    clicks it -- same class of bug as _suppress_unsaved_changes_dialog
    above (see e.g. #166's "Preset Will Briefly Activate on Device"
    confirmation, which slipped through per-test mocking once). Fix it once
    here at the harness level instead of relying on every test that reaches
    a *new* confirmation dialog to remember to mock QMessageBox itself.

    `question` defaults to Yes (matches the common "confirm and proceed"
    case most existing per-test mocks already use); the acknowledgment-only
    dialogs default to Ok. A test that cares about a specific answer (the
    No/decline branch, or asserting the dialog was/wasn't shown) should
    still patch `PySide6.QtWidgets.QMessageBox.<method>` locally --
    unittest.mock layers correctly over this fixture's default within that
    test's own `with`/decorator scope.

    This does NOT cover custom QDialog subclasses (QuickSetupDialog,
    DevicePickerDialog, etc.) -- those must still be mocked individually at
    their own static factory method (e.g. `QuickSetupDialog.get_setup`),
    since there's no single shared base to intercept generically the way
    QMessageBox's static methods allow.
    """
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        QMessageBox, "question", lambda *a, **kw: QMessageBox.StandardButton.Yes
    )
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *a, **kw: QMessageBox.StandardButton.Ok
    )
    monkeypatch.setattr(
        QMessageBox, "critical", lambda *a, **kw: QMessageBox.StandardButton.Ok
    )
    monkeypatch.setattr(
        QMessageBox, "information", lambda *a, **kw: QMessageBox.StandardButton.Ok
    )


@pytest.fixture(autouse=True)
def _isolate_device_capability_file(monkeypatch):
    """Keep CapabilityProber.probe() hermetic against real app-data-dir state.

    `device_capability_file.ensure_user_capability_file()` seeds a user copy
    in the OS app data directory and never overwrites it once it exists. Left
    unmocked, tests would read whatever copy a *previous* run (on this
    machine) happened to seed, rather than the bundled file as currently
    committed in the repo -- silently coupling test results to local machine
    state. Point "ensure" at the bundled file directly (a no-op read, no
    real seeding) and reset the process-wide cache before each test.
    """
    from src.models import device_capability_file as dcf

    monkeypatch.setattr(
        dcf, "ensure_user_capability_file", dcf.bundled_capability_file_path
    )
    monkeypatch.setattr(dcf, "_cached_capability_file", None)


def st_float_near_boundary(center: float, tolerance: float) -> st.SearchStrategy[float]:
    """Generate floats near a boundary: within tolerance OR just outside."""
    return st.one_of(
        # Within tolerance (should match)
        st.floats(
            min_value=center - tolerance,
            max_value=center + tolerance,
            allow_nan=False,
            allow_infinity=False,
        ),
        # Just outside tolerance (should not match)
        st.floats(
            min_value=center + tolerance * 1.001,
            max_value=center + tolerance * 2,
            allow_nan=False,
            allow_infinity=False,
        ),
        st.floats(
            min_value=center - tolerance * 2,
            max_value=center - tolerance * 1.001,
            allow_nan=False,
            allow_infinity=False,
        ),
    )


@st.composite
def st_canonical_filter(draw: st.DrawFn) -> CanonicalFilter:
    """Generate a single valid CanonicalFilter."""
    filter_type = draw(st.sampled_from(["PEAK", "LS", "HS", "LP", "HP", "OFF"]))
    freq = draw(st.floats(min_value=10.0, max_value=22000.0, allow_nan=False, allow_infinity=False))
    gain = draw(st.floats(min_value=-20.0, max_value=20.0, allow_nan=False, allow_infinity=False))
    q = draw(st.floats(min_value=0.01, max_value=24.0, allow_nan=False, allow_infinity=False))
    return CanonicalFilter(type=filter_type, frequency_hz=freq, gain_db=gain, q=q)


@st.composite
def st_canonical_filter_list(
    draw: st.DrawFn, min_size: int = 1, max_size: int = 10
) -> list[CanonicalFilter]:
    """Generate a list of valid CanonicalFilters."""
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    return [draw(st_canonical_filter()) for _ in range(n)]
