"""SQLite (local / test) + Postgres (deploy) persistence for scan results.

Set DATABASE_URL=postgresql://user:pass@host:5432/dbname to use Postgres.
Without it, falls back to a local SQLite file — convenient for local dev.

Postgres is the target for the live demo: it handles concurrent scans without
serializing writes and survives container restarts across all replicas.
"""
from __future__ import annotations
import contextlib
import os
import sqlite3
import uuid
from pathlib import Path

_DATABASE_URL = os.environ.get("DATABASE_URL")
_SQLITE_PATH = Path(__file__).resolve().parent.parent / "acp.db"

# Schema is identical between SQLite and Postgres (UPSERT syntax is the same).
_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS scan_runs (
      id TEXT PRIMARY KEY, started_at TEXT, completed_at TEXT, source TEXT,
      rubric_name TEXT, rubric_hash TEXT,
      files INT, certifiable INT, uncertain INT, error INT, avg_score INT
    )""",
    """CREATE TABLE IF NOT EXISTS file_records (
      scan_id TEXT, file TEXT, engine TEXT, status TEXT, score INT,
      compliant INT, skipped_rules INT,
      PRIMARY KEY (scan_id, file)
    )""",
    """CREATE TABLE IF NOT EXISTS issue_records (
      scan_id TEXT, file TEXT, rule_id TEXT, wcag TEXT, severity TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS inventory (
      file TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT,
      last_status TEXT, last_score INT
    )""",
]

_UPSERT_INV = (
    "INSERT INTO inventory(file,first_seen,last_seen,last_status,last_score) "
    "VALUES(%s,%s,%s,%s,%s) "
    "ON CONFLICT(file) DO UPDATE SET last_seen=EXCLUDED.last_seen, "
    "last_status=EXCLUDED.last_status, last_score=EXCLUDED.last_score"
)


# ── Adapters ────────────────────────────────────────────────────────────────

class _SQLiteAdapter:
    def __init__(self, path: str):
        self._path = path

    def init_schema(self) -> None:
        conn = sqlite3.connect(self._path)
        try:
            cur = conn.cursor()
            for stmt in _SCHEMA:
                cur.execute(stmt)
            conn.commit()
        finally:
            conn.close()

    @contextlib.contextmanager
    def cursor(self):
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(self, cur, sql: str, params: tuple = ()) -> None:
        cur.execute(sql.replace("%s", "?"), params)

    def fetchall(self, cur) -> list[dict]:
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]

    def fetchone(self, cur) -> dict | None:
        if cur.description is None:
            return None
        row = cur.fetchone()
        return dict(zip([d[0] for d in cur.description], row)) if row else None


class _PgAdapter:
    def __init__(self, url: str):
        self._url = url

    def init_schema(self) -> None:
        import psycopg2
        conn = psycopg2.connect(self._url)
        try:
            cur = conn.cursor()
            for stmt in _SCHEMA:
                cur.execute(stmt)
            conn.commit()
        finally:
            conn.close()

    @contextlib.contextmanager
    def cursor(self):
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(self._url)
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(self, cur, sql: str, params: tuple = ()) -> None:
        cur.execute(sql, params)

    def fetchall(self, cur) -> list[dict]:
        return [dict(r) for r in (cur.fetchall() or [])]

    def fetchone(self, cur) -> dict | None:
        row = cur.fetchone()
        return dict(row) if row else None


# ── Store ────────────────────────────────────────────────────────────────────

class Store:
    def __init__(self) -> None:
        self._db: _SQLiteAdapter | _PgAdapter = (
            _PgAdapter(_DATABASE_URL) if _DATABASE_URL else _SQLiteAdapter(str(_SQLITE_PATH))
        )
        self._db.init_schema()

    def save_scan(self, report: dict) -> str:
        sid = uuid.uuid4().hex[:12]
        s = report["summary"]
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO scan_runs(id,started_at,completed_at,source,rubric_name,rubric_hash,"
                "files,certifiable,uncertain,error,avg_score) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (sid, report["started_at"], report["completed_at"], report["source"],
                 report["rubric"]["name"], report["rubric"]["hash"],
                 s["files"], s["certifiable"], s["uncertain"], s["error"], s["avg_score"]))
            for f in report["files"]:
                self._db.execute(cur,
                    "INSERT INTO file_records(scan_id,file,engine,status,score,compliant,skipped_rules) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                    (sid, f["file"], f["engine"], f["status"], f["score"],
                     int(f["compliant"]), f["skipped_rules"]))
                for i in f["issues"]:
                    self._db.execute(cur,
                        "INSERT INTO issue_records(scan_id,file,rule_id,wcag,severity) "
                        "VALUES(%s,%s,%s,%s,%s)",
                        (sid, f["file"], i["ruleId"], i["wcag"], i["severity"]))
                self._db.execute(cur, _UPSERT_INV,
                    (f["file"], report["completed_at"], report["completed_at"],
                     f["status"], f["score"]))
        return sid

    def list_scans(self) -> list[dict]:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT id,completed_at,source,rubric_hash,files,certifiable,uncertain,error,avg_score "
                "FROM scan_runs ORDER BY completed_at DESC")
            return self._db.fetchall(cur)

    def get_scan(self, sid: str) -> dict | None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT * FROM scan_runs WHERE id=%s", (sid,))
            run = self._db.fetchone(cur)
            if not run:
                return None
            self._db.execute(cur,
                "SELECT file,engine,status,score,compliant,skipped_rules FROM file_records "
                "WHERE scan_id=%s ORDER BY file", (sid,))
            files = self._db.fetchall(cur)
            for f in files:
                self._db.execute(cur,
                    "SELECT rule_id,wcag,severity FROM issue_records WHERE scan_id=%s AND file=%s",
                    (sid, f["file"]))
                f["issues"] = self._db.fetchall(cur)
            return {"run": run, "files": files}

    def inventory(self) -> list[dict]:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT file,first_seen,last_seen,last_status,last_score FROM inventory ORDER BY file")
            return self._db.fetchall(cur)

    def rule_findings(self) -> dict:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT id FROM scan_runs ORDER BY completed_at DESC LIMIT 1")
            latest = self._db.fetchone(cur)
            if not latest:
                return {}
            self._db.execute(cur,
                "SELECT rule_id, COUNT(*) AS n FROM issue_records "
                "WHERE scan_id=%s GROUP BY rule_id", (latest["id"],))
            return {r["rule_id"]: r["n"] for r in self._db.fetchall(cur)}
