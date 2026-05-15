---
description: Fetch a URL, distill its content into a source note in inbox/. Refile is a separate step.
argument-hint: <url> [--max-len=<chars>]
allowed-tools: Read, Write, Bash, WebFetch, Glob
---

# /source-capture — Distill external URL → inbox/

Captures an external URL as a `type: source` note in `inbox/`. Refile to `sources/` happens in a separate `/note-refile` step (per the single-ingest contract in `CLAUDE.md` §1).

## Arguments

- **`<url>`** (required) — HTTP/HTTPS URL to fetch.
- `--max-len=<chars>` (default: `8000`) — soft cap on the distilled body length. The note may exceed if the content is dense; `/note-split` can resolve later.

## Behavior

1. **Validate args.** `<url>` must start with `http://` or `https://`. Otherwise non-zero exit with stderr.

2. **Fetch with WebFetch.** Pass a distillation prompt:
   > "Extract the title, author (if shown), and a faithful distillation of the main content. Return as JSON: `{title, author, body_markdown, captured_iso}`. The body should be 3–7 atomic points (markdown bullets) plus any direct quotes worth preserving. Do not invent content. If the page is a paywall, error page, or single-page JS app you cannot read, return `{error: '<reason>'}` instead."

3. **Handle WebFetch result.**
   - If WebFetch returned an `error` field or empty body, write a warning to stderr (`source-capture: distillation failed: <reason>`) and exit non-zero. Do NOT create the note.
   - Otherwise proceed.

4. **Generate ULID** per `CLAUDE.md` §5. Use it for `id` AND `idem_key` (manual capture: idem == id).

5. **Compute filename.** Slugify the fetched title (lowercase, hyphenate, strip punctuation). Filename: `<YYYYMMDDHHMMSS>-<slug>.md`.

6. **Build the note from `templates/source.md`.** Fill:
   - `__ULID__` → ULID (id + idem_key)
   - `__TITLE__` → fetched title
   - `__ISO8601__` → now (UTC) for `created`/`updated`
   - `__URL__` → `<url>`
   - `__AUTHOR__` → fetched author (or empty string if unknown)
   - `__ISO8601__` for `captured` → now (UTC)
   - Body section (under `## Distillation`) → the distilled markdown bullets
   - Quotes section → any extracted direct quotes (else remove the section)

7. **Write to `inbox/<filename>`.** Never overwrite an existing file — if collision, regenerate ULID + filename (retry up to 3 times).

8. **Update `.kb/state.json`:**
   - Set `idempotency[<idem_key>] = <id>` so a future re-capture of the same URL (if the daemon produces the same idem_key from URL hashing) is dedup-able.
   - Set `processed[inbox/<filename>] = {sha: <id>, ts: <now>, source: "manual"}`.

9. **Commit.**
   ```
   kb: add inbox/<slug> [<idem_key>]
   
   Captured: <url>
   
   Co-Authored-By: Claude <noreply@anthropic.com>
   ```

10. **Output (stdout):** the created path. Exit 0.

## Errors → non-zero exit

- Missing/invalid URL.
- WebFetch failed or returned an error.
- File collision after 3 retries.
- Git commit failed.

## Headless contract

- Non-interactive.
- The distillation prompt and the JSON output schema are **frozen in Phase 1** because Phase 4's RSS handler will reuse them. Do not vary them across invocations.
- Idempotency from re-captures of the same URL is not enforced here (URL hashing → idem_key is a Phase 4 concern); for now, manual re-captures will produce new notes.

## Reuse note

`templates/source.md` is the source of truth for the schema. Do not inline alternative formats.
