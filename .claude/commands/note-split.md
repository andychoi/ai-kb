---
description: Split an oversized note into atomic pieces with bidirectional [[wiki-links]] between the parent summary and the splits.
argument-hint: <path> [--target-lines=<n>]
allowed-tools: Read, Edit, Write, Bash, Glob, Grep
---

# /note-split — Split oversized note

Splits a note >300 lines (or `--target-lines`) into atomic pieces. The original note is rewritten as a summary that `[[links]]` to each split. Each split is a new file in the same folder, with its own ULID and frontmatter.

## Arguments

- **`<path>`** (required) — vault-relative path to the note to split.
- `--target-lines=<n>` (default: `200`) — soft target for each resulting note. Splits may exceed slightly to keep semantic boundaries (headings) intact.

## Behavior

1. **Validate args.** `<path>` exists, is `.md`, in vault. Otherwise non-zero exit.

2. **Read the note** and parse:
   - Frontmatter block.
   - Body, segmented by H2 (`##`) headings (these are the natural split boundaries). If no H2 headings, fall back to H3, then to paragraph-count chunking.
   - Preserve fenced code blocks (```...```) and YAML frontmatter as atomic segments — never split across these boundaries. (Adapt the segmentation logic from `gitweb/frontend/src/lib/translate.ts:68-130`; port to Python equivalent.)

3. **Decide split boundaries.** Group segments into chunks of ≤`--target-lines`. Each chunk should be coherent (one or more whole H2 sections).

4. **For each chunk** (except the first, which stays in the original):
   - Generate a new ULID.
   - Derive a new title from the chunk's first heading (or "Split N of <original title>" if no heading).
   - Derive a new filename: `<YYYYMMDDHHMMSS>-<slug>.md` (UTC).
   - Construct a new file with:
     - Frontmatter copied from the original, with: new `id`, new `idem_key` (same as id), new `title`, `created` = now, `updated` = now, `source: manual`, `aliases: []`.
     - Body = the chunk's content.
     - Append a "Parent" footer: `\n\n## Parent\n\n- [[<original-base>]]`
   - Write the file to the same folder as the original.

5. **Rewrite the original note** as a summary:
   - Keep its frontmatter (update `updated` to now).
   - Replace its body with:
     - First chunk's content (intact).
     - A new `## Splits` section listing `[[wiki-links]]` to each new split note.
   - Save.

6. **Commit.** One commit covering original + all splits:
   ```
   kb: split <path> into <N> notes
   
   Original retained as summary; <N> atomic notes created in <folder>/.
   
   Co-Authored-By: Claude <noreply@anthropic.com>
   ```

7. **Output (stdout):**
   ```
   split: <path> → <N> new note(s)
     <new-path-1>
     <new-path-2>
     ...
   parent updated: <path>
   ```

## Errors → non-zero exit

- Missing args, invalid path.
- Note is already ≤target-lines (with stderr: `note already atomic; nothing to split`). Exit 0 in this case actually — running on an already-small note is a benign no-op.
- Cannot find any reasonable split boundaries (single huge code block, etc.) — exit non-zero with `cannot find split boundary`.

## Headless contract

- Non-interactive.
- Splits must produce semantically valid markdown (don't break fenced code, don't orphan list items).
- If splits would result in tiny stubs (<20 lines), merge with adjacent chunk.
