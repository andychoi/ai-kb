---
description: Lint the vault — frontmatter schema, ID uniqueness, dangling [[wiki-links]], oversized notes. Read-only by default; --fix attempts safe repairs.
argument-hint: [--fix]
allowed-tools: Read, Bash, Glob, Grep, Edit
---

# /kb-validate — Vault linter

The **safety net**. Run before commits, before pushes, after bulk operations. Pre-commit hook target. Non-zero exit on any error.

## Arguments

- `--fix` (optional flag) — attempt safe auto-repairs:
  - Add missing `updated:` (set to file mtime).
  - Add empty `tags: []` if missing.
  - Add `aliases: []` if missing.
  - Normalize ISO-8601 timestamps to canonical UTC form.
  - **Never** auto-fix: ID collisions, broken `[[links]]`, oversized notes, missing required per-type fields. Those need human/AI judgment via `/note-rename`, `/note-split`, etc.

Without `--fix`, the command is read-only.

## Behavior

1. **Walk the vault.** Glob all `.md` files. Skip:
   ```
   .git, .obsidian, .claude, .kb, .trash, templates, node_modules, __pycache__
   ```
   (Note: `templates/` is skipped — its frontmatter contains `__ULID__` placeholders that would otherwise trigger false errors.)

2. **For each note, check:**

   **a. Frontmatter parses as YAML.** If not → `ERROR: <path>: frontmatter parse error: <detail>`.

   **b. Required common fields present:** `id`, `type`, `title`, `created`, `updated`, `tags`, `source`, `idem_key`. Each missing → `ERROR: <path>: missing required field "<field>"`.

   **c. `id` and `idem_key` are valid ULIDs** (26 chars, Crockford alphabet `0-9A-Z` excluding `ILOU`). Invalid → `ERROR: <path>: <field> is not a valid ULID: "<value>"`.

   **d. `type` is one of**: `note|source|work|code|ref|daily`. Otherwise → ERROR.

   **e. Per-type required fields** (per `CLAUDE.md` §3):
   - `source`: `url`, `author`, `captured`, `status`.
   - `work`: `project`, `subtype`, `status`.
   - `code`: `repo`, `path`, `kind`.
   - `ref`: `category`.
   - `daily`: `date`.

   **f. ISO-8601 timestamps** for `created`, `updated`, `captured` (where applicable). Reject non-UTC, non-`Z` forms.

3. **Cross-note checks:**

   **a. ID uniqueness.** Build a map `id -> [paths]`. Any id with >1 path → `ERROR: id collision: <id> in [<path1>, <path2>]`.

   **b. Dangling `[[wiki-links]]`.** For each `[[X]]` or `[[X|...]]` or `[[X#...]]` or `![[X...]]` reference:
   - Resolve `X` against vault titles (frontmatter `title:` field) AND against `aliases:` lists.
   - If unresolvable → `ERROR: <path>: dangling wiki-link to "<X>"`.
   - Skip references in code fences (```...```).

   **c. Oversized notes.** Any `.md` >300 lines → `WARN: <path>: <N> lines (>300; consider /note-split)`.

   **d. Orphan notes.** Notes with zero incoming `[[links]]` AND not in `daily/` / `inbox/` / `templates/` / `refs/` → `INFO: <path>: orphan (no incoming links)`. Informational only; doesn't fail the run.

4. **Apply `--fix`** if flag was set, for the safe-repair list above. Re-run check (c)/(d) on fixed files. Commit fixes as ONE commit:
   ```
   kb: validate (auto-fix N file(s))
   
   Co-Authored-By: Claude <noreply@anthropic.com>
   ```

5. **Output:**
   - All ERROR lines to stderr.
   - All WARN / INFO lines to stdout.
   - Summary on stdout:
     ```
     scanned: <N> note(s)
     errors: <E>
     warnings: <W>
     orphans: <O>
     ```

6. **Exit code:**
   - `0` if `errors == 0` (warnings + orphans do not fail the run).
   - `1` if any error.

## Headless contract

- Non-interactive.
- Read-only without `--fix`.
- Safe to run from a pre-commit hook (fast: simple regex + YAML parse over the vault).
- Used by Phase 3 weekly cron as the input to `/kb-stats`.

## Reuse note

Walker logic can adapt `gitweb/gitweb_backend/app.py:_walk_md_files_local` (`SEARCH_SKIP_DIRS`). Heading slugifier `_slugify_heading` is reusable when validating `[[X#heading]]` anchors.
