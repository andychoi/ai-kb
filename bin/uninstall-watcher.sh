#!/usr/bin/env bash
# uninstall-watcher.sh — remove the kb-watcher LaunchAgent.
set -euo pipefail

LABEL="com.aikb.watcher"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"

if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  echo "→ bootout $LABEL"
  launchctl bootout "gui/$(id -u)/$LABEL" || true
else
  echo "→ $LABEL not loaded"
fi

if [[ -f "$PLIST_DST" ]]; then
  rm -f "$PLIST_DST"
  echo "→ removed $PLIST_DST"
else
  echo "→ no plist at $PLIST_DST"
fi

echo "Uninstalled."
