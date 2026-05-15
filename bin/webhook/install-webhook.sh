#!/usr/bin/env bash
# install-webhook.sh — install Phase 4 LaunchAgents (HTTP server + RSS poller).
# Idempotent. Substitutes __VAULT__ and __PORT__ in each plist.
set -euo pipefail

VAULT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="$VAULT_ROOT/.venv-webhook"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH_DIR"

if [[ ! -d "$VENV" ]]; then
  echo "error: venv missing at $VENV"
  echo "       run bin/webhook/setup-webhook.sh first"
  exit 1
fi

# Load .env if present so KB_WEBHOOK_PORT is honored. Don't barf if absent.
# shellcheck disable=SC1091
[[ -f "$VAULT_ROOT/.env" ]] && set -a && . "$VAULT_ROOT/.env" && set +a || true
PORT="${KB_WEBHOOK_PORT:-8765}"

JOBS=(webhook rss-poll)

for job in "${JOBS[@]}"; do
  label="com.aikb.${job}"
  src="$VAULT_ROOT/bin/webhook/${label}.plist"
  dst="$LAUNCH_DIR/${label}.plist"

  if [[ ! -f "$src" ]]; then
    echo "error: $src missing"
    exit 1
  fi

  echo "→ installing $label"
  sed -e "s|__VAULT__|$VAULT_ROOT|g" -e "s|__PORT__|$PORT|g" "$src" > "$dst"

  if launchctl print "gui/$(id -u)/$label" >/dev/null 2>&1; then
    launchctl bootout "gui/$(id -u)/$label" || true
  fi
  launchctl bootstrap "gui/$(id -u)" "$dst"
  launchctl enable "gui/$(id -u)/$label"
done

echo
echo "Installed:"
for job in "${JOBS[@]}"; do
  echo "  com.aikb.${job}"
done
echo
echo "Webhook server: http://127.0.0.1:${PORT}/healthz"
echo "Tail logs:"
echo "  tail -f $VAULT_ROOT/.kb/webhook-stdout.log"
echo "  tail -f $VAULT_ROOT/.kb/rss-poll.stdout.log"
echo
echo "Manual one-shot RSS poll: launchctl kickstart -k gui/\$(id -u)/com.aikb.rss-poll"
echo "Uninstall:                bin/webhook/uninstall-webhook.sh"
