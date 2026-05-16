#!/usr/bin/env bash
# bin/setup-vault.sh — scaffold a new ai-kb user vault
#
# Creates a new git repo with ai-kb as a submodule, copies CLAUDE.md and
# user docs, sets up commands symlink, governance examples, and an
# initial commit.
#
# Usage:
#   setup-vault.sh <vault-name> [--remote=<url>] [--ref=<tag-or-branch>]
#                               [--refresh] [--force]
#
# Options:
#   --remote=<url>   URL of the ai-kb template repo
#                    (default: detected from this script's repo, else
#                     https://github.com/andychoi/ai-kb.git)
#   --ref=<ref>      Tag or branch to pin the submodule to
#                    (default: main; recommend a tag like v1.0.0 once tagged)
#   --refresh        Update an existing vault: re-copy templates, re-link.
#                    Does not touch user-authored content.
#   --force          Overwrite vault directory if it exists (dangerous).
#
# Examples:
#   setup-vault.sh my-vault
#   setup-vault.sh team-kb --remote=git@gitlab.example.com:infra/ai-kb.git --ref=v1.0.0
#   setup-vault.sh existing-vault --refresh
#
# Architecture: see .docs/architecture/gitlab-submodule-architecture.md

set -euo pipefail

# ---------- helpers ----------

die() {
  echo "ERROR: $*" >&2
  exit 1
}

info() {
  echo "[setup-vault] $*"
}

warn() {
  echo "[setup-vault] WARNING: $*" >&2
}

# Copy a file if source exists and target doesn't (or --refresh given).
# Skips silently if source doesn't exist (allows graceful degradation).
copy_if_missing() {
  local src="$1"
  local dst="$2"
  if [ ! -e "$src" ]; then
    return 0  # source doesn't exist; nothing to copy
  fi
  if [ -e "$dst" ] && [ "$REFRESH" != "1" ]; then
    info "  skip (exists): $dst"
    return 0
  fi
  mkdir -p "$(dirname "$dst")"
  cp -R "$src" "$dst"
  info "  copied: $src -> $dst"
}

# ---------- arg parsing ----------

VAULT_NAME=""
REMOTE=""
REF="main"
REFRESH="0"
FORCE="0"

while [ $# -gt 0 ]; do
  case "$1" in
    --remote=*) REMOTE="${1#--remote=}" ;;
    --ref=*)    REF="${1#--ref=}" ;;
    --refresh)  REFRESH="1" ;;
    --force)    FORCE="1" ;;
    -h|--help)
      sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    --*)        die "Unknown option: $1" ;;
    *)
      if [ -z "$VAULT_NAME" ]; then
        VAULT_NAME="$1"
      else
        die "Unexpected argument: $1 (vault name already set to '$VAULT_NAME')"
      fi
      ;;
  esac
  shift
done

[ -n "$VAULT_NAME" ] || die "vault name required. Usage: setup-vault.sh <vault-name> [options]"

# Detect default remote from this script's location, if running inside the ai-kb repo
if [ -z "$REMOTE" ]; then
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
  if [ -d "$SCRIPT_DIR/../.git" ]; then
    REMOTE="$(cd "$SCRIPT_DIR/.." && git remote get-url origin 2>/dev/null || true)"
  fi
  if [ -z "$REMOTE" ]; then
    REMOTE="https://github.com/andychoi/ai-kb.git"
  fi
  info "auto-detected remote: $REMOTE"
fi

if [ "$REF" = "main" ]; then
  warn "pinning to 'main' branch is not recommended for production."
  warn "create and pin to a tag (e.g., 'git tag v1.0.0' in ai-kb, then re-run with --ref=v1.0.0)."
fi

# ---------- preflight ----------

if [ -e "$VAULT_NAME" ]; then
  if [ "$REFRESH" = "1" ]; then
    info "refreshing existing vault: $VAULT_NAME"
    [ -d "$VAULT_NAME/.git" ] || die "$VAULT_NAME exists but isn't a git repo; cannot refresh"
  elif [ "$FORCE" = "1" ]; then
    warn "removing existing directory: $VAULT_NAME"
    rm -rf "$VAULT_NAME"
  else
    die "$VAULT_NAME already exists. Use --refresh to update, or --force to overwrite."
  fi
fi

# ---------- create vault ----------

if [ "$REFRESH" != "1" ]; then
  info "initializing new vault: $VAULT_NAME"
  mkdir -p "$VAULT_NAME"
  cd "$VAULT_NAME"
  git init --quiet
  git branch -m main 2>/dev/null || true
else
  cd "$VAULT_NAME"
fi

# ---------- add submodule ----------

if [ ! -d .ai-kb ]; then
  info "adding ai-kb submodule from $REMOTE @ $REF"
  git submodule add --quiet "$REMOTE" .ai-kb
  (cd .ai-kb && git fetch --quiet --tags origin "$REF" && git checkout --quiet "$REF") \
    || die "could not check out $REF in submodule"
else
  if [ "$REFRESH" = "1" ]; then
    info "updating ai-kb submodule to $REF"
    (cd .ai-kb && git fetch --quiet --tags origin "$REF" && git checkout --quiet "$REF") \
      || die "could not check out $REF in submodule"
  fi
fi

# ---------- copy assets ----------

info "copying templates from .ai-kb/"

copy_if_missing ".ai-kb/CLAUDE.md" "./CLAUDE.md"
copy_if_missing ".ai-kb/templates" "./templates"

# User docs (if present in template)
if [ -d ".ai-kb/.docs/user" ]; then
  copy_if_missing ".ai-kb/.docs/user" "./.docs/user"
fi

# Examples → vault files
copy_if_missing ".ai-kb/examples/.gitignore.example" "./.gitignore"
copy_if_missing ".ai-kb/examples/.gitlab-ci.yml.example" "./.gitlab-ci.yml"

# Governance rule examples → .kb/governance/ (named without .example)
if [ -d ".ai-kb/examples/governance" ]; then
  mkdir -p .kb/governance
  for src in .ai-kb/examples/governance/*.example.md; do
    [ -e "$src" ] || continue
    base="$(basename "$src" .example.md)"
    copy_if_missing "$src" ".kb/governance/${base}.md"
  done
fi

# ---------- symlink commands ----------

mkdir -p .claude
if [ ! -e .claude/commands ]; then
  ln -s ../.ai-kb/.claude/commands .claude/commands
  info "  linked: .claude/commands -> .ai-kb/.claude/commands"
else
  if [ -L .claude/commands ]; then
    info "  skip (already linked): .claude/commands"
  else
    warn "  .claude/commands exists and is not a symlink; not touching"
  fi
fi

# Minimal settings.json if missing
if [ ! -f .claude/settings.json ]; then
  cat > .claude/settings.json <<'EOF'
{
  "permissions": {
    "read":  ["inbox/", "notes/", "sources/", "work/", "code/", "refs/", "daily/", ".claude/", ".kb/", ".ai-kb/"],
    "write": ["inbox/", "notes/", "sources/", "work/", "code/", "refs/", "daily/", ".kb/state.json"],
    "bash":  ["git", "find", "grep", "ls"]
  }
}
EOF
  info "  created: .claude/settings.json"
fi

# ---------- vault folder structure ----------

for d in inbox notes sources work code refs daily; do
  mkdir -p "$d"
  # Touch .gitkeep so empty folders are tracked
  [ -e "$d/.gitkeep" ] || touch "$d/.gitkeep"
done

# ---------- .kb skeleton ----------

mkdir -p .kb
if [ ! -f .kb/state.json ]; then
  cat > .kb/state.json <<'EOF'
{
  "schema_version": 1,
  "processed": {},
  "idempotency": {}
}
EOF
  info "  created: .kb/state.json"
fi

# ---------- initial commit ----------

if [ "$REFRESH" = "1" ]; then
  if [ -n "$(git status --porcelain)" ]; then
    info "uncommitted changes from refresh:"
    git status --short
    info "review and commit when ready."
  else
    info "refresh complete; no changes needed."
  fi
else
  git add .
  git commit --quiet -m "init: vault scaffolded from ai-kb @ $REF

Source: $REMOTE
"
  info "initial commit created."
  info ""
  info "next steps:"
  info "  cd $VAULT_NAME"
  info "  git remote add origin <your-vault-remote-url>"
  info "  git push -u origin main"
  info ""
  info "to update ai-kb later: ./bin/upgrade-vault.sh <new-ref>"
fi
