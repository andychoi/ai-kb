"""
RSS poller — fetches configured feeds, ingests new entries into inbox/.

Trigger: launchd timer (com.aikb.rss-poll.plist) every 30 min, OR the
/webhook/rss/refresh HTTP endpoint (admin-triggered).

Feed config: .kb/feeds.json — committed, hand-edited.
Seen cache:  .kb/seen.json — gitignored; per-feed last-seen entry IDs.

Idempotency key per entry: sha256(feed_url + entry_id-or-link)[:26-base32].
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .ingest import IngestRequest, ingest


@dataclass
class FeedSpec:
    name: str
    url: str
    tags: list[str]


def load_feeds(vault: Path) -> list[FeedSpec]:
    """Read .kb/feeds.json. Schema: [{"name": ..., "url": ..., "tags": [...]}, ...]"""
    feeds_path = vault / ".kb" / "feeds.json"
    if not feeds_path.exists():
        return []
    raw = json.loads(feeds_path.read_text())
    return [FeedSpec(name=f["name"], url=f["url"], tags=f.get("tags", [])) for f in raw]


def _load_seen(vault: Path) -> dict[str, list[str]]:
    p = vault / ".kb" / "seen.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def _save_seen(vault: Path, seen: dict[str, list[str]]) -> None:
    p = vault / ".kb" / "seen.json"
    p.write_text(json.dumps(seen, indent=2) + "\n")


def _fetch(url: str, timeout: float = 15.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ai-kb-rss-poll/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _parse(content: bytes) -> list[dict]:
    """Parse feed bytes into a list of {id, title, link, summary, author}.

    Uses feedparser if available (RSS + Atom + iTunes + Dublin Core), else falls back to
    a tiny stdlib parser that handles RSS 2.0 only. The dependency keeps the install
    surface small without giving up Atom support.
    """
    try:
        import feedparser
    except ImportError:
        return _parse_rss20_stdlib(content)
    parsed = feedparser.parse(content)
    out = []
    for e in parsed.entries:
        out.append({
            "id": e.get("id") or e.get("guid") or e.get("link") or "",
            "title": e.get("title") or "untitled",
            "link": e.get("link") or "",
            "summary": e.get("summary") or e.get("description") or "",
            "author": e.get("author") or "",
        })
    return out


def _parse_rss20_stdlib(content: bytes) -> list[dict]:
    """Fallback RSS 2.0 parser. Best-effort; feedparser is preferred."""
    import xml.etree.ElementTree as ET
    out: list[dict] = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return out
    for item in root.iter("item"):
        out.append({
            "id": _text(item, "guid") or _text(item, "link") or "",
            "title": _text(item, "title") or "untitled",
            "link": _text(item, "link") or "",
            "summary": _text(item, "description") or "",
            "author": _text(item, "author") or "",
        })
    return out


def _text(elem, tag: str) -> str:
    child = elem.find(tag)
    return (child.text or "").strip() if child is not None and child.text else ""


def poll(vault: Path, feed: FeedSpec, max_per_run: int = 20) -> list[Path]:
    """Poll one feed, ingest unseen entries. Returns list of created note paths.

    Cost gate: only ingests entries whose id is not in seen.json[feed.url]. New
    entries get their id appended to seen[feed.url] regardless of ingest outcome,
    so a permanent ingest failure (e.g., git failure) doesn't loop on the same
    entry forever.
    """
    seen = _load_seen(vault)
    known: set[str] = set(seen.get(feed.url, []))
    created: list[Path] = []

    try:
        content = _fetch(feed.url)
    except (urllib.error.URLError, TimeoutError) as e:
        logging.warning("RSS fetch failed for %s: %s", feed.name, e)
        return []

    entries = _parse(content)
    if not entries:
        logging.info("feed %s parsed 0 entries", feed.name)
        return []

    new_entries = [e for e in entries if e["id"] and e["id"] not in known]
    new_entries = new_entries[:max_per_run]
    logging.info("feed %s: %d new entries (of %d total)", feed.name, len(new_entries), len(entries))

    import hashlib
    for entry in new_entries:
        idem_seed = f"{feed.url}|{entry['id']}"
        idem_key = hashlib.sha256(idem_seed.encode()).hexdigest()
        title = f"{feed.name}: {entry['title']}"
        body = (
            f"**Feed**: {feed.name}\n"
            f"**Source**: {feed.url}\n"
            f"**Link**: {entry['link']}\n\n"
            f"## Summary\n\n{entry['summary'] or '_(no summary)_'}\n"
        )
        try:
            path = ingest(vault, IngestRequest(
                source_name="rss",
                idem_key=idem_key,
                title=title,
                body=body,
                note_type="source",
                url=entry["link"],
                author=entry["author"] or None,
                tags=["rss", feed.name.lower().replace(" ", "-")] + feed.tags,
            ))
            if path:
                created.append(path)
        except Exception as e:
            logging.error("ingest failed for %s/%s: %s", feed.name, entry["title"], e)
        # Mark seen regardless of ingest outcome — avoids re-trying broken entries.
        known.add(entry["id"])

    seen[feed.url] = sorted(known)
    _save_seen(vault, seen)
    return created


def poll_all(vault: Path) -> dict[str, list[Path]]:
    """Poll every configured feed. Returns map feed_name -> created paths."""
    out: dict[str, list[Path]] = {}
    for feed in load_feeds(vault):
        out[feed.name] = poll(vault, feed)
    return out
