"""
GitHub webhook handler.

Verifies HMAC-SHA256 signature against GITHUB_WEBHOOK_SECRET (from env), then
maps interesting events to inbox/ notes:

  push    → one note per push, summarizing branch + commit subjects
  release → one note per release, with name + body
  issues  → one note per opened/edited issue

Idempotency key: X-GitHub-Delivery header (a UUID per delivery; GitHub retries
re-use the same delivery ID).
"""

from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path

from .ingest import IngestRequest, ingest


def verify_signature(body: bytes, header: str | None, secret: str | None) -> bool:
    """Verify GitHub's X-Hub-Signature-256 header. Returns False if anything is off.
    Tolerates missing secret (returns False so caller can decide to allow during local dev).
    """
    if not secret or not header:
        return False
    if not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


def handle(vault: Path, event: str, delivery_id: str, payload: dict) -> Path | None:
    """Route a GitHub event to ingest(). Returns the created note path, or None if skipped
    (idempotent replay OR uninteresting event).
    """
    if not delivery_id:
        raise ValueError("missing X-GitHub-Delivery header")

    if event == "ping":
        # GitHub's connectivity test. Don't ingest; just acknowledge.
        return None

    repo = payload.get("repository", {}).get("full_name", "unknown/repo")
    sender = payload.get("sender", {}).get("login", "unknown")

    if event == "push":
        ref = payload.get("ref", "")
        branch = ref.rsplit("/", 1)[-1] if ref else "?"
        commits = payload.get("commits", []) or []
        title = f"GitHub push: {repo}@{branch} ({len(commits)} commit{'s' if len(commits)!=1 else ''})"
        lines = [f"**Repo**: `{repo}`", f"**Branch**: `{branch}`", f"**Pusher**: {sender}", ""]
        if not commits:
            lines.append("_(no commits in payload — likely a force-push or tag)_")
        else:
            lines.append("## Commits")
            for c in commits:
                sha = c.get("id", "")[:8]
                msg = (c.get("message") or "").split("\n", 1)[0]
                author = (c.get("author") or {}).get("name", "?")
                lines.append(f"- `{sha}` {msg} — _{author}_")
        compare = payload.get("compare")
        if compare:
            lines += ["", f"**Compare**: {compare}"]
        return ingest(vault, IngestRequest(
            source_name="github",
            idem_key=delivery_id,
            title=title,
            body="\n".join(lines),
            note_type="source",
            url=compare or payload.get("repository", {}).get("html_url"),
            author=sender,
            tags=["github", "push", repo.replace("/", "-")],
        ))

    if event == "release":
        action = payload.get("action")
        if action != "published":
            return None
        rel = payload.get("release") or {}
        name = rel.get("name") or rel.get("tag_name") or "untitled release"
        title = f"GitHub release: {repo} — {name}"
        body_text = rel.get("body") or "_(no release notes)_"
        url = rel.get("html_url")
        body = f"**Repo**: `{repo}`\n**Tag**: `{rel.get('tag_name')}`\n**URL**: {url}\n\n## Release notes\n\n{body_text}"
        return ingest(vault, IngestRequest(
            source_name="github",
            idem_key=delivery_id,
            title=title,
            body=body,
            note_type="source",
            url=url,
            author=sender,
            tags=["github", "release", repo.replace("/", "-")],
        ))

    if event == "issues":
        action = payload.get("action")
        if action not in ("opened", "edited"):
            return None
        issue = payload.get("issue") or {}
        num = issue.get("number")
        iss_title = issue.get("title") or "untitled issue"
        title = f"GitHub issue: {repo}#{num} — {iss_title}"
        url = issue.get("html_url")
        body_text = issue.get("body") or "_(no body)_"
        body = (
            f"**Repo**: `{repo}`\n"
            f"**Issue**: #{num} ({action})\n"
            f"**Author**: {sender}\n"
            f"**URL**: {url}\n\n"
            f"## Body\n\n{body_text}"
        )
        return ingest(vault, IngestRequest(
            source_name="github",
            idem_key=delivery_id,
            title=title,
            body=body,
            note_type="source",
            url=url,
            author=sender,
            tags=["github", "issue", repo.replace("/", "-")],
        ))

    # Unhandled event: log only, no note.
    return None


def secret_from_env() -> str | None:
    return os.environ.get("GITHUB_WEBHOOK_SECRET")
