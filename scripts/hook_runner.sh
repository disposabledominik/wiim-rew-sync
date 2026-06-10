#!/usr/bin/env bash
# hook_runner.sh — Reliable entry point for Kiro hooks running via WSL.
#
# Usage: hook_runner.sh <command> [args...]
#
# Called from .bat files in scripts/. Handles:
#   1. cd to project root
#   2. PATH setup (adds ~/.local/bin for pip user installs)
#   3. venv activation if available
#   4. Runs the command and ALWAYS exits 0 (Kiro only captures output on exit 0)
#
# NOTE: We force exit 0 because Kiro's hook runner discards stdout when
# the process exits non-zero. Errors are still reported in the output text.

PROJECT_ROOT="/mnt/c/Users/domin/Desktop/Misc/_dev/wiim-rew-sync"
cd "$PROJECT_ROOT" || exit 0

# Ensure user-local bin is on PATH (mypy, ruff, pytest installed via pip --user)
export PATH="$HOME/.local/bin:$PATH"

# Activate venv if it exists
if [ -f ".venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

# Run the command, capture exit code
"$@" 2>&1
CMD_EXIT=$?

if [ $CMD_EXIT -ne 0 ]; then
    echo ""
    echo ">>> FAILED (exit code $CMD_EXIT) <<<"
fi

# Always exit 0 so Kiro displays the output
exit 0
