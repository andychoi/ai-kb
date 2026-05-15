#!/usr/bin/env bash
# uninstall-webhook.sh — remove Phase 4 LaunchAgents.
set -euo pipefail

LAUNCH_DIR="$HOME/Library/LaunchAgents"
JOBS=(webhook rss-poll)

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

echo "Uninstalled Phase 4 services."
