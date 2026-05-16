#!/usr/bin/env python3
"""kb_cluster — Louvain community detection over the ai-kb wiki-link graph.

Pure helper: walks the vault, parses [[wiki-links]] in notes/, refs/, sources/,
builds an undirected weighted graph keyed by frontmatter `id`, runs Louvain,
emits JSON to stdout. The /kb-cluster slash command consumes this JSON.

Determinism: random_state defaults to 42 so consecutive runs on identical input
produce identical partitions.

Exits 0 on success (including empty graph). Exits 1 on any frontmatter parse
failure (surface paths and let the user run /kb-validate --fix first).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

import community as community_louvain  # python-louvain
import frontmatter  # python-frontmatter
import networkx as nx


SCOPE_DIRS = ("notes", "refs", "sources")

# Per CLAUDE.md §9 plus the auto-generated and chronological dirs we explicitly
# exclude from clustering input.
SKIP_DIRS = {
    ".git", ".obsidian", ".claude", ".kb", ".trash",
    "templates", "node_modules", "__pycache__",
    "inbox", "daily", "work", "code", "clusters", "docs",
}

WIKILINK_RE = re.compile(r"!?\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)


def iter_scoped_notes(vault: Path):
    for scope in SCOPE_DIRS:
        root = vault / scope
        if not root.is_dir():
            continue
        for md in root.rglob("*.md"):
            rel_parts = md.relative_to(vault).parts
            if any(part in SKIP_DIRS for part in rel_parts):
                continue
            yield md


def slugify(title: str) -> str:
    s = unicodedata.normalize("NFKD", title)
    s = s.encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "untitled"


def parse_note(path: Path):
    try:
        post = frontmatter.load(str(path))
    except Exception as exc:
        return None, f"frontmatter parse error: {exc}"
    nid = post.metadata.get("id")
    title = post.metadata.get("title")
    if not nid:
        return None, "missing required field 'id'"
    if not title:
        return None, "missing required field 'title'"
    body = CODE_FENCE_RE.sub("", post.content)
    targets = [m.group(1).strip() for m in WIKILINK_RE.finditer(body)]
    return (str(nid), str(title), targets), None


def build_graph(vault: Path):
    id_by_title: dict[str, str] = {}
    id_to_meta: dict[str, dict] = {}
    raw_links: list[tuple[str, str]] = []
    parse_errors: list[str] = []

    for path in iter_scoped_notes(vault):
        parsed, err = parse_note(path)
        if parsed is None:
            parse_errors.append(f"{path.relative_to(vault)}: {err}")
            continue
        nid, title, targets = parsed
        id_by_title[title] = nid
        id_to_meta[nid] = {"title": title, "path": str(path.relative_to(vault))}
        for tgt_title in targets:
            raw_links.append((nid, tgt_title))

    if parse_errors:
        sys.stderr.write(
            "kb-cluster: frontmatter parse errors in "
            f"{len(parse_errors)} note(s); run `/kb-validate --fix` first:\n  "
            + "\n  ".join(parse_errors[:20]) + "\n"
        )
        sys.exit(1)

    directed: set[tuple[str, str]] = set()
    for src_id, target_title in raw_links:
        tgt_id = id_by_title.get(target_title)
        if not tgt_id or tgt_id == src_id:
            continue
        directed.add((src_id, tgt_id))

    g = nx.Graph()
    for nid in id_to_meta:
        g.add_node(nid)
    for (a, b) in directed:
        if g.has_edge(a, b):
            g[a][b]["weight"] += 1
        else:
            g.add_edge(a, b, weight=1)

    return g, id_to_meta


def partition_graph(graph: nx.Graph, resolution: float, seed: int) -> dict[str, int]:
    if graph.number_of_edges() == 0:
        return {n: i for i, n in enumerate(graph.nodes())}
    return community_louvain.best_partition(
        graph, weight="weight", resolution=resolution, random_state=seed
    )


def main() -> int:
    ap = argparse.ArgumentParser(prog="kb_cluster")
    ap.add_argument("--vault", type=Path, default=Path.cwd(),
                    help="vault root (default: cwd)")
    ap.add_argument("--min-size", type=int, default=3,
                    help="drop clusters with fewer than N members (default 3)")
    ap.add_argument("--resolution", type=float, default=1.0,
                    help="Louvain resolution (default 1.0)")
    ap.add_argument("--seed", type=int, default=42,
                    help="random_state for determinism (default 42)")
    args = ap.parse_args()

    vault = args.vault.resolve()
    graph, meta = build_graph(vault)

    if graph.number_of_nodes() == 0:
        json.dump(
            {"clusters": [], "stats": {"nodes": 0, "edges": 0, "dropped": 0}},
            sys.stdout, indent=2,
        )
        sys.stdout.write("\n")
        return 0

    partition = partition_graph(graph, args.resolution, args.seed)

    by_cluster: dict[int, list[str]] = {}
    for nid, cid in partition.items():
        by_cluster.setdefault(cid, []).append(nid)

    out_clusters = []
    dropped = 0
    for cid, members in by_cluster.items():
        if len(members) < args.min_size:
            dropped += 1
            continue
        sub = graph.subgraph(members)
        ordered = sorted(
            members,
            key=lambda n: (-sub.degree(n, weight="weight"), meta[n]["title"]),
        )
        canonical = ordered[0]
        out_clusters.append({
            "canonical_id": canonical,
            "canonical_title": meta[canonical]["title"],
            "slug": slugify(meta[canonical]["title"]),
            "size": len(members),
            "members": [
                {"id": n, "title": meta[n]["title"], "path": meta[n]["path"]}
                for n in ordered
            ],
        })

    out_clusters.sort(key=lambda c: c["slug"])

    json.dump({
        "clusters": out_clusters,
        "stats": {
            "nodes": graph.number_of_nodes(),
            "edges": graph.number_of_edges(),
            "dropped": dropped,
        },
    }, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
