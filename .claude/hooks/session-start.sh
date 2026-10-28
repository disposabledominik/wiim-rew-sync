#!/usr/bin/env bash
# Project SessionStart bootstrap (runs in local and cloud sessions).
# 1. Fallback dependency install: runs this repo's .claude/setup.sh, which is a
#    fast no-op when the environment setup script already installed everything.
# 2. Delegates to the global hook from disposabledominik/claude-config. If that
#    config is not installed yet, installs it from a sibling clone and prints
#    the global rules as context.
setup="$CLAUDE_PROJECT_DIR/.claude/setup.sh"
[ -x "$setup" ] && "$setup" </dev/null
hook="$HOME/.claude/hooks/session-start.sh"
if [ ! -x "$hook" ]; then
  for d in "${CLAUDE_CONFIG_DIR:-}" "$CLAUDE_PROJECT_DIR/../claude-config" /home/user/claude-config "$HOME/code/claude-config"; do
    if [ -n "$d" ] && [ -x "$d/install.sh" ]; then
      "$d/install.sh" >/dev/null 2>&1 && {
        echo "Global rules (claude-config was installed at session start; agents and skills load from the next session):"
        cat "$d/CLAUDE.md"
      }
      break
    fi
  done
fi
if [ -x "$hook" ]; then exec "$hook"; fi
git fetch --quiet --all --prune 2>/dev/null
echo "claude-config not found; global rules are not loaded. See its README."
