# Assessment: Enterprise Knowledge Base Enhancement Ideas

**Date:** 2026-05-16  
**Project:** ai-kb  
**Status:** Evaluation complete — ready for design phase

---

## ARCHITECTURE NOTE

This assessment assumes the **Separate Repos Architecture** (see `.docs/architecture/dual-role-architecture.md`):
- **ai-kb/** = Template system (commands, automation, conventions)
- **user-vault/** = User's knowledge base (separate git repo, uses ai-kb as submodule)

Key implications:
- Idea (1) (Ingest filtering): `.kb/governance/` files are **per-vault**
- Idea (2) (Health agent): `.kb/vector-db/` is **per-vault**
- Both ideas integrate naturally into per-vault `.kb/daemon/` automations

---

## Executive Summary

Three ideas proposed to enhance ai-kb for enterprise RAG use cases:

| Idea | Concept | Priority | Complexity | Value |
|------|---------|----------|-----------|-------|
| (1) | LLM-based filtering at ingestion | **First (3-4w)** | Medium | High (RAG quality) |
| (2) | Semantic health diagnosis agent | **Second (4-6w)** | Medium-High | High (consistency) |
| (3) | Dev/POC with Claude Code + Obsidian | Deferred | TBD | TBD |

---

## Idea (1) – LLM Filtering & Compression (`/ingest-filter`)

### Problem
Enterprise knowledge bases suffer from 'garbage in, garbage out': legacy docs, marketing noise, and stale information degrade Vector DB retrieval quality.

### Proposal
Insert **LLM-based governance filter** at Phase 4 (webhook) ingestion. Documents must pass:
1. Governance standards (admin-defined via prompt)
2. Freshness check (recency)
3. Relevance filter (aligned with domain)

### Decisions Made

| Decision | Choice |
|----------|--------|
| **Scope** | Configurable per-source (GitHub, RSS, email opt-in/out) |
| **Rules** | Prompt-based; stored in `.kb/governance/<source>.md` |
| **Enforcement** | Block ingestion on failure |
| **Timeline** | 3-4 weeks; pilot with RSS source first |

### Cost
- Per-document: ~50-200 tokens
- Monthly: ~2-40K tokens (varies by source volume)
- Start with low-volume source (RSS); scale after tuning

---

## Idea (2) – Health Diagnosis Agent (`/kb-lint`)

### Problem
Enterprise knowledge drifts: documents contradict, references break, duplicates spread. Current `/kb-validate` is schema-focused only.

### Proposal
**Weekly cron job** that:
1. Scans vault via Vector DB similarity
2. Detects contradictions via LLM comparison
3. Identifies broken reference links
4. Reports findings to GitHub issues

### Decisions Made

| Decision | Choice |
|----------|--------|
| **Vector DB** | Self-hosted (Chroma or Qdrant) |
| **Resolution** | Report + suggest; NO auto-fix |
| **Reporting** | GitHub issues (one per finding) |
| **Frequency** | Weekly (Phase 3 cron pattern) |
| **Timeline** | 4-6 weeks after Idea (1) completes |

### Cost
- Initial embedding: ~5-10 tokens per note
- Weekly comparison: ~20-50 tokens
- Monthly: ~400-800 tokens (low cost; computation-heavy)

---

## Idea (3) – Development & POC Stage

**Status:** Incomplete / Deferred — original proposal cut off. Revisit when details available.

---

## Architecture Notes

### Integration Points

```
Current Pipeline                 Enhanced with Ideas
─────────────────────────────────────────────────
Phase 1: Manual                  Phase 1: Manual (unchanged)
Phase 2: Daemon (refile)         Phase 2: Daemon + embed trigger
Phase 3: Cron (stats/validate)   Phase 3: Cron + /kb-lint (new)
Phase 4: Webhook (ingest)        Phase 4: Webhook + /ingest-filter (new)
Vector DB (NEW)                  Seeded by (1), consumed by (2)
```

### Design Principles
- **Headless:** Both ideas are CLI-invocable
- **Non-interactive:** Missing args → exit non-zero
- **State management:** Atomic git commits
- **Idempotency:** Filters use idem_key; linter uses issue creation
- **Cost-gated:** Filters start low-volume; linter batches weekly

---

## Implementation Roadmap

### Phase A: Idea (1) (Weeks 1-4)
- Week 1-2: Design governance prompts, create `.kb/governance/` structure
- Week 2-3: Implement `/ingest-filter`, wire Phase 4 webhooks
- Week 3-4: Pilot on RSS, tune prompts, expand to email

### Phase B: Idea (2) (Weeks 5-10)
- Week 5-6: Set up Vector DB (Chroma), embedding pipeline
- Week 6-8: Implement `/kb-lint`, contradiction detection
- Week 8-10: Integrate with Phase 3 cron, GitHub issue creation

---

## Success Metrics

### Idea (1) (Filtering)
- Quality: >90% precision (passes are relevant)
- Coverage: <5% false-negative (valid docs not filtered)
- Cost: <25K tokens/month

### Idea (2) (Health Agent)
- Detection: 100% of broken `[[wiki-links]]`; 80%+ contradiction precision
- False positives: <20%
- Latency: <5 minutes per weekly run

---

## Recommendations

1. **Idea (1) first** — lower-risk, higher-ROI, immediate RAG quality improvement
2. **Idea (2) foundational** — enables future semantic features
3. **Use Chroma** for Vector DB POC
4. **Monitor token costs** religiously

---

## Related

- Dual-role architecture: `.docs/architecture/dual-role-architecture.md`
- Implementation: `/ingest-filter`, `/kb-lint` commands
