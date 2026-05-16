# Dual-Role Architecture: Template System + User Instances

**Date:** 2026-05-16  
**Status:** Design approved; ready for implementation

---

## Problem

ai-kb serves two fundamentally different roles:

1. **Development context** (this repo): Building/improving ai-kb itself
   - Slash commands, automation phases, conventions
   - Contributions by template developers
   - CLAUDE.md, skills, CI/CD for the *system*

2. **Usage context** (when cloned): Users manage their own knowledge bases
   - Users want to *use* ai-kb's commands and infrastructure
   - Different CLAUDE.md guidance (conventions, not development)
   - Per-vault customizations (governance rules, automations)

**Current issue:** Single repo with no clear separation causes confusion.

---

## Solution: Separate Repos with Git Submodule

### Architecture Overview

```
ai-kb/                              ← TEMPLATE SYSTEM (this repo)
├── CLAUDE-TEMPLATE.md              ← For ai-kb developers
├── CLAUDE.md                       ← Vault conventions (shared)
├── .claude/commands/               ← All slash commands
├── bin/                            ← Utilities & automations
├── templates/                      ← YAML note templates
├── .docs/
│   ├── template/                   ← For developers
│   └── user/                       ← Templates for vault owners
└── README.md                       ← Clear: 'Develop' vs. 'Use'

user-vault/                         ← USER'S VAULT (separate repo)
├── CLAUDE.md                       ← Copied & customized per-vault
├── CLAUDE-USER.md                  ← How to use this vault
├── .ai-kb/                         ← Git submodule (pinned version)
├── .claude/
│   ├── settings.json              ← User customizations
│   └── commands/                  ← Symlink to ../.ai-kb/.claude/commands/
├── .kb/
│   ├── state.json                 ← This vault's ingestion state
│   ├── daemon/                     ← Per-vault automations
│   ├── governance/                ← THIS VAULT's rules
│   └── vector-db/                 ← THIS VAULT's embeddings
└── inbox/, notes/, sources/, ...  ← Knowledge content
```

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Separate repos** | Clear role separation |
| **Git submodule** | Explicit version pinning |
| **Pinned branch** (v1-stable) | Stable releases |
| **CLAUDE.md copied** | Users customize per-vault |
| **Commands symlinked** | DRY (don't change per-vault) |
| **Per-vault governance** | Each vault has different standards |
| **Per-vault daemon** | Each vault owns its automations |
| **Setup once, clone many** | Owner sets up; team clones |

---

## Setup Flow

### Vault Owner (First Time)

```bash
# 1. Create vault repo
git init my-vault && cd my-vault

# 2. Add ai-kb as submodule
git submodule add -b v1-stable https://github.com/andychoi/ai-kb .ai-kb

# 3. Copy & customize CLAUDE.md
cp .ai-kb/CLAUDE.md ./CLAUDE.md

# 4. Copy user documentation
mkdir -p .docs/user
cp .ai-kb/.docs/user/* .docs/user/

# 5. Symlink commands
ln -s .ai-kb/.claude/commands .claude/commands

# 6. Copy automation tooling
mkdir -p .kb/daemon
cp .ai-kb/bin/kb-watcher.py .kb/daemon/

# 7. Per-vault governance rules
mkdir -p .kb/governance
cp .ai-kb/.kb/governance/*.example.md .kb/governance/

# 8. Create .claude/settings.json
mkdir -p .claude
# (write settings.json)

# 9. Commit & push
git add . && git commit -m 'Init: vault with ai-kb submodule (v1-stable)'
git remote add origin <vault-repo-url>
git push -u origin main
```

### Team Members

```bash
git clone --recursive <vault-repo-url>
# Everything ready!
```

---

## Versioning & Updates

### Branch Strategy

```
ai-kb/
├── main              ← Development; may be unstable
├── v1-stable         ← Stable v1 release (users pin to this)
├── v2-stable         ← Future; for v2 migrations
└── release/v1.0.0    ← Tagged release points
```

### User Updates

```bash
# Stay on v1-stable
git submodule update --remote
git commit -m 'chore: update ai-kb'

# Upgrade to v2-stable (breaking changes)
git submodule set-branch --branch v2-stable .ai-kb
git submodule update --remote
git commit -m 'chore: upgrade to ai-kb v2'
```

---

## What Changes for Users

| Scenario | Before | After |
|----------|--------|-------|
| **First-time setup** | `git clone ai-kb` | `git init` + submodule add |
| **CLAUDE.md** | Single, shared | Copied per-vault |
| **Team member clone** | `git clone` | `git clone --recursive` |
| **Update template** | `git merge main` (risky) | `git submodule update --remote` (safe) |
| **Customize settings** | Risky | Safe (local repo) |
| **Governance rules** | Global in ai-kb | Per-vault in .kb/governance/ |
| **Automations** | System-wide | Per-vault in .kb/daemon/ |

---

## Success Criteria

- ai-kb is clearly a system (CLAUDE-TEMPLATE.md, .docs/template/)
- Vault owner setup is ~9 commands
- Team member clone is trivial (`--recursive`)
- Per-vault customization is safe
- Updates are explicit & safe

---

## Related

- Enterprise Enhancement Ideas: `.docs/assessments/enterprise-kb-enhancement-ideas.md`
- CLAUDE-TEMPLATE.md (for ai-kb developers)
- CLAUDE.md (vault conventions)
