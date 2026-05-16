# /kb-cluster — Auto-MOC generation via Louvain community detection

**Status**: design approved
**Date**: 2026-05-16
**Phase**: Phase 5 (post-Phase-4 enhancement)
**Author**: Claude (brainstorm with @andychoi)

---

## 1. Why

The vault is a link graph. Today the only "map" surfaces are hand-written `MOC.md` (root) and per-folder index notes. As ingest volume grows (Phases 2–4 are landing notes via watch / cron / webhook), an emergent map — clusters of densely interlinked notes — becomes a primary discovery aid.

This is the lowest-friction step in the nashsu/llm_wiki direction: add Louvain community detection over the `[[wiki-link]]` graph and emit one Map-of-Content (MOC) note per cluster.

## 2. Scope (in / out)

**In:**

- A new slash command `/kb-cluster`, headless-invocable per CLAUDE.md §8.
- A Python helper `bin/cluster/kb_cluster.py` that builds the link graph and runs Louvain, emitting JSON to stdout.
- A new top-level `clusters/` folder containing auto-generated MOC notes (one per cluster) and an `_index.md`.
- Persistent cluster identity via `.kb/clusters/state.json` so MOC ULIDs and `created:` timestamps survive across runs.
- CLAUDE.md updates to §1 (folder semantics), §6 (commit verbs), §9 (skip list).

**Out (deferred):**

- Cron / launchd scheduling (the command is manual-only initially).
- Per-cluster human prose (MOC notes are fully auto-generated; edits are lost on next run).
- Including `code/` in the input graph (it would form one giant per-repo lump and swamp the conceptual clusters).
- Multi-resolution or hierarchical clustering.
- Backfilling MOC links into individual note frontmatter.

## 3. User-visible behavior

```sh
claude -p "/kb-cluster"                       # default: min-size=3, resolution=1.0
claude -p "/kb-cluster --min-size 5"          # only emit clusters with >=5 members
claude -p "/kb-cluster --resolution 1.4"      # higher resolution → more, smaller clusters
claude -p "/kb-cluster --dry-run"             # print plan to stdout, write nothing, no commit
```

After a successful run:

- `clusters/<slug>.md` exists for each cluster, where `<slug>` is derived from the cluster's canonical (most-linked-to) member's title.
- `clusters/_index.md` lists every cluster with its subtitle, member count, and canonical member.
- One git commit: `kb: cluster clusters/ (<N> clusters, <M> members)`.
- Exit code 0 on success, non-zero on any error (missing deps, invalid frontmatter encountered, git failure).

## 4. Input graph

**Included note types** (decided 2026-05-16): `notes/`, `refs/`, `sources/`.

**Excluded:** `code/` (intra-repo links dominate), `work/` (project-scoped), `daily/` (chronological), `inbox/` (pre-classification), and everything in §9 skip list.

**Graph construction:**

- Nodes: every included note, keyed by its frontmatter `id` (ULID).
- Edges: for each `[[wiki-link]]` (including `[[X|Y]]`, `[[X#heading]]`, `![[X]]`) from note A to note B (both in scope), record a directed reference A → B.
- Edge weight (undirected): `count of distinct source notes referencing target` summed over both directions. Concretely: if A links to B (regardless of repetition) **and** B links to A, the edge `{A,B}` has weight 2. If only one direction exists, weight 1. Multiple `[[B]]` references inside note A still contribute weight 1 — repetition within one source doesn't compound.
- Self-loops dropped.
- Dangling `[[wiki-links]]` (target not resolvable to a vault title or alias) are dropped silently — `/kb-validate` is the authority that flags those.
- Code fences (```` ``` ````) excluded from link scanning.

## 5. Algorithm

Louvain modularity-based community detection via `python-louvain` (`community.community_louvain.best_partition`), with:

- `resolution` parameter exposed (default `1.0`).
- `random_state` fixed to a deterministic seed (`42`) so consecutive runs on identical input produce identical partitions. Louvain is non-deterministic without this.

**Post-processing:**

- Drop clusters with `< --min-size` members (default 3). Their members are not assigned a cluster; they simply don't appear in any MOC.
- For each surviving cluster, pick the **canonical member**: the node with the highest in-degree restricted to the cluster's subgraph. Tie-break by alphabetical title.
- Compute `slug = slugify(canonical_member.title)` (lowercase, ASCII-only, `[a-z0-9-]+`, dashes for spaces, no trailing dash).

## 6. Stable cluster identity

`.kb/clusters/state.json` schema:

```json
{
  "schema_version": 1,
  "clusters": {
    "<canonical_id (ULID)>": {
      "moc_ulid": "<ULID>",
      "slug": "claude-api",
      "first_seen": "2026-05-16T14:30:00Z",
      "last_seen": "2026-05-16T14:30:00Z"
    }
  }
}
```

- **Key** = canonical member's ULID. If a cluster persists across runs with the same canonical member, its MOC keeps the same `id:` and `created:` (preserving git blame continuity).
- A cluster whose canonical member changes between runs is treated as a *new* cluster (new MOC ULID, new `created:`). The old MOC file is deleted as part of cleanup (§7).
- Entries for clusters that disappear (because they dropped below `--min-size` or their canonical member's connections changed) are kept in state for one additional run as tombstones, then removed. (Simplification: we may skip tombstones in v1 and just delete + re-add. Trade-off documented but not blocking.)

## 7. Output files

### `clusters/<slug>.md` (per cluster)

```yaml
---
id: <moc_ulid from state.json or fresh>
type: note
title: "Cluster: <canonical-title>"
created: <first_seen from state.json>
updated: <this-run ISO-8601 UTC>
tags: [auto-cluster]
source: manual
idem_key: <id>
subtitle: "<LLM-generated one-liner, ~80 chars>"
cluster_size: <N>
canonical_member: <canonical_id>
---

> Auto-generated by `/kb-cluster`. Manual edits will be lost on next run.

## Members (<N>)

- [[<member-1-title>]]
- [[<member-2-title>]]
- ...
```

Members ordered by in-degree within the cluster, descending. Subtitle is generated by Claude (the slash command's orchestrator) from the top member titles — no separate LLM client call.

### `clusters/_index.md`

A single table listing all current clusters:

```markdown
---
id: <stable ULID for _index>
type: note
title: "Cluster index"
created: <first ever run>
updated: <this run>
tags: [auto-cluster, index]
source: manual
idem_key: <id>
---

> Auto-generated by `/kb-cluster`.

| Cluster | Size | Canonical member |
|---|---|---|
| [[Cluster: Claude API]] | 12 | [[Claude API]] |
| ... | ... | ... |
```

The `_index.md` ULID is also persisted in `.kb/clusters/state.json` under a reserved key `"_index"` so it stays stable.

## 8. Cleanup of stale MOCs

Before committing:

1. Compute the set of slugs this run produced.
2. List all `clusters/*.md` (excluding `_index.md`).
3. Delete any file whose slug is not in the produced set.
4. Update `state.json`: remove entries for canonical IDs not in this run.

All deletes happen inside the working tree; the single commit captures additions, modifications, and deletions atomically.

## 9. Components

```
.claude/commands/kb-cluster.md     # the slash command (markdown spec; what Claude executes)
bin/cluster/
  kb_cluster.py                    # graph builder + Louvain; outputs JSON to stdout
  setup-cluster.sh                 # creates .venv-cluster, installs requirements.txt
  requirements.txt                 # networkx, python-louvain, python-frontmatter, python-ulid
.venv-cluster/                     # gitignored, created by setup-cluster.sh
.kb/clusters/state.json            # persistent identity map
clusters/                          # new vault folder (top-level)
  _index.md                        # auto-generated overview
  <slug>.md                        # one per cluster
```

## 10. CLAUDE.md changes

- **§1 — folder semantics table**: add `clusters/` row, `Auto-generated cluster MOCs. **Never** write directly; only \`/kb-cluster\` mutates this folder.`
- **§6 — commit verb enumeration**: add `cluster` to the verb set.
- **§9 — vault traversal skip list**: add `docs/` (so this spec doc and future ones aren't walked by `/kb-validate`).

The vault walker in `/kb-validate`, `/kb-stats`, and `/note-link` will need `clusters/` treated as:

- Walked **for ID uniqueness and frontmatter validation** (cluster MOC IDs must be unique vault-wide).
- **Excluded** from orphan detection (auto-generated indexes will always be orphans; they have outgoing links but no incoming ones).
- **Excluded** from `/note-link` candidate scoring (we don't want auto-MOCs suggested as related notes).

These exclusions are added in this change to the relevant slash-command markdown files.

## 11. Headless contract

- Non-interactive. Missing args → defaults, never prompts.
- Idempotent: same vault + same args → same `clusters/` modulo (a) the Claude-generated subtitle, which is treated as fuzzy-stable, and (b) `updated:` timestamps.
- Exit code 0 on success, non-zero on:
  - `bin/cluster/kb_cluster.py` failure (missing venv, bad input).
  - Any walked note has invalid frontmatter (we surface the path and exit 1; the user should run `/kb-validate --fix` first).
  - Git pull/commit failure.
- Reads `state.json` if present; treats missing as `{"schema_version": 1, "clusters": {}}`.

## 12. Error handling

- **Empty graph** (no notes in scope, e.g., fresh vault): exit 0 with stderr message `kb-cluster: no notes in scope, nothing to do`. Don't commit.
- **Single cluster** (all notes connect into one community): write one MOC + `_index.md`. Normal.
- **All clusters below `--min-size`**: same as empty graph — exit 0, no commit, stderr message.
- **Disconnected components**: Louvain handles these naturally; each component yields ≥1 cluster (or is dropped if below min-size).
- **Frontmatter parse failure in a walked note**: log path to stderr, exit 1 without commit. Direct the user to `/kb-validate`.

## 13. Testing strategy

A `verify-phase5.sh` script (mirroring `verify-phase4.sh`) that:

1. Confirms `.venv-cluster/` exists; if not, prompts the user to run `bin/cluster/setup-cluster.sh`.
2. Creates a temp vault fixture with ~12 notes in `notes/` and `refs/` forming two obvious clusters.
3. Runs `bin/cluster/kb_cluster.py --vault <fixture>` and asserts:
   - JSON output is valid.
   - Exactly 2 clusters returned.
   - Each cluster has the expected canonical member.
4. Runs `claude -p "/kb-cluster"` against the fixture (or asserts the slash command's markdown exists and parses).
5. Asserts `clusters/<slug>.md` files exist with correct frontmatter.
6. Re-runs `/kb-cluster` — asserts MOC ULIDs are stable.
7. Cleans up the fixture.

Run the script in CI (once we have CI; for now, manually before merging to main).

## 14. Future work (explicitly out of scope)

- **Cron wiring**: a `bin/cron/cluster.sh` and a `com.aikb.cluster.plist` to run nightly. Trivial to add later because all the heavy lifting is already headless.
- **Per-cluster human prose**: introduce managed-block markers (`<!-- kb-cluster:members:start/end -->`) so users can annotate clusters without losing their notes on regen.
- **Including code/ with a separate clustering pass**: `/kb-cluster --domain=code` could cluster `code/<repo>/` independently, producing `code/<repo>/clusters/` MOCs.
- **Multi-resolution**: run Louvain at multiple resolution values and nest the results (hierarchical MOCs).
- **Hyperlink-augmented graph**: use Claude semantic similarity scores as additional edges, not just `[[wiki-links]]`.

## 15. Acceptance checklist

- [ ] `.claude/commands/kb-cluster.md` exists, parses as a slash command, includes correct frontmatter (`description`, `argument-hint`, `allowed-tools`).
- [ ] `bin/cluster/kb_cluster.py` exists and runs against a fixture vault, emitting valid JSON.
- [ ] `bin/cluster/setup-cluster.sh` creates `.venv-cluster/` and installs requirements.
- [ ] `bin/cluster/requirements.txt` pins direct dependencies.
- [ ] `clusters/.gitkeep` exists (so the folder is tracked even when empty).
- [ ] `.kb/clusters/state.json` is created on first run with schema_version: 1.
- [ ] CLAUDE.md §1, §6, §9 updated.
- [ ] `.gitignore` includes `.venv-cluster/`.
- [ ] `/kb-validate` and `/kb-stats` continue to pass after running `/kb-cluster` on the current vault.
- [ ] One commit captures everything; commit message follows §6 grammar.
- [ ] Pushed to `github` remote on branch `main`.
