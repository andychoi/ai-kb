#!/usr/bin/env bash
# bin/upgrade-vault.sh — guided ai-kb submodule upgrade
#
# Run from inside a user vault. Updates the .ai-kb submodule to a new ref,
# shows a diff of CHANGELOG and user docs, and commits the submodule
# pointer update.
#
# Usage:
#   upgrade-vault.sh <new-ref> [--dry-run]
#
# Arguments:
#   <new-ref>   The tag or branch to upgrade to (e.g., v1.1.0).
#
# Options:
#   --dry-run   Show what would change without modifying anything.
#
# Architecture: see .docs/architecture/gitlab-submodule-architecture.md

set -euo pipefail

die() { echo "ERROR: $*" >&2; exit 1; }
info() { echo "[upgrade-vault] $*"; }
warn() { echo "[upgrade-vault] WARNING: $*" >&2; }

# ---------- arg parsing ----------

NEW_REF=""
DRY_RUN="0"

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN="1" ;;
    -h|--help)
      sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    --*) die "Unknown option: $1" ;;
    *)
      [ -z "$NEW_REF" ] || die "Unexpected argument: $1"
      NEW_REF="$1"
      ;;
  esac
  shift
done

[ -n "$NEW_REF" ] || die "new ref required. Usage: upgrade-vault.sh <new-ref> [--dry-run]"

# ---------- preflight ----------

[ -d .ai-kb ] || die "no .ai-kb submodule found. Run this from inside a vault."
[ -d .ai-kb/.git ] || [ -f .ai-kb/.git ] || die ".ai-kb exists but is not a git submodule."

if [ -n "$(git status --porcelain)" ]; then
  git status --short
  die "vault has uncommitted changes. Commit or stash before upgrading."
fi

# ---------- fetch and identify refs ----------

info "fetching from ai-kb submodule remote..."
(cd .ai-kb && git fetch --quiet --tags origin)

OLD_REF="$(cd .ai-kb && git rev-parse HEAD)"
OLD_DESC="$(cd .ai-kb && git describe --tags --always 2>/dev/null || echo "$OLD_REF")"

# Verify new ref exists
if ! (cd .ai-kb && git rev-parse --verify --quiet "$NEW_REF" >/dev/null) \
   && ! (cd .ai-kb && git rev-parse --verify --quiet "origin/$NEW_REF" >/dev/null); then
  echo ""
  warn "ref '$NEW_REF' not found in submodule. Available tags:"
  (cd .ai-kb && git tag --sort=-version:refname | head -10) >&2
  die "ref '$NEW_REF' does not exist"
fi

NEW_SHA="$(cd .ai-kb && git rev-parse "$NEW_REF^{commit}")"

if [ "$OLD_REF" = "$NEW_SHA" ]; then
  info "already at $NEW_REF ($NEW_SHA). Nothing to do."
  exit 0
fi

# ---------- show what's changing ----------

info ""
info "upgrade summary:"
info "  from: $OLD_DESC ($OLD_REF)"
info "  to:   $NEW_REF ($NEW_SHA)"
info ""

# Show commit count
COMMIT_COUNT="$(cd .ai-kb && git rev-list --count "$OLD_REF..$NEW_SHA" 2>/dev/null || echo "?")"
info "commits between refs: $COMMIT_COUNT"

# Show CHANGELOG diff if present
if (cd .ai-kb && git show "$NEW_SHA:CHANGELOG.md" >/dev/null 2>&1); then
  info ""
  info "--- CHANGELOG changes ---"
  (cd .ai-kb && git diff "$OLD_REF..$NEW_SHA" -- CHANGELOG.md | head -80) || true
  info "--- end CHANGELOG ---"
fi

# Detect potentially breaking changes
if (cd .ai-kb && git log "$OLD_REF..$NEW_SHA" --oneline 2>/dev/null \
    | grep -iE 'BREAKING|breaking change|schema_version' >/dev/null); then
  warn ""
  warn "this upgrade contains potentially BREAKING changes."
  warn "review the CHANGELOG and any migration notes before proceeding."
fi

# Detect user-doc changes
if [ -d .ai-kb/.docs/user ] && [ -d .docs/user ]; then
  DOC_DIFF="$(cd .ai-kb && git diff "$OLD_REF..$NEW_SHA" --name-only -- '.docs/user/' 2>/dev/null || true)"
  if [ -n "$DOC_DIFF" ]; then
    info ""
    info "user docs changed in this upgrade. Files affected in .ai-kb/.docs/user/:"
    echo "$DOC_DIFF" | sed 's/^/  /'
    info "your vault's .docs/user/ was copied at setup time; manual re-sync may be desired."
    info "to re-sync: ../bin/setup-vault.sh . --refresh --ref=$NEW_REF"
  fi
fi

# ---------- apply or dry-run ----------

if [ "$DRY_RUN" = "1" ]; then
  info ""
  info "dry-run complete. No changes applied."
  exit 0
fi

info ""
info "applying upgrade..."

(cd .ai-kb && git checkout --quiet "$NEW_REF")

git add .ai-kb
git commit --quiet -m "chore: upgrade ai-kb to $NEW_REF

From: $OLD_DESC ($OLD_REF)
To:   $NEW_REF ($NEW_SHA)
Commits: $COMMIT_COUNT
"

info "submodule pointer updated and committed."
info ""
info "next steps:"
info "  - review the new commit with: git show HEAD"
info "  - push to your vault remote: git push"
info "  - notify your team if this is a shared vault"
