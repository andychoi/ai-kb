"""
CLI for the Phase 4 webhook service. Adapted from gitweb/gitweb_backend/cli.py.

Subcommands:
  serve     — run the FastAPI app via uvicorn (foreground; meant for launchd)
  rss-poll  — one-shot RSS poll of all configured feeds, then exit (cron-ish)
  version   — print version info

Usage:
  python3 -m bin.webhook.cli serve --port 8765
  python3 -m bin.webhook.cli rss-poll
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path


def _setup_logging(vault: Path, name: str) -> None:
    log_path = vault / ".kb" / f"webhook-{name}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(log_path)],
    )


def _resolve_vault(arg: str | None) -> Path:
    if arg:
        return Path(arg).resolve()
    env = os.environ.get("KB_VAULT_ROOT")
    if env:
        return Path(env).resolve()
    return Path(__file__).resolve().parent.parent.parent


def cmd_serve(args: argparse.Namespace) -> int:
    vault = _resolve_vault(args.vault)
    _setup_logging(vault, "serve")
    # Make app pick up the same vault root.
    os.environ["KB_VAULT_ROOT"] = str(vault)
    try:
        import uvicorn
    except ImportError:
        print("error: uvicorn not installed; run bin/webhook/setup-webhook.sh", file=sys.stderr)
        return 3
    logging.info("kb-webhook serve starting on %s:%d (vault=%s)", args.host, args.port, vault)
    uvicorn.run(
        "bin.webhook.app:app",
        host=args.host,
        port=args.port,
        log_level="info",
        access_log=True,
    )
    return 0


def cmd_rss_poll(args: argparse.Namespace) -> int:
    vault = _resolve_vault(args.vault)
    _setup_logging(vault, "rss-poll")
    from . import rss
    logging.info("rss-poll: vault=%s", vault)
    feeds = rss.load_feeds(vault)
    if not feeds:
        logging.info("no feeds configured in .kb/feeds.json; nothing to do")
        return 0
    results = rss.poll_all(vault)
    for name, paths in results.items():
        logging.info("feed %s: %d new note(s)", name, len(paths))
    return 0


def cmd_version(_args: argparse.Namespace) -> int:
    print("kb-webhook 0.1")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kb-webhook", description="ai-kb Phase 4 receiver")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_serve = sub.add_parser("serve", help="run FastAPI receiver")
    p_serve.add_argument("--host", default="127.0.0.1",
                         help="bind host (default 127.0.0.1 — loopback only)")
    p_serve.add_argument("--port", type=int,
                         default=int(os.environ.get("KB_WEBHOOK_PORT", "8765")),
                         help="bind port (default 8765 or $KB_WEBHOOK_PORT)")
    p_serve.add_argument("--vault", help="vault root override")
    p_serve.set_defaults(fn=cmd_serve)

    p_rss = sub.add_parser("rss-poll", help="one-shot RSS poll of all feeds")
    p_rss.add_argument("--vault", help="vault root override")
    p_rss.set_defaults(fn=cmd_rss_poll)

    p_ver = sub.add_parser("version", help="print version")
    p_ver.set_defaults(fn=cmd_version)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
