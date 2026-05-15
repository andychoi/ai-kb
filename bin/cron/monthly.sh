#!/usr/bin/env bash
# monthly.sh — Phase 3 monthly cron job.
# Archives:
#   inbox/*.md          older than 30 days  → inbox/_archive/<YYYY-MM>/
#   work/**/*.md done   older than 90 days  → work/_archive/<YYYY-MM>/
#
# Schedule: 1st of month, 04:00 local time (via com.aikb.monthly.plist).
JOB_NAME="monthly"
# shellcheck source=./_lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

guard_lock
log "=== monthly run starting ==="

kb_pull || exit 1

DRY_FLAG=""
[[ "${DRY_RUN:-0}" == "1" ]] && DRY_FLAG="--dry-run"

log "running kb_archive.py $DRY_FLAG"
python3 "$VAULT_ROOT/bin/cron/kb_archive.py" --vault "$VAULT_ROOT" $DRY_FLAG >>"$LOG_FILE" 2>&1

kb_push

log "=== monthly run complete ==="
