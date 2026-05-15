---
id: 01HKZX0000000000MOC0000001
type: ref
title: "Map of Content"
created: 2026-05-15T00:00:00Z
updated: 2026-05-15T00:00:00Z
tags: [moc]
source: manual
idem_key: 01HKZX0000000000MOC0000001
category: concepts
aliases: ["MOC", "Index"]
---

# Map of Content

Top-level Dataview-driven index. Open this file in Obsidian; the queries refresh live as the vault changes.

## Inbox (refile target)

```dataview
TABLE WITHOUT ID file.link AS "Note", file.mtime AS "Modified"
FROM "inbox"
WHERE type
SORT file.mtime DESC
LIMIT 20
```

## Recently touched (last 14 days)

```dataview
TABLE WITHOUT ID file.link AS "Note", type AS "Type", file.mtime AS "Modified"
FROM "" 
WHERE type AND file.mtime > date(today) - dur(14 days)
SORT file.mtime DESC
LIMIT 30
```

## By type

### Personal / research

```dataview
LIST FROM "notes" SORT file.mtime DESC LIMIT 10
```

### Work (active)

```dataview
TABLE WITHOUT ID file.link AS "Note", subtype, status
FROM "work"
WHERE status = "active"
SORT file.mtime DESC
```

### Sources (recently captured)

```dataview
TABLE WITHOUT ID file.link AS "Note", author, captured
FROM "sources"
SORT captured DESC
LIMIT 15
```

### Code intelligence

See [[code/index]] for the per-repo breakdown.

### References

```dataview
LIST FROM "refs" SORT file.name ASC LIMIT 20
```

### Daily

```dataview
LIST FROM "daily" SORT file.name DESC LIMIT 7
```

## Orphans (no incoming links)

```dataview
LIST FROM "" WHERE type AND length(file.inlinks) = 0 AND !contains(file.folder, "daily") AND !contains(file.folder, "inbox") AND !contains(file.folder, "templates")
LIMIT 20
```
