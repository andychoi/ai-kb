---
description: Generate atomic code-intelligence notes from a repository into inbox/. Refile promotes them to code/<repo>/.
argument-hint: <repo-path> [--scope=<glob>] [--kind=<function|class|module|flow|adr>]
allowed-tools: Read, Write, Bash, Glob, Grep
---

# /code-doc — Generate code-intelligence notes

Walks a target repository, identifies code units (functions, classes, modules), and emits one atomic note per unit into `inbox/` with `type: code`. `/note-refile` then promotes them to `code/<repo>/`.

## Arguments

- **`<repo-path>`** (required) — absolute or vault-relative path to the repository to document. Must be a directory.
- `--scope=<glob>` (default: discover top-level source folders) — glob pattern relative to `<repo-path>` (e.g., `src/**/*.ts`, `pkg/**/*.go`). Limits which files are documented.
- `--kind=<function|class|module|flow|adr>` (default: auto-detect per unit) — forces all generated notes to one `kind` if specified.

## Behavior

1. **Validate args.** `<repo-path>` must exist as a directory. Resolve to absolute. If a `.git` subfolder exists, capture HEAD SHA via `git -C <repo-path> rev-parse HEAD` for the `commit:` frontmatter field; else leave empty.

2. **Repo name.** Derive from `basename <repo-path>`. This becomes the `repo:` frontmatter value.

3. **Discover files** matching `--scope` (or sensible defaults: `src/`, `pkg/`, `lib/`, `internal/`, `app/`). Skip vendored / generated paths (`node_modules`, `vendor`, `dist`, `build`, `__pycache__`).

4. **For each file, identify code units.** Use a lightweight per-language strategy (don't write a real parser — read the file, extract structure):
   - Python: top-level `def` / `class` definitions.
   - JS/TS: top-level `export function`, `export class`, `export const = (...) =>`.
   - Go: top-level `func`, `type`.
   - Module-level: if file is short (<100 lines) or contains primarily wiring, emit ONE `kind: module` note for the whole file instead of per-function.
   - If a unit's body is >300 lines, emit `kind: flow` and document its high-level steps rather than line-by-line.

5. **For each unit, generate a note.** Use `templates/code.md` as the schema:
   - Generate fresh ULID per note (id + idem_key, where idem_key = hash(repo+path+unit_name) is preferable for re-runs being dedup-able — implement via SHA-256 hex truncated to 26 chars Crockford-encoded, OR simply use the same ULID and document the limitation).
   - Filename: `<YYYYMMDDHHMMSS>-<repo>-<unit-slug>.md`.
   - Frontmatter: `type: code`, `repo: <repo-name>`, `path: <relative-to-repo-path>`, `commit: <SHA-or-empty>`, `kind: <detected-or-flag>`.
   - Body: brief Purpose, Interface (signature), Behavior (non-obvious bits), Dependencies. Do NOT paste the full source — link via the `path:` frontmatter.
   - Tags: include `code`, the language (`python`, `typescript`, etc.), and the repo name.

6. **Write all notes to `inbox/`.** Skip a unit if `idempotency[<idem_key>]` already exists in `.kb/state.json` (dedup re-runs).

7. **Commit all notes in ONE commit:**
   ```
   kb: add inbox/code-<repo> (<N> notes)
   
   Source: <repo-path> @ <SHA-or-HEAD>
   Scope: <scope-glob>
   
   Co-Authored-By: Claude <noreply@anthropic.com>
   ```

8. **Output (stdout):**
   ```
   captured <N> code unit(s) from <repo-path>
     <inbox/note-1>
     <inbox/note-2>
     ...
   ```

## Errors → non-zero exit

- `<repo-path>` doesn't exist or isn't a directory.
- `--scope` matches zero files (with stderr `code-doc: no files match scope`).
- All units already in `idempotency{}` → exit 0 with stdout `no new units; <N> previously captured`.

## Headless contract

- Non-interactive.
- This command can produce large batches; consider running `/kb-validate` after (the verify script does this).
- Phase 3 cron may invoke this on watched repos; idempotency from `idem_key` keeps re-runs cheap.
- Per `CLAUDE.md` §1, output lands in `inbox/`. Promotion to `code/<repo>/` is `/note-refile`'s job.
