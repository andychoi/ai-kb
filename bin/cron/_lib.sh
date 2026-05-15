#!/usr/bin/env bash
# _lib.sh — shared setup for Phase 3 cron jobs.
# Sourced by daily.sh / weekly.sh / monthly.sh. Not standalone.
#
# Provides:
#   VAULT_ROOT      absolute repo path
#   LOG_FILE        per-job logfile under .kb/
#   log "msg"       append timestamped line to LOG_FILE (and stdout)
#   kb_pull         pull --rebase --autostash if origin is set
#   kb_push         push if origin is set; warn-on-fail
#   guard_lock      cooperative lock to prevent concurrent same-job runs
#   release_lock    paired with guard_lock; auto-released on EXIT

set -euo pipefail

VAULT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$VAULT_ROOT"

# Load env (KB_BOT_NAME / KB_BOT_EMAIL). Tolerate missing .env.
# shellcheck disable=SC1091
[[ -f "$VAULT_ROOT/.env" ]] && set -a && . "$VAULT_ROOT/.env" && set +a || true

# Bot identity for automated commits. CLAUDE.md §7.
export GIT_AUTHOR_NAME="${KB_BOT_NAME:-kb-bot}"
export GIT_AUTHOR_EMAIL="${KB_BOT_EMAIL:-kb-bot@local}"
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME"
export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"

# Caller sets JOB_NAME before sourcing _lib.sh; default if unset.
: "${JOB_NAME:=unknown}"
LOG_FILE="$VAULT_ROOT/.kb/cron-${JOB_NAME}.log"
mkdir -p "$(dirname "$LOG_FILE")"

log() {
  printf '%s [%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$JOB_NAME" "$*" | tee -a "$LOG_FILE"
}

guard_lock() {
  local lock="$VAULT_ROOT/.kb/cron-${JOB_NAME}.lock"
  if [[ -f "$lock" ]]; then
    local pid; pid=$(cat "$lock" 2>/dev/null || echo "?")
    if kill -0 "$pid" 2>/dev/null; then
      log "another ${JOB_NAME} run is active (pid $pid); skipping this tick"
      exit 0
    fi
    log "stale lock at $lock (pid $pid not running); reclaiming"
  fi
  echo "$$" > "$lock"
  # Auto-release on any exit.
  # shellcheck disable=SC2064
  trap "rm -f '$lock'" EXIT
}

kb_pull() {
  if ! git remote get-url origin >/dev/null 2>&1; then
    log "no origin remote; skipping pull"
    return 0
  fi
  log "git pull --rebase --autostash origin main"
  if ! git pull --rebase --autostash origin main >>"$LOG_FILE" 2>&1; then
    log "ERROR: pull failed; aborting (manual conflict resolution needed)"
    return 1
  fi
  return 0
}

kb_push() {
  if ! git remote get-url origin >/dev/null 2>&1; then
    log "no origin remote; skipping push"
    return 0
  fi
  log "git push origin main"
  if ! git push origin main >>"$LOG_FILE" 2>&1; then
    log "WARN: push failed (next run will retry)"
    return 0   # non-fatal; retry next cycle
  fi
  return 0
}

# --dry-run support: cron jobs respect $DRY_RUN=1.
kb_run() {
  if [[ "${DRY_RUN:-0}" == "1" ]]; then
    log "[dry-run] would run: $*"
    return 0
  fi
  log "running: $*"
  "$@" >>"$LOG_FILE" 2>&1
}
