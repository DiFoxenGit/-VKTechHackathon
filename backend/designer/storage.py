import json
import re
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException


class Store:
    """Atomic JSON records in SQLite; artifacts are scoped to opaque resource IDs."""

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connection() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, data TEXT, PRIMARY KEY(kind,id))"
            )

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.root / "designer.sqlite3", timeout=30)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def new_id(self):
        return uuid.uuid4().hex

    def directory(self, kind, identifier):
        if not re.fullmatch(r"[a-z_]+", kind) or not re.fullmatch(
            r"[a-f0-9]{32}", identifier
        ):
            raise HTTPException(404, "Resource not found")
        path = self.root / kind / identifier
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get(self, kind, identifier):
        with self.connection() as conn:
            row = conn.execute(
                "SELECT data FROM records WHERE kind=? AND id=?", (kind, identifier)
            ).fetchone()
        if row is None:
            raise HTTPException(404, f"{kind} not found")
        return json.loads(row[0])

    def put(self, kind, data):
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO records VALUES (?,?,?) ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data",
                (kind, data["id"], json.dumps(data, ensure_ascii=False)),
            )
        return data

    def list(self, kind):
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT data FROM records WHERE kind=? ORDER BY rowid DESC", (kind,)
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def page(self, kind, *, offset, limit, exclude=()):
        """Bound rows and strip heavy fields in SQL, before decoding any JSON."""
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError('Invalid page bounds')
        if any(not re.fullmatch(r'[a-z_]+', field) for field in exclude):
            raise ValueError('Invalid projection field')
        expression = 'data'
        paths = tuple('$.' + field for field in exclude)
        if paths:
            expression = 'json_remove(data,' + ','.join('?' for _ in paths) + ')'
        with self.connection() as conn:
            conn.execute('BEGIN')
            total = conn.execute('SELECT count(*) FROM records WHERE kind=?', (kind,)).fetchone()[0]
            rows = conn.execute('SELECT ' + expression + ' FROM records WHERE kind=? '
                                'ORDER BY rowid DESC LIMIT ? OFFSET ?', (*paths, kind, limit, offset)).fetchall()
        return {'total': total, 'items': [json.loads(row[0]) for row in rows]}

    def recover(self):
        for job in self.list("jobs"):
            if job["status"] in ("queued", "running"):
                job.update(
                    status="failed",
                    stage="interrupted",
                    error="Server restarted; submit generation again",
                )
                self.put("jobs", job)
