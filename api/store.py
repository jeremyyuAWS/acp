"""SQLite persistence for scans (StorageProvider local backend; Postgres is the
deploy target per ADR 0001). Stores scan runs, per-file results, issues, and an
idempotent inventory (first/last seen) so re-scans reconcile rather than duplicate.
"""
from __future__ import annotations
import sqlite3
import uuid
from pathlib import Path

DB = Path(__file__).resolve().parent.parent / "acp.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS scan_runs (
  id TEXT PRIMARY KEY, started_at TEXT, completed_at TEXT, source TEXT,
  rubric_name TEXT, rubric_hash TEXT,
  files INT, certifiable INT, uncertain INT, error INT, avg_score INT
);
CREATE TABLE IF NOT EXISTS file_records (
  scan_id TEXT, file TEXT, engine TEXT, status TEXT, score INT,
  compliant INT, skipped_rules INT,
  PRIMARY KEY (scan_id, file)
);
CREATE TABLE IF NOT EXISTS issue_records (
  scan_id TEXT, file TEXT, rule_id TEXT, wcag TEXT, severity TEXT
);
CREATE TABLE IF NOT EXISTS inventory (
  file TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT,
  last_status TEXT, last_score INT
);
"""


class Store:
    def __init__(self, path=DB):
        self.path = str(path)
        with self._c() as c:
            c.executescript(SCHEMA)

    def _c(self):
        c = sqlite3.connect(self.path)
        c.row_factory = sqlite3.Row
        return c

    def save_scan(self, report: dict) -> str:
        sid = uuid.uuid4().hex[:12]
        s = report["summary"]
        with self._c() as c:
            c.execute(
                "INSERT INTO scan_runs(id,started_at,completed_at,source,rubric_name,rubric_hash,"
                "files,certifiable,uncertain,error,avg_score) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (sid, report["started_at"], report["completed_at"], report["source"],
                 report["rubric"]["name"], report["rubric"]["hash"],
                 s["files"], s["certifiable"], s["uncertain"], s["error"], s["avg_score"]))
            for f in report["files"]:
                c.execute(
                    "INSERT INTO file_records(scan_id,file,engine,status,score,compliant,skipped_rules) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (sid, f["file"], f["engine"], f["status"], f["score"],
                     int(f["compliant"]), f["skipped_rules"]))
                for i in f["issues"]:
                    c.execute("INSERT INTO issue_records(scan_id,file,rule_id,wcag,severity) VALUES(?,?,?,?,?)",
                              (sid, f["file"], i["ruleId"], i["wcag"], i["severity"]))
                c.execute(
                    "INSERT INTO inventory(file,first_seen,last_seen,last_status,last_score) VALUES(?,?,?,?,?) "
                    "ON CONFLICT(file) DO UPDATE SET last_seen=excluded.last_seen, "
                    "last_status=excluded.last_status, last_score=excluded.last_score",
                    (f["file"], report["completed_at"], report["completed_at"], f["status"], f["score"]))
        return sid

    def list_scans(self) -> list[dict]:
        with self._c() as c:
            return [dict(r) for r in c.execute(
                "SELECT id,completed_at,source,rubric_hash,files,certifiable,uncertain,error,avg_score "
                "FROM scan_runs ORDER BY completed_at DESC")]

    def get_scan(self, sid: str) -> dict | None:
        with self._c() as c:
            run = c.execute("SELECT * FROM scan_runs WHERE id=?", (sid,)).fetchone()
            if not run:
                return None
            files = [dict(r) for r in c.execute(
                "SELECT file,engine,status,score,compliant,skipped_rules FROM file_records "
                "WHERE scan_id=? ORDER BY file", (sid,))]
            for f in files:
                f["issues"] = [dict(r) for r in c.execute(
                    "SELECT rule_id,wcag,severity FROM issue_records WHERE scan_id=? AND file=?",
                    (sid, f["file"]))]
            return {"run": dict(run), "files": files}

    def inventory(self) -> list[dict]:
        with self._c() as c:
            return [dict(r) for r in c.execute(
                "SELECT file,first_seen,last_seen,last_status,last_score FROM inventory ORDER BY file")]
