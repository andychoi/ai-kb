#!/usr/bin/env bash
# setup-cluster.sh — create the venv for /kb-cluster and install its deps.
# Idempotent; safe to re-run.
set -euo pipefail

VAULT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="$VAULT_ROOT/.venv-cluster"
REQS="$VAULT_ROOT/bin/cluster/requirements.txt"

cd "$VAULT_ROOT"

if [[ ! -d "$VENV" ]]; then
  echo "→ creating venv at $VENV"
  python3 -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"
echo "→ upgrading pip"
pip install --quiet --upgrade pip
echo "→ installing cluster requirements"
pip install --quiet -r "$REQS"

echo
echo "venv ready: $VENV"
echo "python:    $($VENV/bin/python3 --version)"
echo "networkx:  $($VENV/bin/python3 -c 'import networkx; print(networkx.__version__)')"
echo "louvain:   $($VENV/bin/python3 -c 'import community; print(getattr(community, "__version__", "installed"))')"
echo
echo "Next:"
echo "  smoke test:    .venv-cluster/bin/python3 bin/cluster/kb_cluster.py --vault ."
echo "  full run:      claude -p '/kb-cluster'"
