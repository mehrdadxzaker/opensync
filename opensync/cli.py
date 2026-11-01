"""Machine-readable CLI shared by people, timers, and agent skills."""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import sys

from . import __version__
from .adapters import normalize
from .core import KnowledgeBase, writer_lock
from . import scheduler


def duration(value):
    m = re.fullmatch(r"([1-9][0-9]{0,6})([mhd])", value)
    if not m:
        raise argparse.ArgumentTypeError("Use an interval such as 15m, 6h, or 1d.")
    return int(m[1]) * {"m": 60, "h": 3600, "d": 86400}[m[2]]


def output(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def parser():
    p = argparse.ArgumentParser(prog="kb", description="Sync anything to a local, searchable knowledge base.")
    p.add_argument("--version", action="version", version="OpenSync " + __version__)
    p.add_argument("--home", type=Path, help="Knowledge base directory (also OPENSYNC_HOME).")
    sub = p.add_subparsers(dest="command", required=True)
    sync = sub.add_parser("sync", help="Register sources and index immediately.")
    sync.add_argument("sources", nargs="*", metavar="SOURCE")
    sync.add_argument("--from", dest="from_file", metavar="FILE", help="Import one source per line, or - for stdin. Paths are relative to the list file.")
    sync.add_argument("--every", type=duration, default=21600, metavar="6h")
    sync.add_argument("--no-schedule", action="store_true", help="Skip OS timer setup; use kb worker or an existing scheduler.")
    search = sub.add_parser("search", help="Rank matching passages with citations; JSON output.")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--source", help="Filter by source ID or registered URI.")
    search.add_argument("--any", action="store_true", help="Match any query word instead of all words.")
    read = sub.add_parser("read", help="Read indexed document lines without accessing the original source.")
    read.add_argument("document_id")
    read.add_argument("--start", type=int, default=1)
    read.add_argument("--lines", type=int, default=100)
    sub.add_parser("sources", help="Show sources, freshness, errors, and document counts.")
    refresh = sub.add_parser("refresh", help="Refresh due sources; failed snapshots remain searchable.")
    refresh.add_argument("source", nargs="?", help="Refresh one source immediately.")
    refresh.add_argument("--all", action="store_true", help="Refresh all unpaused sources, even if not due.")
    for name in ("pause", "resume", "remove"):
        cmd = sub.add_parser(name, help={"pause": "Pause automatic refresh.", "resume": "Resume automatic refresh.", "remove": "Remove a registration and its index; originals stay untouched."}[name])
        cmd.add_argument("source")
        if name == "remove":
            cmd.add_argument("--yes", action="store_true", help="Confirm deletion of indexed content.")
    history = sub.add_parser("history", help="Recent successful and failed sync runs.")
    history.add_argument("--source")
    history.add_argument("--limit", type=int, default=20)
    sub.add_parser("status", help="Knowledge base location and counts.")
    sub.add_parser("export", help="Export source registrations as JSON (no document content).")
    schedule = sub.add_parser("schedule", help="Manage the user-level refresh timer.")
    schedule.add_argument("action", choices=["install", "uninstall", "status", "plan"])
    worker = sub.add_parser("worker", help="Refresh due sources until interrupted (portable foreground worker).")
    worker.add_argument("--poll", type=int, default=60, help="Poll seconds, at least 10.")
    worker.add_argument("--once", action="store_true", help="One iteration, useful for containers and tests.")
    return p


def inputs(args):
    for value in args.sources:
        yield value, Path.cwd()
    if args.from_file is not None:
        if args.from_file == "-":
            context, base = nullcontext(sys.stdin), Path.cwd()
        else:
            path = Path(args.from_file).expanduser().resolve()
            context, base = path.open(encoding="utf-8-sig"), path.parent
        with context as stream:
            for line in stream:
                value = line.strip()
                if value and not value.startswith("#"):
                    yield value, base


def sync(kb, args):
    sources, errors = {}, []
    for value, base in inputs(args):
        try:
            uri, kind = normalize(value, base)
            sources[uri] = kind
        except (OSError, ValueError) as exc:
            errors.append({"source": value, "ok": False, "error": str(exc)})
    if not sources and not errors:
        raise ValueError("Supply a source or --from FILE containing at least one source.")
    # Register the whole batch first, so interruption preserves pending work.
    ids = [kb.register(uri, kind, args.every) for uri, kind in sources.items()]
    results = [kb.refresh(ident) for ident in ids]
    timer = {"installed": None, "setup_skipped": True, "note": "Existing timers are unaffected; kb worker also refreshes due sources."}
    if not args.no_schedule and sources:
        try:
            timer = scheduler.install(kb.home)
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            timer = {"installed": False, "error": str(exc), "next_step": "Run kb worker, or fix the timer and run kb schedule install."}
    output({"results": results + errors, "schedule": timer})
    return int(bool(errors) or any(not r["ok"] for r in results) or (not args.no_schedule and timer.get("installed") is False))


def worker(kb, args):
    if args.poll < 10:
        raise ValueError("Worker poll interval must be at least 10 seconds.")
    import threading
    stopped = threading.Event()
    previous = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.signal(sig, lambda *_: stopped.set())
    try:
        while not stopped.is_set():
            with writer_lock(kb.home):
                results = kb.refresh_due()
            if results or args.once:
                output({"results": results})
                sys.stdout.flush()
            if args.once:
                return int(any(not r["ok"] for r in results))
            stopped.wait(args.poll)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0


def run(args):
    with KnowledgeBase(args.home) as kb:
        if args.command == "worker":
            return worker(kb, args)
        mutation = args.command in {"sync", "refresh", "pause", "resume", "remove", "schedule"}
        with writer_lock(kb.home) if mutation else nullcontext():
            if args.command == "sync":
                return sync(kb, args)
            if args.command == "search":
                output(kb.search(args.query, args.limit, args.source, args.any))
            elif args.command == "read":
                output(kb.read(args.document_id, args.start, args.lines))
            elif args.command == "sources":
                output(kb.sources())
            elif args.command == "refresh":
                results = kb.refresh_due(args.all, args.source)
                output({"results": results})
                return int(any(not r["ok"] for r in results))
            elif args.command in {"pause", "resume"}:
                output(kb.pause(args.source, args.command == "pause"))
            elif args.command == "remove":
                if not args.yes:
                    raise ValueError("Use --yes to remove the source registration and indexed content. Original files are untouched.")
                output(kb.remove(args.source))
            elif args.command == "history":
                output(kb.history(args.source, args.limit))
            elif args.command == "status":
                output({"version": __version__, "home": str(kb.home), "sources": len(kb.sources()), "documents": kb.db.execute("SELECT count(*) FROM documents").fetchone()[0], "passages": kb.db.execute("SELECT count(*) FROM passages").fetchone()[0]})
            elif args.command == "export":
                output({"version": 1, "sources": [{"source": r["uri"], "every_seconds": r["period"], "paused": r["paused"]} for r in kb.sources()]})
            elif args.command == "schedule":
                action = args.action
                output({"plan": scheduler.plan(kb.home)} if action == "plan" else getattr(scheduler, action)(kb.home))
    return 0


def main(argv=None):
    # JSON pipes use UTF-8 consistently, including on Windows legacy locales.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        return run(parser().parse_args(argv))
    except KeyboardInterrupt:
        return 130
    except (OSError, ValueError, RuntimeError, sqlite3.Error, subprocess.SubprocessError, LookupError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
