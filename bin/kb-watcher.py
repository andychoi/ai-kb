#!/usr/bin/env python3
"""
kb-watcher — Phase 2 file-watch daemon for ai-kb.

Watches inbox/ for new/changed .md files, debounces, filters out cheap-skip
cases, then shells `claude -p "/note-refile <paths>"` to drive the refile.

Single-instance via .kb/watcher.pid. Designed for launchd LaunchAgent
(per-user; inherits ~/.claude credentials).

Usage:
    python3 bin/kb-watcher.py [--vault PATH] [--debounce SEC] [--once]

Flags:
    --vault PATH    Vault root (default: parent of this script's dir).
    --debounce SEC  Settle window in seconds (default: 8).
    --once          Process the current inbox/ contents and exit (no watch).
    --dry-run       Log decisions but do not invoke claude or commit.

Exits:
    0 on clean shutdown (SIGTERM/SIGINT) or after --once completes.
    2 if another instance is running.
    3 on missing dependency (watchfiles).
    4 on missing claude CLI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable

# Cost-gate thresholds. Tuned to filter Obsidian's autosave noise without
# missing real drops. If you change these, document in CLAUDE.md.
MIN_FILE_BYTES = 50          # below this, file is presumed mid-write
MIN_FILE_AGE_SEC = 2         # below this since mtime, autosave race likely
DEFAULT_DEBOUNCE_SEC = 8.0   # window to collect related events into one batch


def _setup_logging(vault: Path) -> None:
    log_path = vault / ".kb" / "watcher.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_path),
        ],
    )


def _acquire_pidfile(vault: Path) -> Path:
    pidfile = vault / ".kb" / "watcher.pid"
    if pidfile.exists():
        try:
            existing = int(pidfile.read_text().strip())
            os.kill(existing, 0)  # signal 0 = liveness check
            logging.error("another watcher is running (pid %s); refusing to start", existing)
            sys.exit(2)
        except (ValueError, ProcessLookupError, PermissionError):
            logging.warning("stale pidfile at %s; reclaiming", pidfile)
    pidfile.write_text(str(os.getpid()))
    return pidfile


def _release_pidfile(pidfile: Path) -> None:
    try:
        pidfile.unlink(missing_ok=True)
    except OSError:
        pass


def _read_state(vault: Path) -> dict:
    state_path = vault / ".kb" / "state.json"
    if not state_path.exists():
        return {"schema_version": 1, "processed": {}, "idempotency": {}}
    try:
        return json.loads(state_path.read_text())
    except json.JSONDecodeError:
        logging.error(".kb/state.json malformed; refusing to overwrite. Fix manually.")
        raise


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _should_process(path: Path, state: dict, vault: Path) -> tuple[bool, str]:
    """Cost gate. Returns (should_process, reason).

    State.json keys are vault-relative (e.g. "inbox/foo.md") because that's how
    /note-refile writes them. The lookup MUST use the same form or the sha gate
    never matches and the daemon hot-loops on failed refiles.
    """
    if not path.exists():
        return False, "deleted"
    if path.suffix != ".md":
        return False, f"not markdown ({path.suffix})"
    # Phase 3 monthly job creates inbox/_archive/<YYYY-MM>/ — don't re-process.
    if "/_archive/" in str(path) or path.parent.name.startswith("_"):
        return False, "archived (_-prefix folder)"
    try:
        st = path.stat()
    except OSError as e:
        return False, f"stat failed: {e}"
    if st.st_size < MIN_FILE_BYTES:
        return False, f"too small ({st.st_size}B < {MIN_FILE_BYTES})"
    age = time.time() - st.st_mtime
    if age < MIN_FILE_AGE_SEC:
        return False, f"too fresh ({age:.1f}s < {MIN_FILE_AGE_SEC}s)"
    rel = str(path.relative_to(vault))
    sha = _file_sha(path)
    prior = state.get("processed", {}).get(rel)
    if prior and prior.get("sha") == sha:
        return False, f"unchanged since last refile (sha {sha[:8]})"
    return True, f"sha={sha[:8]} size={st.st_size}B"


def _invoke_refile(paths: Iterable[Path], vault: Path, dry_run: bool) -> int:
    """Shell out to `claude -p "/note-refile <paths>"`. Returns exit code."""
    rel_paths = [str(p.relative_to(vault)) for p in paths]
    cmd = ["claude", "-p", f"/note-refile {' '.join(rel_paths)}"]
    logging.info("invoking: %s", " ".join(cmd))
    if dry_run:
        logging.info("dry-run: skipping claude invocation")
        return 0
    try:
        proc = subprocess.run(
            cmd,
            cwd=vault,
            timeout=300,
            capture_output=True,
            text=True,
        )
        if proc.stdout.strip():
            logging.info("claude stdout: %s", proc.stdout.strip())
        if proc.stderr.strip():
            logging.warning("claude stderr: %s", proc.stderr.strip())
        if proc.returncode != 0:
            logging.error("claude exited %d", proc.returncode)
        return proc.returncode
    except FileNotFoundError:
        logging.error("`claude` CLI not found on PATH; cannot refile")
        return 4
    except subprocess.TimeoutExpired:
        logging.error("claude -p timed out after 300s")
        return 124


def _collect_inbox(vault: Path) -> list[Path]:
    inbox = vault / "inbox"
    if not inbox.is_dir():
        return []
    # Top-level only; _archive/ and other _-prefix subfolders are excluded.
    return sorted(p for p in inbox.glob("*.md") if p.is_file())


def _stamp_attempts(vault: Path, paths: list[Path]) -> None:
    """Mark each path's current sha as 'attempted' in state.json to prevent hot loops.

    /note-refile updates state.json keyed by the NEW path after move. If refile
    succeeds, the inbox file is gone — re-processing skips via 'deleted'. If
    refile fails, the file stays in inbox/ with the same sha, and without this
    stamp we'd retry the same content forever. Re-saving the file changes sha
    and naturally retriggers a real retry.
    """
    state_path = vault / ".kb" / "state.json"
    try:
        state = json.loads(state_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        state = {"schema_version": 1, "processed": {}, "idempotency": {}}
    processed = state.setdefault("processed", {})
    for p in paths:
        if not p.exists():
            continue
        rel = str(p.relative_to(vault))
        processed[rel] = {
            "sha": _file_sha(p),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source": "watch",
        }
    state_path.write_text(json.dumps(state, indent=2) + "\n")


def _process_batch(paths: list[Path], vault: Path, dry_run: bool) -> None:
    state = _read_state(vault)
    to_process: list[Path] = []
    for p in paths:
        ok, reason = _should_process(p, state, vault)
        if ok:
            logging.info("queue: %s (%s)", p.name, reason)
            to_process.append(p)
        else:
            logging.debug("skip:  %s (%s)", p.name, reason)
    if not to_process:
        logging.info("nothing to refile after cost-gate filter")
        return
    rc = _invoke_refile(to_process, vault, dry_run)
    if rc == 0:
        logging.info("refile pass complete: %d file(s)", len(to_process))
    # Stamp attempts (success or failure) to prevent hot-loop on persistent failures.
    # /note-refile may also update state.json keyed by the new (post-move) path;
    # both writes coexist (different keys after a successful move).
    if not dry_run:
        _stamp_attempts(vault, [p for p in to_process if p.exists()])


def _watch_loop(vault: Path, debounce: float, dry_run: bool) -> None:
    try:
        from watchfiles import Change, watch
    except ImportError:
        logging.error("missing dependency: pip install watchfiles>=0.21")
        sys.exit(3)

    inbox = vault / "inbox"
    inbox.mkdir(exist_ok=True)
    logging.info("watching %s (debounce=%.1fs, dry_run=%s)", inbox, debounce, dry_run)

    pending: set[Path] = set()
    last_event = 0.0

    def flush() -> None:
        nonlocal pending
        if pending:
            logging.info("debounce window closed; processing %d path(s)", len(pending))
            _process_batch(sorted(pending), vault, dry_run)
            pending = set()

    # watchfiles.watch yields batches of changes; step_ms controls min interval.
    for changes in watch(
        str(inbox),
        step=int(debounce * 1000),
        rust_timeout=int(debounce * 1500),
        stop_event=_STOP_EVENT,
    ):
        now = time.time()
        for change, path_str in changes:
            p = Path(path_str)
            if p.suffix != ".md":
                continue
            if change == Change.deleted:
                pending.discard(p)
                continue
            pending.add(p)
            last_event = now
        # Flush after the watch's own debounce; watchfiles already batches.
        flush()
    # Final flush on shutdown.
    flush()


class _StopEvent:
    def __init__(self) -> None:
        self._stop = False
    def is_set(self) -> bool:
        return self._stop
    def set(self) -> None:
        self._stop = True


_STOP_EVENT = _StopEvent()


def _install_signal_handlers() -> None:
    def _handler(signum: int, _frame) -> None:
        logging.info("received signal %d; shutting down", signum)
        _STOP_EVENT.set()
    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ai-kb file-watch daemon")
    parser.add_argument("--vault", type=Path, default=None,
                        help="vault root (default: repo containing this script)")
    parser.add_argument("--debounce", type=float, default=DEFAULT_DEBOUNCE_SEC,
                        help=f"settle window seconds (default: {DEFAULT_DEBOUNCE_SEC})")
    parser.add_argument("--once", action="store_true",
                        help="process current inbox/ contents and exit")
    parser.add_argument("--dry-run", action="store_true",
                        help="log decisions; do not invoke claude")
    args = parser.parse_args(argv)

    script_dir = Path(__file__).resolve().parent
    vault = (args.vault or script_dir.parent).resolve()
    if not (vault / ".kb").exists() or not (vault / "inbox").exists():
        print(f"error: {vault} doesn't look like an ai-kb vault (missing .kb/ or inbox/)",
              file=sys.stderr)
        return 1

    _setup_logging(vault)
    if not shutil.which("claude") and not args.dry_run:
        logging.error("`claude` CLI not found on PATH; pass --dry-run to test without it")
        return 4

    pidfile = _acquire_pidfile(vault)
    _install_signal_handlers()
    logging.info("kb-watcher starting (pid %d, vault %s)", os.getpid(), vault)

    try:
        if args.once:
            _process_batch(_collect_inbox(vault), vault, args.dry_run)
        else:
            _watch_loop(vault, args.debounce, args.dry_run)
    finally:
        _release_pidfile(pidfile)
        logging.info("kb-watcher stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
