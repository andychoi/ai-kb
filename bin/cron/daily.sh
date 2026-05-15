#!/usr/bin/env bash
# daily.sh — Phase 3 daily cron job.
# Runs /daily to ensure today's daily note exists. Pulls before, pushes after.
# Idempotent — second run on the same day is a no-op (per /daily spec).
#
# Schedule: 00:05 local time (via com.aikb.daily.plist).
# Manual run:        bin/cron/daily.sh
# Dry run (no claude, no push): DRY_RUN=1 bin/cron/daily.sh
JOB_NAME="daily"
# shellcheck source=./_lib.sh
. "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

guard_lock
log "=== daily run starting ==="

kb_pull || exit 1

# Run /daily; it commits its own work (or no-ops if today's note exists).
kb_run claude -p "/daily"

kb_push

log "=== daily run complete ==="
