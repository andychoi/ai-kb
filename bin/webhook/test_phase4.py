"""
test_phase4.py — Phase 4 dynamic acceptance tests.

Spins up FastAPI's TestClient against bin.webhook.app pointed at a fresh tmpdir
"mini-vault", exercises every endpoint with synthetic payloads, asserts files
appear + idempotency holds.

Prints `[PASS] ...` / `[FAIL] ...` lines and exits non-zero on any failure so
the verify-phase4.sh wrapper can aggregate counts.

Run directly:
  .venv-webhook/bin/python3 -m bin.webhook.test_phase4
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


PASS = 0
FAIL = 0


def _ok(msg: str) -> None:
    global PASS
    PASS += 1
    print(f"  \033[32m✓\033[0m {msg}")


def _err(msg: str) -> None:
    global FAIL
    FAIL += 1
    print(f"  \033[31m✗\033[0m {msg}")


def _header(msg: str) -> None:
    print(f"\n\033[1m{msg}\033[0m")


def _setup_tmp_vault() -> Path:
    """Create a minimal vault-shaped tmpdir with git initialized."""
    tmp = Path(tempfile.mkdtemp(prefix="aikb-test-"))
    (tmp / "inbox").mkdir()
    (tmp / ".kb").mkdir()
    (tmp / ".kb" / "state.json").write_text(json.dumps({
        "schema_version": 1, "processed": {}, "idempotency": {}
    }) + "\n")
    # git init + initial commit so `git log --grep` works.
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp, check=True)
    subprocess.run(["git", "config", "user.name", "test-bot"], cwd=tmp, check=True)
    subprocess.run(["git", "config", "user.email", "test@local"], cwd=tmp, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp, check=True)
    return tmp


def _reload_app_with_vault(vault: Path):
    """The app reads KB_VAULT_ROOT at import time, so re-import after setting it."""
    os.environ["KB_VAULT_ROOT"] = str(vault)
    import importlib
    import bin.webhook.app as app_module
    importlib.reload(app_module)
    return app_module


def test_healthz(client) -> None:
    r = client.get("/healthz")
    if r.status_code == 200 and r.json().get("status") == "ok":
        _ok("GET /healthz returns 200 + status:ok")
    else:
        _err(f"GET /healthz unexpected: {r.status_code} {r.text}")


def test_github_no_secret(client) -> None:
    # No env var set → 503
    os.environ.pop("GITHUB_WEBHOOK_SECRET", None)
    r = client.post("/webhook/github",
                    content=b"{}",
                    headers={"X-GitHub-Event": "ping", "X-GitHub-Delivery": "d1",
                             "X-Hub-Signature-256": "sha256=deadbeef"})
    if r.status_code == 503:
        _ok("POST /webhook/github without GITHUB_WEBHOOK_SECRET → 503")
    else:
        _err(f"expected 503, got {r.status_code}: {r.text}")


def test_github_bad_signature(client) -> None:
    os.environ["GITHUB_WEBHOOK_SECRET"] = "test-secret"
    r = client.post("/webhook/github",
                    content=b'{"hello":1}',
                    headers={"X-GitHub-Event": "ping", "X-GitHub-Delivery": "d2",
                             "X-Hub-Signature-256": "sha256=wrong"})
    if r.status_code == 401:
        _ok("POST /webhook/github with bad HMAC → 401")
    else:
        _err(f"expected 401, got {r.status_code}: {r.text}")


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_github_ping(client) -> None:
    secret = os.environ["GITHUB_WEBHOOK_SECRET"]
    body = json.dumps({"zen": "non est ad astra mollis"}).encode()
    r = client.post("/webhook/github",
                    content=body,
                    headers={"X-GitHub-Event": "ping", "X-GitHub-Delivery": "d-ping",
                             "X-Hub-Signature-256": _sign(body, secret),
                             "Content-Type": "application/json"})
    if r.status_code == 200 and r.json().get("status") == "skipped":
        _ok("GitHub 'ping' event → 200, skipped (no note)")
    else:
        _err(f"expected 200 skipped, got {r.status_code}: {r.text}")


def test_github_push(client, vault: Path) -> None:
    secret = os.environ["GITHUB_WEBHOOK_SECRET"]
    payload = {
        "ref": "refs/heads/main",
        "compare": "https://github.com/x/y/compare/abc...def",
        "repository": {"full_name": "x/y", "html_url": "https://github.com/x/y"},
        "sender": {"login": "alice"},
        "commits": [
            {"id": "abcdef1234567890", "message": "feat: add a thing", "author": {"name": "Alice"}},
            {"id": "1234567890abcdef", "message": "fix: a bug", "author": {"name": "Bob"}},
        ],
    }
    body = json.dumps(payload).encode()
    r = client.post("/webhook/github",
                    content=body,
                    headers={"X-GitHub-Event": "push", "X-GitHub-Delivery": "d-push-1",
                             "X-Hub-Signature-256": _sign(body, secret),
                             "Content-Type": "application/json"})
    if r.status_code == 200 and r.json().get("status") == "ingested":
        path = vault / r.json()["path"]
        if path.exists() and "x/y" in path.read_text():
            _ok("GitHub push → note created in inbox/ with repo in body")
        else:
            _err(f"note path {path} missing or lacks expected content")
    else:
        _err(f"GitHub push: expected 200 ingested, got {r.status_code}: {r.text}")


def test_github_push_idempotent(client, vault: Path) -> None:
    """Re-deliver the same delivery ID → no new note, status:skipped."""
    secret = os.environ["GITHUB_WEBHOOK_SECRET"]
    payload = {
        "ref": "refs/heads/main",
        "repository": {"full_name": "x/y"},
        "sender": {"login": "alice"},
        "commits": [{"id": "abc", "message": "msg", "author": {"name": "A"}}],
    }
    body = json.dumps(payload).encode()
    before = len(list((vault / "inbox").glob("*.md")))
    r = client.post("/webhook/github",
                    content=body,
                    headers={"X-GitHub-Event": "push", "X-GitHub-Delivery": "d-push-1",
                             "X-Hub-Signature-256": _sign(body, secret),
                             "Content-Type": "application/json"})
    after = len(list((vault / "inbox").glob("*.md")))
    if r.status_code == 200 and r.json().get("status") == "skipped" and after == before:
        _ok("GitHub push replay → idempotent (no new note)")
    else:
        _err(f"replay expected skipped + same count; got {r.json()}, count {before}→{after}")


def test_email_no_token(client) -> None:
    os.environ.pop("KB_EMAIL_TOKEN", None)
    r = client.post("/email/inbound", json={"message_id": "<x@y>"})
    if r.status_code == 503:
        _ok("POST /email/inbound without KB_EMAIL_TOKEN → 503")
    else:
        _err(f"expected 503, got {r.status_code}: {r.text}")


def test_email_bad_token(client) -> None:
    os.environ["KB_EMAIL_TOKEN"] = "supersecret"
    r = client.post("/email/inbound",
                    json={"message_id": "<x@y>", "subject": "hi", "text": "body"},
                    headers={"Authorization": "Bearer wrong"})
    if r.status_code == 401:
        _ok("POST /email/inbound with wrong bearer → 401")
    else:
        _err(f"expected 401, got {r.status_code}: {r.text}")


def test_email_happy(client, vault: Path) -> None:
    body_text = "This is the body of a forwarded email."
    r = client.post("/email/inbound",
                    json={
                        "message_id": "<unique-msgid-1@example.com>",
                        "from": "Alice <alice@example.com>",
                        "to": "kb-inbox@me",
                        "subject": "An article worth keeping",
                        "date": "2026-05-15T14:00:00Z",
                        "text": body_text,
                    },
                    headers={"Authorization": "Bearer supersecret"})
    if r.status_code == 200 and r.json().get("status") == "ingested":
        path = vault / r.json()["path"]
        if path.exists() and body_text in path.read_text():
            _ok("Email happy-path → note created with body preserved")
        else:
            _err(f"email note path {path} missing or body not in content")
    else:
        _err(f"email happy: expected 200 ingested, got {r.status_code}: {r.text}")


def test_email_idempotent(client, vault: Path) -> None:
    before = len(list((vault / "inbox").glob("*.md")))
    r = client.post("/email/inbound",
                    json={
                        "message_id": "<unique-msgid-1@example.com>",
                        "from": "Alice <alice@example.com>",
                        "subject": "duplicate",
                        "text": "Same Message-ID; should dedup",
                    },
                    headers={"Authorization": "Bearer supersecret"})
    after = len(list((vault / "inbox").glob("*.md")))
    if r.status_code == 200 and "skipped" in r.json().get("status", "") and after == before:
        _ok("Email replay (same Message-ID) → idempotent")
    else:
        _err(f"email replay expected skipped + same count; got {r.json()}, count {before}→{after}")


def test_email_html_fallback(client, vault: Path) -> None:
    r = client.post("/email/inbound",
                    json={
                        "message_id": "<msgid-html-1@example.com>",
                        "from": "Bob <bob@example.com>",
                        "subject": "HTML-only email",
                        "html": "<p>Hello <a href='https://x.test'>world</a></p>",
                    },
                    headers={"Authorization": "Bearer supersecret"})
    if r.status_code == 200 and r.json().get("status") == "ingested":
        path = vault / r.json()["path"]
        content = path.read_text()
        if "[world](https://x.test)" in content:
            _ok("Email HTML→markdown fallback preserves links")
        else:
            _err(f"HTML→md conversion did not yield expected link; content: {content[:300]}")
    else:
        _err(f"email html: expected 200 ingested, got {r.status_code}")


def test_rss_synthetic(vault: Path) -> None:
    """Direct call to rss.poll() with a local file:// feed so we don't hit the network."""
    feed_file = vault / ".kb" / "feed.xml"
    feed_file.write_text("""<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Test feed</title>
<item>
  <guid>rss-entry-1</guid>
  <title>First entry</title>
  <link>https://example.com/1</link>
  <description>Body of first entry.</description>
</item>
<item>
  <guid>rss-entry-2</guid>
  <title>Second entry</title>
  <link>https://example.com/2</link>
  <description>Body of second.</description>
</item>
</channel></rss>""")
    from bin.webhook import rss as rss_mod
    feed = rss_mod.FeedSpec(name="testfeed", url=feed_file.as_uri(), tags=["test"])
    paths = rss_mod.poll(vault, feed)
    if len(paths) == 2:
        _ok(f"RSS poll: 2 entries → 2 inbox notes")
    else:
        _err(f"RSS poll: expected 2 notes, got {len(paths)}")
    # Replay should produce 0.
    paths2 = rss_mod.poll(vault, feed)
    if len(paths2) == 0:
        _ok("RSS poll replay → idempotent (seen.json blocks)")
    else:
        _err(f"RSS replay: expected 0 notes, got {len(paths2)}")


def test_git_log_idem_fallback(client, vault: Path) -> None:
    """If state.json is wiped, the git log --grep fallback should still dedup."""
    # Wipe state.json
    state_path = vault / ".kb" / "state.json"
    state_path.write_text(json.dumps({"schema_version": 1, "processed": {}, "idempotency": {}}) + "\n")
    # Try to redeliver a previously-ingested email
    before = len(list((vault / "inbox").glob("*.md")))
    r = client.post("/email/inbound",
                    json={
                        "message_id": "<unique-msgid-1@example.com>",
                        "from": "Alice <alice@example.com>",
                        "subject": "should still dedup via git log",
                        "text": "after wipe",
                    },
                    headers={"Authorization": "Bearer supersecret"})
    after = len(list((vault / "inbox").glob("*.md")))
    if "skipped" in r.json().get("status", "") and after == before:
        _ok("Idempotency survives state.json wipe (git log --grep fallback)")
    else:
        _err(f"git-log fallback failed; got {r.json()}, count {before}→{after}")


def main() -> int:
    _header("Phase 4 dynamic tests — TestClient against tmp vault")
    # Make `bin.webhook` importable when running this file directly.
    repo_root = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(repo_root))

    vault = _setup_tmp_vault()
    try:
        print(f"  tmp vault: {vault}")
        app_mod = _reload_app_with_vault(vault)
        from fastapi.testclient import TestClient
        client = TestClient(app_mod.app)

        test_healthz(client)

        _header("GitHub webhook")
        test_github_no_secret(client)
        test_github_bad_signature(client)
        test_github_ping(client)
        test_github_push(client, vault)
        test_github_push_idempotent(client, vault)

        _header("Email webhook")
        test_email_no_token(client)
        test_email_bad_token(client)
        test_email_happy(client, vault)
        test_email_idempotent(client, vault)
        test_email_html_fallback(client, vault)

        _header("RSS poller")
        test_rss_synthetic(vault)

        _header("Idempotency fallback")
        test_git_log_idem_fallback(client, vault)
    finally:
        import shutil
        shutil.rmtree(vault, ignore_errors=True)

    print()
    print(f"  passed: {PASS}")
    print(f"  failed: {FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
