---
description: Alias-preserving rename. Moves the file, rewrites all [[wiki-links]] across the vault, appends the old name to the note's aliases.
argument-hint: <old-path> <new-path>
allowed-tools: Read, Edit, Write, Bash, Glob, Grep
---

# /note-rename — Alias-preserving rename

This is the **silent-corruption guard**. Without it, AI-driven refile that renames a note silently breaks every `[[wiki-link]]` to it. Read `CLAUDE.md` §4 (linking) before proceeding.

## Arguments

- **`<old-path>`** (required) — vault-relative current path of the note.
- **`<new-path>`** (required) — vault-relative destination path.

Both paths must end in `.md`. Both must be inside the vault (path-traversal guard: resolve to absolute, verify under vault root).

## Behavior

1. **Validate args.**
   - Both paths required → exit non-zero with clear stderr message.
   - `<old-path>` must exist and be a regular file.
   - `<new-path>` must NOT exist (refuse to merge / overwrite).
   - Both must be `.md` and inside the vault root.

2. **Extract old and new base names** (filename without extension or path):
   - `<old-base>` = basename of `<old-path>` minus `.md`.
   - `<new-base>` = basename of `<new-path>` minus `.md`.
   - Also compute `<old-title>` = the `title:` from the note's frontmatter (may differ from base name).

3. **Read and update the note's frontmatter.**
   - Set `updated` to now (ISO-8601 UTC).
   - Append `<old-base>` and `<old-title>` (if different) to `aliases: []` — preserve existing aliases, dedupe.
   - If `<new-path>` implies a different folder than `<old-path>`, update `type:` if the folder mapping requires it (per refile rules in `note-refile.md`). When in doubt, leave `type:` alone.

4. **Move the file** with `git mv <old-path> <new-path>` to preserve history.

5. **Scan the entire vault for incoming links** to rewrite:
   - Walk all `.md` files using `Glob` (skip `.git`, `.obsidian`, `.claude`, `.kb`, `.trash`, `templates`, `node_modules`, `__pycache__`).
   - In each file, search for these link forms:
     - `[[<old-base>]]` → `[[<new-base>]]`
     - `[[<old-base>|<display>]]` → `[[<new-base>|<display>]]` (preserve display text)
     - `[[<old-base>#<heading>]]` → `[[<new-base>#<heading>]]` (preserve heading anchor)
     - `[[<old-base>#<heading>|<display>]]` → likewise
     - `![[<old-base>...]]` (transclusions) → likewise with leading `!`
     - Also handle `[[<old-title>]]` forms if `<old-title>` differs from `<old-base>` — Obsidian resolves by title.
   - Use `Edit` for each file you modify. Skip files you don't need to change.

6. **Commit.** One commit covering the rename + all link rewrites:
   ```
   kb: rename <old-path> → <new-path>
   
   Updated N incoming wiki-link(s) across M file(s).
   Added "<old-base>" to aliases.
   
   Co-Authored-By: Claude <noreply@anthropic.com>
   ```

7. **Output (stdout):**
   ```
   renamed: <old-path> → <new-path>
   links rewritten: <N> in <M> files
   alias added: <old-base>
   ```
   Exit 0.

## Errors → non-zero exit

- Missing args, invalid paths, destination exists, path-traversal attempt, frontmatter corruption, git mv failure.

## Headless contract

- Non-interactive. No confirmation prompts even for large rewrites.
- Idempotent: running again with the same args after success errors (destination exists) — that's correct behavior.
- Run `/kb-validate` mentally after — but do NOT shell out to it. The verify script does that separately.
