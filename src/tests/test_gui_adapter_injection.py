"""Guard test: no adapter is instantiated directly under src/gui/.

CLAUDE.md: "Adapters are injected via constructor... never instantiate an
adapter inside business logic." src/gui/adapter_factories.py is the one
place allowed to call WiiMAdapter()/WiiMHttpClient()/CapabilityProber()/
REWHttpApiClient()/SafeWrite()/RoomFitSafeWrite() directly; MainWindow takes
these as constructor-injected factory callables (or, for the latter two,
lambdas delegating to that module's factory functions) defaulting to that
module's functions (see D1 in docs/backlog.md / MainWindow.__init__).

Mirrors test_safe_write.py::TestNoDirectWriteBypass's grep-based pattern
(reusing its iter_src_python_files() helper from conftest.py) for the same
reason: a cheap CI check beats waiting for a manual audit to notice a
regression -- 4 such direct-instantiation call sites were found and fixed
in main_window.py by exactly that kind of manual audit before this test
existed. SafeWrite/RoomFitSafeWrite were added to this pattern after a
follow-up review found main_window.py constructing them directly, outside
this guard's original scope.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.gui.app_settings import AppSettings
from src.gui.main_window import MainWindow
from src.tests.conftest import close_coroutine_tree, iter_src_python_files

_DIRECT_ADAPTER_INSTANTIATION_PATTERN = re.compile(
    r"\bWiiMAdapter\(|\bWiiMHttpClient\(|\bCapabilityProber\(|\bREWHttpApiClient\("
    r"|\bSafeWrite\(|\bRoomFitSafeWrite\("
)
_ALLOWED_DIRECT_INSTANTIATION_FILES = {
    Path("src/gui/adapter_factories.py"),
}


class TestNoDirectAdapterInstantiationInGui:
    def test_no_gui_file_outside_adapter_factories_instantiates_an_adapter(self) -> None:
        repo_root = Path(__file__).resolve().parents[2]
        violations: list[str] = []

        for path in iter_src_python_files():
            rel_path = path.relative_to(repo_root)
            if rel_path.parts[:2] != ("src", "gui"):
                continue  # rule only applies to the GUI layer
            if rel_path in _ALLOWED_DIRECT_INSTANTIATION_FILES:
                continue

            text = path.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), start=1):
                if _DIRECT_ADAPTER_INSTANTIATION_PATTERN.search(line):
                    violations.append(f"{rel_path}:{line_no}: {line.strip()}")

        assert not violations, (
            "Found direct adapter instantiation under src/gui/ outside "
            "adapter_factories.py -- adapters must be injected via "
            "constructor-provided factories (see MainWindow.__init__ and "
            "src/gui/adapter_factories.py):\n" + "\n".join(violations)
        )


def _make_caps() -> MagicMock:
    """Minimal mock DeviceCapabilities sufficient to drive
    MainWindow._on_capabilities_ready() without crashing."""
    caps = MagicMock()
    caps.supports_roomfit = False
    caps.supports_roomfit_read = False
    caps.supports_roomfit_write = False
    caps.device_name = "WiiM Pro Plus"
    caps.model = "WiiM Pro Plus"
    caps.source_names = ["wifi", "optical", "hdmi"]
    caps.active_source = "wifi"
    caps.supports_profile_enumeration = False
    caps.capability_file_override = False
    caps.used_generic_capabilities = False
    caps.supports_lr_filters = False
    return caps


class TestMainWindowFactoryInjection:
    """MainWindow.__init__'s 4 constructor-injected adapter factories are
    real, production-used code (main_window.py:270,855-856,1413) -- but
    every existing test substitutes SecondaryWorkflowManager's
    post-configure() attributes directly instead of exercising the
    constructor injection point itself, so nothing ever proved substitution
    actually works end-to-end (round-4 review finding #11, 2026-07-19). This
    closes that gap with a real substitution test."""

    def test_constructor_factories_are_actually_invoked(self, qtbot) -> None:
        """Constructing MainWindow with non-default factories, then driving
        it through device-select -> capabilities-ready, must produce the
        *custom* factories' return values -- not just store the callables
        unused."""
        rew_sentinel = MagicMock()
        wiim_http_sentinel = MagicMock()
        # No .probe() setup needed: _on_capabilities_ready consumes an
        # already-resolved `caps` argument and never calls prober.probe()
        # itself -- probing happens earlier, in _do_probe, which this test
        # doesn't drive. A bare MagicMock() is enough since this sentinel is
        # only ever compared by identity here, never invoked.
        prober_sentinel = MagicMock()
        adapter_sentinel = MagicMock()

        mock_bridge = MagicMock()
        mock_bridge.start = MagicMock()
        mock_bridge.shutdown = MagicMock()
        mock_bridge.capabilities_ready = MagicMock()
        # _on_device_selected dispatches the probe via
        # self._primary_workflows.probe(...) -> self._bridge.run_async(coro)
        # -- a bare MagicMock() there would swallow the coroutine without
        # closing it, producing a "never awaited" RuntimeWarning that
        # surfaces during an unrelated *later* test's garbage collection.
        mock_bridge.run_async = MagicMock(side_effect=close_coroutine_tree)

        app_settings = AppSettings(first_run_complete=True)
        with (
            patch("src.gui.app_settings.AppSettings.load", return_value=app_settings),
            patch("src.gui.app_settings.AppSettings.save"),
        ):
            window = MainWindow(
                async_bridge=mock_bridge,
                rew_client_factory=lambda: rew_sentinel,
                wiim_http_client_factory=lambda ip: wiim_http_sentinel,
                capability_prober_factory=lambda client: prober_sentinel,
                wiim_adapter_factory=lambda client, caps: adapter_sentinel,
            )
            qtbot.addWidget(window)

            assert window._rew_client is rew_sentinel  # invoked unconditionally in __init__
            # PrimaryWorkflowManager.configure() is called in __init__ with
            # rew_client=self._rew_client -- confirm that leg of propagation too.
            assert window._primary_workflows._rew_client is rew_sentinel

            window._on_device_selected("192.168.1.100")
            assert window._wiim_http_client is wiim_http_sentinel
            assert window._capability_prober is prober_sentinel

            window._on_capabilities_ready(_make_caps())
            assert window._wiim_adapter is adapter_sentinel
            # SecondaryWorkflowManager.configure() only sees these 3
            # factories (not rew_client_factory -- PrimaryWorkflowManager
            # never takes them at all) -- assert identity of the *callables
            # themselves*, not a re-invocation, so this proves the same
            # object was threaded through unchanged rather than
            # re-wrapped/copied.
            assert (
                window._secondary_workflows._wiim_http_client_factory
                is window._wiim_http_client_factory
            )
            assert (
                window._secondary_workflows._capability_prober_factory
                is window._capability_prober_factory
            )
            assert (
                window._secondary_workflows._target_adapter_factory
                is window._wiim_adapter_factory
            )
            # And that MainWindow's own attributes are in turn the exact
            # custom callables passed to the constructor (not defaults that
            # happen to look similar).
            assert window._wiim_http_client_factory("1.2.3.4") is wiim_http_sentinel
            assert (
                window._wiim_adapter_factory(wiim_http_sentinel, _make_caps())
                is adapter_sentinel
            )

            window._wizard_controller.state.current_filters = []
            window.close()
