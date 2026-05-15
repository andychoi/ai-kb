#!/usr/bin/env bash
# verify-phase3.sh — Phase 3 acceptance gate for ai-kb.
#
# Static checks: cron scripts exist + parse, plists lint, install scripts work.
# Dynamic checks: kb_archive.py end-to-end with a synthetic fixture (no claude needed),
#                 dry-run smoke of each cron shell script.
#
# Does NOT install LaunchAgents and does NOT invoke claude.

set -euo pipefail

VAULT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$VAULT_ROOT"

fail=0
pass=0
ok()  { printf "  \033[32m✓\033[0m %s\n" "$*"; pass=$((pass+1)); }
err() { printf "  \033[31m✗\033[0m %s\n" "$*"; fail=$((fail+1)); }
header() { printf "\n\033[1m%s\033[0m\n" "$*"; }

header "1. Phase 3 files exist"
for f in bin/cron/_lib.sh \
         bin/cron/daily.sh bin/cron/weekly.sh bin/cron/monthly.sh \
         bin/cron/kb_archive.py \
         bin/cron/com.aikb.daily.plist bin/cron/com.aikb.weekly.plist bin/cron/com.aikb.monthly.plist \
         bin/cron/install-cron.sh bin/cron/uninstall-cron.sh; do
  if [[ -f "$f" ]]; then ok "$f"; else err "$f missing"; fi
done

header "2. Scripts are executable"
for f in bin/cron/daily.sh bin/cron/weekly.sh bin/cron/monthly.sh \
         bin/cron/kb_archive.py bin/cron/install-cron.sh bin/cron/uninstall-cron.sh; do
  if [[ -x "$f" ]]; then ok "$f executable"; else err "$f not executable"; fi
done

header "3. Plists lint with plutil"
for p in bin/cron/com.aikb.daily.plist bin/cron/com.aikb.weekly.plist bin/cron/com.aikb.monthly.plist; do
  if plutil -lint "$p" >/dev/null 2>&1; then ok "$p valid"; else err "$p failed plutil"; fi
  if grep -q "__VAULT__" "$p"; then ok "$p has __VAULT__ placeholder"; else err "$p missing __VAULT__"; fi
done

header "4. Shell + Python syntax"
for s in bin/cron/daily.sh bin/cron/weekly.sh bin/cron/monthly.sh bin/cron/_lib.sh \
         bin/cron/install-cron.sh bin/cron/uninstall-cron.sh; do
  if bash -n "$s" 2>/dev/null; then ok "$s syntax OK"; else err "$s syntax error"; fi
done
if python3 -m py_compile bin/cron/kb_archive.py 2>/dev/null; then
  ok "bin/cron/kb_archive.py compiles"
else
  err "bin/cron/kb_archive.py syntax error"
fi

header "5. kb_archive.py --help"
if python3 bin/cron/kb_archive.py --help >/dev/null 2>&1; then
  ok "kb_archive.py --help exits 0"
else
  err "kb_archive.py --help failed"
fi

header "6. Cron scripts honor DRY_RUN (no claude needed)"
# daily/weekly/monthly all share _lib.sh's kb_run which respects DRY_RUN.
for j in daily weekly monthly; do
  out=$(DRY_RUN=1 bash bin/cron/${j}.sh 2>&1 || true)
  if echo "$out" | grep -qE "(dry-run|=== ${j} run complete ===)"; then
    ok "bin/cron/${j}.sh respects DRY_RUN"
  else
    err "bin/cron/${j}.sh dry-run unexpected output: $out"
  fi
done

header "7. Lock files are released after each run"
for j in daily weekly monthly; do
  if [[ -f ".kb/cron-${j}.lock" ]]; then
    err "lock file .kb/cron-${j}.lock not released"
  else
    ok ".kb/cron-${j}.lock released"
  fi
done

header "8. kb_archive.py — end-to-end with synthetic fixture"
# Set up a fake-old inbox note and a fake-done work note, then run archive in dry-run
# (so git mv isn't actually executed in the verify run).
FIX_INBOX="inbox/.phase3-test-fixture.md"
FIX_WORK="work/.phase3-test-work.md"

cat > "$FIX_INBOX" <<EOF
---
id: 01HKZX9PHASE3TESTINBOX0001
type: note
title: "Phase 3 archive test (inbox)"
created: 2024-01-01T00:00:00Z
updated: 2024-01-01T00:00:00Z
tags: [test]
source: manual
idem_key: 01HKZX9PHASE3TESTINBOX0001
---

This note's frontmatter \`created\` is from 2024, so it should be flagged for archival.
EOF

cat > "$FIX_WORK" <<EOF
---
id: 01HKZX9PHASE3TESTWORK0001
type: work
title: "Phase 3 archive test (work)"
created: 2024-01-01T00:00:00Z
updated: 2024-01-01T00:00:00Z
tags: [test]
source: manual
idem_key: 01HKZX9PHASE3TESTWORK0001
project: phase3
subtype: spec
status: done
---

This work note is status: done and >90 days old; should be archived.
EOF

out=$(python3 bin/cron/kb_archive.py --vault . --dry-run 2>&1)
if echo "$out" | grep -q "inbox-archive: .phase3-test-fixture.md"; then
  ok "kb_archive identifies aged inbox note"
else
  err "kb_archive missed aged inbox note. Output: $out"
fi
if echo "$out" | grep -q "work-archive: work/.phase3-test-work.md"; then
  ok "kb_archive identifies status:done >90d work note"
else
  err "kb_archive missed status:done work note. Output: $out"
fi

# Cleanup synthetic fixtures.
rm -f "$FIX_INBOX" "$FIX_WORK"
ok "fixtures cleaned"

header "9. Bot identity env in _lib.sh"
# Source _lib.sh in a subshell and verify the env vars are exported.
JOB_NAME=verify_test
identity=$(JOB_NAME=verify_test bash -c '. bin/cron/_lib.sh; echo "$GIT_AUTHOR_NAME / $GIT_AUTHOR_EMAIL"')
if [[ "$identity" == *"kb-bot"* ]]; then
  ok "_lib.sh exports bot identity: $identity"
else
  err "_lib.sh did not export bot identity correctly: $identity"
fi

# Remove the verify_test lockfile if _lib.sh's trap didn't catch it
rm -f .kb/cron-verify_test.lock 2>/dev/null || true

# ────────────────────────────────────────────────────────────────────
header "Summary"
printf "  passed: %d\n  failed: %d\n" "$pass" "$fail"
if [[ "$fail" -gt 0 ]]; then
  printf "\n\033[31mPhase 3 acceptance gate FAILED.\033[0m\n"
  exit 1
fi
printf "\n\033[32mPhase 3 acceptance gate PASSED.\033[0m\n"
printf "\nManual end-to-end test (requires authenticated Claude CLI):\n"
cat <<'EOF'
  # 1. Dry-run each job; logs go to .kb/cron-*.log
  DRY_RUN=1 bin/cron/daily.sh
  DRY_RUN=1 bin/cron/weekly.sh
  DRY_RUN=1 bin/cron/monthly.sh

  # 2. Real run (requires claude on PATH + your auth; will pull/push if origin set)
  bin/cron/daily.sh
  tail -f .kb/cron-daily.log    # in another terminal

  # 3. Install all three as LaunchAgents (auto-run on schedule)
  bin/cron/install-cron.sh

  # 4. Kick a job manually for testing
  launchctl kickstart -k gui/$(id -u)/com.aikb.daily
EOF
exit 0
