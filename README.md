# ai-kb

A knowledge base whose **source of truth is this git repo**, whose **read/write UI is Obsidian**, and whose **content is maintained by Claude Code** — on demand now, and via background automation in later phases.

Notes are small, atomic markdown files (one concept per file) so Claude can edit safely without churning whole documents. The vault unifies four content domains in a single tree: personal/research notes, work docs, curated external knowledge, and code/repo intelligence.

---

## Table of Contents

1. [How the system works](#how-the-system-works)
2. [Prerequisites](#prerequisites)
3. [Install & first-time setup](#install--first-time-setup)
4. [Layout](#layout)
5. [The single-ingest rule](#the-single-ingest-rule)
6. [Daily workflow](#daily-workflow)
7. [Command reference](#command-reference)
8. [Worked examples](#worked-examples)
9. [Obsidian setup](#obsidian-setup)
10. [Headless / scripting use](#headless--scripting-use)
11. [Maintenance & validation](#maintenance--validation)
12. [Troubleshooting](#troubleshooting)
13. [Phase 2 — File-watch daemon](#phase-2--file-watch-daemon)
14. [Phase 3 — Cron jobs](#phase-3--cron-jobs)
15. [Phase 4 — Webhook receiver](#phase-4--webhook-receiver)
16. [Roadmap](#roadmap)
17. [Conventions you must follow](#conventions-you-must-follow)

---

## How the system works

Three components, each doing one thing well:

- **Obsidian** reads and writes plain markdown files on your filesystem. Wiki-links, Dataview queries, backlinks, the graph view — all standard Obsidian behavior over a normal folder.
- **Git** versions the vault. Every change is a commit. Self-hosted Gitea or GitLab gives you backup + a deploy target for later automation phases.
- **Claude Code** mutates the vault through slash commands defined in `.claude/commands/`. Each command is a markdown file describing a prompt + tool whitelist; Claude follows it and writes/edits/commits on your behalf. The same commands are runnable from chat (`/note-add ...`) *and* from the shell (`claude -p "/note-add ..."`) — that latter form is how later phases (file-watch, cron, webhooks) drive the vault headlessly.

Everything is files. There is no daemon, no database, no server in Phase 1. If you delete `.claude/` and `.kb/`, you still have a perfectly usable Obsidian vault.

---

## Prerequisites

| Tool | Why | How to check |
|---|---|---|
| [Obsidian](https://obsidian.md) (desktop, free) | Read/write UI for the vault | `Obsidian.app` on macOS, `obsidian` in `/usr/bin` |
| [Claude Code CLI](https://claude.ai/code) | Runs the slash commands | `claude --version` |
| Git (any recent) | Versioning + remote | `git --version` |
| Python 3.10+ | Used by a few helper snippets (ULID generation, frontmatter parsing) | `python3 --version` |
| A self-hosted Gitea or GitLab account *(optional in Phase 1)* | Remote backup; required for Phase 3+ automation | — |

The vault works **fully offline / local-only** if you don't configure a git remote. The remote is required only when you reach Phase 3 (cron jobs that push) or Phase 4 (webhooks).

---

## Install & first-time setup

```sh
# 1. Clone (or you're already here)
git clone <your-remote-url> ai-kb && cd ai-kb
# OR for greenfield:
git init && cd ai-kb     # then follow the rest

# 2. Configure your remote (optional now, required by Phase 3)
cp .env.example .env
$EDITOR .env                                  # set KB_GIT_REMOTE
git remote add origin "$(grep KB_GIT_REMOTE .env | cut -d= -f2-)"

# 3. Verify Claude Code sees the slash commands
claude -p "/help" | grep -E "note-add|kb-validate" && echo "OK"

# 4. Open the vault in Obsidian
open -a Obsidian .                            # macOS
# OR: File → Open vault → select this folder

# 5. Enable the Dataview plugin (required for MOC views)
#    Obsidian: Settings → Community plugins → Browse → "Dataview" → Install → Enable
#    (or it auto-prompts on first open because .obsidian/community-plugins.json lists it)

# 6. Run the acceptance gate to confirm everything works end-to-end
./verify-phase1.sh
```

If `verify-phase1.sh` passes, the foundation is ready and you can move to daily use.

---

## Layout

```
inbox/      raw drops — every new note enters here, regardless of trigger
notes/      personal/research atomic notes
work/       specs, ADRs, runbooks (frontmatter: subtype + status)
sources/    distilled external (articles, papers, talks) — frontmatter: url, author, captured
code/       repo intelligence — code/<repo>/ with kind-faceted MOC per repo
refs/       people/, tools/, concepts/ — stable, long-lived reference notes
daily/      YYYY-MM-DD.md daily notes
templates/  one .md per note type — slash commands copy from these
.claude/    slash commands + project-local Claude Code settings (permission allowlist)
.kb/        machine state (idempotency keys, processed paths); schema frozen
.obsidian/  Dataview plugin manifest; per-machine workspace state is .gitignored
MOC.md      top-level map of content (Dataview query)
code/index.md  list-of-repos surface (avoids flat MOC explosion as code/ scales)
```

Why this structure: domain folders make it easy for both humans and Claude to know where a note belongs. Atomic notes inside each folder keep individual files small enough to edit without re-flowing surrounding content.

---

## The single-ingest rule

> **Every new note — from any trigger — lands in `inbox/` first. Refile is a separate step.**

This is the most important architectural rule. It collapses three pipelines into one:

```
manual    ─┐
file-watch ─┼──→ inbox/<file.md>  ──/note-refile──→  notes/ | work/ | sources/ | code/ | refs/
webhook   ─┘                                          (correct folder, frontmatter filled)
```

Why: refile logic lives in exactly one place (`/note-refile`). Later phases (Phase 2 file-watch, Phase 4 webhooks) just write to `inbox/` and reuse the same command. No duplicate classifiers.

The exception: `/note-add --folder=<f>` lets you skip the inbox detour when you already know where the note belongs. `/daily` writes directly to `daily/` because the destination is unambiguous.

---

## Daily workflow

A representative session:

```sh
# Morning: open today's daily note
claude -p "/daily"
# → creates/opens daily/2026-05-15.md

# Read an article you want to remember
claude -p "/source-capture https://example.com/article"
# → distilled note in inbox/

# Quick thought capture during the day (in Obsidian or via CLI)
claude -p "/note-add 'why prompt caching helps long agent loops'"
# → atomic draft in inbox/

# End of day: sweep the inbox
claude -p "/note-refile"
# → moves drafts to notes/, sources/, etc. with proper frontmatter

# Once a week or so: weave the graph
claude -p "/note-link notes/202605151430-prompt-caching.md"
# → adds [[backlinks]] to related notes

# Anytime you want a health check
claude -p "/kb-validate"
claude -p "/kb-stats"
```

Inside Obsidian, you can also just type `/note-add ...` etc. into the Claude Code chat panel — the CLI is one way to invoke commands, not the only way.

---

## Command reference

All commands are headless-capable (non-interactive) — see [Headless / scripting use](#headless--scripting-use).

### Capture

| Command | Purpose | Required args | Optional flags |
|---|---|---|---|
| `/note-add <topic>` | New atomic note → `inbox/` | `topic` | `--type=<note\|source\|work\|code\|ref>` (default: `note`), `--folder=<path>` (skip classification), `--tags=<csv>` |
| `/source-capture <url>` | Fetch URL, distill to a source note in `inbox/` | `url` | `--max-len=<chars>` (cap distillation length) |
| `/code-doc <repo-path>` | Generate atomic code-intelligence notes in `inbox/` | `repo-path` (absolute or relative) | `--scope=<glob>` (e.g., `src/**/*.ts`), `--kind=<function\|class\|module\|flow\|adr>` |
| `/daily` | Create/append today's `daily/YYYY-MM-DD.md` from template, idempotent | — | `--date=YYYY-MM-DD` (override today) |

### Organize

| Command | Purpose | Required args | Optional flags |
|---|---|---|---|
| `/note-refile [path...]` | Sweep `inbox/` (or given paths); classify, move, fill frontmatter | — | paths default to all of `inbox/*.md` |
| `/note-rename <old> <new>` | Move + rewrite all `[[wiki-links]]` to point to new title; append old title to `aliases:` | both paths | — |
| `/note-split <path>` | Break an oversized note into atomic pieces with bidirectional `[[links]]` | path | `--target-lines=<n>` (default 200) |
| `/note-link [path]` | Inject `[[backlinks]]` based on content overlap with other notes | path (defaults to most-recent inbox/) | `--threshold=<0.0–1.0>` (similarity floor) |

### Maintain

| Command | Purpose | Required args | Optional flags |
|---|---|---|---|
| `/kb-validate` | Lint: frontmatter schema, ID uniqueness, dangling `[[links]]`, oversized notes. Non-zero exit on any failure. | — | `--fix` (attempt safe auto-fixes; never destructive) |
| `/kb-stats` | One-page health report: counts by type, orphans, broken links, oversized | — | `--json` (machine-readable) |

---

## Worked examples

### Example 1 — Capture a paper, then split it

```sh
claude -p "/source-capture https://arxiv.org/abs/2401.12345"
# → inbox/202605151430-on-prompt-caching-for-long-agents.md (oversized: 380 lines)

claude -p "/note-refile"
# → moves to sources/202605151430-on-prompt-caching-for-long-agents.md

claude -p "/note-split sources/202605151430-on-prompt-caching-for-long-agents.md"
# → splits into 3 atomic notes + the original now contains a summary + [[links]] to the splits
```

### Example 2 — Document a repo

```sh
claude -p "/code-doc ~/projects/myapp --scope='src/services/**/*.ts'"
# → multiple inbox/ notes, each type:code, repo:myapp, kind:function|class|module

claude -p "/note-refile"
# → all moved to code/myapp/

# In Obsidian, open code/myapp/MOC.md → Dataview groups them by kind
```

### Example 3 — Rename without breaking the graph

```sh
claude -p "/note-rename notes/old-title.md notes/new-clearer-title.md"
# → file moved, every [[old title]] across the vault rewritten to [[new clearer title]],
#   the new note's frontmatter has: aliases: ["old title"]
# → /kb-validate confirms zero broken links
```

---

## Obsidian setup

The vault is designed around **Obsidian core + Dataview only**. No Templater, no other community plugins — for maximum portability (you can open this vault in Logseq, VS Code, or any plain markdown editor).

**Required plugin**: Dataview. It powers the MOC views that surface recently-touched notes by type and the per-repo code MOC.

**Recommended settings** (Settings → ...):

- *Files & Links* → *New link format*: **Shortest path when possible** (matches `[[wiki-link]]` convention).
- *Files & Links* → *Use [[Wikilinks]]*: **On**.
- *Editor* → *Default new pane mode*: your preference, doesn't affect the vault.
- *Hotkeys*: bind your favorite key to "Open daily note" (or just `claude -p "/daily"`).

**`.obsidian/community-plugins.json`** is committed; Obsidian prompts to install Dataview the first time you open the vault.

**`.obsidian/workspace*`** and `.obsidian/cache/` are `.gitignored` — they're per-machine state.

---

## Headless / scripting use

Every command runs without a chat session. This is what enables Phases 2–4.

```sh
# Plain headless invocation:
claude -p "/note-add 'kysely dialect quirks' --type=code"

# Capture exit code:
if ! claude -p "/kb-validate"; then
  echo "Vault has errors; aborting"
  exit 1
fi

# Pipe input (some commands like /note-add accept stdin for body content):
echo "Body of the note" | claude -p "/note-add 'idea' --stdin-body"
```

**Rules** the commands honor for headless use:

- Missing required args → exit non-zero with one-line error to stderr. **Never prompt.**
- All optional args have documented defaults.
- Commands that mutate state commit their own changes. No "now run `git commit`" follow-up needed.
- `--json` flag where applicable produces machine-readable output for piping.

---

## Maintenance & validation

`/kb-validate` is the safety net. Run it whenever:

- After a bulk operation (multiple refiles, a big `/code-doc` run, a `/note-split`).
- Before pushing to the remote.
- (Optionally) as a pre-commit hook.

To install as a pre-commit hook:

```sh
cat > .git/hooks/pre-commit <<'EOF'
#!/usr/bin/env bash
set -e
claude -p "/kb-validate" || exit 1
EOF
chmod +x .git/hooks/pre-commit
```

`/kb-stats` gives you the at-a-glance numbers: notes by type, broken-link count, orphan count, oversized count. In Phase 3, this becomes the weekly cron job that commits a snapshot.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Slash commands don't appear in Claude Code | `.claude/commands/` not detected | Confirm you opened *this folder* as the working directory; run `claude -p "/help"` to list available commands. |
| `/kb-validate` reports ID collisions | Two notes share a ULID (usually from copy-paste) | Open both files, regenerate one ID via the snippet in `CLAUDE.md` §5. |
| `/kb-validate` reports broken `[[links]]` | A note was renamed/moved without `/note-rename` | Re-run `/note-rename <correct-new-path>` for each, OR add the old name to the target's `aliases:`. |
| Obsidian shows lots of "untitled" wiki-links | New-link-format setting is wrong | Settings → Files & Links → New link format: **Shortest path when possible**; Use [[Wikilinks]]: **On**. |
| MOC.md is empty | Dataview plugin not installed/enabled | Settings → Community plugins → Browse → Dataview → Install → Enable. |
| Commit fails: "non-fast-forward" | Remote has commits you don't | `git pull --rebase` then re-run the command (Phase 2+ automation does this itself). |
| `claude -p` hangs | A command violated the no-prompt rule | Check the command file in `.claude/commands/<name>.md` — its prompt must never ask follow-up questions. Report as a bug. |
| `/source-capture` returns very short distillation | WebFetch hit a paywall or a JS-rendered page | The command exits with a warning; capture the page manually via Obsidian Web Clipper, then `/note-refile`. |

---

## Phase 2 — File-watch daemon

The Phase 2 watcher reacts to drops in `inbox/` and refiles them automatically by shelling out to `/note-refile`. It uses macOS FSEvents (via `watchfiles`) and runs as a launchd LaunchAgent so it inherits your `~/.claude/` credentials.

### Install

```sh
# 1. Create the watcher's dedicated venv and install dependencies (one-time)
bin/setup-watcher.sh

# 2. Verify the daemon works (static checks + dry-run cost-gate behavior)
./verify-phase2.sh

# 3. (Optional) Install as a LaunchAgent that auto-starts on login
bin/install-watcher.sh
```

### Manual test (foreground)

```sh
# Run in the foreground; Ctrl-C to stop.
.venv-watcher/bin/python3 bin/kb-watcher.py

# In another terminal, drop a note:
cat > inbox/test.md <<'NOTE'
# A real test

Real body content, big enough to clear the cost gate.
NOTE

# Within ~10 seconds the watcher should log the queue + invoke claude.
```

### Cost gate

Every `inbox/` event firing `claude -p` costs real money. The daemon filters out:

| Skip condition | Why |
|---|---|
| File <50 bytes | Likely a mid-write Obsidian autosave |
| File modified <2s ago | Autosave race; wait for next debounce |
| File's sha already in `.kb/state.json` `processed{}` | Same content was already attempted; re-saving changes sha and naturally retriggers |
| Path doesn't end in `.md` | Out of scope |
| Path deleted | Nothing to do |

The daemon stamps `processed[path]={sha,ts,source:"watch"}` after each invocation (success or failure). This prevents hot-loops if `/note-refile` ever fails — re-saving the file is the explicit retry signal.

### Logs & lifecycle

| File | What |
|---|---|
| `.kb/watcher.log` | Application log (rotated only when launchd restarts the process) |
| `.kb/watcher.stdout.log` | launchd-captured stdout |
| `.kb/watcher.stderr.log` | launchd-captured stderr |
| `.kb/watcher.pid` | Single-instance guard |

All four are `.gitignored`.

### Uninstall

```sh
bin/uninstall-watcher.sh    # remove the LaunchAgent
rm -rf .venv-watcher        # remove the venv (optional)
```

### Tunables

```sh
# Override the debounce window (default 8s):
.venv-watcher/bin/python3 bin/kb-watcher.py --debounce 5

# Process the current inbox once and exit (useful as a cron alternative):
.venv-watcher/bin/python3 bin/kb-watcher.py --once

# Test mode — log decisions but never invoke claude:
.venv-watcher/bin/python3 bin/kb-watcher.py --dry-run
```

---

## Phase 3 — Cron jobs

Three launchd `LaunchAgent` timers handle time-driven maintenance. Each job pulls from origin first, runs its work, and pushes after — so the vault on Gitea stays in sync without manual `git push`.

| Job | Schedule | What it does |
|---|---|---|
| `daily.sh` | 00:05 local | `claude -p "/daily"` (idempotent — no-ops if today's note already exists) |
| `weekly.sh` | Sun 03:00 local | `/kb-stats --json` → `.kb/stats/<YYYY>-W<WW>.json`; `/kb-validate` for drift |
| `monthly.sh` | 1st @ 04:00 local | Archives `inbox/*.md >30d` → `inbox/_archive/<YYYY-MM>/`; `work/**/*.md` with `status: done >90d` → `work/_archive/<YYYY-MM>/` |

### Install

```sh
# Install all three LaunchAgents at once
bin/cron/install-cron.sh

# View install status
launchctl print "gui/$(id -u)/com.aikb.daily" | head -20
```

### Bot identity

Cron jobs export `GIT_AUTHOR_NAME=kb-bot` and `GIT_AUTHOR_EMAIL=kb-bot@local` (from `.env` if set; default `kb-bot`/`kb-bot@local`) before invoking `claude -p` or `git`. This means automation commits show `kb-bot` in `git log --author`, distinct from your interactive commits. See `CLAUDE.md` §7.

### Manual run / dry-run

```sh
# Dry-run any job (no claude calls, no push)
DRY_RUN=1 bin/cron/daily.sh
DRY_RUN=1 bin/cron/weekly.sh
DRY_RUN=1 bin/cron/monthly.sh

# Real run (requires claude on PATH + your auth; will pull/push if origin set)
bin/cron/daily.sh
tail -f .kb/cron-daily.log   # in another terminal

# Force a scheduled job to fire NOW (useful for testing the LaunchAgent path)
launchctl kickstart -k gui/$(id -u)/com.aikb.daily
```

### Archive layout

The monthly job creates `inbox/_archive/<YYYY-MM>/` and `work/_archive/<YYYY-MM>/`. The Phase 2 watcher's cost-gate explicitly skips `_archive/` paths so archived notes don't get re-processed. The archive folders are committed to git — they're part of the vault, just dormant.

### Concurrency

Each cron job acquires a per-job lockfile (`.kb/cron-<job>.lock`) at start and releases on exit. If a second tick fires while one is running (rare), the second exits immediately. Locks are also released on crash via `trap EXIT`.

### Logs

| File | What |
|---|---|
| `.kb/cron-daily.log` (and `weekly`, `monthly`) | Application log, append-only |
| `.kb/cron-<job>.stdout.log` / `.stderr.log` | launchd-captured (rotated by launchd) |

All gitignored.

### Uninstall

```sh
bin/cron/uninstall-cron.sh
```

---

## Phase 4 — Webhook receiver

A small FastAPI server that accepts external triggers (GitHub, email, RSS) and writes them to `inbox/` with `source: webhook:<name>` and a stable `idem_key`. Phase 2 daemon picks them up and refiles. Same single-ingest contract as the other phases.

### Endpoints

| Endpoint | Auth | What it does |
|---|---|---|
| `GET /healthz` | none | Liveness — returns vault path and whether `state.json` is present |
| `POST /webhook/github` | HMAC-SHA256 on body (`X-Hub-Signature-256`) | Maps `push` / `release` / `issues` events to inbox notes; idempotency key = `X-GitHub-Delivery` |
| `POST /webhook/rss/refresh` | bearer token (`KB_ADMIN_TOKEN`) | Triggers a poll of every configured feed in `.kb/feeds.json` |
| `POST /email/inbound` | bearer token (`KB_EMAIL_TOKEN`) | Accepts JSON-forwarded email (Mailgun, SES, custom MTA hook); idempotency key = `Message-ID` |

### Install

```sh
# 1. Create the webhook venv and install deps (one-time)
bin/webhook/setup-webhook.sh

# 2. Configure secrets (NOT committed — .env is .gitignored)
cat >> .env <<EOF
KB_WEBHOOK_PORT=8765
GITHUB_WEBHOOK_SECRET=$(openssl rand -hex 32)
KB_EMAIL_TOKEN=$(openssl rand -hex 32)
KB_ADMIN_TOKEN=$(openssl rand -hex 32)
EOF

# 3. (Optional) Configure RSS feeds (committed)
cat > .kb/feeds.json <<JSON
[
  {"name": "Hacker News", "url": "https://hnrss.org/frontpage", "tags": ["hn"]}
]
JSON

# 4. Verify everything works (no network, no claude needed)
./verify-phase4.sh

# 5. Install as LaunchAgents (HTTP server + RSS poll every 30 min)
bin/webhook/install-webhook.sh
```

### Manual test

```sh
# Foreground server (Ctrl-C to stop)
.venv-webhook/bin/python3 -m bin.webhook.cli serve

# Health check
curl -s http://127.0.0.1:8765/healthz | python3 -m json.tool

# Trigger an RSS poll manually
launchctl kickstart -k gui/$(id -u)/com.aikb.rss-poll
tail -f .kb/rss-poll.stdout.log

# Send a test GitHub push payload
body='{"ref":"refs/heads/main","repository":{"full_name":"a/b"},"sender":{"login":"alice"},"commits":[]}'
sig="sha256=$(printf '%s' "$body" | openssl dgst -sha256 -hmac "$GITHUB_WEBHOOK_SECRET" | awk '{print $2}')"
curl -X POST http://127.0.0.1:8765/webhook/github \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: push" \
  -H "X-GitHub-Delivery: $(uuidgen)" \
  -H "X-Hub-Signature-256: $sig" \
  -d "$body"
```

### Idempotency model

Every handler derives a stable `idem_key` from a source-specific ID:

| Source | Idempotency key derived from |
|---|---|
| GitHub | `X-GitHub-Delivery` header (GitHub re-uses this on retries) |
| RSS | `sha256(feed_url + entry_guid)` |
| Email | `Message-ID` header (RFC 5322; globally unique) |

The shared `ingest()` checks both `.kb/state.json` `idempotency{}` AND `git log --grep=[<key>]` before writing. If either says we've seen the key, the request returns `status: skipped` and produces no note. State.json wipe still recovers via git log — verified by `verify-phase4.sh`.

### Security notes

- **Binding**: server listens on `127.0.0.1` only. To expose externally, put a reverse proxy in front (Caddy / nginx / Tailscale Funnel) — never bind to `0.0.0.0` directly.
- **GitHub HMAC** is verified constant-time. Without `GITHUB_WEBHOOK_SECRET` set, the endpoint returns 503 (not 200) — fail-closed.
- **Email bearer** uses `hmac.compare_digest` for constant-time comparison.
- **RSS** is pull-only; no auth surface there. The `/webhook/rss/refresh` admin endpoint is bearer-protected.
- `.env` is `.gitignored`; secrets never enter the repo.

### Tunables

```sh
# Custom port (default 8765 from $KB_WEBHOOK_PORT)
.venv-webhook/bin/python3 -m bin.webhook.cli serve --port 9000

# One-shot RSS poll without starting the server
.venv-webhook/bin/python3 -m bin.webhook.cli rss-poll

# View server version
.venv-webhook/bin/python3 -m bin.webhook.cli version
```

### Files & logs

| File | What |
|---|---|
| `.kb/feeds.json` | RSS feed config (committed) |
| `.kb/seen.json` | Per-feed last-seen entry IDs (gitignored) |
| `.kb/webhook-serve.log` | Server application log |
| `.kb/webhook-rss-poll.log` | RSS poll application log |
| `.kb/webhook-stdout.log` / `.stderr.log` | launchd-captured server output |
| `.kb/rss-poll.stdout.log` / `.stderr.log` | launchd-captured RSS poll output |

### Uninstall

```sh
bin/webhook/uninstall-webhook.sh
rm -rf .venv-webhook          # optional
```

---

## Roadmap

- **Phase 1** — vault foundation + on-demand slash commands. ✅
- **Phase 2** — file-watch daemon. ✅
- **Phase 3** — cron (launchd timers). ✅
- **Phase 4** — webhook receiver. ✅

All four phases shipped. The architecture's load-bearing decisions — `inbox/`-first single-ingest contract, headless slash commands, frozen `.kb/state.json` schema, idempotency-keyed commit grammar — held without modification across every phase.

**Next adventures, not part of the original plan:**
- Mobile editing path (Obsidian mobile or gitweb companion against the Gitea repo).
- A Phase 2.1 "rich pre-filter" if Claude headless cost gets uncomfortable — e.g., a tiny local classifier that decides whether a note even needs Claude.
- A `/kb-search` slash command for semantic vault search if Dataview becomes insufficient.

---

## Conventions you must follow

See [`CLAUDE.md`](CLAUDE.md) for the full enforced ruleset. The short version:

1. **One concept per note.** Target ≤300 lines. Split if you exceed.
2. **`[[wiki-links]]` only**, never markdown links, for inter-vault references.
3. **All new notes start in `inbox/`** unless you pass `--folder=` explicitly.
4. **Never store backlinks in frontmatter** — Obsidian/Dataview compute them.
5. **Use `/note-rename`** to rename. Direct `git mv` will silently break wiki-links.
6. **Commit message format**: `kb: <verb> <scope> [<idem_key>]`.
7. **All slash commands are non-interactive** (Phase 2 daemons depend on this).

Breaking these makes the vault inconsistent and the automation phases harder to build. The verification script (`verify-phase1.sh`) gates Phase 2 and checks most of them.

---

## License & attribution

Vault content is yours. The slash commands and CLAUDE.md conventions in this scaffold are reusable; copy freely. Built with Claude Code.
