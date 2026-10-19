#!/usr/bin/env python3
"""Export Sublime Text's unsaved tabs to plain files.

Sublime keeps unsaved buffers only in its session file. This reads that file
(never writes it) and writes one .md file per unsaved buffer into OUT_DIR:

    OUT_DIR/<first-line-slug>-<hash>.md     buffers open in Sublime right now
    OUT_DIR/closed/...                      exports whose buffer has since been
                                            closed or edited; never deleted

Files are named by a hash of their content, so re-running is safe: unchanged
buffers are left alone, and an edited buffer becomes a new file while its old
version moves to closed/.

    sublime_export.py [--out DIR] [--session FILE] [--dry-run]
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SESSION_DIRS = [
    Path.home() / "Library/Application Support/Sublime Text/Local",
    Path.home() / "Library/Application Support/Sublime Text 3/Local",
]
SESSION_NAMES = ["Auto Save Session.sublime_session", "Session.sublime_session"]
DEFAULT_OUT = Path.home() / "notes" / "sublime"
HASH_RE = re.compile(r"-([0-9a-f]{10})\.md$")


def find_session():
    """The most recently written session file: the auto-save one while Sublime runs."""
    found = [d / n for d in SESSION_DIRS for n in SESSION_NAMES if (d / n).exists()]
    return max(found, key=lambda p: p.stat().st_mtime) if found else None


def unsaved_buffers(session):
    """Text of every non-empty buffer that has no file behind it, duplicates dropped."""
    seen = set()
    for window in session.get("windows", []):
        for buf in window.get("buffers", []):
            text = buf.get("contents")
            if buf.get("file") or not text or not text.strip():
                continue
            digest = hashlib.sha1(text.encode()).hexdigest()[:10]
            if digest not in seen:
                seen.add(digest)
                yield digest, buf.get("settings", {}).get("name") or "", text


def slug(name, text):
    """A readable file name from the tab title, else the first line with words in it."""
    lines = [name] + text.splitlines()
    for line in lines:
        words = re.findall(r"[A-Za-z0-9]+", line.lower())
        if words:
            return "-".join(words)[:60].strip("-")
    return "untitled"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"default {DEFAULT_OUT}")
    parser.add_argument("--session", type=Path, help="session file; default: newest in Sublime's Local folder")
    parser.add_argument("--dry-run", action="store_true", help="say what would happen, write nothing")
    args = parser.parse_args()

    session_path = args.session or find_session()
    if not session_path or not session_path.exists():
        sys.exit("no Sublime Text session file found; pass --session")
    with open(session_path, encoding="utf-8") as f:
        session = json.load(f)

    buffers = list(unsaved_buffers(session))
    existing = {m.group(1): p for p in args.out.glob("*.md") if (m := HASH_RE.search(p.name))}
    current = {digest for digest, _, _ in buffers}
    new = [(d, n, t) for d, n, t in buffers if d not in existing]
    gone = [p for d, p in existing.items() if d not in current]

    if not args.dry_run:
        args.out.mkdir(parents=True, exist_ok=True)
        for digest, name, text in new:
            path = args.out / f"{slug(name, text)}-{digest}.md"
            path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
        if gone:
            (args.out / "closed").mkdir(exist_ok=True)
        for path in gone:
            path.rename(args.out / "closed" / path.name)

    would = "would be " if args.dry_run else ""
    print(f"session    {session_path}")
    print(f"unsaved    {len(buffers)} buffers")
    print(f"new        {len(new)} {would}written to {args.out}")
    print(f"unchanged  {len(buffers) - len(new)}")
    print(f"closed     {len(gone)} {would}moved to {args.out / 'closed'}")

if __name__ == "__main__":
    main()
