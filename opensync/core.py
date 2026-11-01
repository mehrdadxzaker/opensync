"""Transactional snapshots and SQLite FTS5 retrieval."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time

from .adapters import snapshot


def default_home() -> Path:
    if os.environ.get("OPENSYNC_HOME"):
        return Path(os.environ["OPENSYNC_HOME"]).expanduser().resolve()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "opensync"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "opensync"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "opensync"


@contextmanager
def writer_lock(home: Path):
    """Serialize writers across processes while WAL readers remain available."""
    with (home / "writer.lock").open("a+b") as stream:
        if sys.platform == "win32":
            import msvcrt
            stream.seek(0)
            stream.write(b"\0")
            stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if sys.platform == "win32":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def chunks(body: str):
    """Bound chunks by lines and characters, retaining extracted line citations."""
    lines = body.splitlines()
    start, buf, size = 1, [], 0
    for number, line in enumerate(lines, 1):
        if buf and (len(buf) >= 60 or size + len(line) > 8000):
            yield start, number - 1, "\n".join(buf)
            start, buf, size = number, [], 0
        if len(line) > 8000:
            if buf:
                yield start, number - 1, "\n".join(buf)
                buf, size = [], 0
            for offset in range(0, len(line), 8000):
                yield number, number, line[offset:offset + 8000]
            start = number + 1
        else:
            if not buf:
                start = number
            buf.append(line)
            size += len(line) + 1
    if buf:
        yield start, len(lines), "\n".join(buf)


class KnowledgeBase:
    def __init__(self, home: Path | None = None):
        self.home = (home or default_home()).expanduser().resolve()
        self.home.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(self.home / "knowledge.sqlite", timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        with self.db:
            self.db.execute("CREATE TABLE IF NOT EXISTS sources (id INTEGER PRIMARY KEY, uri TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, period INTEGER NOT NULL, due REAL NOT NULL DEFAULT 0, last_ok REAL, error TEXT, paused INTEGER NOT NULL DEFAULT 0)")
            self.db.execute("CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE, location TEXT NOT NULL, title TEXT NOT NULL, digest TEXT NOT NULL, body TEXT NOT NULL, updated_at REAL NOT NULL, UNIQUE(source_id,location))")
            self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(document_id UNINDEXED, source_id UNINDEXED, location UNINDEXED, title, line_start UNINDEXED, line_end UNINDEXED, body, tokenize='unicode61 remove_diacritics 2')")
            self.db.execute("CREATE TABLE IF NOT EXISTS runs (id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE, at REAL NOT NULL, ok INTEGER NOT NULL, details TEXT NOT NULL)")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def register(self, uri: str, kind: str, period: int) -> int:
        with self.db:
            self.db.execute("INSERT INTO sources(uri,kind,period) VALUES (?,?,?) ON CONFLICT(uri) DO UPDATE SET period=excluded.period, due=0, paused=0", (uri, kind, period))
        return self.db.execute("SELECT id FROM sources WHERE uri=?", (uri,)).fetchone()[0]

    def source(self, key: str | int):
        row = self.db.execute("SELECT * FROM sources WHERE id=? OR uri=?", (str(key), str(key))).fetchone()
        if row is None:
            raise ValueError(f"Unknown source: {key}. Use kb sources to list IDs.")
        return row

    def refresh(self, source_id: int) -> dict:
        row = self.source(source_id)
        now = time.time()
        try:
            docs = snapshot(row["uri"], row["kind"], self.home)
            old = {r["location"]: r for r in self.db.execute("SELECT id,location,digest FROM documents WHERE source_id=?", (source_id,))}
            stats = {"added": 0, "updated": 0, "deleted": 0, "unchanged": 0}
            with self.db:
                for doc in docs:
                    digest = hashlib.sha256((doc.title + "\0" + doc.body).encode()).hexdigest()
                    prev = old.pop(doc.location, None)
                    if prev and prev["digest"] == digest:
                        stats["unchanged"] += 1
                        continue
                    ident = hashlib.sha256((str(source_id) + "\0" + doc.location).encode()).hexdigest()[:24]
                    if prev:
                        self.db.execute("DELETE FROM passages WHERE document_id=?", (ident,))
                    self.db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title, digest=excluded.digest, body=excluded.body, updated_at=excluded.updated_at", (ident, source_id, doc.location, doc.title, digest, doc.body, now))
                    self.db.executemany("INSERT INTO passages VALUES (?,?,?,?,?,?,?)", ((ident, source_id, doc.location, doc.title, start, end, text) for start, end, text in chunks(doc.body)))
                    stats["updated" if prev else "added"] += 1
                for prev in old.values():
                    self.db.execute("DELETE FROM passages WHERE document_id=?", (prev["id"],))
                    self.db.execute("DELETE FROM documents WHERE id=?", (prev["id"],))
                    stats["deleted"] += 1
                completed = time.time()
                self.db.execute("UPDATE sources SET last_ok=?,due=?,error=NULL WHERE id=?", (completed, completed + row["period"], source_id))
                self._record(source_id, completed, True, stats)
            return {"source_id": source_id, "source": row["uri"], "ok": True, **stats}
        except Exception as exc:
            with self.db:
                # Keep the complete previous snapshot and retry with a bounded delay.
                self.db.execute("UPDATE sources SET due=?,error=? WHERE id=?", (time.time() + min(300, row["period"]), str(exc), source_id))
                self._record(source_id, time.time(), False, {"error": str(exc)})
            return {"source_id": source_id, "source": row["uri"], "ok": False, "error": str(exc)}

    def _record(self, source_id, now, ok, details):
        self.db.execute("INSERT INTO runs(source_id,at,ok,details) VALUES (?,?,?,?)", (source_id, now, int(ok), json.dumps(details)))
        self.db.execute("DELETE FROM runs WHERE source_id=? AND id NOT IN (SELECT id FROM runs WHERE source_id=? ORDER BY id DESC LIMIT 100)", (source_id, source_id))

    def refresh_due(self, force=False, key=None):
        if key is not None:
            selected = [self.source(key)]
        else:
            selected = self.db.execute("SELECT * FROM sources WHERE paused=0" + ("" if force else " AND due <= ?") + " ORDER BY due,id", () if force else (time.time(),)).fetchall()
        return [self.refresh(r["id"]) for r in selected]

    def sources(self):
        now = time.time()
        rows = self.db.execute("SELECT s.*,count(d.id) AS documents FROM sources s LEFT JOIN documents d ON d.source_id=s.id GROUP BY s.id ORDER BY s.id").fetchall()
        return [{**dict(r), "stale": r["last_ok"] is None or r["due"] <= now or r["error"] is not None, "paused": bool(r["paused"])} for r in rows]

    def search(self, query: str, limit=10, source=None, any_word=False):
        words = re.findall(r"[^\W_]+", query, re.UNICODE)
        if not words or len(words) > 64:
            raise ValueError("Search requires 1 to 64 words.")
        if not 1 <= limit <= 100:
            raise ValueError("Limit must be between 1 and 100.")
        match = (" OR " if any_word else " AND ").join('"' + w + '"' for w in words)
        params = [match]
        where = "passages MATCH ?"
        if source is not None:
            where += " AND p.source_id=?"
            params.append(self.source(source)["id"])
        params.append(limit)
        rows = self.db.execute("SELECT p.document_id,p.location,p.title,p.line_start,p.line_end,s.uri AS source,s.last_ok,s.due,s.error,s.paused,snippet(passages,6,'','',' … ',48) AS passage,bm25(passages,0,0,0,2,0,0,1) AS rank FROM passages p JOIN sources s ON s.id=p.source_id WHERE " + where + " ORDER BY rank LIMIT ?", params).fetchall()
        now = time.time()
        return [{"document_id": r["document_id"], "source": r["source"], "location": r["location"], "title": r["title"], "line_start": int(r["line_start"]), "line_end": int(r["line_end"]), "passage": r["passage"], "score": -r["rank"], "last_synced_at": r["last_ok"], "stale": r["last_ok"] is None or r["due"] <= now or r["error"] is not None, "sync_error": r["error"], "paused": bool(r["paused"])} for r in rows]

    def read(self, ident: str, start=1, lines=100):
        if start < 1 or not 1 <= lines <= 1000:
            raise ValueError("Read requires start >= 1 and lines between 1 and 1000.")
        row = self.db.execute("SELECT d.*,s.uri AS source,s.last_ok,s.due,s.error FROM documents d JOIN sources s ON s.id=d.source_id WHERE d.id=?", (ident,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown document: {ident}")
        body = row["body"].splitlines()
        selected = body[start - 1:start - 1 + lines]
        return {"document_id": ident, "source": row["source"], "location": row["location"], "title": row["title"], "line_start": start, "line_end": start + len(selected) - 1, "total_lines": len(body), "text": "\n".join(selected), "last_synced_at": row["last_ok"], "stale": row["last_ok"] is None or row["due"] <= time.time() or row["error"] is not None, "sync_error": row["error"]}

    def pause(self, key, paused=True):
        ident = self.source(key)["id"]
        with self.db:
            self.db.execute("UPDATE sources SET paused=?,due=0 WHERE id=?", (int(paused), ident))
        return {"source_id": ident, "paused": paused}

    def remove(self, key):
        ident = self.source(key)["id"]
        with self.db:
            self.db.execute("DELETE FROM passages WHERE source_id=?", (ident,))
            self.db.execute("DELETE FROM sources WHERE id=?", (ident,))
        return {"source_id": ident, "removed": True, "originals_untouched": True}

    def history(self, key=None, limit=20):
        if not 1 <= limit <= 100:
            raise ValueError("Limit must be between 1 and 100.")
        params = []
        where = ""
        if key is not None:
            where = " WHERE source_id=?"
            params.append(self.source(key)["id"])
        params.append(limit)
        return [{**dict(r), "ok": bool(r["ok"]), "details": json.loads(r["details"])} for r in self.db.execute("SELECT * FROM runs" + where + " ORDER BY id DESC LIMIT ?", params)]
