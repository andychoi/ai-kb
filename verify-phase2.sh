#!/usr/bin/env bash
# verify-phase2.sh — Phase 2 acceptance gate for ai-kb.
#
# Static checks: daemon files exist, plist parses, scripts are executable.
# Dynamic checks: --once --dry-run smoke + cost-gate behavior (sha skip, age skip).
# Does NOT invoke claude. Real end-to-end /note-refile testing is a manual step.
#
# Exit code: 0 if all checks pass, non-zero on first failure.

set -euo pipefail

VAULT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$VAULT_ROOT"

fail=0
pass=0
ok()  { printf "  \033[32m✓\033[0m %s\n" "$*"; pass=$((pass+1)); }
err() { printf "  \033[31m✗\033[0m %s\n" "$*"; fail=$((fail+1)); }
header() { printf "\n\033[1m%s\033[0m\n" "$*"; }

header "1. Phase 2 files exist"
for f in bin/kb-watcher.py bin/com.aikb.watcher.plist bin/setup-watcher.sh \
         bin/install-watcher.sh bin/uninstall-watcher.sh bin/requirements.txt; do
  if [[ -f "$f" ]]; then ok "$f"; else err "$f missing"; fi
done

header "2. Scripts are executable"
for f in bin/kb-watcher.py bin/setup-watcher.sh bin/install-watcher.sh bin/uninstall-watcher.sh; do
  if [[ -x "$f" ]]; then ok "$f executable"; else err "$f not executable"; fi
done

header "3. Plist parses (plutil)"
if plutil -lint bin/com.aikb.watcher.plist >/dev/null 2>&1; then
  ok "bin/com.aikb.watcher.plist is valid plist XML"
else
  err "bin/com.aikb.watcher.plist failed plutil -lint"
fi
if grep -q "__VAULT__" bin/com.aikb.watcher.plist; then
  ok "plist still contains __VAULT__ placeholder (install-watcher.sh substitutes it)"
else
  err "plist missing __VAULT__ placeholder — install-watcher.sh won't work"
fi

header "4. Python syntax"
if python3 -m py_compile bin/kb-watcher.py 2>/dev/null; then
  ok "bin/kb-watcher.py compiles"
else
  err "bin/kb-watcher.py has syntax errors"
fi

header "5. venv is set up"
if [[ -x .venv-watcher/bin/python3 ]]; then
  ok ".venv-watcher/bin/python3 exists"
  if .venv-watcher/bin/python3 -c "import watchfiles" 2>/dev/null; then
    ver=$(.venv-watcher/bin/python3 -c "import watchfiles; print(watchfiles.__version__)")
    ok "watchfiles installed in venv ($ver)"
  else
    err "watchfiles not importable in venv; run bin/setup-watcher.sh"
  fi
else
  err ".venv-watcher missing; run bin/setup-watcher.sh"
fi

header "6. --help works"
if .venv-watcher/bin/python3 bin/kb-watcher.py --help >/dev/null 2>&1; then
  ok "kb-watcher --help exits 0"
else
  err "kb-watcher --help failed"
fi

header "7. --once --dry-run on empty inbox (no fixtures)"
rm -f inbox/test-fixture.md 2>/dev/null || true
out=$(.venv-watcher/bin/python3 bin/kb-watcher.py --once --dry-run 2>&1)
if echo "$out" | grep -q "nothing to refile"; then
  ok "empty inbox: 'nothing to refile' logged"
else
  err "empty inbox: expected 'nothing to refile' in log, got: $out"
fi

header "8. Cost gate: file too small (<50B) is skipped"
echo "tiny" > inbox/tiny.md
sleep 3   # clear MIN_FILE_AGE_SEC
out=$(.venv-watcher/bin/python3 bin/kb-watcher.py --once --dry-run 2>&1)
if echo "$out" | grep -q "nothing to refile"; then
  ok "tiny.md correctly skipped (size gate)"
else
  err "tiny.md should have been skipped by size gate, got: $out"
fi
rm -f inbox/tiny.md

header "9. Cost gate: fresh file (<2s old) is skipped"
cat > inbox/fresh.md <<'EOF'
# Fresh fixture for age gate test
Body big enough to clear the 50-byte threshold but written just now.
EOF
out=$(.venv-watcher/bin/python3 bin/kb-watcher.py --once --dry-run 2>&1)
if echo "$out" | grep -q "nothing to refile"; then
  ok "fresh.md correctly skipped (age gate)"
else
  err "fresh.md should have been skipped by age gate, got: $out"
fi

header "10. Cost gate: file passes after settling"
sleep 3
out=$(.venv-watcher/bin/python3 bin/kb-watcher.py --once --dry-run 2>&1)
if echo "$out" | grep -q "queue: fresh.md"; then
  ok "fresh.md queued after age gate window"
else
  err "fresh.md should have been queued after settling, got: $out"
fi

header "11. Cost gate: stamped sha is skipped on next pass"
# Simulate a prior attempt by writing the sha into state.json directly,
# then verify the daemon skips it.
.venv-watcher/bin/python3 - <<'PY'
import hashlib, json, pathlib, time
vault = pathlib.Path(".")
p = vault / "inbox" / "fresh.md"
sha = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
state_path = vault / ".kb" / "state.json"
state = json.loads(state_path.read_text())
state["processed"]["inbox/fresh.md"] = {
    "sha": sha,
    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "source": "watch",
}
state_path.write_text(json.dumps(state, indent=2) + "\n")
print(f"stamped sha={sha[:8]}")
PY
out=$(.venv-watcher/bin/python3 bin/kb-watcher.py --once --dry-run 2>&1)
if echo "$out" | grep -q "nothing to refile"; then
  ok "fresh.md correctly skipped (sha already processed)"
else
  err "fresh.md should have been skipped by sha gate, got: $out"
fi

header "12. Cost gate: modified file (different sha) is re-queued"
echo "" >> inbox/fresh.md   # bump mtime + change content
echo "More text added to change the sha." >> inbox/fresh.md
sleep 3
out=$(.venv-watcher/bin/python3 bin/kb-watcher.py --once --dry-run 2>&1)
if echo "$out" | grep -q "queue: fresh.md"; then
  ok "fresh.md re-queued after content change"
else
  err "fresh.md should have been re-queued after content change, got: $out"
fi

header "Cleanup"
# Restore state.json to clean baseline and remove fixtures.
.venv-watcher/bin/python3 - <<'PY'
import json, pathlib
sp = pathlib.Path(".kb/state.json")
state = json.loads(sp.read_text())
state.get("processed", {}).pop("inbox/fresh.md", None)
sp.write_text(json.dumps(state, indent=2) + "\n")
print("state.json: removed inbox/fresh.md stamp")
PY
rm -f inbox/fresh.md
ok "fixtures cleaned"

# ────────────────────────────────────────────────────────────────────
header "Summary"
printf "  passed: %d\n  failed: %d\n" "$pass" "$fail"
if [[ "$fail" -gt 0 ]]; then
  printf "\n\033[31mPhase 2 acceptance gate FAILED.\033[0m\n"
  exit 1
fi
printf "\n\033[32mPhase 2 acceptance gate PASSED.\033[0m\n"
printf "\nManual end-to-end test (requires authenticated Claude CLI):\n"
cat <<'EOF'
  # 1. Start the watcher in foreground (Ctrl-C to stop)
  .venv-watcher/bin/python3 bin/kb-watcher.py

  # 2. In another terminal, drop a real note:
  cat > inbox/real-test.md <<'NOTE'
  # Phase 2 real test

  This is a real refile target. The watcher should pick it up after the
  debounce window and shell out to /note-refile.
  NOTE

  # 3. Wait ~12 seconds; the daemon log should show queue → invoke claude.
  # 4. The note should move out of inbox/ to the correct folder with frontmatter filled.
  # 5. git log should show a "kb: refile ..." commit.

  # To install as a LaunchAgent (auto-start on login):
  bin/install-watcher.sh
EOF
exit 0
