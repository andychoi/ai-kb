#!/usr/bin/env bash
# setup-webhook.sh — create .venv-webhook and install Phase 4 deps. Idempotent.
set -euo pipefail

VAULT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="$VAULT_ROOT/.venv-webhook"

cd "$VAULT_ROOT"

if [[ ! -d "$VENV" ]]; then
  echo "→ creating venv at $VENV"
  python3 -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"
echo "→ upgrading pip"
pip install --quiet --upgrade pip
echo "→ installing webhook requirements"
pip install --quiet -r "$VAULT_ROOT/bin/webhook/requirements.txt"

echo
echo "venv ready: $VENV"
echo "python:     $($VENV/bin/python3 --version)"
echo "fastapi:    $($VENV/bin/python3 -c 'import fastapi; print(fastapi.__version__)')"
echo "uvicorn:    $($VENV/bin/python3 -c 'import uvicorn; print(uvicorn.__version__)')"
echo "feedparser: $($VENV/bin/python3 -c 'import feedparser; print(feedparser.__version__)')"
echo
echo "Next:"
echo "  manual run:  .venv-webhook/bin/python3 -m bin.webhook.cli serve"
echo "  install:     bin/webhook/install-webhook.sh"
