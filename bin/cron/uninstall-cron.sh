#!/usr/bin/env bash
# uninstall-cron.sh — remove Phase 3 cron LaunchAgents.
set -euo pipefail

LAUNCH_DIR="$HOME/Library/LaunchAgents"
JOBS=(daily weekly monthly)

for job in "${JOBS[@]}"; do
  label="com.aikb.${job}"
  if launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1; then
    echo "→ bootout $label"
    launchctl bootout "gui/$(id -u)/$label" || true
  fi
  dst="$LAUNCH_DIR/${label}.plist"
  if [[ -f "$dst" ]]; then
    rm -f "$dst"
    echo "→ removed $dst"
  fi
done

echo "Uninstalled all Phase 3 cron jobs."
