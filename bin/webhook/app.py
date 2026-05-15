"""
FastAPI app — Phase 4 webhook receiver.

Endpoints:
  GET  /healthz                  — liveness probe (no auth)
  POST /webhook/github           — GitHub webhook (HMAC-verified)
  POST /webhook/rss/refresh      — kick an RSS poll (bearer token)
  POST /email/inbound            — email JSON forwarder (bearer token)

All writes go through bin/webhook/ingest.py → inbox/. Phase 2 daemon picks
them up and refiles.

Logging: stdout + .kb/webhook.log (set up by cli.py when running as a service).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import Body, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse

from . import email as email_mod
from . import github as github_mod
from . import rss as rss_mod


def _vault_from_env() -> Path:
    raw = os.environ.get("KB_VAULT_ROOT")
    if raw:
        return Path(raw).resolve()
    # Fall back to two levels up from this file (bin/webhook/app.py → repo root).
    return Path(__file__).resolve().parent.parent.parent


VAULT = _vault_from_env()
LOG = logging.getLogger("kb-webhook")

app = FastAPI(title="ai-kb webhook receiver", version="0.1")


@app.get("/healthz")
def healthz() -> dict:
    return {
        "status": "ok",
        "vault": str(VAULT),
        "vault_present": (VAULT / ".kb" / "state.json").exists(),
    }


@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
    x_github_delivery: str | None = Header(default=None),
) -> JSONResponse:
    """Receive a GitHub webhook. Verifies HMAC, dedups by delivery ID, ingests."""
    raw = await request.body()
    secret = github_mod.secret_from_env()
    if not secret:
        LOG.error("GITHUB_WEBHOOK_SECRET not set; refusing webhook")
        raise HTTPException(status_code=503, detail="webhook secret not configured")
    if not github_mod.verify_signature(raw, x_hub_signature_256, secret):
        LOG.warning("GitHub HMAC verify failed (delivery=%s, event=%s)",
                    x_github_delivery, x_github_event)
        raise HTTPException(status_code=401, detail="invalid signature")
    if not x_github_event or not x_github_delivery:
        raise HTTPException(status_code=400, detail="missing GitHub headers")

    import json
    payload = json.loads(raw)
    try:
        path = github_mod.handle(VAULT, x_github_event, x_github_delivery, payload)
    except Exception as e:
        LOG.exception("github handler failed")
        raise HTTPException(status_code=500, detail=str(e))

    if path is None:
        return JSONResponse({"status": "skipped", "delivery": x_github_delivery,
                             "event": x_github_event})
    return JSONResponse({"status": "ingested", "delivery": x_github_delivery,
                         "event": x_github_event, "path": str(path.relative_to(VAULT))})


@app.post("/webhook/rss/refresh")
async def rss_refresh(
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Trigger a poll of every configured RSS feed. Bearer token required."""
    token = os.environ.get("KB_ADMIN_TOKEN")
    if not email_mod.verify_bearer(authorization, token):
        # Reuse email's bearer verifier; identical semantics, different env var.
        raise HTTPException(status_code=401, detail="bearer auth failed")
    results = rss_mod.poll_all(VAULT)
    return JSONResponse({
        "status": "ok",
        "feeds": {name: [str(p.relative_to(VAULT)) for p in paths]
                  for name, paths in results.items()},
    })


@app.post("/email/inbound")
async def email_inbound(
    payload: dict = Body(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    """Receive a forwarded email (JSON). Bearer token required."""
    token = email_mod.token_from_env()
    if not token:
        raise HTTPException(status_code=503, detail="email token not configured")
    if not email_mod.verify_bearer(authorization, token):
        raise HTTPException(status_code=401, detail="bearer auth failed")
    try:
        path = email_mod.handle(VAULT, payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        LOG.exception("email handler failed")
        raise HTTPException(status_code=500, detail=str(e))
    if path is None:
        return JSONResponse({"status": "skipped (idempotent replay)"})
    return JSONResponse({"status": "ingested", "path": str(path.relative_to(VAULT))})
