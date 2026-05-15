#!/usr/bin/env bash
# verify-phase4.sh — Phase 4 acceptance gate for ai-kb.
#
# Static checks: webhook files exist + parse, plists lint, venv set up.
# Dynamic checks: delegated to bin.webhook.test_phase4 (FastAPI TestClient
# against a tmp vault). No network required, no claude required.

set -euo pipefail

VAULT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$VAULT_ROOT"

fail=0
pass=0
ok()  { printf "  \033[32m✓\033[0m %s\n" "$*"; pass=$((pass+1)); }
err() { printf "  \033[31m✗\033[0m %s\n" "$*"; fail=$((fail+1)); }
header() { printf "\n\033[1m%s\033[0m\n" "$*"; }

header "1. Phase 4 files exist"
for f in bin/__init__.py bin/webhook/__init__.py \
         bin/webhook/app.py bin/webhook/ingest.py bin/webhook/cli.py \
         bin/webhook/github.py bin/webhook/rss.py bin/webhook/email.py \
         bin/webhook/test_phase4.py bin/webhook/requirements.txt \
         bin/webhook/com.aikb.webhook.plist bin/webhook/com.aikb.rss-poll.plist \
         bin/webhook/setup-webhook.sh bin/webhook/install-webhook.sh bin/webhook/uninstall-webhook.sh; do
  if [[ -f "$f" ]]; then ok "$f"; else err "$f missing"; fi
done

header "2. Scripts executable"
for f in bin/webhook/setup-webhook.sh bin/webhook/install-webhook.sh bin/webhook/uninstall-webhook.sh; do
  if [[ -x "$f" ]]; then ok "$f executable"; else err "$f not executable"; fi
done

header "3. Plists lint"
for p in bin/webhook/com.aikb.webhook.plist bin/webhook/com.aikb.rss-poll.plist; do
  if plutil -lint "$p" >/dev/null 2>&1; then ok "$p valid"; else err "$p failed plutil"; fi
  if grep -q "__VAULT__" "$p"; then ok "$p has __VAULT__ placeholder"; else err "$p missing __VAULT__"; fi
done
# Webhook plist also needs __PORT__ substitution.
if grep -q "__PORT__" bin/webhook/com.aikb.webhook.plist; then
  ok "webhook plist has __PORT__ placeholder"
else
  err "webhook plist missing __PORT__"
fi

header "4. Python syntax"
for f in bin/webhook/*.py; do
  if python3 -m py_compile "$f" 2>/dev/null; then ok "$f compiles"; else err "$f syntax error"; fi
done

header "5. venv set up"
if [[ -x .venv-webhook/bin/python3 ]]; then
  ok ".venv-webhook/bin/python3 exists"
  for pkg in fastapi uvicorn feedparser httpx; do
    if .venv-webhook/bin/python3 -c "import $pkg" 2>/dev/null; then
      ver=$(.venv-webhook/bin/python3 -c "import $pkg; print($pkg.__version__)" 2>/dev/null)
      ok "$pkg installed ($ver)"
    else
      err "$pkg missing from venv; run bin/webhook/setup-webhook.sh"
    fi
  done
else
  err ".venv-webhook missing; run bin/webhook/setup-webhook.sh"
fi

header "6. CLI subcommands work"
if .venv-webhook/bin/python3 -m bin.webhook.cli version >/dev/null 2>&1; then
  ok "kb-webhook version exits 0"
else
  err "kb-webhook version failed"
fi
# rss-poll on empty feeds.json should be a no-op success.
if .venv-webhook/bin/python3 -m bin.webhook.cli rss-poll >/dev/null 2>&1; then
  ok "kb-webhook rss-poll on empty feed list exits 0"
else
  err "kb-webhook rss-poll failed on empty feed list"
fi

header "7. Dynamic tests (FastAPI TestClient against tmp vault)"
# Run the Python test harness and capture output.
if dyn_out=$(.venv-webhook/bin/python3 -m bin.webhook.test_phase4 2>&1); then
  echo "$dyn_out" | grep -E "^\s*\[?[✓✗]\]?" || true
  echo "$dyn_out" | grep -E "(passed|failed):" | head -2 | sed 's/^/  /'
  # Parse pass/fail counts and add to ours.
  dyn_pass=$(echo "$dyn_out" | grep -oE "passed: [0-9]+" | head -1 | awk '{print $2}')
  dyn_fail=$(echo "$dyn_out" | grep -oE "failed: [0-9]+" | head -1 | awk '{print $2}')
  pass=$((pass + ${dyn_pass:-0}))
  fail=$((fail + ${dyn_fail:-0}))
else
  err "dynamic test harness crashed"
  echo "$dyn_out" | tail -10 | sed 's/^/    /'
fi

header "Summary"
printf "  passed: %d\n  failed: %d\n" "$pass" "$fail"
if [[ "$fail" -gt 0 ]]; then
  printf "\n\033[31mPhase 4 acceptance gate FAILED.\033[0m\n"
  exit 1
fi
printf "\n\033[32mPhase 4 acceptance gate PASSED.\033[0m\n"

cat <<'EOF'

Manual end-to-end test (real network, real auth):

  # 1. Configure secrets in .env (NOT committed)
  echo 'GITHUB_WEBHOOK_SECRET=your-shared-secret' >> .env
  echo 'KB_EMAIL_TOKEN=your-bearer-token'         >> .env
  echo 'KB_ADMIN_TOKEN=your-admin-token'          >> .env
  echo 'KB_WEBHOOK_PORT=8765'                     >> .env

  # 2. Configure RSS feeds (committed)
  cat > .kb/feeds.json <<JSON
  [
    {"name": "Hacker News", "url": "https://hnrss.org/frontpage", "tags": ["hn"]},
    {"name": "Anthropic", "url": "https://www.anthropic.com/rss.xml", "tags": ["ai"]}
  ]
  JSON

  # 3. Start the server in foreground (Ctrl-C to stop)
  .venv-webhook/bin/python3 -m bin.webhook.cli serve

  # 4. Test healthz from another terminal
  curl -s http://127.0.0.1:8765/healthz | python3 -m json.tool

  # 5. Install as LaunchAgents
  bin/webhook/install-webhook.sh

  # 6. Trigger an RSS poll manually
  launchctl kickstart -k gui/$(id -u)/com.aikb.rss-poll
  tail -f .kb/rss-poll.stdout.log

  # 7. Point a GitHub webhook at http://your-host:8765/webhook/github
  #    with content-type: application/json and the shared secret.
EOF
exit 0
