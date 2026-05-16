# Opus Re-Assessment: Critique of Haiku Design

**Date:** 2026-05-16
**Author:** Claude Opus 4.7 (re-assessing Haiku 4.5 design)
**Status:** Critique → awaiting direction before re-implementation

---

## Summary of Disagreements

Haiku's design was reasonable on surface but has 6 substantive issues I'd reconsider before implementing. Some are architectural (significant rework), some are implementation quality (rewrite, same shape).

| Issue | Haiku's choice | My objection | Severity |
|-------|----------------|--------------|----------|
| 1. Architecture distribution | Git submodule | Submodules are painful in practice | **High** |
| 2. LLM integration | Mock `call_claude()` | Not production-ready | **High** |
| 3. Cost optimization | One call per document | No prompt caching = 10× cost waste | **High** |
| 4. Vector DB | Mock with `hashlib` | Not actually semantic | **Critical** |
| 5. Contradiction detection | Year-string matching heuristic | Doesn't detect real contradictions | **Critical** |
| 6. GitHub integration | Shell to `gh` CLI | Should use MCP tools | **Medium** |

---

## Issue 1: Submodules vs. Template + CLI Package

### Haiku's choice
Two repos, `user-vault/` adds `ai-kb/` as git submodule pinned to `v1-stable` branch.

### Why I disagree

Git submodules are notoriously painful:
- `git clone` without `--recursive` silently leaves you broken
- Submodule updates need explicit commits (forgotten constantly)
- Detached HEAD on submodule confuses every team member
- IDEs and CI tools handle them inconsistently
- Symlinking `.claude/commands` to a submodule path is fragile on Windows
- "Setup once, clone many" works until someone clones wrong

The 9-command setup flow is a red flag — every command is a place users will mess up.

### Better alternative: GitHub Template + Installable CLI

**Two distinct mechanisms instead of one awkward one:**

1. **GitHub Template Repository** for the vault scaffold
   - User clicks "Use this template" on GitHub → instant fresh repo
   - No submodule, no symlinks, no shared history
   - Updates: cherry-pick or manual sync (rare; vault content is the value, not scaffolding)

2. **Installable CLI tool** (`pip install ai-kb` or `uvx ai-kb`) for commands
   - `ai-kb refile inbox/*.md` works anywhere
   - `ai-kb lint --report=github`
   - `ai-kb filter <doc> --source=rss`
   - Versioned via PyPI; users `pip install -U ai-kb`
   - Commands shell out to `claude -p` internally (still uses Claude Code)

**Why this is better:**
- One-click vault creation (template button)
- Tool updates are explicit (`pip install -U`) and auditable (lockfile)
- Tool and vault are decoupled — fix a bug in linter without touching every vault
- Works in CI naturally (`pip install` is universal)
- No symlink fragility
- No detached-HEAD submodule pain

### Cost
Higher: needs PyPI publishing pipeline, semantic versioning, CLI argparse setup. But much better UX once shipped.

---

## Issue 2: Mock LLM Integration

### Haiku's choice
```python
def call_claude(prompt: str) -> dict:
    # Mock for now
    return {"decision": "pass", "confidence": 85, ...}
```

### Why I disagree
This is non-functional. Anyone running the code gets "all docs pass with 85% confidence" forever. The `# In real implementation:` comments are not a substitute for actual implementation.

### Better
Use the Anthropic SDK properly with:
- Real `client.messages.create()` calls
- Structured output via tool use (not JSON-in-text parsing, which breaks)
- Prompt caching for governance rules (see Issue 3)
- Proper error handling (rate limits, network failures, retries with backoff)
- Tests using `respx` or VCR-style fixtures

The `claude-api` skill exists for exactly this. Should be triggered automatically when this code runs.

---

## Issue 3: No Prompt Caching = 10× Cost Waste

### Haiku's choice
Each document is a separate LLM call with full governance rules in the prompt.

### Why this is critical
Governance rules are 500-2000 tokens each. With 50 docs/day:
- Without caching: 50 × 2000 = 100K tokens/day on rules alone = 3M/month
- With caching (1h TTL): Rules cached after first call = 2000 + (49 × 100 read) = 7K/day = 200K/month

That's a **15× cost reduction** for a 5-line code change.

### Better
```python
client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=200,
    system=[
        {
            "type": "text",
            "text": governance_rules,
            "cache_control": {"type": "ephemeral"}  # ← key change
        }
    ],
    messages=[{"role": "user", "content": document_text}],
    tools=[{"name": "evaluate", "input_schema": {...}}],
    tool_choice={"type": "tool", "name": "evaluate"}
)
```

Cache hit on second+ document in same hour.

---

## Issue 4: Mock Vector DB

### Haiku's choice
```python
def get_embedding(text: str, model: str = "claude") -> List[float]:
    import hashlib
    h = hashlib.sha256(text.encode()).digest()
    return [float(b) / 255.0 for b in h[:128]]
```

### Why this is critical
A SHA-256 hash is **not an embedding**. Two semantically identical sentences with one word changed will have completely different hashes. The `find_similar()` then returns "the first N items in dict order" — also not similarity.

This means the entire contradiction-detection pipeline is broken. It will find zero real contradictions and zero false positives — because it's not actually doing semantic comparison.

### Better
Three production-grade options, ranked by simplicity:

1. **sentence-transformers + Chroma** (local, free)
   ```python
   from sentence_transformers import SentenceTransformer
   model = SentenceTransformer('all-MiniLM-L6-v2')  # 80MB, fast, decent quality
   embedding = model.encode(text).tolist()
   ```
   - No API costs
   - Runs on CPU (60ms/note on M-series Mac)
   - Chroma handles cosine similarity natively

2. **Voyage AI embeddings** (Anthropic's recommended embedding provider)
   - Better quality than sentence-transformers
   - $0.05/1M tokens; ~$0.50 for 500-note vault
   - Requires API key

3. **OpenAI text-embedding-3-small** (if user already has key)
   - Comparable quality
   - $0.02/1M tokens

Use Chroma as the actual store, not a `dict` saved to JSON. Chroma handles persistence, similarity search, and metadata filtering correctly.

---

## Issue 5: Contradiction Detection is Year-Matching

### Haiku's choice
```python
if "2024" in note["body"] and any("2025" in n["body"] for n in notes.values()):
    findings.append({...})
```

### Why this is critical
This isn't contradiction detection — it's "does the word 2024 appear somewhere and 2025 appear elsewhere?" It will flag every vault with both 2024 and 2025 references, regardless of whether they actually conflict.

Real contradictions:
- "Claude has 200K context" vs "Claude has 128K context"
- "Use Redis for caching" vs "Switched from Redis to Memcached last quarter"
- "X is deprecated" vs "X is the recommended approach"

These require semantic understanding, not string matching.

### Better
Real algorithm:
1. Embed all notes (Issue 4) → Chroma
2. For each note, query top-5 most similar (cosine ≥ 0.75)
3. For each similar pair, ask Claude:
   > "Note A says: '<excerpt with assertion>'. Note B says: '<excerpt with related assertion>'. Do these contradict? Output via tool: {contradicts: bool, confidence: int, explanation: str}"
4. Only report contradictions where confidence ≥ threshold

This is 1 LLM call per similar pair (with caching for the system prompt). For 500-note vault with ~50 similar pairs/week, that's 50 calls/week = trivial cost.

---

## Issue 6: Shell-out to `gh` CLI for GitHub Issues

### Haiku's choice
Print "Would create issues" — never actually implemented. The plan was to shell out to `gh issue create`.

### Why I disagree
- `gh` may not be installed
- Auth setup is per-machine
- Error handling is bash-quoting hell
- Hard to test

### Better
Use GitHub MCP tools directly (they're available in this environment):
- `mcp__github__issue_write` to create issues
- Built-in auth via the MCP server
- Structured input/output
- No subprocess management

For the standalone CLI (Issue 1), use PyGithub or httpx + GitHub API.

---

## What I'd Build Instead

### Revised Architecture
1. **Distribution:** GitHub template repo + `pip install ai-kb` CLI (not submodule)
2. **Idea ① (Filtering):** Real Anthropic SDK + prompt caching + tool-use structured output
3. **Idea ② (Linting):** Real sentence-transformers + Chroma + Claude semantic comparison
4. **GitHub integration:** MCP tools or PyGithub (no shell-out)
5. **Cost:** Properly modeled with caching (10-15× lower than Haiku estimates)

### Scope Question

Before I implement, three questions:

**Q1: Architecture — accept the bigger pivot?**
- (a) Yes, switch to GitHub template + pip-installable CLI (significant rework, much better UX)
- (b) No, keep submodule design but fix implementation issues only
- (c) Defer architecture decision; implement Ideas ① & ② to be portable to either

**Q2: Implementation depth — what's "done"?**
- (a) Production-ready: real SDK, real Chroma, real GitHub MCP, tests, error handling
- (b) Reference implementation: working but needs polish (current Haiku target)
- (c) Architecture-only: detailed code stubs with interfaces, no working implementation

**Q3: Cost budget for implementation**
- (a) Time-box: 1-2 PRs, ship what's high-impact
- (b) Comprehensive: 3-5 PRs covering all critique points
- (c) Just architecture + Idea ①; defer Idea ② to next milestone

---

## What I Won't Repeat from Haiku

- ❌ `# Mock implementation` comments substituting for code
- ❌ String-matching heuristics for semantic problems
- ❌ Hashed bytes used as embeddings
- ❌ JSON-in-text parsing from LLM (use tool-use instead)
- ❌ Skipping prompt caching for repeated context
- ❌ Submodules + symlinks (fragile)

---

## Recommendation

**My recommendation: Q1=(c), Q2=(a), Q3=(a).**

- Keep architecture decision open — implement Ideas ① & ② to be portable
- Make them production-ready (real SDK, real Chroma, real MCP)
- Time-box: 2 PRs, focus on the things that actually work

Then revisit architecture (template vs submodule) as a separate decision based on user research.

What direction do you want?
