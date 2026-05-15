---
description: Create or append today's daily/YYYY-MM-DD.md from the template. Idempotent across same-day runs.
argument-hint: [--date=YYYY-MM-DD]
allowed-tools: Read, Write, Edit, Bash, Glob
---

# /daily — Daily note

Creates `daily/YYYY-MM-DD.md` if it doesn't exist; otherwise opens it for append (no destructive overwrite). Pulls forward unresolved "threads to pull" from the previous day.

## Arguments

- `--date=YYYY-MM-DD` (default: today UTC) — override the date. Used by `/note-rename` retroactively or by Phase 3 cron testing.

## Behavior

1. **Resolve date.** UTC today, or `--date` value. Format: `YYYY-MM-DD`.

2. **Compute paths.**
   - Today: `daily/<date>.md`
   - Yesterday: `daily/<date-minus-1>.md` (skip if it doesn't exist)

3. **If today's file exists**: this is a re-run.
   - Print `daily/<date>.md already exists; no-op` to stdout.
   - Exit 0 (idempotent — no commit).

4. **If today's file does NOT exist**:
   - Read `templates/daily.md`.
   - Generate ULID.
   - Fill placeholders:
     - `__ULID__` → ULID (id + idem_key)
     - `__TITLE__` → `<date>`
     - `__ISO8601__` → current UTC timestamp
     - `__DATE__` → `<date>` (used in `date:` field and the Dataview block)
     - `__YESTERDAY__` → previous date as a wiki-link target (e.g., `2026-05-14`); if yesterday's file doesn't exist, replace the `[[__YESTERDAY__]]` line with `_(no previous daily note)_`.
   - If yesterday's daily exists, extract its `## Threads to pull tomorrow` section. Copy items to today's `## What I worked on` placeholders (commented or as a `### Carried forward` subsection).
   - Write `daily/<date>.md`.

5. **Commit:**
   ```
   kb: daily daily/<date>
   
   Co-Authored-By: Claude <noreply@anthropic.com>
   ```

6. **Output (stdout):** the created path. Exit 0.

## Errors → non-zero exit

- `templates/daily.md` not found.
- `--date` malformed (must match `YYYY-MM-DD`).
- Git commit failed.

## Headless contract

- Non-interactive.
- **Idempotent**: running twice in the same day produces no second commit.
- Phase 3 cron will invoke this nightly at 00:05 UTC (or per timezone).
