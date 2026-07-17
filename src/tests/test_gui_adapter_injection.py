"""Guard test: no adapter is instantiated directly under src/gui/.

CLAUDE.md: "Adapters are injected via constructor... never instantiate an
adapter inside business logic." src/gui/adapter_factories.py is the one
place allowed to call WiiMAdapter()/WiiMHttpClient()/CapabilityProber()/
REWHttpApiClient() directly; MainWindow takes these as constructor-injected
factory callables defaulting to that module's functions (see D1 in
docs/backlog.md / MainWindow.__init__).

Mirrors test_safe_write.py::TestNoDirectWriteBypass's grep-based pattern
(reusing its iter_src_python_files() helper from conftest.py) for the same
reason: a cheap CI check beats waiting for a manual audit to notice a
regression -- 4 such direct-instantiation call sites were found and fixed
in main_window.py by exactly that kind of manual audit before this test
existed.
"""

from __future__ import annotations

import re
from pathlib import Path

from src.tests.conftest import iter_src_python_files

_DIRECT_ADAPTER_INSTANTIATION_PATTERN = re.compile(
    r"\bWiiMAdapter\(|\bWiiMHttpClient\(|\bCapabilityProber\(|\bREWHttpApiClient\("
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
