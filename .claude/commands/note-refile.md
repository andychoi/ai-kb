---
description: Sweep inbox/ (or given paths), classify each note by type, move to the correct folder, fill missing frontmatter, commit.
argument-hint: [path...]
allowed-tools: Read, Edit, Write, Bash, Glob, Grep
---

# /note-refile — Central refile primitive

This is the **central refile primitive**. Phase 2's file-watch daemon will literally `claude -p "/note-refile <files>"`. Phase 4 webhooks rely on this command's classification logic. Read `CLAUDE.md` (especially §1, §3, §5, §6) before proceeding.

## Arguments

- **`[path...]`** (optional) — one or more vault-relative paths to refile. If empty, refile **every `.md` file in `inbox/`** (top level; recurse one level if needed).

## Behavior

1. **Resolve target list.** If no paths given, `Glob inbox/*.md`. Skip dotfiles and any non-`.md`.

2. **For each note, parse frontmatter.** Use the YAML block at the top (delimited by `---`). If missing, create one with defaults (will be fully populated below).

3. **Classify each note** to determine destination folder:
   - If `type: source` OR frontmatter contains `url:` → **`sources/`**
   - If `type: work` OR title/body mentions ADR/spec/runbook → **`work/`**
   - If `type: code` OR frontmatter contains `repo:` → **`code/<repo>/`** (create subfolder if needed; if `repo:` absent, fall back to `code/misc/`)
   - If `type: ref` OR frontmatter contains `category: people|tools|concepts` → **`refs/<category>/`**
   - If `type: daily` OR frontmatter contains `date: YYYY-MM-DD` → **`daily/`**
   - Otherwise → **`notes/`**
   
   If the note is *already* in its target folder, **leave it in place** but still fix frontmatter (idempotent).

4. **Fill / repair frontmatter** per `CLAUDE.md` §3:
   - Ensure `id` is a valid ULID; regenerate if missing/invalid (preserve `idem_key` if present, else set equal to `id`).
   - Ensure `type` matches the destination folder.
   - Ensure `title` is set (derive from first `# heading` or filename if absent).
   - Ensure `created` and `updated` are ISO-8601 UTC. Set `updated` to now.
   - Ensure `tags: []` exists (don't invent tags — leave empty if unknown).
   - Ensure `source` is set (default `manual` if missing).
   - For per-type required fields: if a `source` note has no `url:`, leave empty (don't fail). For `code`, fill `repo`/`path`/`kind` if derivable from the note body, else leave empty.

5. **Move the file.** Use `git mv <old> <new>` (preserves git history). New filename keeps the existing slug; if filename is just a ULID, append slugified title.

6. **Rewrite incoming `[[wiki-links]]`** if the filename (not just the path) changed. Use `/note-rename`'s scan logic: grep the vault for `[[<old-base>]]` and rewrite. Append old base to the moved note's `aliases:` frontmatter.

7. **Commit each refile as one commit.** Message:
   ```
   kb: refile inbox/<old> → <new-folder>/<file> [<idem_key>]
   
   Co-Authored-By: Claude <noreply@anthropic.com>
   ```
   Batch multiple refiles into one commit only if processing >5 files in a single sweep.

8. **Update `.kb/state.json`** (read → modify → write):
   - Set `processed[<new-path>] = { "sha": "<frontmatter-id>", "ts": "<now>", "source": "<frontmatter-source>" }`.
   - If `idem_key` differs from `id`, set `idempotency[<idem_key>] = <id>`.

9. **Output.** One line per refiled note: `<old-path> → <new-path>`. Exit 0 on success.

## Errors → non-zero exit

- A target path doesn't exist or isn't a `.md` file.
- Frontmatter is corrupt and cannot be parsed/repaired.
- `git mv` fails (e.g., destination exists as a different file).
- `.kb/state.json` cannot be read/written.

## Headless contract

This command is the load-bearing automation entrypoint. It must:
- Never prompt or ask for confirmation.
- Be idempotent: running twice on the same already-refiled note is a no-op (frontmatter `updated` may bump; no other change).
- Exit deterministically: non-zero only on real errors, never on "nothing to refile" (that's exit 0 with no output).
