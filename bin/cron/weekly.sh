#!/usr/bin/env bash
# weekly.sh — Phase 3 weekly cron job.
# Captures a /kb-stats JSON snapshot to .kb/stats/ and runs /kb-validate to
# surface drift. Pulls before, commits the snapshot, pushes after.
#
# Schedule: Sunday 03:00 local time (via com.aikb.weekly.plist).
JOB_NAME="weekly"
# shellcheck source=./_lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

guard_lock
log "=== weekly run starting ==="

kb_pull || exit 1

WEEK_TAG="$(date -u +%G-W%V)"     # ISO week, e.g. 2026-W20
STATS_DIR="$VAULT_ROOT/.kb/stats"
STATS_FILE="$STATS_DIR/${WEEK_TAG}.json"
mkdir -p "$STATS_DIR"

# Run /kb-stats --json and capture to file. Slash command exits 0 even on
# unhealthy vaults — /kb-validate is the gate that fails on errors.
if [[ "${DRY_RUN:-0}" == "1" ]]; then
  log "[dry-run] would write $STATS_FILE"
else
  log "capturing /kb-stats --json → $STATS_FILE"
  if claude -p "/kb-stats --json" > "$STATS_FILE" 2>>"$LOG_FILE"; then
    # Validate the JSON; if claude returned non-JSON, scrap the file.
    if ! python3 -m json.tool "$STATS_FILE" >/dev/null 2>&1; then
      log "WARN: /kb-stats returned non-JSON; removing $STATS_FILE"
      rm -f "$STATS_FILE"
    fi
  else
    log "WARN: /kb-stats failed; skipping snapshot"
  fi
fi

# Run /kb-validate to surface broken links / oversized / collisions.
# Don't fail the weekly job on validate errors — surface in log for human review.
log "running /kb-validate"
if [[ "${DRY_RUN:-0}" != "1" ]]; then
  if ! claude -p "/kb-validate" >>"$LOG_FILE" 2>&1; then
    log "WARN: /kb-validate reported errors (see log above)"
  fi
fi

# Commit the snapshot if anything changed.
if [[ "${DRY_RUN:-0}" != "1" ]] && ! git diff --quiet HEAD -- .kb/stats 2>/dev/null; then
  log "committing weekly stats snapshot"
  git add .kb/stats
  git commit -m "kb: stats weekly ${WEEK_TAG}

Co-Authored-By: Claude <noreply@anthropic.com>" >>"$LOG_FILE" 2>&1
fi
# Also catch the case of a brand-new .kb/stats file (untracked, not in HEAD).
if [[ "${DRY_RUN:-0}" != "1" ]] && [[ -n "$(git ls-files --others --exclude-standard .kb/stats 2>/dev/null)" ]]; then
  log "committing new weekly stats snapshot (untracked)"
  git add .kb/stats
  git commit -m "kb: stats weekly ${WEEK_TAG}

Co-Authored-By: Claude <noreply@anthropic.com>" >>"$LOG_FILE" 2>&1
fi

kb_push

log "=== weekly run complete ==="
