#!/usr/bin/env bash
# Project SessionStart bootstrap (runs in local and cloud sessions).
# Delegates to the global hook from disposabledominik/claude-config. If that
# config is not installed yet (e.g. a cloud setup script did not run), it
# installs it from a sibling clone and prints the global rules as context.
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
echo "Git: $(git branch --show-current) at $(git rev-parse --short HEAD). claude-config not found; global rules are not loaded."
