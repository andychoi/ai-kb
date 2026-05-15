---
description: Create a new atomic note in inbox/ (or a specified folder) with filled frontmatter.
argument-hint: <topic> [--type=note|source|work|code|ref] [--folder=<path>] [--tags=<csv>]
allowed-tools: Read, Write, Bash, Glob
---

# /note-add — Create an atomic note

You are creating a single atomic markdown note in the ai-kb vault. Read `CLAUDE.md` if you have not already (especially §1, §2, §3, §5, §6, §8).

## Arguments

- **`<topic>`** (required) — the title / subject of the note. Quoted if it contains spaces.
- `--type=<note|source|work|code|ref>` (default: `note`) — selects the template and frontmatter.
- `--folder=<path>` (default: `inbox`) — vault-relative folder. If omitted, the note goes to `inbox/`.
- `--tags=<csv>` (default: empty) — comma-separated frontmatter tags (lowercase kebab-case).

## Behavior

1. **Argument parsing.**
   - If `<topic>` is missing, write `error: /note-add requires a <topic> argument` to stderr and exit non-zero. **Do not prompt.**
   - If `--type` is given an invalid value, error similarly.
   - If `--folder` is given but the folder is not one of `inbox`, `notes`, `work`, `sources`, `code/<repo>`, `refs/{people,tools,concepts}`, error.

2. **Generate ULID.** Use the snippet in `CLAUDE.md` §5 (prefer `python3 -c "import ulid; print(ulid.new())"`; fall back to the inline base32 generator). Capture the value as `<ID>`.

3. **Compute filename.** Slugify `<topic>` (lowercase, ASCII, hyphenate spaces, strip punctuation). Filename: `<YYYYMMDDHHMMSS>-<slug>.md`. UTC timestamp.

4. **Pick template.** Read `templates/<type>.md` (where `<type>` matches the `--type` flag; default `note`).

5. **Fill placeholders.** Replace:
   - `__ULID__` → `<ID>` (used for both `id` and `idem_key`)
   - `__TITLE__` → `<topic>`
   - `__ISO8601__` → current UTC timestamp in `YYYY-MM-DDTHH:MM:SSZ` format
   - `__DATE__` → `YYYY-MM-DD` (for daily template only)
   - `__URL__`, `__AUTHOR__`, `__REPO__`, `__PATH__`, `__SHA__` → leave blank (user fills) unless flags later provide them
   - Apply `--tags` to the `tags:` frontmatter line if provided

6. **Write file.** Path: `<folder>/<filename>`. If file already exists, regenerate ULID + filename (retry up to 3 times) — never overwrite.

7. **Commit.** Run:
   ```sh
   git add <path>
   git commit -m "kb: add <folder>/<slug> [<ID>]" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
   ```

8. **Output.** Print the created path on stdout (one line, no other output). Exit 0.

## Errors → non-zero exit, one line to stderr

- Missing/invalid args.
- Template file not found.
- Filename collision after 3 retries.
- Git commit failed.

## Headless contract

This command is invoked by Phase 2 daemons via `claude -p "/note-add ..."`. It must never:
- Ask for clarification.
- Prompt for confirmation.
- Print anything other than the path on stdout (errors go to stderr).
