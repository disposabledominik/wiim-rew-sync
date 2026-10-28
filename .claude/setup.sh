#!/usr/bin/env bash
# Install this repo's dev dependencies; a no-op when they are already present.
# Run by the cloud environment setup script (with --system) and, as a
# fallback, by the SessionStart hook. Locally it installs only inside a venv.
set -u
cd "$(dirname "$0")/.." || exit 0
name=wiim-rew-sync log="${TMPDIR:-/tmp}/$name-setup.log"
check() {  # find (don't import) the packages; Qt also needs libEGL from the OS
  python3 -c 'import importlib.util as u, sys; sys.exit(any(u.find_spec(m) is None for m in ("PySide6", "httpx", "pydantic", "zeroconf", "hypothesis", "pytest", "ruff", "mypy")))' 2>/dev/null &&
    { ! command -v ldconfig >/dev/null || ldconfig -p | grep -q 'libEGL\.so\.1'; }
}
check && exit 0
if [ "${1:-}" != --system ] && [ "${CLAUDE_CODE_REMOTE:-}" != true ] && [ -z "${VIRTUAL_ENV:-}" ]; then
  echo "$name: dev dependencies missing. Activate your venv and run .claude/setup.sh."
  exit 0
fi
{
  if [ "$(id -u)" = 0 ] && command -v apt-get >/dev/null; then  # Qt runtime libraries
    pkgs="libegl1 libgl1 libxkbcommon0 libfontconfig1 libdbus-1-3"
    apt-get install -y -qq $pkgs || { apt-get update -qq && apt-get install -y -qq $pkgs; }
  fi
  python3 -m pip install -q -e '.[dev]'
} >>"$log" 2>&1
check && echo "$name: dev dependencies installed." || echo "$name: dependency install failed; see $log."
