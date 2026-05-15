#!/usr/bin/env bash
# install-cron.sh — install Phase 3 cron LaunchAgents (daily, weekly, monthly).
# Idempotent. Substitutes __VAULT__ in each plist before bootstrapping.
set -euo pipefail

VAULT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CRON_DIR="$VAULT_ROOT/bin/cron"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH_DIR"

JOBS=(daily weekly monthly)

for job in "${JOBS[@]}"; do
  label="com.aikb.${job}"
  src="$CRON_DIR/${label}.plist"
  dst="$LAUNCH_DIR/${label}.plist"

  if [[ ! -f "$src" ]]; then
    echo "error: $src missing"
    exit 1
  fi

  echo "→ installing $label"
  sed "s|__VAULT__|$VAULT_ROOT|g" "$src" > "$dst"

  if launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1; then
    launchctl bootout "gui/$(id -u)/$label" || true
  fi
  launchctl bootstrap "gui/$(id -u)" "$dst"
  launchctl enable "gui/$(id -u)/$label"
done

echo
echo "Installed cron jobs:"
for job in "${JOBS[@]}"; do
  printf "  com.aikb.%-8s — next scheduled run:\n" "$job"
  launchctl print "gui/$(id -u)/com.aikb.${job}" 2>/dev/null | grep -E "next run|state =" | sed 's/^/    /' || true
done
echo
echo "Manually trigger any job for testing:"
echo "  launchctl kickstart -k gui/\$(id -u)/com.aikb.daily"
echo
echo "To uninstall: bin/cron/uninstall-cron.sh"
