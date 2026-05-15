---
description: Find candidate related notes by content overlap and inject [[wiki-links]] into a "Related" section.
argument-hint: [path] [--threshold=<0.0-1.0>]
allowed-tools: Read, Edit, Bash, Glob, Grep
---

# /note-link — Weave the graph

Scans the vault for notes whose content overlaps with the target note, then injects `[[wiki-links]]` to the strongest candidates into the target's `## Related` section. Read-mostly; only the target file is edited.

## Arguments

- **`[path]`** (optional) — vault-relative path to the target note. Defaults to the most-recently-modified file in `inbox/` if omitted; if `inbox/` is empty, error.
- `--threshold=<0.0-1.0>` (default: `0.3`) — similarity floor for inclusion. Lower = more aggressive linking.

## Behavior

1. **Resolve target.** Read the target note. Extract its title, tags, first H1 + first paragraph, and any explicit references in the body.

2. **Walk the vault** (skip `.git`, `.obsidian`, `.claude`, `.kb`, `.trash`, `templates`). For each candidate:
   - Read its frontmatter `title`, `tags`, and the first H1 + opening paragraph.
   - Compute similarity to the target. Use a combined signal:
     - Tag overlap (Jaccard).
     - Title token overlap.
     - Shared proper nouns / domain terms (case-sensitive identifiers, code symbols).
     - Penalize if candidate is `type: daily` (those are journals, not knowledge).
   - Score 0.0–1.0.

3. **Pick top N candidates** above `--threshold`. Cap at 5 to avoid graph spam. Exclude:
   - The target itself.
   - Notes already linked from the target's body (`[[...]]` scan).
   - Notes in `templates/`.

4. **Edit the target.** Locate the `## Related` section. If absent, append one before the EOF.
   - Insert each candidate as `- [[<candidate-title>]]` — Obsidian resolves by title.
   - Preserve existing entries; dedupe.

5. **Update target frontmatter** `updated` to now.

6. **Commit:**
   ```
   kb: link <path> (+<N> related)
   
   Co-Authored-By: Claude <noreply@anthropic.com>
   ```
   If N=0 (no candidates above threshold), exit 0 with no commit and stdout message `no candidates above threshold`.

7. **Output (stdout):**
   ```
   linked: <path>
   added:
     [[<candidate-1>]] (score: 0.42)
     [[<candidate-2>]] (score: 0.38)
   ```

## Errors → non-zero exit

- Target path doesn't exist / isn't a `.md` file.
- `inbox/` empty when no path given.
- Cannot read/edit target.

## Headless contract

- Non-interactive.
- No commit if no changes were made.
- Bounded: never adds more than 5 links per invocation, even if many candidates score high.
