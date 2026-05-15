---
id: 01HKZX0000000000CODE000001
type: ref
title: "Code intelligence — index"
created: 2026-05-15T00:00:00Z
updated: 2026-05-15T00:00:00Z
tags: [moc, code]
source: manual
idem_key: 01HKZX0000000000CODE000001
category: concepts
aliases: ["code index", "code MOC"]
---

# Code intelligence — index

A list of repos for which atomic code-intelligence notes exist. Per-repo MOCs (`code/<repo>/MOC.md`) facet by `kind`.

Two-level surfacing is used here because a single flat MOC over `code/` would explode past ~200 rows once multiple repos are captured.

## Repos

```dataview
TABLE WITHOUT ID repo AS "Repo", length(rows) AS "Notes", max(rows.file.mtime) AS "Last updated"
FROM "code"
WHERE type = "code" AND repo
GROUP BY repo
SORT max(rows.file.mtime) DESC
```

## Per-repo MOCs

```dataview
LIST FROM "code" WHERE file.name = "MOC" SORT file.path ASC
```

## Recent code notes (all repos)

```dataview
TABLE WITHOUT ID file.link AS "Note", repo, kind, file.mtime AS "Modified"
FROM "code"
WHERE type = "code"
SORT file.mtime DESC
LIMIT 20
```
