# GitLab-Aware Submodule Architecture

**Date:** 2026-05-16
**Author:** Claude Opus 4.7
**Status:** Architecture only (no implementation in this doc)
**Supersedes:** `dual-role-architecture.md` (Haiku) for GitLab context

---

## Why Submodule Is Right for GitLab (Reversal of Earlier Critique)

The Opus critique (`opus-redesign-critique.md`, Issue 1) initially argued against submodules in favor of GitHub template + pip-installable CLI. **In a self-hosted GitLab enterprise context, that argument is wrong**, for four reasons:

1. **Controlled team conventions.** Public OSS submodules fail because random contributors forget `--recursive`. An enterprise team can enforce conventions through onboarding docs, lint hooks, and code review.
2. **GitLab CI handles submodules natively.** `GIT_SUBMODULE_STRATEGY: recursive` in `.gitlab-ci.yml` makes CI Just Work.
3. **No PyPI publishing pipeline needed.** Publishing a private package to GitLab Package Registry adds setup friction (auth tokens per user, CI publish pipelines, version bumping). Submodule is zero-overhead.
4. **GitLab has no 'template repository' button** (the way GitHub does). Project templates in GitLab are group-level and require admin setup. Submodule is the idiomatic GitLab pattern for shared infra.

The Haiku design's submodule choice was right for this context. The follow-up critique applies only to: (a) GitHub OSS distribution, or (b) cross-organizational sharing.

---

## What Haiku Got Right (Keep)

- Template repo (`ai-kb`) separate from user vault (`<team>/my-vault`)
- Git submodule for distribution
- Pinned branch (`v1-stable`) for explicit version control
- Per-vault `.kb/governance/` and `.kb/vector-db/`
- Symlink `.claude/commands/ -> .ai-kb/.claude/commands/`
- Copy-and-customize CLAUDE.md (not symlink — vault-specific)

## What Haiku Got Wrong (Fix)

| Haiku assumed | Reality for GitLab | Fix |
|---|---|---|
| GitHub Issues for `/kb-lint` reports | GitLab Issues (different API, different MCP) | Abstract issue creation behind a `Reporter` interface |
| `https://github.com/andychoi/ai-kb` URLs in setup docs | GitLab self-hosted URL | Parameterize via env var `KB_TEMPLATE_REMOTE` |
| 9-command setup with no helper script | Users will skip a step | Ship `bin/setup-vault.sh` doing all 9 steps |
| No GitLab CI config | Submodule won't init in CI by default | Ship `.gitlab-ci.yml.example` for vault repo |
| `git clone` without `--recursive` left to memory | Will be forgotten | Add a check to commands; print warning if `.ai-kb/` is empty |

---

## Revised Architecture

### Two repos, one workflow

```
gitlab.example.com/
├── ai-kb/                            <- Template system (this repo)
│   ├── CLAUDE-TEMPLATE.md            <- For ai-kb developers
│   ├── CLAUDE.md                     <- Vault conventions (copied to vaults)
│   ├── .claude/commands/             <- All slash commands
│   ├── bin/                          <- Utilities, daemons, webhook handlers
│   │   ├── setup-vault.sh            <- NEW: scaffolds a new vault
│   │   ├── upgrade-vault.sh          <- NEW: handles submodule updates
│   │   └── ...
│   ├── templates/                    <- YAML note templates
│   ├── .docs/
│   │   ├── template/                 <- For ai-kb developers
│   │   ├── user/                     <- For vault owners (copied)
│   │   └── architecture/             <- Design docs (this file)
│   ├── examples/
│   │   ├── .gitlab-ci.yml.example    <- NEW: vault CI config
│   │   ├── .gitignore.example        <- NEW: vault gitignore
│   │   └── governance/
│   │       ├── rss.example.md
│   │       ├── github.example.md
│   │       └── email.example.md
│   └── README.md
│
└── <team>/my-vault/                  <- User's vault (separate repo)
    ├── CLAUDE.md                     <- Copied from .ai-kb/, customized
    ├── .ai-kb/                       <- Submodule, pinned to v1.0.0 tag
    ├── .claude/
    │   ├── settings.json             <- User permissions
    │   └── commands -> ../.ai-kb/.claude/commands/  (symlink, POSIX)
    ├── .kb/
    │   ├── state.json                <- Idempotency log
    │   ├── governance/               <- Vault-specific filter rules
    │   │   ├── rss.md
    │   │   ├── github.md
    │   │   └── email.md
    │   └── vector-db/                <- Chroma persist directory
    ├── .gitlab-ci.yml                <- Copied from examples/
    ├── inbox/, notes/, sources/, ... <- Content
    └── .gitignore
```

### Submodule pinning strategy

**Pin to tags, not branches.** This is a departure from Haiku's 'pin to v1-stable branch' approach.

| Strategy | Pro | Con |
|---|---|---|
| Pin to `main` branch | Always latest | Breakage on every push |
| Pin to `v1-stable` branch | Auto-updates within v1 | 'Latest of v1' can still surprise; CI varies between runs |
| **Pin to `v1.0.0` tag** <- chosen | Reproducible builds; no surprise updates | Manual upgrade required (good) |

```bash
# In vault repo:
git submodule add https://gitlab.example.com/ai-kb/ai-kb.git .ai-kb
cd .ai-kb && git checkout v1.0.0 && cd ..
git add .ai-kb && git commit -m 'Pin ai-kb to v1.0.0'
```

Upgrade flow is explicit:
```bash
cd .ai-kb
git fetch --tags
git checkout v1.1.0
cd ..
git add .ai-kb
git commit -m 'Upgrade ai-kb to v1.1.0'
```

---

## Mitigations for Submodule Pitfalls

These are the guardrails that make submodule work in practice.

### 1. `bin/setup-vault.sh` — scaffolds a new vault

Goal: replace the 9-command manual flow with a single `./setup-vault.sh my-vault`.

**Interface (no implementation here):**
```
./setup-vault.sh <vault-name> [--remote=<gitlab-url>] [--tag=v1.0.0]
```

**Behavior outline:**
1. `git init <vault-name>; cd <vault-name>`
2. `git submodule add <ai-kb-remote-url> .ai-kb`
3. `cd .ai-kb && git checkout <tag> && cd ..`
4. Copy `CLAUDE.md` from `.ai-kb/CLAUDE.md`
5. Copy `.docs/user/*` from `.ai-kb/.docs/user/`
6. Copy `examples/.gitlab-ci.yml.example` to `.gitlab-ci.yml`
7. Copy `examples/.gitignore.example` to `.gitignore`
8. Copy `examples/governance/*.example.md` to `.kb/governance/*.md`
9. Create symlink `.claude/commands -> ../.ai-kb/.claude/commands`
10. Create `.claude/settings.json` with defaults
11. `mkdir -p inbox notes sources work code refs daily`
12. Initial commit
13. Print next steps (remote add, push)

**Idempotent:** Re-running detects existing files and skips them (or warns).

### 2. `.gitlab-ci.yml.example` — vault CI config

Goal: CI checks out submodule correctly; runs `/kb-validate` on every push.

```yaml
variables:
  GIT_SUBMODULE_STRATEGY: recursive
  GIT_SUBMODULE_DEPTH: 1

stages:
  - validate
  - health

validate:
  stage: validate
  image: python:3.12-slim
  script:
    - pip install -e .ai-kb/
    - python .ai-kb/bin/kb-validate.py --strict
  rules:
    - if: $CI_PIPELINE_SOURCE == 'push'

weekly_health:
  stage: health
  image: python:3.12-slim
  script:
    - pip install -e .ai-kb/
    - python .ai-kb/bin/kb-lint.py --report=gitlab
  rules:
    - if: $CI_PIPELINE_SOURCE == 'schedule'
  variables:
    GITLAB_TOKEN: $CI_JOB_TOKEN
```

### 3. Commands check submodule health

Every command that depends on `.ai-kb/` should fail fast with a clear error if the submodule isn't initialized.

**Pattern (every command's preamble):**
```bash
if [ ! -f .ai-kb/CLAUDE.md ]; then
  echo 'ERROR: .ai-kb submodule not initialized.'
  echo 'Run: git submodule update --init --recursive'
  exit 1
fi
```

This catches the most common failure mode immediately rather than producing confusing errors downstream.

### 4. `bin/upgrade-vault.sh` — guided upgrades

Goal: vault owner runs `./upgrade-vault.sh v1.1.0` and gets a guided update.

**Behavior outline:**
1. Verify `git status` is clean
2. `cd .ai-kb && git fetch --tags && git checkout <new-tag>`
3. Diff `CHANGELOG.md` between old and new tag; show breaking changes
4. If breaking changes detected, print migration instructions
5. Diff `.ai-kb/.docs/user/` vs vault's `.docs/user/`; offer to re-sync
6. `cd ..; git add .ai-kb && git commit -m 'Upgrade ai-kb to <tag>'`
7. Print 'Don't forget to push and notify team.'

### 5. Documentation: `--recursive` is mandatory

The vault repo's `README.md` and `CLAUDE.md` should both prominently state:

> **Cloning this vault:** Always use `git clone --recursive`. If you forget, run `git submodule update --init --recursive` afterward.

Combined with the command preamble check (#3), this is two-layer defense.

---

## GitLab-Specific Adaptations

### Issue creation: GitLab vs GitHub

Idea ② (kb-lint) creates issues for findings. The Haiku design hard-coded GitHub Issues. Need to abstract:

**Interface:**
```python
class IssueReporter(Protocol):
    def create_issue(self, title: str, body: str, labels: list[str]) -> str: ...
    # Returns issue URL

class GitLabReporter(IssueReporter):
    def __init__(self, gitlab_url: str, project_id: str, token: str): ...

class GitHubReporter(IssueReporter):
    def __init__(self, owner: str, repo: str): ...  # Uses MCP

class StdoutReporter(IssueReporter):
    def create_issue(self, ...): print(...)  # For local testing
```

Selection via `.kb/config.toml`:
```toml
[reporter]
type = 'gitlab'  # or 'github' or 'stdout'
gitlab_url = 'https://gitlab.example.com'
project_id = 'team/my-vault'
# Token from env: KB_GITLAB_TOKEN
```

### Setup remote URL configuration

The vault setup script and docs should not hardcode `gitlab.example.com`. Use env var or `.kb/config.toml`:

```toml
[ai_kb]
template_remote = 'https://gitlab.internal.example.com/infra/ai-kb.git'
template_pin = 'v1.0.0'
```

`setup-vault.sh` reads this for the submodule URL.

### Self-hosted considerations

| Concern | Mitigation |
|---|---|
| Internal CA cert for HTTPS | Document `GIT_SSL_CAINFO` setup; provide example |
| SSH vs HTTPS for submodules | Default to SSH; document HTTPS fallback |
| GitLab Runner availability | Document CI requirements (Python, network access) |
| Air-gapped Python deps | Document `pip download` + vendoring pattern |

---

## Migration from Haiku Design

If anyone already adopted the Haiku design (branch-pinned submodule, manual 9-command setup):

1. `cd .ai-kb && git fetch --tags && git checkout v1.0.0` (switch from branch to tag)
2. `cd ..` and re-run `./setup-vault.sh --refresh` (idempotent; updates ci config, etc.)
3. Commit submodule pointer update.

No data loss; only metadata updates.

---

## What This Architecture Does NOT Specify

This is architecture only. The following are deferred to implementation PRs:

- Actual `setup-vault.sh` code (script syntax, error handling, prompts)
- Actual `upgrade-vault.sh` code
- Actual `.gitlab-ci.yml` content (more than the snippet above)
- `IssueReporter` implementations (GitLab API client, error handling)
- `.kb/config.toml` schema and parser
- Test strategy for setup scripts

These are tractable once the architecture is approved.

---

## Open Questions

1. **Vault discovery for `kb-watcher`:** if the watcher runs across multiple vaults, how does it find them? Config file? Walk filesystem? **Recommend:** Each vault's `.kb/` directory is the discovery anchor; watcher is started per-vault, not centrally.

2. **Submodule update notifications:** when ai-kb releases v1.1.0, how do vault owners learn? **Recommend:** GitLab webhook from ai-kb releases -> notification channel; no in-vault auto-check (privacy).

3. **Token management for `kb-lint` GitLab issue creation:** per-vault token vs shared service account? **Recommend:** CI uses `$CI_JOB_TOKEN`; manual runs use per-user PAT in `~/.config/ai-kb/credentials`.

4. **Multiple ai-kb versions in one organization:** can `<team>/vault-a` run v1.0.0 while `<team>/vault-b` runs v1.1.0? **Answer:** Yes, by design — each vault pins its own tag. This is a primary benefit over a shared installed package.

---

## Related Documents

- `opus-redesign-critique.md` — Why Haiku design needed revision
- `idea1-filter-design.md` (forthcoming) — Filter architecture
- `idea2-linter-design.md` (forthcoming) — Linter architecture
- `dual-role-architecture.md` (Haiku, deprecated for GitLab context)
