# Idea (2) — Health Diagnosis Linter: Architecture Design

**Date:** 2026-05-16
**Author:** Claude Opus 4.7
**Status:** Architecture only (no implementation code)
**Replaces:** Haiku design in `.claude/commands/kb-lint.md`, `bin/kb-lint.py`, `bin/kb-embeddings.py` (PR #1, has mocked Vector DB and year-string heuristics)

---

## Goal

Periodically (weekly cron) detect three classes of knowledge-base drift:

1. **Broken wiki-links** — `[[Some Note]]` references where target doesn't exist
2. **Semantic contradictions** — two notes asserting conflicting facts about the same topic
3. **Near-duplicates** — multiple notes covering substantially the same ground

Report findings via configurable channel (GitLab Issues, GitHub Issues, stdout). Never auto-fix.

**Non-goals:**
- Replace `/kb-validate` (schema/structural lint) — different problem
- Real-time linting on every save — weekly batch is enough
- Auto-merge or auto-rewrite notes — human-in-loop only

---

## What the Haiku Implementation Got Wrong

| Mistake | Impact | Fix |
|---|---|---|
| `embedding = hashlib.sha256(text).digest()` used as vector | SHA hash is not semantic; "similar" returned arbitrary notes | Real `sentence-transformers` model or Voyage AI API |
| `find_similar()` returned `list(dict.keys())[:top_k]` | Not similarity, just dict ordering | Real Chroma `query()` with cosine distance |
| `if "2024" in body and "2025" in n.body` flagged as contradiction | False positives on every vault with both years | Embedding similarity + LLM semantic comparison |
| "Duplicate" = "title has 2+ shared words" | Flags every common topic; useless | Embedding similarity threshold + LLM diff check |
| `IssueReporter` printed "Would create issues" | Never actually created issues | Real `python-gitlab` / GitHub MCP / PyGithub |
| Embedded as Python dict saved to JSON | No actual vector ops, can't scale | Chroma's HNSW index handles 1M+ vectors |

---

## Architecture

### Component diagram

```
              Phase 3 cron (weekly)
                       |
                       v
       +----------------------------+
       |  bin/kb-lint.py            |
       |   - scan vault             |
       |   - embed new/changed      |
       |   - check broken links     |
       |   - find contradictions    |
       |   - find duplicates        |
       |   - report findings        |
       +----------------------------+
              |          |          |
              v          v          v
      +----------+  +----------+  +----------+
      | embedder |  | chroma   |  | reporter |
      |          |  |          |  |          |
      | local    |  | local    |  | gitlab/  |
      | or API   |  | persist  |  | github/  |
      +----------+  +----------+  | stdout   |
                                  +----------+
```

### Three-pass algorithm

**Pass 1: Sync embeddings (incremental)**
- For each markdown file in vault (excluding `inbox/`, `.archive/`, `templates/`)
- Compute content hash; compare to stored hash in Chroma metadata
- If new or changed: embed, upsert; if unchanged: skip
- Delete embeddings for notes no longer present

**Pass 2: Broken-link check (no embeddings needed)**
- Parse all `[[wiki-link]]` and `[[wiki-link#anchor]]` references
- Maintain index of all note titles + aliases (from frontmatter)
- Any link with no matching target -> finding

**Pass 3: Contradiction + duplicate check (uses embeddings)**
- For each note, query Chroma for top-K similar notes (cosine >= 0.78)
- For each pair (A, B) above threshold:
  - Ask Claude: "Do these notes contradict each other? Are they duplicates?"
  - Receive structured `PairAnalysis` via tool-use
  - If contradicts: finding
  - If duplicate: finding
- Cache pair-analysis results by `(hash(A) + hash(B))` to avoid re-analyzing unchanged pairs

---

## Interfaces

### `Finding` (output)

```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class Finding:
    kind: Literal["broken_link", "contradiction", "duplicate"]
    severity: Literal["low", "medium", "high"]
    confidence: int  # 0-100
    title: str       # human-readable summary
    body: str        # markdown explanation; what to do
    note_paths: list[str]  # affected notes (1 for broken_link, 2 for pair)
    suggested_fix: str | None  # optional remediation hint
```

### `Embedder` (interface)

```python
from typing import Protocol

class Embedder(Protocol):
    """Computes embedding vectors. Stateless."""

    dim: int  # vector dimension (384, 768, 1024, etc.)
    name: str  # for logging/cache invalidation

    def embed(self, text: str) -> list[float]: ...
    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...
```

Two implementations:

#### `SentenceTransformerEmbedder`
- Uses `sentence-transformers` library
- Default model: `all-MiniLM-L6-v2` (384-dim, 80MB, fast on CPU)
- Larger option: `all-mpnet-base-v2` (768-dim, 420MB, slower but better quality)
- Pros: free, offline, deterministic
- Cons: lower quality than commercial; first import is slow (model download)

#### `VoyageEmbedder`
- Uses Voyage AI API (`voyage-3-large` or `voyage-3.5-lite`)
- Anthropic-recommended embedding provider
- Pros: best quality; better for multilingual; managed
- Cons: $0.06/1M tokens; requires `VOYAGE_API_KEY`; network dependency

Selection via `.kb/config.toml`:
```toml
[linter.embedder]
type = "sentence-transformer"  # or "voyage"
model = "all-MiniLM-L6-v2"
# For voyage: model = "voyage-3-large"
```

### `VectorStore` (interface)

```python
class VectorStore(Protocol):
    """Persistent vector store. Abstracted so we can swap Chroma later."""

    def upsert(self, id: str, vector: list[float], metadata: dict) -> None: ...
    def delete(self, id: str) -> None: ...
    def get_metadata(self, id: str) -> dict | None: ...
    def query(self, vector: list[float], top_k: int, where: dict | None = None) -> list[QueryHit]: ...
    def count(self) -> int: ...
    def list_ids(self) -> list[str]: ...

@dataclass
class QueryHit:
    id: str
    score: float  # cosine similarity 0-1
    metadata: dict
```

#### `ChromaStore` (default implementation)

```python
import chromadb

class ChromaStore:
    def __init__(self, persist_path: str = ".kb/vector-db"):
        self.client = chromadb.PersistentClient(path=persist_path)
        self.collection = self.client.get_or_create_collection(
            name="vault",
            metadata={"hnsw:space": "cosine"},
        )
```

Chroma is the chosen backend because:
- Embedded mode (no separate server process) — perfect for per-vault scope
- Persists to local disk in `.kb/vector-db/`
- HNSW index handles 100K+ vectors with sub-100ms queries
- Stable file format (one of the few "boring" vector DBs)
- Apache 2.0 licensed

Server mode (for multi-vault) is documented but not required for v1.

### `IssueReporter` (interface — from gitlab-submodule-architecture.md)

```python
from typing import Protocol

class IssueReporter(Protocol):
    """Creates issues for findings. Implemented per platform."""

    def create_issue(
        self,
        title: str,
        body: str,
        labels: list[str],
    ) -> str:  # returns URL
        ...

    def list_existing(self, label: str) -> list[ExistingIssue]:
        """For deduplication; returns issues with given label that are open."""
        ...
```

Three implementations:

#### `GitLabReporter`
```python
class GitLabReporter:
    def __init__(self, url: str, project_id: str, token: str): ...
    # Uses python-gitlab
```

#### `GitHubReporter`
```python
class GitHubReporter:
    def __init__(self, owner: str, repo: str): ...
    # Uses MCP tools when available (mcp__github__issue_write)
    # Falls back to PyGithub for non-Claude-Code contexts
```

#### `StdoutReporter`
```python
class StdoutReporter:
    def create_issue(self, title, body, labels):
        print(f"[{','.join(labels)}] {title}\n{body}\n---")
        return "stdout://"
```

Selection via `.kb/config.toml`:
```toml
[linter.reporter]
type = "gitlab"  # or "github", "stdout"
gitlab_url = "https://gitlab.example.com"
project_id = "team/my-vault"
# Token from env: KB_GITLAB_TOKEN

[linter.reporter.deduplication]
# Re-create issue if older than N days
max_age_days = 30
# Label all findings with this, used for "is this finding already an issue?"
finding_label = "kb-lint"
```

### `Linter` (top-level)

```python
class Linter:
    def __init__(
        self,
        vault_path: Path,
        embedder: Embedder,
        store: VectorStore,
        reporter: IssueReporter,
        anthropic_client: Anthropic,
        config: LinterConfig,
    ): ...

    def run(self) -> LinterReport: ...
    # Runs all three passes; returns aggregate report
```

---

## Detailed Algorithms

### Pass 1: Incremental embedding sync

```
For each .md file in vault (skip inbox/, .archive/, templates/):
  read content
  hash = sha256(content)
  existing_meta = store.get_metadata(file_path)
  if existing_meta is None:
    # New file
    embedding = embedder.embed(prepare_for_embedding(content))
    store.upsert(file_path, embedding, {"hash": hash, "title": ..., "modified": ...})
  elif existing_meta["hash"] != hash:
    # Changed
    embedding = embedder.embed(prepare_for_embedding(content))
    store.upsert(file_path, embedding, {"hash": hash, ...})
  else:
    # Unchanged; skip
    pass

# Delete stale entries
existing_ids = set(store.list_ids())
current_ids = set(file_paths_in_vault)
for stale_id in existing_ids - current_ids:
  store.delete(stale_id)
```

**`prepare_for_embedding(content)`:**
- Strip frontmatter
- Strip code blocks (don't embed code; it dilutes semantic signal)
- Strip wiki-link syntax (`[[X]]` -> `X`)
- Truncate to ~2000 chars (most embedders cap at 512 tokens; ~2000 chars is safe)
- Prepend title as separate sentence for stronger title signal

### Pass 2: Broken link detection

```
all_targets = set()
for file in vault_files:
  fm = parse_frontmatter(file)
  all_targets.add(file.stem)  # filename without .md
  all_targets.add(fm.get("title", ""))
  for alias in fm.get("aliases", []):
    all_targets.add(alias)

for file in vault_files:
  body = file.read_text()
  for match in re.finditer(r'\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]', body):
    target = match.group(1).strip()
    if target not in all_targets:
      findings.append(Finding(
        kind="broken_link",
        severity="medium",
        confidence=100,  # this is deterministic
        title=f"Broken link: [[{target}]] in {file.name}",
        body=f"Note `{file}` references `[[{target}]]` but no note with that title or alias exists.",
        note_paths=[str(file)],
        suggested_fix=_find_close_match(target, all_targets),  # fuzzy match suggestion
      ))
```

Confidence is always 100 for broken links — it's a deterministic check.

### Pass 3: Contradiction + duplicate detection

```
candidate_pairs = []
for note_id in store.list_ids():
  vector = store.get_vector(note_id)
  hits = store.query(vector, top_k=5)
  for hit in hits:
    if hit.id == note_id:
      continue
    if hit.score < 0.78:  # similarity threshold
      continue
    pair = tuple(sorted([note_id, hit.id]))
    candidate_pairs.append((pair, hit.score))

# Deduplicate (each pair appears twice from both directions)
candidate_pairs = sorted(set(candidate_pairs))

# Check cache for already-analyzed pairs
pair_cache = load_pair_cache(".kb/vector-db/pair-cache.json")

for (note_a_id, note_b_id), similarity in candidate_pairs:
  cache_key = f"{hash_of(note_a_id, note_b_id)}"
  if cache_key in pair_cache and not _hashes_changed(pair_cache[cache_key]):
    analysis = pair_cache[cache_key]["analysis"]
  else:
    analysis = _llm_pair_analysis(note_a_id, note_b_id)
    pair_cache[cache_key] = {
      "analysis": analysis,
      "hashes": [hash_a, hash_b],
      "ts": now(),
    }

  if analysis.contradicts and analysis.confidence >= threshold:
    findings.append(Finding(
      kind="contradiction",
      ...
    ))
  if analysis.duplicates and analysis.confidence >= threshold:
    findings.append(Finding(
      kind="duplicate",
      ...
    ))

save_pair_cache(pair_cache)
```

### LLM pair analysis (the critical step)

```python
PAIR_ANALYSIS_TOOL = {
    "name": "analyze_pair",
    "description": "Analyze two notes for contradiction or near-duplication.",
    "input_schema": {
        "type": "object",
        "properties": {
            "contradicts": {"type": "boolean"},
            "duplicates": {"type": "boolean"},
            "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
            "explanation": {"type": "string", "maxLength": 500},
            "suggested_action": {"type": "string", "maxLength": 200},
        },
        "required": ["contradicts", "duplicates", "confidence", "explanation"],
    },
}

response = client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=400,
    system=[
        {
            "type": "text",
            "text": _PAIR_ANALYSIS_SYSTEM_PROMPT,  # task description
            "cache_control": {"type": "ephemeral"},  # cached across all pair analyses
        },
    ],
    tools=[PAIR_ANALYSIS_TOOL],
    tool_choice={"type": "tool", "name": "analyze_pair"},
    messages=[
        {
            "role": "user",
            "content": (
                f"Note A ({note_a.title}):\n{note_a.excerpt}\n\n"
                f"Note B ({note_b.title}):\n{note_b.excerpt}"
            ),
        }
    ],
    timeout=15.0,
)
```

System prompt explains the task; cached because it's stable across all pair calls in the run.

User message has the two note excerpts (titles + first ~2000 chars each). Note that we don't pass full bodies — focus on what's likely contradictory.

---

## Finding -> Issue Mapping

### Issue body template (Markdown)

```markdown
**Kind:** Contradiction
**Severity:** Medium
**Confidence:** 85%

## Affected notes

- [notes/claude-models.md](../notes/claude-models.md)
- [sources/2026-05-anthropic-blog.md](../sources/2026-05-anthropic-blog.md)

## Explanation

Note A says Claude has 200K context window, Note B says 128K. These were both updated within the last 30 days. Likely one is stale relative to the other.

## Suggested action

Confirm which is current. Update the stale note and add `aliases: ["...old name..."]` if the topic split.

---
*Created by `/kb-lint` on 2026-05-16. Labels: `kb-lint`, `kind:contradiction`.*
*To suppress repeats of this exact finding, label it `wontfix`.*
```

### Deduplication

Before creating each issue:
1. Compute finding hash: `sha256(kind + sorted(note_paths) + key_assertion_summary)`
2. Search existing issues with label `kb-lint` AND title containing hash prefix
3. If exists and not `wontfix`/`completed`: skip (don't re-create)
4. If `wontfix`: skip permanently
5. If `completed` and >30 days old: re-create (finding may have re-emerged)

This prevents weekly spam.

### Severity assignment

| Kind | Severity rule |
|---|---|
| `broken_link` | medium (always); if in `daily/`, low |
| `contradiction` | medium if confidence 70-85; high if >85 |
| `duplicate` | low if confidence <85; medium if >85 |

---

## Configuration

### `.kb/config.toml`

```toml
[linter]
enabled = true
schedule = "weekly"  # or "manual"; cron job reads this
similarity_threshold = 0.78
contradiction_confidence_threshold = 70
duplicate_confidence_threshold = 80
max_findings_per_run = 50  # avoid issue spam

[linter.embedder]
type = "sentence-transformer"
model = "all-MiniLM-L6-v2"

[linter.vector_store]
type = "chroma"
persist_path = ".kb/vector-db"

[linter.reporter]
type = "gitlab"  # or "github", "stdout"
gitlab_url = "https://gitlab.example.com"
project_id = "team/my-vault"
finding_label = "kb-lint"

[linter.scan]
# Folders to lint
include = ["notes", "sources", "work", "code", "refs"]
# Folders to skip
exclude = ["inbox", ".archive", "templates", "daily"]
```

### CLI

```bash
# Run all passes; report to configured channel
python -m ai_kb.lint

# Run specific pass
python -m ai_kb.lint --check=broken_links
python -m ai_kb.lint --check=contradictions

# Dry-run (don't create issues)
python -m ai_kb.lint --dry-run

# Override reporter
python -m ai_kb.lint --report=stdout

# Reset embeddings (rebuild from scratch)
python -m ai_kb.lint --reset-embeddings
```

---

## Phase 3 Cron Integration

`bin/cron/weekly.sh` adds:

```bash
# Run lint after stats and validate
python -m ai_kb.lint --report=auto >> .kb/logs/lint-$(date +%Y%m%d).log 2>&1
```

`--report=auto` reads `.kb/config.toml`. Catches and logs errors but doesn't fail the cron job.

### CI integration (GitLab)

`.gitlab-ci.yml`:
```yaml
weekly_health:
  stage: health
  image: python:3.12-slim
  script:
    - pip install -e .ai-kb/[linter]
    - python -m ai_kb.lint
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
  variables:
    GIT_SUBMODULE_STRATEGY: recursive
    GITLAB_TOKEN: $CI_JOB_TOKEN
    KB_VOYAGE_API_KEY: $KB_VOYAGE_API_KEY  # if using voyage embedder
```

---

## Cost Model

### Assumptions

- 500-note vault
- 5% of notes change per week (25 re-embeds)
- After first run, ~80% of candidate pairs are cached
- 50 new pair analyses per week (5 notes x 5 similar each, minus cache hits)

### Embedding cost (per week)

**sentence-transformers:** $0 (local CPU)
- 25 re-embeds x 60ms = 1.5s CPU time. Negligible.

**Voyage AI (alternative):**
- 25 notes x ~500 tokens = 12.5K tokens
- $0.06/1M tokens -> $0.00075/week
- $0.04/month

### LLM pair-analysis cost (per week)

- 50 new pair analyses
- System prompt (cached): ~800 tokens
- User message: ~2000 tokens (two note excerpts)
- Output: ~150 tokens

With caching (cache write once, then 49 reads):
- Cache write: 800 x 1.25 = 1000 input tokens, $0.0008
- Cache reads: 800 x 0.10 x 49 = 3920 input tokens, $0.003
- User messages: 2000 x 50 = 100K input tokens, $0.08
- Output: 150 x 50 = 7500 tokens, $0.03
- Total: ~$0.11/week = ~$0.50/month

**Total for Idea (2):** under $1/month for typical vault.

For larger vaults (5000 notes, 250 changes/week, 500 pair analyses):
- ~$5/month — still trivial

---

## Failure Handling

| Failure | Behavior |
|---|---|
| Chroma DB corrupt | Log error; `--reset-embeddings` flag rebuilds from scratch |
| sentence-transformers model download fails | Log; skip embedding pass; broken-link pass still runs |
| Voyage API down | Fall back to sentence-transformers if configured; otherwise skip |
| Claude API down | Skip pair-analysis pass; broken-link pass still runs |
| Reporter (GitLab/GitHub) down | Write findings to `.kb/logs/findings-<date>.jsonl` for later retry |
| Out of disk | Halt; alert via reporter if reachable |

Linter is **degradation-tolerant**: a partial run produces partial findings. Never silently exits without explanation.

---

## Testing

### Unit tests (pure, no I/O)

```python
def test_broken_link_detection_simple():
    files = {"foo.md": "see [[Bar]] for details"}
    findings = check_broken_links(files, all_titles=set())
    assert len(findings) == 1
    assert findings[0].kind == "broken_link"
    assert "[[Bar]]" in findings[0].title

def test_broken_link_anchor_ignored():
    # [[Foo#section]] still resolves to Foo
    files = {"foo.md": "see [[Bar#some-section]]"}
    findings = check_broken_links(files, all_titles={"Bar"})
    assert len(findings) == 0

def test_finding_hash_deterministic():
    f1 = Finding(kind="contradiction", note_paths=["a.md", "b.md"], ...)
    f2 = Finding(kind="contradiction", note_paths=["b.md", "a.md"], ...)  # different order
    assert finding_hash(f1) == finding_hash(f2)  # paths normalized
```

### Embedder tests (replay fixtures)

```python
def test_sentence_transformer_dimensions():
    embedder = SentenceTransformerEmbedder("all-MiniLM-L6-v2")
    vec = embedder.embed("test")
    assert len(vec) == 384
    assert all(isinstance(x, float) for x in vec)
```

### Chroma tests (in-memory)

```python
def test_chroma_upsert_query():
    store = ChromaStore(persist_path=":memory:")  # in-memory for tests
    store.upsert("a", [0.1] * 384, {"title": "Note A"})
    store.upsert("b", [0.9] * 384, {"title": "Note B"})
    hits = store.query([0.1] * 384, top_k=2)
    assert hits[0].id == "a"  # closest to query vector
```

### LLM pair-analysis tests (VCR)

```python
@pytest.mark.vcr
def test_pair_analysis_detects_version_contradiction():
    a = NoteExcerpt(title="Claude context", body="Claude has 200K context")
    b = NoteExcerpt(title="Claude models", body="Claude context limit is 128K")
    analysis = analyze_pair(a, b, anthropic_client)
    assert analysis.contradicts
    assert analysis.confidence >= 70

@pytest.mark.vcr
def test_pair_analysis_complementary_notes_are_not_contradictions():
    a = NoteExcerpt(title="Python typing basics", body="Use type hints for clarity")
    b = NoteExcerpt(title="Python typing advanced", body="Generics and protocols enable...")
    analysis = analyze_pair(a, b, anthropic_client)
    assert not analysis.contradicts
    # Maybe duplicates if too similar; depends on actual excerpts
```

### Reporter tests (mock backends)

```python
def test_stdout_reporter_prints():
    r = StdoutReporter()
    url = r.create_issue("Title", "Body", labels=["kb-lint"])
    assert url == "stdout://"
    # Captured by pytest's capsys

def test_gitlab_reporter_creates_issue(mock_gitlab):
    r = GitLabReporter(url="https://gitlab.test", project_id="me/vault", token="x")
    url = r.create_issue("Title", "Body", labels=["kb-lint"])
    assert "gitlab.test" in url
    mock_gitlab.assert_called_with_issue(title="Title", body="Body", labels=["kb-lint"])
```

---

## Performance Targets

For 500-note vault on M1 MacBook:

| Phase | Target |
|---|---|
| Pass 1 (embedding, no changes) | <2s (Chroma scan) |
| Pass 1 (embedding, 25 changes) | <5s (25 x ~60ms encode + Chroma upsert) |
| Pass 2 (broken links) | <1s (regex scan) |
| Pass 3 (pair analysis, 50 pairs, cached) | <5s |
| Pass 3 (pair analysis, 50 pairs, fresh) | <90s (Claude API rate-limited to ~1 req/s for safety) |
| Total weekly run | <2min |

For 5000-note vault: <10min.

---

## Open Questions

1. **Should `kb-lint` also embed `inbox/` notes?** Currently excluded.
   - **Recommend:** No. Inbox is transient by design. Embed only after refile.

2. **What about deleted notes' embeddings?** When a note is deleted, Chroma still has its vector.
   - **Recommend:** Pass 1 already handles this via `list_ids` set difference.

3. **Should embedded model be pinned per-vault (in `.kb/state.json`)?** If a user changes embedder, all existing embeddings become incompatible.
   - **Recommend:** Yes. Store embedder name+model in collection metadata. On mismatch, prompt user with `--reset-embeddings` instruction.

4. **Multi-vault Chroma?** Could share one Chroma server across vaults.
   - **Recommend:** No. Per-vault embedded mode is simpler. Multi-vault is a future concern.

5. **Should findings produce GitHub PRs (not issues) for broken links?** Auto-fix is tempting.
   - **Recommend:** No, per the "never auto-fix" non-goal. Issue with suggested fix only.

6. **Schedule frequency:** weekly default. Monthly for stable vaults? Daily for high-velocity?
   - **Recommend:** Make `schedule` config option (weekly|monthly|daily). Cron reads it.

---

## What This PR Does NOT Include

- No `bin/kb-lint.py` code
- No `bin/kb-embeddings.py` code
- No `.claude/commands/kb-lint.md` rewrite
- No `IssueReporter` implementations
- No `ChromaStore` implementation
- No tests

These are implementation work, in scope for follow-up PRs.

---

## Acceptance Criteria for Implementation PR

When someone implements this, they should be able to check:

- [ ] `Embedder` is real (sentence-transformers or Voyage), not SHA-based mock
- [ ] `VectorStore` is real Chroma, not dict-saved-to-JSON
- [ ] Pass 1 (sync) is incremental — unchanged files skip embedding
- [ ] Pass 2 (broken links) handles `[[link#anchor]]` and `[[link|alias]]` syntax
- [ ] Pass 3 (contradictions) uses real LLM with tool-use, cached system prompt
- [ ] Pair cache persists between runs in `.kb/vector-db/pair-cache.json`
- [ ] Findings have deterministic hash for issue dedup
- [ ] `IssueReporter` actually creates issues (no print-only mock in prod)
- [ ] Degradation-tolerant: partial failures produce partial reports
- [ ] CLI: `--dry-run`, `--check=<kind>`, `--reset-embeddings`, `--report=<channel>`
- [ ] Embedder version stored in collection metadata; rebuild prompt on mismatch
- [ ] Weekly run on 500-note vault completes in <2min

---

## Related

- `opus-redesign-critique.md` — Issues #4 (mock Vector DB), #5 (year-matching), #6 (gh CLI)
- `gitlab-submodule-architecture.md` — Where Linter code lives + IssueReporter abstraction
- `idea1-filter-design.md` — Companion design (same SDK patterns, prompt caching)
