# Idea (1) — Ingest Filter: Architecture Design

**Date:** 2026-05-16
**Author:** Claude Opus 4.7
**Status:** Architecture only (no implementation code)
**Replaces:** Haiku design in `.claude/commands/ingest-filter.md` and `bin/kb-filter.py` (PR #1, has mock LLM calls)

---

## Goal

At Phase 4 webhook ingestion, evaluate each candidate document against per-vault governance rules using Claude. Reject documents that fail; annotate documents that pass with structured governance metadata.

**Non-goals:**
- Replace `/kb-validate` (schema lint) — different problem
- Filter manually-added notes (Phase 1) — user trust assumed
- Make filtering perfect — false-positive rate <10% is success

---

## What the Haiku Implementation Got Wrong

| Mistake | Impact | Fix |
|---|---|---|
| `def call_claude(): return mock` | All docs pass with mocked confidence=85 forever | Real `anthropic.Anthropic().messages.create()` |
| Governance rules in user-message every call | ~15x cost waste on repeated context | `cache_control: ephemeral` on system message |
| JSON-in-text response parsing | Brittle; LLM can produce malformed JSON | `tools=[evaluate]` + `tool_choice="evaluate"` |
| No retry on rate limit | Single failure = lost document | Exponential backoff with `tenacity` |
| No timeout | One slow call blocks the webhook | 10s deadline, fail open or queue |
| No batching for high-throughput sources | Each doc = full LLM round-trip | (Future) batch <=8 docs in single call |
| No fallback on API outage | Webhook becomes unavailable | "Fail open" (accept all) vs "fail closed" (reject all) decision |

This document specifies what to build instead.

---

## Architecture

### Component diagram

```
                          Phase 4 webhook receiver
                                  |
                                  v
                    +------------------------------+
                    |  bin/webhook/ingest.py       |
                    |   (existing entry point)     |
                    +------------------------------+
                                  |
                          if governance enabled
                                  v
                    +------------------------------+
                    |  bin/kb-filter.py            |
                    |   - load_governance(source)  |
                    |   - evaluate(doc, rules)     |
                    |   - return FilterDecision    |
                    +------------------------------+
                                  |
                            calls Anthropic SDK
                                  v
                    +------------------------------+
                    |  Claude (haiku-4-5)          |
                    |   - system: rules (cached)   |
                    |   - user: doc                |
                    |   - tools: [evaluate]        |
                    +------------------------------+
                                  |
                          FilterDecision
                                  v
                    +------------------------------+
                    |  ingest.py decides:          |
                    |   pass -> write to inbox/    |
                    |   fail -> log + skip         |
                    +------------------------------+
```

### Data flow

1. Webhook handler receives event (GitHub push, RSS entry, email)
2. Handler creates `IngestCandidate` (in-memory; not yet a file)
3. If `.kb/governance/<source>.md` exists, call `filter.evaluate(candidate, source)`
4. `evaluate` loads rules (cached in process), calls Claude
5. Claude returns structured `FilterDecision` via tool-use
6. Handler either writes to `inbox/` (pass) or logs and discards (fail)

---

## Interfaces

### `FilterDecision` (return type)

```python
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class FilterDecision:
    verdict: Literal["pass", "fail", "abstain"]
    confidence: int  # 0-100
    reason: str      # <=200 chars; used as governance_notes
    rule_matched: str | None  # which rule fired (for analytics)
    eval_ms: int     # eval latency for metrics
    cache_hit: bool  # was governance prompt cached?
```

`abstain` is distinct from `fail` — used when Claude declines (off-topic, model uncertainty, rate-limit fallback). Treated as `pass` for safety unless config says otherwise.

### `IngestCandidate` (input)

Already exists from the Haiku design's `IngestRequest`. Add no new fields; the filter operates on existing `title`, `body`, `url`, `author`, `captured`.

### Filter function signature

```python
class Filter:
    def __init__(
        self,
        client: Anthropic,
        vault_path: Path,
        config: FilterConfig,
    ): ...

    def evaluate(
        self,
        candidate: IngestCandidate,
        source: str,  # "rss" | "github" | "email"
    ) -> FilterDecision: ...
```

Single method. Stateless except for governance-rule cache (in-process). Thread-safe.

### `FilterConfig` (from `.kb/config.toml`)

```toml
[filter]
enabled = true
model = "claude-haiku-4-5"  # cost-optimized; user can override
threshold = 70              # min confidence to accept "fail"
on_abstain = "pass"         # or "fail" — what to do when Claude abstains
on_timeout = "pass"         # fail-open default; "fail" for stricter vaults
on_api_error = "pass"       # fail-open default
timeout_ms = 10000
max_retries = 3
retry_backoff_base = 1.0    # seconds

[filter.sources.rss]
enabled = true
rules_path = ".kb/governance/rss.md"   # relative to vault root

[filter.sources.github]
enabled = false  # internal, trusted; skip filter

[filter.sources.email]
enabled = true
rules_path = ".kb/governance/email.md"
```

Per-source enable. Per-source rules path. Failure-mode policies are vault-wide.

---

## Anthropic SDK Usage (Critical Section)

This is where the Haiku design failed most badly. Specifying exact patterns.

### Prompt caching

**Why this matters:** governance rules are 500-2000 tokens. Without caching, every document re-sends them.

| Mode | Tokens per doc | 50 docs/day | Monthly |
|---|---|---|---|
| No caching | 2000 system + 500 doc + 100 output = 2600 | 130K | 3.9M |
| With ephemeral caching | 200 cache-read + 500 doc + 100 output = 800 | 40K (cache holds within 5min TTL refresh) | 1.2M |

Roughly **3-4x reduction** for typical RSS volume; up to 15x for high-volume sources.

### Anthropic call shape

```python
from anthropic import Anthropic
import os

client = Anthropic()  # reads ANTHROPIC_API_KEY

response = client.messages.create(
    model="claude-haiku-4-5",
    max_tokens=200,  # tool call is small; no prose generation
    system=[
        {
            "type": "text",
            "text": _SYSTEM_PROMPT,  # describes the eval task, not rules
        },
        {
            "type": "text",
            "text": governance_rules,  # the per-source rules
            "cache_control": {"type": "ephemeral"},
        },
    ],
    tools=[EVALUATE_TOOL],
    tool_choice={"type": "tool", "name": "evaluate"},
    messages=[
        {
            "role": "user",
            "content": _format_candidate(candidate),
        }
    ],
    timeout=10.0,  # httpx timeout in seconds
)
```

**Why each piece:**

- `model="claude-haiku-4-5"`: cheapest model that handles governance reasoning well. Sonnet/Opus only if rules need deep reasoning.
- `max_tokens=200`: forces conciseness; we only need the tool call.
- `system` is a list of two text blocks: first is task description (small, no caching needed), second is rules (large, cached).
- `cache_control: ephemeral`: 5-minute TTL; refreshes on each use within window. Long enough for typical webhook batches.
- `tools` + `tool_choice`: forces structured output. No JSON-in-text parsing.
- `timeout=10.0`: documents that take >10s to evaluate get the configured fallback (pass/fail).

### Tool schema

```python
EVALUATE_TOOL = {
    "name": "evaluate",
    "description": "Evaluate the candidate document against governance rules.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "enum": ["pass", "fail", "abstain"],
                "description": "pass=meets rules; fail=violates rules; abstain=insufficient info",
            },
            "confidence": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "description": "Confidence in verdict, 0-100",
            },
            "reason": {
                "type": "string",
                "maxLength": 200,
                "description": "One sentence explaining the verdict",
            },
            "rule_matched": {
                "type": ["string", "null"],
                "description": "Specific rule label that fired (for fail verdicts)",
            },
        },
        "required": ["verdict", "confidence", "reason"],
    },
}
```

Schema-validated. Reject any response missing `verdict` or with `confidence` out of range — treat as `abstain`.

### System prompt (the small, uncached part)

```
You are an ingestion governance evaluator for a knowledge base.

You will be given:
  - A set of governance rules for a content source
  - A candidate document

Apply the rules to the document and return a structured verdict via
the `evaluate` tool. Be conservative: when a document is borderline,
prefer `abstain` over guessing.

Rules follow.
```

Short, focused. The actual rules are in the second (cached) system block.

### Candidate formatting

```python
def _format_candidate(c: IngestCandidate) -> str:
    parts = [f"Title: {c.title}"]
    if c.author:
        parts.append(f"Author: {c.author}")
    if c.url:
        parts.append(f"URL: {c.url}")
    if c.captured:
        parts.append(f"Captured: {c.captured.isoformat()}")
    parts.append("")
    # Truncate body to keep tokens predictable; ~3000 chars ~ 750 tokens
    body = c.body[:3000]
    if len(c.body) > 3000:
        body += "\n[truncated]"
    parts.append(body)
    return "\n".join(parts)
```

3000-char body cap is a cost guardrail; tunable. Most filtering decisions are made from title+excerpt; full body rarely matters.

---

## Error Handling

### Decision tree

```
client.messages.create(...)
  |
  +-- success
  |      |
  |      +-- tool_use block present
  |      |      |
  |      |      +-- valid schema -> FilterDecision (pass/fail/abstain)
  |      |      +-- invalid schema -> log, treat as abstain
  |      |
  |      +-- no tool_use block (model produced text instead)
  |             -> log, treat as abstain
  |
  +-- anthropic.RateLimitError
  |      -> retry with exponential backoff (max_retries=3)
  |      -> after exhaustion: apply on_api_error policy
  |
  +-- anthropic.APITimeoutError / httpx.TimeoutException
  |      -> apply on_timeout policy
  |
  +-- anthropic.APIConnectionError
  |      -> retry once (transient network)
  |      -> on second failure: apply on_api_error policy
  |
  +-- anthropic.APIStatusError (5xx)
  |      -> retry once
  |      -> on second failure: apply on_api_error policy
  |
  +-- anthropic.BadRequestError (4xx)
         -> log, treat as abstain (don't retry; will fail again)
```

### Retry strategy

Use `tenacity`:

```python
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from anthropic import RateLimitError, APIConnectionError, APIStatusError

@retry(
    retry=retry_if_exception_type(
        (RateLimitError, APIConnectionError, APIStatusError)
    ),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _call_with_retry(client, **kwargs):
    return client.messages.create(**kwargs)
```

### Fail-open vs fail-closed

Per `FilterConfig.on_api_error`:

- `pass` (default): on Claude unavailable, accept the document. Governance metadata records `verdict: "abstain"`, `reason: "Filter unavailable: <error>"`. Manual review later.
- `fail`: on Claude unavailable, reject the document. Useful for sensitive vaults where any unfiltered ingestion is unacceptable.

Document this loudly. Most vaults should default to `pass` (filtering is an enhancement, not a security boundary).

---

## Per-Vault Governance Rules

### File format

`.kb/governance/<source>.md` — plain markdown, no frontmatter. Free-form prose. Examples in `examples/governance/`.

Recommended structure:
```markdown
# RSS Governance Rules

## Domain
This vault tracks AI/ML systems engineering. Off-topic articles fail.

## Acceptance Criteria
- [accept] Original research, technical deep-dives, post-mortems
- [accept] Discussions of production AI systems (latency, cost, debugging)
- [accept] New frameworks/tools with concrete benchmarks

## Rejection Criteria
- [reject] Marketing posts, "X just announced..."
- [reject] Listicles, "10 ways to..."
- [reject] AI hype without technical substance
- [reject] Crypto/Web3 content unless directly relevant

## Edge Cases
- Conference talk announcements: pass if abstract is substantive
- Personal blog posts: pass if technical content >50%
- Twitter threads via syndication: usually fail (low signal)
```

No fixed schema — Claude interprets the rules. This is by design: writing rules as prose is easier than writing them as JSON, and Claude handles natural language better than rule DSLs.

### Cache busting

Cache key is the rules text. If rules change, cache is invalidated automatically (different text = different cache key). No explicit invalidation needed.

---

## Testing

### Unit tests (no API calls)

Test the parsing and decision logic without hitting the API.

```python
# tests/test_filter_decision.py
def test_filter_decision_from_tool_use():
    response = mock_response(tool_use={"verdict": "pass", "confidence": 90, "reason": "..."})
    decision = _parse_response(response)
    assert decision.verdict == "pass"

def test_filter_decision_invalid_schema_becomes_abstain():
    response = mock_response(tool_use={"verdict": "maybe", ...})  # invalid enum
    decision = _parse_response(response)
    assert decision.verdict == "abstain"

def test_filter_decision_no_tool_use_becomes_abstain():
    response = mock_response(text_only=True)
    decision = _parse_response(response)
    assert decision.verdict == "abstain"
```

### Integration tests (recorded API calls)

Use `pytest-recording` or `vcrpy` to record real API responses once, replay in CI.

```python
# tests/test_filter_integration.py
@pytest.mark.vcr
def test_marketing_post_is_filtered():
    candidate = IngestCandidate(
        title="10 AI Tools That Will Change Your Life!",
        body="In this listicle...",
        ...
    )
    decision = filter.evaluate(candidate, source="rss")
    assert decision.verdict == "fail"
    assert "marketing" in decision.reason.lower() or "listicle" in decision.reason.lower()
```

VCR cassettes go in `tests/cassettes/`; committed to repo. Re-record when prompts or rules change significantly.

### Smoke tests (real API, manual)

Document a manual test plan for vault owners after first install:

```bash
# Run governance evaluator on 5 sample documents
python -m ai_kb.filter smoke --source=rss --count=5
```

Outputs per-doc verdict + reason; vault owner sanity-checks.

---

## Metrics & Observability

### Per-evaluation metrics

Log structured JSON for each evaluation:

```json
{
  "ts": "2026-05-16T14:30:00Z",
  "source": "rss",
  "candidate_url": "https://example.com/article",
  "verdict": "pass",
  "confidence": 87,
  "rule_matched": null,
  "eval_ms": 423,
  "cache_hit": true,
  "input_tokens": 542,
  "output_tokens": 28,
  "cache_read_tokens": 1834,
  "cache_creation_tokens": 0
}
```

Written to `.kb/logs/filter.jsonl`. Append-only.

### Weekly summary

A `kb-stats --filter` subcommand summarizes:

- Pass/fail/abstain counts by source
- Average confidence
- Median latency
- Token consumption
- Top reasons for failure (for prompt tuning)

This data drives governance rule refinement.

---

## Cost Model

### Assumptions

- 50 documents/day across all sources
- 70% pass rate (35 docs/day stored)
- 5-minute cache TTL; typical webhook batches deliver within 1-2 minutes

### Token budget (with caching)

| Component | Tokens/call | Cost (Haiku 4.5) |
|---|---|---|
| Cache write (first call/window) | 2000 input x 1.25 = 2500 | $0.00200 |
| Cache read (subsequent calls) | 2000 input x 0.10 = 200 | $0.00016 |
| User message (doc) | 500 input | $0.00040 |
| Output (tool call) | 50 tokens | $0.00020 |

Assuming 1 cache write per 10 calls (5min TTL, bursty traffic):
- 50 calls/day x ($0.00016 x 9 + $0.00200 x 1 + $0.00040 + $0.00020) / 10
- ~ $0.04/day = ~$1.20/month

For 500 calls/day, ~$12/month. Trivial.

Compare to Haiku-style no-caching estimate of $25/month for the same volume.

---

## Open Questions

1. **Should `kb-watcher` also call the filter?** Currently filtering is only at Phase 4 (webhook). Should manually-dropped files in `inbox/` also be evaluated?
   - **Recommend:** No. Manually-dropped files have user intent. Filtering would be patronizing.

2. **Should the filter ever produce summaries (not just pass/fail)?** Haiku design mentioned "auto-summarize on pass."
   - **Recommend:** Defer to separate concern. Summary generation is a different operation with different cost/latency tradeoffs. Don't bundle.

3. **Should abstain results trigger a notification?** Operations team might want to know about high abstain rates.
   - **Recommend:** Track in metrics; alert if >20% abstain rate over 24h. Don't notify per-event.

4. **Multi-rule files: split or single?** e.g., `rss.md` could become `rss/freshness.md`, `rss/relevance.md`.
   - **Recommend:** Start single-file. Split only if rules grow >100 lines.

5. **Caching across sources:** if `rss.md` and `email.md` share 80% of rules, can we share cache?
   - **Recommend:** No. Cache key is exact text; different files = different cache. If sharing matters, factor common rules into a shared file referenced from both. Cost difference is marginal.

---

## What This PR Does NOT Include

- No `bin/kb-filter.py` code
- No `.claude/commands/ingest-filter.md` rewrite
- No `IssueReporter` implementation (covered in PR-3 architecture)
- No webhook handler modifications
- No tests
- No example governance files (those exist from Haiku PR #1, adequate for now)

These are implementation work. Architecture establishes the contract; implementation follows separately.

---

## Acceptance Criteria for Implementation PR

When someone implements this, they should be able to check:

- [ ] `Filter.evaluate()` uses `anthropic.Anthropic.messages.create()` (no mocks in production code)
- [ ] System prompt has rules in second block with `cache_control: ephemeral`
- [ ] Response is parsed via tool-use (`evaluate` tool), not JSON-in-text
- [ ] Rate limits trigger exponential backoff retry
- [ ] Timeouts fall back per `FilterConfig.on_timeout`
- [ ] Per-evaluation metrics written to `.kb/logs/filter.jsonl`
- [ ] Unit tests cover parsing + decision logic without API calls
- [ ] VCR-style integration tests cover real prompt behavior
- [ ] Manual smoke test command works
- [ ] Cache hit/miss visible in metrics

---

## Related

- `opus-redesign-critique.md` — Issues #2, #3, #5 driving this design
- `gitlab-submodule-architecture.md` — Where this code lives in the repo layout
- `idea2-linter-design.md` (forthcoming) — Companion design for Idea (2)
- `examples/governance/*.example.md` (from Haiku PR #1) — Adequate baseline content
