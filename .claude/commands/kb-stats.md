---
description: One-page vault health report — counts by type, orphans, broken links, oversized notes. Read-only.
argument-hint: [--json]
allowed-tools: Read, Bash, Glob, Grep
---

# /kb-stats — Vault health snapshot

A cheap, read-only report. In Phase 3, the weekly cron job is essentially `/kb-stats --json` → commit the snapshot to `daily/_stats/<week>.md`.

## Arguments

- `--json` (optional flag) — emit a single JSON object on stdout instead of the human-readable report. Useful for piping into other tools or storing in commits.

## Behavior

1. **Walk the vault** with the same skip-set as `/kb-validate` (§Vault traversal in `CLAUDE.md` §9).

2. **Collect counts:**
   - Total notes.
   - Notes by `type` (note / source / work / code / ref / daily).
   - For `work`: counts by `status` (draft / active / done) and `subtype` (spec / adr / runbook).
   - For `source`: counts by `status` (unread / read / distilled).
   - For `code`: counts by `repo` and by `kind`.

3. **Compute health metrics** (lightweight; reuse `/kb-validate` logic without `--fix`):
   - **Orphans** — notes with zero incoming `[[wiki-links]]`. Exclude `daily/`, `inbox/`, `templates/`, `refs/`.
   - **Broken links** — count of dangling `[[wiki-links]]`.
   - **Oversized** — count of notes >300 lines (list the top 5 paths).
   - **ID collisions** — should be 0; if non-zero, surface prominently.
   - **Inbox depth** — count of `.md` files in `inbox/` (lower is better; high means refile is overdue).

4. **Activity (last 7 days)** — using git log:
   ```sh
   git log --since="7 days ago" --pretty=format:"%h %s" -- '*.md' | wc -l
   git log --since="7 days ago" --pretty=format:"%h" -- '*.md' | head -20
   ```
   Count of commits, sample of recent subjects.

5. **Output (human-readable, default):**
   ```
   ai-kb stats — <ISO timestamp>
   ──────────────────────────────────────────
   Total notes:    <N>
     note:    <n>
     source:  <n>  (unread <u>, read <r>, distilled <d>)
     work:    <n>  (draft <d>, active <a>, done <D>)
     code:    <n>  across <R> repo(s)
     ref:     <n>
     daily:   <n>

   Health
     inbox depth:    <n>   (>5 ⇒ run /note-refile)
     broken links:   <n>   (>0 ⇒ run /kb-validate)
     oversized:      <n>   (>0 ⇒ /note-split candidates)
     orphans:        <n>
     ID collisions:  <n>   (>0 is a bug)

   Activity (last 7d)
     commits:        <n>
     recent: <sha> <subject>
             ...
   ```

6. **Output (`--json`):**
   ```json
   {
     "generated_at": "<ISO>",
     "total": <N>,
     "by_type": { "note": <n>, "source": <n>, ... },
     "by_status": { "work": {...}, "source": {...} },
     "by_repo": { "<repo>": <n>, ... },
     "by_kind": { "function": <n>, ... },
     "health": {
       "inbox_depth": <n>,
       "broken_links": <n>,
       "oversized": <n>,
       "oversized_top": ["<path1>", ...],
       "orphans": <n>,
       "id_collisions": <n>
     },
     "activity_7d": {
       "commits": <n>,
       "recent": [{"sha": "...", "subject": "..."}, ...]
     }
   }
   ```

7. **Exit code:** always 0 unless the command itself crashed. Stats reporting does not fail on unhealthy vaults (that's `/kb-validate`'s job).

## Headless contract

- Read-only.
- Fast: should complete in seconds on vaults <10k notes.
- `--json` output is suitable for piping into commit bodies (Phase 3 weekly snapshot).
