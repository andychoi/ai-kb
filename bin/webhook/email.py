"""
Email-to-vault handler.

Receives JSON POSTs from a mail forwarder (Mailgun, SES, simple SMTP→HTTP bridge,
or a homegrown procmail/MTA hook). Bearer-token auth via KB_EMAIL_TOKEN env var.

Expected JSON schema (minimal; tolerates extras):
  {
    "message_id": "<...@example.com>",   // RFC 5322 Message-ID — idempotency key
    "from":       "Alice <alice@x.com>",
    "to":         "kb-inbox@me.com",
    "subject":    "Article worth keeping",
    "date":       "2026-05-15T14:30:00Z",   // optional, ISO-8601
    "text":       "plain text body",         // preferred for ingestion
    "html":       "<p>html body</p>"         // fallback if no text
  }

Notes:
  - We do NOT parse raw RFC 822 here. Forwarders should pre-extract the JSON
    fields. This keeps the receiver small.
  - HTML bodies are converted to a minimal markdown approximation (paragraphs +
    links only). For rich emails, send the text part.
"""

from __future__ import annotations

import os
import re
from html.parser import HTMLParser
from pathlib import Path

from .ingest import IngestRequest, ingest


def token_from_env() -> str | None:
    return os.environ.get("KB_EMAIL_TOKEN")


def verify_bearer(authorization_header: str | None, expected_token: str | None) -> bool:
    """Bearer token check. Returns False if either side is missing/mismatched."""
    if not expected_token or not authorization_header:
        return False
    parts = authorization_header.split(maxsplit=1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False
    # Constant-time compare to avoid timing leaks on the local-network surface.
    import hmac
    return hmac.compare_digest(parts[1], expected_token)


class _HtmlToMd(HTMLParser):
    """Minimal HTML→markdown. Paragraphs, links, line breaks. Strips everything else."""
    def __init__(self) -> None:
        super().__init__()
        self._out: list[str] = []
        self._in_skip = 0   # script/style depth
        self._href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self._in_skip += 1
        elif tag in ("p", "div", "br"):
            self._out.append("\n")
        elif tag in ("h1", "h2", "h3", "h4"):
            self._out.append("\n\n## ")
        elif tag == "li":
            self._out.append("\n- ")
        elif tag == "a":
            href = dict(attrs).get("href")
            self._href = href
            self._out.append("[")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._in_skip = max(0, self._in_skip - 1)
        elif tag in ("p", "div"):
            self._out.append("\n")
        elif tag in ("h1", "h2", "h3", "h4"):
            self._out.append("\n")
        elif tag == "a" and self._href:
            self._out.append(f"]({self._href})")
            self._href = None

    def handle_data(self, data: str) -> None:
        if self._in_skip == 0:
            self._out.append(data)

    def text(self) -> str:
        s = "".join(self._out)
        s = re.sub(r"[ \t]+", " ", s)
        s = re.sub(r"\n{3,}", "\n\n", s)
        return s.strip()


def html_to_markdown(html: str) -> str:
    p = _HtmlToMd()
    p.feed(html)
    return p.text()


def handle(vault: Path, payload: dict) -> Path | None:
    """Ingest a forwarded email. Returns the created note path or None on idem skip."""
    msg_id = payload.get("message_id") or payload.get("messageId")
    if not msg_id:
        raise ValueError("missing message_id in payload")
    subject = (payload.get("subject") or "(no subject)").strip() or "(no subject)"
    sender = (payload.get("from") or "").strip()
    recipient = (payload.get("to") or "").strip()
    date_iso = payload.get("date")

    text_body = (payload.get("text") or "").strip()
    if not text_body and payload.get("html"):
        text_body = html_to_markdown(payload["html"])
    if not text_body:
        text_body = "_(empty body)_"

    title = f"Email: {subject}"
    body = (
        f"**From**: {sender}\n"
        f"**To**: {recipient}\n"
        f"**Date**: {date_iso or '(unknown)'}\n"
        f"**Message-ID**: `{msg_id}`\n\n"
        f"## Body\n\n{text_body}\n"
    )
    return ingest(vault, IngestRequest(
        source_name="email",
        idem_key=msg_id,
        title=title,
        body=body,
        note_type="source",
        author=sender or None,
        tags=["email"],
    ))
