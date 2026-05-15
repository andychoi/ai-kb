"""
ingest — shared write-to-inbox primitive for Phase 4 webhook handlers.

All three handlers (GitHub, RSS, email) call ingest(...) with a source name,
an idempotency key, and content. ingest() does:

  1. Idempotency check: state.json idempotency{idem_key} AND `git log --grep`
     (belt-and-suspenders; survives state.json loss).
  2. Generate ULID for note id (NOT for idem_key — that comes from caller).
  3. Write to inbox/<YYYYMMDDHHMMSS>-<slug>.md with frontmatter:
     type: source (or as specified), source: webhook:<name>, idem_key: <key>
  4. Update state.json idempotency{} and processed{}.
  5. Commit with message: "kb: add inbox/<slug> [<idem_key>]"

Returns the absolute path to the created note, or None if idempotent-skipped.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

NoteType = Literal["note", "source", "work", "code", "ref", "daily"]

# Crockford base32, excluding I L O U (per ULID spec).
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _new_ulid() -> str:
    """Generate a ULID. Time-prefixed, sortable, collision-resistant.
    Format: 10 chars timestamp (ms) + 16 chars randomness = 26 chars Crockford base32.
    """
    ms = int(time.time() * 1000)
    rand = int.from_bytes(secrets.token_bytes(10), "big")
    n = (ms << 80) | rand
    out: list[str] = []
    for i in range(26):
        out.append(_CROCKFORD[(n >> (5 * i)) & 31])
    return "".join(reversed(out))


def _slugify(text: str, max_len: int = 60) -> str:
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[-\s]+", "-", text).strip("-")
    return (text[:max_len] or "untitled").strip("-")


def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _utc_now_compact() -> str:
    return time.strftime("%Y%m%d%H%M%S", time.gmtime())


@dataclass
class IngestRequest:
    """Payload for the shared ingest() function.

    Fields:
      source_name      logical source label: "github" | "rss" | "email"
      idem_key         caller-provided stable id (GitHub delivery / RSS guid / Message-ID).
                       Will be hashed/truncated to 26-char ULID-like form if longer.
      title            human-readable title (becomes frontmatter title + filename slug)
      body             markdown body for the note (after frontmatter)
      note_type        frontmatter type field (default "source")
      url              optional source URL (for type=source)
      author           optional author (for type=source)
      tags             extra tags to add (in addition to type-tag and source name)
      extra_frontmatter additional frontmatter key/value pairs (kept as scalars)
    """
    source_name: str
    idem_key: str
    title: str
    body: str
    note_type: NoteType = "source"
    url: str | None = None
    author: str | None = None
    tags: list[str] | None = None
    extra_frontmatter: dict[str, str] | None = None


def _normalize_idem_key(raw: str) -> str:
    """Turn an arbitrary external id into a 26-char Crockford-base32 ULID-shaped key.

    Webhook idem_keys (delivery UUIDs, RSS guids, Message-IDs) vary wildly; we hash
    to a fixed-shape token that fits the state.json idempotency map and can be
    grep'd in commit messages without escaping headaches.
    """
    if len(raw) == 26 and all(c in _CROCKFORD for c in raw):
        return raw  # already ULID-shaped
    import hashlib
    digest = hashlib.sha256(raw.encode("utf-8")).digest()
    n = int.from_bytes(digest[:13], "big")  # 13 bytes = 104 bits → 26 base32 chars
    out: list[str] = []
    for i in range(26):
        out.append(_CROCKFORD[(n >> (5 * i)) & 31])
    return "".join(reversed(out))


def _load_state(state_path: Path) -> dict:
    if not state_path.exists():
        return {"schema_version": 1, "processed": {}, "idempotency": {}}
    return json.loads(state_path.read_text())


def _save_state(state_path: Path, state: dict) -> None:
    state_path.write_text(json.dumps(state, indent=2) + "\n")


def _git_log_has_key(vault: Path, key: str) -> bool:
    """Belt-and-suspenders idempotency: even if state.json is wiped, a prior
    commit's message contains [<idem_key>]. grep for it.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(vault), "log", "--all", f"--grep=[{key}]",
             "--fixed-strings", "--max-count=1", "--format=%H"],
            capture_output=True, text=True, timeout=10,
        )
        return bool(result.stdout.strip())
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


def _git_commit(vault: Path, path: Path, message: str) -> None:
    """Commit a single file with the supplied message. Bot identity comes from
    GIT_AUTHOR_NAME / GIT_AUTHOR_EMAIL env (set by the cron/webhook wrappers).
    """
    subprocess.run(["git", "-C", str(vault), "add", str(path.relative_to(vault))],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(vault), "commit", "-m", message],
                   check=True, capture_output=True)


def _render_frontmatter(req: IngestRequest, idem_key: str, ulid: str) -> str:
    now = _utc_now_iso()
    fields: list[tuple[str, str]] = [
        ("id", ulid),
        ("type", req.note_type),
        ("title", f'"{req.title}"'),
        ("created", now),
        ("updated", now),
        ("source", f"webhook:{req.source_name}"),
        ("idem_key", idem_key),
    ]
    tags = list(req.tags or [])
    if req.source_name not in tags:
        tags.append(req.source_name)
    fields.append(("tags", "[" + ", ".join(tags) + "]"))
    if req.url:
        fields.append(("url", req.url))
    if req.author:
        fields.append(("author", f'"{req.author}"'))
    if req.note_type == "source":
        fields.append(("captured", now))
        fields.append(("status", "unread"))
    for k, v in (req.extra_frontmatter or {}).items():
        fields.append((k, v))
    body = "---\n"
    for k, v in fields:
        body += f"{k}: {v}\n"
    body += "---\n\n"
    return body


def ingest(vault: Path, req: IngestRequest) -> Path | None:
    """The shared ingest primitive. Returns path to created note, or None if dedup-skipped."""
    state_path = vault / ".kb" / "state.json"
    state = _load_state(state_path)

    idem_key = _normalize_idem_key(req.idem_key)
    if idem_key in state.get("idempotency", {}):
        return None
    if _git_log_has_key(vault, idem_key):
        # State.json was wiped but prior commit exists. Update state to heal.
        state.setdefault("idempotency", {})[idem_key] = "recovered-from-git-log"
        _save_state(state_path, state)
        return None

    ulid = _new_ulid()
    slug = _slugify(req.title)
    filename = f"{_utc_now_compact()}-{slug}.md"
    inbox = vault / "inbox"
    inbox.mkdir(exist_ok=True)
    target = inbox / filename
    # Collision retry (unlikely given the ms timestamp + slug, but defensive).
    for attempt in range(3):
        if not target.exists():
            break
        ulid = _new_ulid()
        filename = f"{_utc_now_compact()}-{slug}-{attempt + 1}.md"
        target = inbox / filename
    if target.exists():
        raise RuntimeError(f"unable to find unique filename for {slug}")

    content = _render_frontmatter(req, idem_key, ulid) + req.body.rstrip() + "\n"
    target.write_text(content)

    # Update state.json BEFORE commit (so a commit failure still records the dedup key).
    state.setdefault("idempotency", {})[idem_key] = ulid
    state.setdefault("processed", {})[str(target.relative_to(vault))] = {
        "sha": _normalize_idem_key(ulid),
        "ts": _utc_now_iso(),
        "source": f"webhook:{req.source_name}",
    }
    _save_state(state_path, state)

    rel = target.relative_to(vault)
    message = (
        f"kb: add {rel} [{idem_key}]\n\n"
        f"Source: webhook:{req.source_name}\n\n"
        f"Co-Authored-By: Claude <noreply@anthropic.com>"
    )
    _git_commit(vault, target, message)
    return target
