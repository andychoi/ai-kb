#!/usr/bin/env bash
# verify-phase1.sh — Phase 1 acceptance gate for ai-kb
#
# Static checks (always run): structure, templates, slash commands, settings.
# Dynamic checks (claude -p round-trips): commented at bottom; run manually with
# an authenticated Claude Code CLI to validate end-to-end command behavior.
#
# Exit code: 0 if all static checks pass, non-zero on first failure.

set -euo pipefail

VAULT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$VAULT_ROOT"

fail=0
pass=0
note() { printf "  %s\n" "$*"; }
ok()   { printf "  \033[32m✓\033[0m %s\n" "$*"; pass=$((pass+1)); }
err()  { printf "  \033[31m✗\033[0m %s\n" "$*"; fail=$((fail+1)); }
header() { printf "\n\033[1m%s\033[0m\n" "$*"; }

header "1. Directory structure"
for dir in inbox notes work sources code refs/people refs/tools refs/concepts daily templates .claude/commands .kb .obsidian; do
  if [[ -d "$dir" ]]; then ok "$dir/ exists"; else err "$dir/ missing"; fi
done

header "2. Anchor files"
for f in CLAUDE.md README.md .gitignore .gitattributes .env.example MOC.md code/index.md verify-phase1.sh; do
  if [[ -f "$f" ]]; then ok "$f exists"; else err "$f missing"; fi
done

header "3. Templates (6 expected)"
for t in note source work code ref daily; do
  if [[ -f "templates/$t.md" ]]; then
    if grep -q "^---$" "templates/$t.md" && grep -q "^type: $t" "templates/$t.md"; then
      ok "templates/$t.md (has frontmatter, type: $t)"
    else
      err "templates/$t.md missing frontmatter or wrong type"
    fi
  else
    err "templates/$t.md missing"
  fi
done

header "4. Slash commands (10 expected)"
for c in note-add note-refile note-rename note-split note-link source-capture code-doc daily kb-validate kb-stats; do
  cmd=".claude/commands/$c.md"
  if [[ -f "$cmd" ]]; then
    if grep -qE "^description:" "$cmd" && grep -qE "^allowed-tools:" "$cmd"; then
      ok "$cmd (has description, allowed-tools)"
    else
      err "$cmd missing required frontmatter (description / allowed-tools)"
    fi
  else
    err "$cmd missing"
  fi
done

header "5. State & settings"
if [[ -f .kb/state.json ]]; then
  if python3 -c "import json,sys; d=json.load(open('.kb/state.json')); assert d.get('schema_version')==1 and 'processed' in d and 'idempotency' in d" 2>/dev/null; then
    ok ".kb/state.json (schema_version=1, processed{}, idempotency{})"
  else
    err ".kb/state.json malformed or missing reserved keys"
  fi
else
  err ".kb/state.json missing"
fi

if [[ -f .claude/settings.json ]]; then
  if python3 -c "import json,sys; d=json.load(open('.claude/settings.json')); assert 'permissions' in d" 2>/dev/null; then
    ok ".claude/settings.json (permissions present)"
  else
    err ".claude/settings.json malformed"
  fi
else
  err ".claude/settings.json missing"
fi

header "6. Obsidian config"
if [[ -f .obsidian/community-plugins.json ]]; then
  if grep -q "dataview" .obsidian/community-plugins.json; then
    ok ".obsidian/community-plugins.json (dataview enabled)"
  else
    err ".obsidian/community-plugins.json missing dataview"
  fi
else
  err ".obsidian/community-plugins.json missing"
fi

header "7. CLAUDE.md content checks"
for needle in "Single ingest contract" "Atomic rule" "ULID" "kb: <verb> <scope>" "Headless-invocability"; do
  if grep -qF "$needle" CLAUDE.md; then ok "CLAUDE.md mentions: $needle"; else err "CLAUDE.md missing: $needle"; fi
done

header "8. README.md guide checks"
for needle in "Prerequisites" "Install" "Daily workflow" "Command reference" "Troubleshooting" "Roadmap"; do
  if grep -qF "$needle" README.md; then ok "README.md has section: $needle"; else err "README.md missing section: $needle"; fi
done

header "9. Git hygiene"
if grep -q "^\.obsidian/workspace" .gitignore; then ok ".gitignore excludes Obsidian per-machine state"; else err ".gitignore missing Obsidian workspace exclusions"; fi
if grep -q "^\.env$" .gitignore; then ok ".gitignore excludes .env"; else err ".gitignore missing .env"; fi

header "10. settings.json — destructive ops must be in deny, not allow"
# Parse JSON properly and verify each dangerous pattern is in deny[] and NOT in allow[].
check_denied() {
  local pattern="$1"
  python3 - "$pattern" <<'PY' .claude/settings.json
import json, sys
pattern = sys.argv[1]
data = json.load(open(sys.argv[2] if len(sys.argv) > 2 else ".claude/settings.json"))
perms = data.get("permissions", {})
allow = perms.get("allow", [])
deny  = perms.get("deny",  [])
in_allow = any(pattern in a for a in allow)
in_deny  = any(pattern in d for d in deny)
if in_allow:
    print(f"FAIL: '{pattern}' present in allow[]"); sys.exit(1)
if not in_deny:
    print(f"FAIL: '{pattern}' missing from deny[]"); sys.exit(2)
print(f"OK: '{pattern}' denied, not allowed")
PY
}
for pat in "rm -rf" "git push --force" "git reset --hard" "git branch -D"; do
  if check_denied "$pat" >/dev/null 2>&1; then ok "settings.json denies '$pat'"; else err "settings.json does NOT properly deny '$pat'"; fi
done

# ────────────────────────────────────────────────────────────────────
header "Summary"
printf "  passed: %d\n  failed: %d\n" "$pass" "$fail"
if [[ "$fail" -gt 0 ]]; then
  printf "\n\033[31mPhase 1 acceptance gate FAILED.\033[0m Fix the above and re-run.\n"
  exit 1
fi
printf "\n\033[32mPhase 1 static acceptance gate PASSED.\033[0m\n"
printf "\nDynamic round-trip tests (run manually with an authenticated Claude Code CLI):\n"
cat <<'EOF'
  # 1. Note creation
  claude -p "/note-add 'phase 1 smoke test' --type=note --tags=meta"  # → inbox/<file>.md

  # 2. Inbox refile
  claude -p "/note-refile"  # → moves smoke-test note to notes/

  # 3. Source capture
  claude -p "/source-capture https://example.com"  # → inbox/<file>.md, type:source

  # 4. Rename + alias-preservation
  claude -p "/note-rename notes/<smoke>.md notes/<renamed>.md"  # → wiki-link rewrites, alias added

  # 5. Validate
  claude -p "/kb-validate"  # → exit 0, summary line printed

  # 6. Stats
  claude -p "/kb-stats"  # → human-readable health report
  claude -p "/kb-stats --json" | python3 -m json.tool  # → valid JSON

  # 7. Daily idempotency
  claude -p "/daily" && claude -p "/daily"  # → second run prints "already exists; no-op"

  # 8. Oversized + split (requires fixture: a note >300 lines)
  claude -p "/note-split notes/<oversized>.md"
EOF
exit 0
