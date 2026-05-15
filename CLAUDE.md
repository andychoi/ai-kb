# ai-kb — Vault Conventions & Operating Rules

This is a Claude-Code-driven Obsidian knowledge base. The source of truth is this git repo. Obsidian is the read/write UI. You (Claude) maintain the contents through the slash commands in `.claude/commands/`.

**Read this entire file before any write operation in the vault.** Every rule below is enforced — `/kb-validate` and the verification suite check most of them.

---

## 1. Folder semantics

| Folder | What lives here | When *you* write here |
|---|---|---|
| `inbox/` | Raw, unclassified drops. Every new note enters here regardless of trigger (manual, file-watch, webhook). | Default destination for *every* new note unless the user explicitly says otherwise via `--folder=`. |
| `notes/` | Personal/research atomic notes. | Only via `/note-refile` (promotion from `inbox/`) or `--folder=notes`. |
| `work/` | Specs, ADRs, runbooks. Has `subtype` frontmatter (`spec`/`adr`/`runbook`) and `status` (`draft`/`active`/`done`). | Only via `/note-refile` or `--folder=work`. |
| `sources/` | Distilled external knowledge (articles, papers, talks). Each note has `url`, `author`, `captured`. | Only via `/note-refile` promoting from `inbox/`. **`/source-capture` writes to `inbox/`, not here** — refile is a separate step. |
| `code/<repo>/` | Code/repo intelligence. Per-repo subfolder; each note has `repo`, `path`, `commit`, `kind`. | Via `/note-refile` from `inbox/`. `/code-doc` writes to `inbox/` first. |
| `refs/{people,tools,concepts}/` | Stable reference notes. Long-lived; rarely change. | Direct write OK once stabilized; otherwise `inbox/` → refile. |
| `daily/` | `YYYY-MM-DD.md` daily notes. | Only via `/daily`. |
| `templates/` | One `.md` per note type. All slash commands that create notes copy from these. | Don't modify without bumping `schema_version` in `.kb/state.json` and updating §3 below. |

**Single ingest contract**: every new note starts in `inbox/` with frontmatter `source: manual|watch|webhook:<name>` and an `idem_key` (ULID). Refile promotes it. This collapses 3 pipelines (manual / watch / webhook) into 1.

---

## 2. Atomic rule

- **One concept per note.** If you find yourself writing two distinct ideas in one note, stop and create two notes that link to each other.
- Target ≤300 lines per note. `/kb-validate` flags oversized; `/note-split` resolves them.
- Notes **link, don't quote**. Use `![[other-note#heading]]` to embed an excerpt rather than copy-pasting prose. The graph is the value — duplication degrades it.

---

## 3. Frontmatter schemas (FROZEN — do not change without bumping `schema_version`)

All notes share these **required** fields:

```yaml
id: 01HKZX1234567890ABCDEFGHJK     # ULID (26 chars, Crockford base32). MUST be unique vault-wide.
type: note|source|work|code|ref|daily
title: "Short, specific title (no trailing period)"
created: 2026-05-15T14:30:00Z      # ISO-8601 UTC, set once at creation
updated: 2026-05-15T14:30:00Z      # ISO-8601 UTC, refresh on every meaningful edit
tags: []                            # flat list, lowercase kebab-case (e.g., [prompt-caching, claude-api])
source: manual                      # one of: manual | watch | webhook:<name>
idem_key: 01HKZX1234567890ABCDEFGHJK   # often equals id; differs for re-ingestion paths
```

**Conditional / per-type fields:**

| Type | Adds | Notes |
|---|---|---|
| `note` | — | Required fields only. |
| `source` | `url`, `author`, `captured`, `status: unread\|read\|distilled` | `captured` is ISO-8601 UTC when fetched. |
| `work` | `project`, `subtype: spec\|adr\|runbook`, `status: draft\|active\|done` | `decision_status: proposed\|accepted\|rejected\|superseded` allowed for ADRs. |
| `code` | `repo`, `path`, `commit`, `kind: function\|class\|module\|flow\|adr` | `commit` is the SHA at time of capture. `kind` drives Dataview facets. |
| `ref` | `category: people\|tools\|concepts` | Mirrors the subfolder. |
| `daily` | `date: YYYY-MM-DD` | Used for Dataview daily queries. |

**Optional everywhere:** `aliases: []` — populated by `/note-rename` to preserve old titles. Never required.

**Do NOT store** `links_in` / `links_out` / `backlinks` in frontmatter. Obsidian and Dataview compute these. Stored backlinks fight `/note-link` and rot fast.

---

## 4. Linking conventions

- **Use Obsidian `[[wiki-links]]` exclusively.** Never use standard markdown links (`[text](path.md)`) for inter-vault references — they don't trigger Obsidian backlink graphs and break under `/note-rename`.
- Link to titles, not paths: `[[Prompt caching basics]]` — Obsidian resolves by title across the vault.
- Heading anchors: `[[Some note#A specific section]]` is valid and supported.
- Aliases: when `/note-rename` is invoked, the *old* title is appended to the renamed note's `aliases:` so existing `[[old name]]` references continue to resolve.
- Transclusion: `![[note]]` or `![[note#heading]]` embeds the content. Use it instead of quoting.

---

## 5. ID generation (ULID)

- **Format**: Crockford base32, 26 chars (e.g., `01HKZX1234567890ABCDEFGHJK`).
- **Why**: sortable (time-ordered prefix), collision-resistant, no clock-skew issues across triggers. Phase 4 webhook idempotency depends on this; do not change.
- **How**: prefer `python -c "import ulid; print(ulid.new())"` if `python-ulid` is available; otherwise the deterministic-enough approximation:
  ```sh
  python3 -c 'import time,secrets,base64; ts=int(time.time()*1000).to_bytes(6,"big"); r=secrets.token_bytes(10); raw=ts+r; \
    a="0123456789ABCDEFGHJKMNPQRSTVWXYZ"; n=int.from_bytes(raw,"big"); s=""; \
    [s:=a[n&31]+s for _ in range(26)] if False else None; \
    out=[]; \
    [out.append(a[(n>>(5*i))&31]) for i in range(26)]; \
    print("".join(reversed(out)))'
  ```
  Slash commands may also use `uuidgen | tr -d - | tr a-f A-F | cut -c1-26` as a last-resort fallback; document the choice in commit message.

---

## 6. Commit message grammar (data, not prose)

```
kb: <verb> <scope> [<idem_key>]
```

- **`<verb>`** ∈ {`add`, `refile`, `rename`, `split`, `link`, `update`, `archive`, `validate`, `daily`, `stats`, `init`}
- **`<scope>`**: short noun phrase identifying what was touched (`inbox/foo`, `code/ai-kb`, `daily/2026-05-15`).
- **`<idem_key>`**: optional trailing ULID, in square brackets, when the change corresponds to an idempotent ingest. Lets `git log --grep=<key>` detect prior delivery even if `.kb/state.json` is wiped.

Examples:

```
kb: add inbox/202605151430-claude-headless-mode
kb: refile inbox/foo → code/ai-kb/foo [01HKZX1234567890ABCDEFGHJK]
kb: rename code/old-name → code/new-name
kb: daily daily/2026-05-15
kb: validate (12 notes, 0 errors)
```

If Claude authored the commit, add:
```
Co-Authored-By: Claude <noreply@anthropic.com>
```

---

## 7. Bot identity for automation

- **Interactive commits** (you running a slash command on behalf of the user during a chat session): use the user's git identity. Add the `Co-Authored-By: Claude` trailer.
- **Automated commits** (Phase 2 file-watch daemon, Phase 3 cron jobs, Phase 4 webhook receiver — none of which exist yet): use `kb-bot <kb-bot@local>` configured in `.kb/gitconfig` and applied via `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL` env. Still add the `Co-Authored-By: Claude` trailer.

This split lets `git log --author=kb-bot` show *only* automation activity.

---

## 8. Headless-invocability (HARD RULE)

Every slash command in `.claude/commands/` MUST be runnable via `claude -p "/cmd <args>"` with no interactive prompts. This means:

- All required args are positional or flagged. Missing required args → **exit non-zero with a one-line error**, never prompt.
- Optional args have sensible defaults documented in the command's frontmatter.
- Commands do not depend on conversational context (chat history, prior tool results, "the file we were just looking at").
- Commands that mutate state must commit their changes — they do not assume a follow-up `git commit` step.

Phase 2's file-watch daemon literally shells out to `claude -p` to drive refile. If a command violates this rule, it breaks the daemon.

---

## 9. Vault traversal — skip these directories

When walking the vault (`/kb-validate`, `/kb-stats`, `/note-link` candidate search), skip:

```
.git, .obsidian, .claude, .kb, .trash, templates, node_modules, __pycache__
```

`templates/` is skipped because its frontmatter is *example* frontmatter, not vault content. Including it triggers false ID-collision warnings.

---

## 10. Conflict & error handling

- If a write would create a duplicate `id`, regenerate (don't overwrite). Log to commit message.
- If `/note-rename` would create a target path that already exists, fail with non-zero exit — don't silently merge.
- If `.kb/state.json` is missing, treat it as `{"schema_version": 1, "processed": {}, "idempotency": {}}` and create it on first write.
- Before any automated commit, run `git pull --rebase` (Phase 2+). If conflicts, bail and surface — don't auto-resolve.
- `/kb-validate` is the gate: if it reports errors, fix them before committing (when interactive) or surface them (when automated).

---

## 11. What you should NOT do

- Don't store backlinks in frontmatter (§3).
- Don't use markdown links for inter-vault references (§4).
- Don't write directly to `notes/` / `work/` / `sources/` / `code/` unless the user explicitly says `--folder=`. Use `inbox/` + refile (§1).
- Don't bump `schema_version` casually — it forces a migration of every note.
- Don't ask the user for clarification mid-command. Commands are non-interactive (§8). If args are insufficient, exit with a clear error.
- Don't introduce new note types without updating this file *and* `templates/`.
- Don't run destructive git operations (`reset --hard`, `push --force`, `branch -D`) from inside slash commands. Ever.
