#!/usr/bin/env bash
# install-watcher.sh — install the kb-watcher as a launchd LaunchAgent.
# Substitutes __VAULT__ in the plist with the absolute repo path, copies to
# ~/Library/LaunchAgents/, and loads it. Idempotent.
set -euo pipefail

VAULT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$VAULT_ROOT/.venv-watcher"
LABEL="com.aikb.watcher"
PLIST_SRC="$VAULT_ROOT/bin/com.aikb.watcher.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ ! -d "$VENV" ]]; then
  echo "error: venv missing at $VENV"
  echo "       run bin/setup-watcher.sh first"
  exit 1
fi

mkdir -p "$(dirname "$PLIST_DST")"

# Generate the plist with the absolute path substituted.
sed "s|__VAULT__|$VAULT_ROOT|g" "$PLIST_SRC" > "$PLIST_DST"
echo "→ wrote $PLIST_DST"

# If a previous version is loaded, bootout cleanly first.
if launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; then
  echo "→ bootout existing $LABEL"
  launchctl bootout "gui/$(id -u)/$LABEL" || true
fi

echo "→ bootstrap $LABEL"
launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"

echo "→ enable $LABEL"
launchctl enable "gui/$(id -u)/$LABEL"

echo
echo "Installed. Status:"
launchctl print "gui/$(id -u)/$LABEL" | head -20 || true
echo
echo "Logs:"
echo "  $VAULT_ROOT/.kb/watcher.log         (application log)"
echo "  $VAULT_ROOT/.kb/watcher.stdout.log  (launchd captured stdout)"
echo "  $VAULT_ROOT/.kb/watcher.stderr.log  (launchd captured stderr)"
echo
echo "To uninstall: bin/uninstall-watcher.sh"
