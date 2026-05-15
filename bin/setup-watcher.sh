#!/usr/bin/env bash
# setup-watcher.sh — create a dedicated venv for the Phase 2 watcher and install its deps.
# Idempotent; safe to re-run.
set -euo pipefail

VAULT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$VAULT_ROOT/.venv-watcher"

cd "$VAULT_ROOT"

if [[ ! -d "$VENV" ]]; then
  echo "→ creating venv at $VENV"
  python3 -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"
echo "→ upgrading pip"
pip install --quiet --upgrade pip
echo "→ installing watcher requirements"
pip install --quiet -r "$VAULT_ROOT/bin/requirements.txt"

echo
echo "venv ready: $VENV"
echo "python:     $($VENV/bin/python3 --version)"
echo "watchfiles: $($VENV/bin/python3 -c 'import watchfiles; print(watchfiles.__version__)')"
echo
echo "Next:"
echo "  manual test:    .venv-watcher/bin/python3 bin/kb-watcher.py --once --dry-run"
echo "  launchd install: bin/install-watcher.sh"
