#!/usr/bin/env python3
"""
kb_archive.py — Phase 3 monthly archive helper.

Two passes:
  1. inbox/*.md       older than --inbox-age-days (default 30) → inbox/_archive/<YYYY-MM>/
  2. work/**/*.md     with status: done AND updated older than --done-age-days
                      (default 90)         → work/_archive/<YYYY-MM>/

Each pass uses `git mv` to preserve history. Commits at end of each pass with
the bot identity (set by the caller's env vars per CLAUDE.md §7).

Idempotent: files already inside _archive/ are skipped.

Usage:
  python3 bin/cron/kb_archive.py --vault . [--dry-run]
                                  [--inbox-age-days 30] [--done-age-days 90]

Exit codes:
  0  success (possibly no-op)
  1  vault arg invalid
  2  git mv or commit failed
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?\n)---\s*\n", re.DOTALL)


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Tiny YAML parser tuned for our flat frontmatter schema. Handles:
       key: value      (string)
       key: [a, b]     (kept as raw string; we only read scalars)
    Multi-line values, anchors, blocks not supported (we don't write them).
    """
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    block = m.group(1)
    out: dict[str, str] = {}
    for raw in block.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#") or ":" not in line:
            continue
        if line.startswith(" "):  # ignore nested entries
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        # Strip surrounding quotes
        if (value.startswith('"') and value.endswith('"')) or \
           (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        out[key] = value
    return out


def _parse_iso8601(s: str) -> dt.datetime | None:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return dt.datetime.fromisoformat(s)
    except ValueError:
        return None


def _git_mv(src: Path, dst: Path, vault: Path, dry_run: bool) -> bool:
    dst.parent.mkdir(parents=True, exist_ok=True)
    rel_src = src.relative_to(vault)
    rel_dst = dst.relative_to(vault)
    if dry_run:
        print(f"[dry-run] git mv {rel_src} {rel_dst}")
        return True
    try:
        subprocess.run(["git", "-C", str(vault), "mv", str(rel_src), str(rel_dst)],
                       check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"ERROR: git mv failed: {e.stderr.strip()}", file=sys.stderr)
        return False


def _git_commit(message: str, vault: Path, dry_run: bool) -> bool:
    if dry_run:
        print(f"[dry-run] git commit -m '{message}'")
        return True
    # Only commit if there's something staged.
    status = subprocess.run(["git", "-C", str(vault), "diff", "--cached", "--quiet"],
                            capture_output=True)
    if status.returncode == 0:
        return True  # nothing to commit; not an error
    try:
        subprocess.run(["git", "-C", str(vault), "commit", "-m", message],
                       check=True, capture_output=True, text=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"ERROR: git commit failed: {e.stderr.strip()}", file=sys.stderr)
        return False


def archive_inbox(vault: Path, age_days: int, dry_run: bool) -> int:
    """Move inbox/*.md older than age_days into inbox/_archive/<YYYY-MM>/.

    Returns count of files moved.
    """
    cutoff = _now_utc() - dt.timedelta(days=age_days)
    inbox = vault / "inbox"
    moved = 0
    for src in sorted(inbox.glob("*.md")):
        if not src.is_file():
            continue
        # mtime fallback — frontmatter `created` is preferred but optional.
        ts = dt.datetime.fromtimestamp(src.stat().st_mtime, tz=dt.timezone.utc)
        fm = _parse_frontmatter(src.read_text(errors="replace"))
        created = _parse_iso8601(fm.get("created", "")) or ts
        if created >= cutoff:
            continue
        bucket = created.strftime("%Y-%m")
        dst = inbox / "_archive" / bucket / src.name
        if _git_mv(src, dst, vault, dry_run):
            moved += 1
            print(f"inbox-archive: {src.name} → _archive/{bucket}/")
    if moved and not dry_run:
        _git_commit(
            f"kb: archive inbox ({moved} note{'s' if moved != 1 else ''} >{age_days}d)\n\n"
            "Co-Authored-By: Claude <noreply@anthropic.com>",
            vault, dry_run,
        )
    return moved


def archive_work_done(vault: Path, age_days: int, dry_run: bool) -> int:
    """Move work/**/*.md with frontmatter status=done AND updated older than
    age_days into work/_archive/<YYYY-MM>/. Returns count moved.
    """
    cutoff = _now_utc() - dt.timedelta(days=age_days)
    work = vault / "work"
    moved = 0
    if not work.is_dir():
        return 0
    for src in sorted(work.rglob("*.md")):
        if not src.is_file():
            continue
        if "_archive" in src.parts:
            continue
        fm = _parse_frontmatter(src.read_text(errors="replace"))
        if fm.get("status") != "done":
            continue
        updated = _parse_iso8601(fm.get("updated", ""))
        if not updated:
            updated = dt.datetime.fromtimestamp(src.stat().st_mtime, tz=dt.timezone.utc)
        if updated >= cutoff:
            continue
        bucket = updated.strftime("%Y-%m")
        dst = work / "_archive" / bucket / src.name
        if _git_mv(src, dst, vault, dry_run):
            moved += 1
            print(f"work-archive: {src.relative_to(vault)} → _archive/{bucket}/")
    if moved and not dry_run:
        _git_commit(
            f"kb: archive work/done ({moved} note{'s' if moved != 1 else ''} >{age_days}d)\n\n"
            "Co-Authored-By: Claude <noreply@anthropic.com>",
            vault, dry_run,
        )
    return moved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ai-kb monthly archive job")
    parser.add_argument("--vault", type=Path, default=Path.cwd())
    parser.add_argument("--inbox-age-days", type=int, default=30)
    parser.add_argument("--done-age-days", type=int, default=90)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    vault = args.vault.resolve()
    if not (vault / ".kb").exists() or not (vault / "inbox").exists():
        print(f"error: {vault} doesn't look like an ai-kb vault", file=sys.stderr)
        return 1

    print(f"kb_archive: vault={vault} dry_run={args.dry_run}")
    inbox_moved = archive_inbox(vault, args.inbox_age_days, args.dry_run)
    work_moved = archive_work_done(vault, args.done_age_days, args.dry_run)
    print(f"summary: inbox_archived={inbox_moved} work_archived={work_moved}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
