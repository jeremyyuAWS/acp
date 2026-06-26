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
      files INT, certifiable INT, uncertain INT, error INT, avg_score INT,
      status TEXT, files_done INT
    )""",
    """CREATE TABLE IF NOT EXISTS file_records (
      scan_id TEXT, file TEXT, engine TEXT, status TEXT, score INT,
      compliant INT, skipped_rules INT,
      drive_file_id TEXT,
      remediated_at TEXT,
      drive_write_url TEXT,
      PRIMARY KEY (scan_id, file)
    )""",
    # Fan-out scan pipeline (ADR 0007): scan_runs is created at 'discover' with
    # status=running + a files_done counter, then finalized once all per-file jobs land.
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS status TEXT",
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS files_done INT",
    # Migrations for existing deployments
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS drive_file_id TEXT",
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS remediated_at TEXT",
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS drive_write_url TEXT",
    """CREATE TABLE IF NOT EXISTS issue_records (
      scan_id TEXT, file TEXT, rule_id TEXT, wcag TEXT, severity TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS inventory (
      file TEXT PRIMARY KEY, first_seen TEXT, last_seen TEXT,
      last_status TEXT, last_score INT
    )""",
    """CREATE TABLE IF NOT EXISTS schedule_config (
      key TEXT PRIMARY KEY, value TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS scan_rule_traces (
      scan_id TEXT, file TEXT, rule_id TEXT, rule_name TEXT, plain_name TEXT,
      level TEXT, fix_mode TEXT, outcome TEXT, finding_count INT,
      PRIMARY KEY (scan_id, file, rule_id)
    )""",
    # plain-English label (ADR: non-technical surfaces). Backfilled per scan.
    "ALTER TABLE scan_rule_traces ADD COLUMN IF NOT EXISTS plain_name TEXT",
    """CREATE TABLE IF NOT EXISTS hitl_queue (
      id TEXT PRIMARY KEY,
      created_at TEXT,
      scan_id TEXT,
      file TEXT,
      rule_id TEXT,
      rule_name TEXT,
      finding_count INT,
      status TEXT DEFAULT 'pending',
      reviewed_at TEXT,
      reviewer_note TEXT
    )""",
    # Per-file, per-rule-id (from rule-catalog.json) execution manifest.
    # PASS = rule ran, no findings; FAIL = findings found; ERROR = engine error.
    """CREATE TABLE IF NOT EXISTS scan_file_manifests (
      scan_id TEXT, file TEXT, rule_id TEXT, status TEXT, finding_count INT,
      PRIMARY KEY (scan_id, file, rule_id)
    )""",
    # Admin-controlled platform settings (key/value). e.g. ai_enabled='false'
    # forces deterministic-only mode for the whole platform (overrides per-scan ?ai=).
    """CREATE TABLE IF NOT EXISTS app_settings (
      key TEXT PRIMARY KEY, value TEXT
    )""",
    # Append-only audit log of every consequential decision (HITL review, scan
    # mode, remediation, disposition). Never updated or deleted — the immutable
    # record an auditor asks for. id is monotonic via created_at + a uuid tiebreak.
    """CREATE TABLE IF NOT EXISTS decision_log (
      id TEXT PRIMARY KEY, ts TEXT, actor TEXT, action TEXT,
      scan_id TEXT, file TEXT, rule_id TEXT, detail TEXT
    )""",
    # Durable job queue (ADR 0004). Survives restarts; retried with backoff;
    # exhausted jobs become 'dead' (dead-letter). Timestamps are ISO-8601 TEXT so
    # they sort chronologically and compare portably across Postgres + SQLite.
    """CREATE TABLE IF NOT EXISTS jobs (
      id TEXT PRIMARY KEY, type TEXT, payload TEXT,
      status TEXT DEFAULT 'queued',
      priority INT DEFAULT 100, attempts INT DEFAULT 0, max_attempts INT DEFAULT 5,
      run_after TEXT, locked_at TEXT, locked_by TEXT,
      campaign_id TEXT, batch_id TEXT, scan_id TEXT,
      last_error TEXT, created_at TEXT, updated_at TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_jobs_claim ON jobs(status, run_after, priority)",
    # Sensitive-data (PII) findings per document (ADR 0006). A detection dimension
    # orthogonal to WCAG. samples holds JSON array of MASKED strings only — never
    # raw PII (the masking is enforced in api/pii.py).
    """CREATE TABLE IF NOT EXISTS pii_findings (
      scan_id TEXT, file TEXT, pii_type TEXT, label TEXT,
      count INT, severity TEXT, samples TEXT,
      PRIMARY KEY (scan_id, file, pii_type)
    )""",
]

_UPSERT_INV = (
    "INSERT INTO inventory(file,first_seen,last_seen,last_status,last_score) "
    "VALUES(%s,%s,%s,%s,%s) "
    "ON CONFLICT(file) DO UPDATE SET last_seen=EXCLUDED.last_seen, "
    "last_status=EXCLUDED.last_status, last_score=EXCLUDED.last_score"
)

# Rule catalog — mirrors frontend/src/rules/index.js.
# Used to compute per-file pass/fail/skip traces when saving scan results.
# fix_mode: 'auto' = deterministic, 'ai-assisted' = AI draft + human approve,
#           'human-only' = must be verified by a person.
# plain: a non-technical phrase for the rule, used in Langfuse span names and the
# Grafana "most common problems" panel (persisted to scan_rule_traces.plain_name).
# This is the single source of truth for the plain-English rule labels.
RULE_CATALOG: list[dict] = [
    {"id": "1.1.1",  "name": "Non-text Content",           "level": "A",   "fix_mode": "ai-assisted", "plain": "Images missing a text description"},
    {"id": "1.3.1",  "name": "Info and Relationships",      "level": "A",   "fix_mode": "auto",         "plain": "Structure not marked up (headings, lists, tables)"},
    {"id": "1.4.1",  "name": "Use of Color",                "level": "A",   "fix_mode": "auto",         "plain": "Information shown by color alone"},
    {"id": "1.4.3",  "name": "Contrast (Minimum)",          "level": "AA",  "fix_mode": "auto",         "plain": "Text with low color contrast"},
    {"id": "1.4.4",  "name": "Resize Text",                 "level": "AA",  "fix_mode": "auto",         "plain": "Text that can't be enlarged"},
    {"id": "1.4.10", "name": "Reflow",                      "level": "AA",  "fix_mode": "auto",         "plain": "Content that doesn't reflow on small screens"},
    {"id": "1.4.11", "name": "Non-text Contrast",           "level": "AA",  "fix_mode": "ai-assisted", "plain": "Buttons or icons with low contrast"},
    {"id": "1.4.12", "name": "Text Spacing",                "level": "AA",  "fix_mode": "auto",         "plain": "Text spacing can't be adjusted"},
    {"id": "2.1.1",  "name": "Keyboard",                    "level": "A",   "fix_mode": "auto",         "plain": "Can't be used with a keyboard"},
    {"id": "2.4.2",  "name": "Page Titled",                 "level": "A",   "fix_mode": "auto",         "plain": "Missing a page or document title"},
    {"id": "2.4.3",  "name": "Focus Order",                 "level": "A",   "fix_mode": "auto",         "plain": "Illogical keyboard navigation order"},
    {"id": "2.4.4",  "name": "Link Purpose (In Context)",   "level": "A",   "fix_mode": "ai-assisted", "plain": "Unclear link text (e.g. 'click here')"},
    {"id": "2.4.6",  "name": "Headings and Labels",         "level": "AA",  "fix_mode": "auto",         "plain": "Unclear headings or labels"},
    {"id": "2.4.7",  "name": "Focus Visible",               "level": "AA",  "fix_mode": "auto",         "plain": "No visible keyboard focus indicator"},
    {"id": "3.1.1",  "name": "Language of Page",            "level": "A",   "fix_mode": "auto",         "plain": "Document language not set"},
    {"id": "3.1.4",  "name": "Abbreviations",               "level": "AAA", "fix_mode": "auto",         "plain": "Unexplained abbreviations"},
    {"id": "4.1.2",  "name": "Name, Role, Value",           "level": "A",   "fix_mode": "ai-assisted", "plain": "Controls missing names/roles for assistive tech"},
]

def _extract_sc(wcag: str) -> str:
    """Extract the 'X.Y.Z' SC number from any wcag field format.
    Handles: '1.1.1', '1.1.1 Non-text Content', 'SC_1_1_1', 'wcag111'."""
    import re as _re
    m = _re.search(r'(\d+)[._](\d+)[._](\d+)', wcag or '')
    return f"{m.group(1)}.{m.group(2)}.{m.group(3)}" if m else ""


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
    # Keep a small pool (2–5 connections) so ACA's single-replica container
    # never exhausts the Azure Postgres max_connections limit (~50 on small SKUs).
    _MIN_CONN = 1
    _MAX_CONN = 5

    def __init__(self, url: str):
        # Strip query params that confuse psycopg2 (e.g. ?sslmode=require can
        # get mangled when stored via az containerapp secret set). Pass them as
        # explicit kwargs instead.
        import urllib.parse as _up
        parsed = _up.urlparse(url)
        params = dict(_up.parse_qsl(parsed.query))
        clean = parsed._replace(query="").geturl()
        self._url = clean
        self._ssl_kwargs: dict = {}
        if "sslmode" in params:
            self._ssl_kwargs["sslmode"] = params["sslmode"]
        self._pool = None  # lazy init after schema is applied

    def _connect_kwargs(self) -> dict:
        return {"dsn": self._url, **self._ssl_kwargs}

    def _get_pool(self):
        if self._pool is None:
            import psycopg2.pool
            self._pool = psycopg2.pool.ThreadedConnectionPool(
                self._MIN_CONN, self._MAX_CONN, self._url, **self._ssl_kwargs)
        return self._pool

    def init_schema(self) -> None:
        import psycopg2
        conn = psycopg2.connect(self._url, **self._ssl_kwargs)
        try:
            cur = conn.cursor()
            for stmt in _SCHEMA:
                cur.execute(stmt)
            conn.commit()
        finally:
            conn.close()

    @contextlib.contextmanager
    def cursor(self):
        import psycopg2.extras
        pool = self._get_pool()
        conn = pool.getconn()
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            pool.putconn(conn)

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

    def _save_file_manifest(self, cur, sid: str, f: dict, catalog: dict) -> None:
        """Compute and persist the per-rule execution manifest for one file."""
        ext = Path(f["file"]).suffix.lower().lstrip(".")
        rules = catalog.get(ext, [])
        if not rules:
            return
        # Which rule IDs actually produced findings (FAIL)?
        fail_ids = {i["ruleId"] for i in f.get("issues", [])}
        # Which rule IDs had engine errors (ERROR)?
        error_ids = {e["rule"] for e in f.get("errors", [])
                     if isinstance(e, dict) and e.get("rule")}
        # Finding count per rule
        counts: dict[str, int] = {}
        for i in f.get("issues", []):
            counts[i["ruleId"]] = counts.get(i["ruleId"], 0) + 1
        for rule in rules:
            rid = rule["id"]
            if rid in error_ids:
                status = "ERROR"
            elif rid in fail_ids:
                status = "FAIL"
            else:
                status = "PASS"
            self._db.execute(cur,
                "INSERT INTO scan_file_manifests(scan_id,file,rule_id,status,finding_count) "
                "VALUES(%s,%s,%s,%s,%s) "
                "ON CONFLICT(scan_id,file,rule_id) DO UPDATE SET "
                "status=EXCLUDED.status,finding_count=EXCLUDED.finding_count",
                (sid, f["file"], rid, status, counts.get(rid, 0)))

    def save_scan(self, report: dict) -> str:
        # Reuse the scan_id generated in run_scan() so the Langfuse trace ID
        # and the DB scan_id are the same — enables join in Langfuse by scan_id.
        sid = report.pop("_scan_id", None) or uuid.uuid4().hex[:12]
        s = report["summary"]
        import json as _json
        catalog = _json.loads(
            (Path(__file__).resolve().parent.parent / "config" / "rule-catalog.json").read_text()
        )
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO scan_runs(id,started_at,completed_at,source,rubric_name,rubric_hash,"
                "files,certifiable,uncertain,error,avg_score,status,files_done) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'done',%s)",
                (sid, report["started_at"], report["completed_at"], report["source"],
                 report["rubric"]["name"], report["rubric"]["hash"],
                 s["files"], s["certifiable"], s["uncertain"], s["error"], s["avg_score"], s["files"]))
            for f in report["files"]:
                self._db.execute(cur,
                    "INSERT INTO file_records(scan_id,file,engine,status,score,compliant,skipped_rules,drive_file_id) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                    (sid, f["file"], f["engine"], f["status"], f["score"],
                     int(f["compliant"]), f["skipped_rules"], f.get("drive_file_id")))
                for i in f["issues"]:
                    self._db.execute(cur,
                        "INSERT INTO issue_records(scan_id,file,rule_id,wcag,severity) "
                        "VALUES(%s,%s,%s,%s,%s)",
                        (sid, f["file"], i["ruleId"], i["wcag"], i["severity"]))
                # Per-rule trace: one row per catalog rule per file — PASS/FAIL/SKIP.
                sc_counts: dict[str, int] = {}
                for i in f["issues"]:
                    sc = _extract_sc(i.get("wcag", ""))
                    if sc:
                        sc_counts[sc] = sc_counts.get(sc, 0) + 1
                for rule in RULE_CATALOG:
                    rid = rule["id"]
                    count = sc_counts.get(rid, 0)
                    outcome = "FAIL" if count > 0 else "PASS"
                    self._db.execute(cur,
                        "INSERT INTO scan_rule_traces(scan_id,file,rule_id,rule_name,plain_name,level,fix_mode,outcome,finding_count) "
                        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT(scan_id,file,rule_id) DO UPDATE SET outcome=EXCLUDED.outcome,finding_count=EXCLUDED.finding_count",
                        (sid, f["file"], rid, rule["name"], rule.get("plain"), rule["level"], rule["fix_mode"], outcome, count))
                self._save_file_manifest(cur, sid, f, catalog)
                # Sensitive-data (PII) findings — masked samples only (ADR 0006).
                for pf in (f.get("pii") or {}).get("findings", []):
                    self._db.execute(cur,
                        "INSERT INTO pii_findings(scan_id,file,pii_type,label,count,severity,samples) "
                        "VALUES(%s,%s,%s,%s,%s,%s,%s) "
                        "ON CONFLICT(scan_id,file,pii_type) DO UPDATE SET "
                        "count=EXCLUDED.count,severity=EXCLUDED.severity,samples=EXCLUDED.samples",
                        (sid, f["file"], pf["type"], pf["label"], pf["count"],
                         pf["severity"], _json.dumps(pf["samples"])))
                self._db.execute(cur, _UPSERT_INV,
                    (f["file"], report["completed_at"], report["completed_at"],
                     f["status"], f["score"]))
        return sid

    # ── Fan-out scan pipeline (ADR 0007) ──────────────────────────────────────
    def init_scan_run(self, scan_id: str, source: str, total: int, started_at: str,
                      rubric_name: str, rubric_hash: str) -> None:
        """Create the scan_runs row at discover time (status=running, counter=0)."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO scan_runs(id,started_at,source,rubric_name,rubric_hash,files,files_done,status) "
                "VALUES(%s,%s,%s,%s,%s,%s,0,'running') ON CONFLICT(id) DO NOTHING",
                (scan_id, started_at, source, rubric_name, rubric_hash, total))

    def save_file_result(self, scan_id: str, f: dict, completed_at: str) -> None:
        """Persist one assessed file (same shape save_scan writes). Idempotent so a
        retried scan_file job doesn't double-insert."""
        import json as _json
        catalog = _json.loads(
            (Path(__file__).resolve().parent.parent / "config" / "rule-catalog.json").read_text())
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO file_records(scan_id,file,engine,status,score,compliant,skipped_rules,drive_file_id) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(scan_id,file) DO UPDATE SET "
                "engine=EXCLUDED.engine,status=EXCLUDED.status,score=EXCLUDED.score,"
                "compliant=EXCLUDED.compliant,skipped_rules=EXCLUDED.skipped_rules,drive_file_id=EXCLUDED.drive_file_id",
                (scan_id, f["file"], f["engine"], f["status"], f["score"],
                 int(f["compliant"]), f["skipped_rules"], f.get("drive_file_id")))
            self._db.execute(cur, "DELETE FROM issue_records WHERE scan_id=%s AND file=%s", (scan_id, f["file"]))
            for i in f.get("issues", []):
                self._db.execute(cur,
                    "INSERT INTO issue_records(scan_id,file,rule_id,wcag,severity) VALUES(%s,%s,%s,%s,%s)",
                    (scan_id, f["file"], i["ruleId"], i["wcag"], i["severity"]))
            sc_counts: dict[str, int] = {}
            for i in f.get("issues", []):
                sc = _extract_sc(i.get("wcag", ""))
                if sc:
                    sc_counts[sc] = sc_counts.get(sc, 0) + 1
            for rule in RULE_CATALOG:
                rid = rule["id"]; count = sc_counts.get(rid, 0)
                outcome = "FAIL" if count > 0 else "PASS"
                self._db.execute(cur,
                    "INSERT INTO scan_rule_traces(scan_id,file,rule_id,rule_name,plain_name,level,fix_mode,outcome,finding_count) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(scan_id,file,rule_id) DO UPDATE SET "
                    "outcome=EXCLUDED.outcome,finding_count=EXCLUDED.finding_count",
                    (scan_id, f["file"], rid, rule["name"], rule.get("plain"), rule["level"],
                     rule["fix_mode"], outcome, count))
            self._save_file_manifest(cur, scan_id, f, catalog)
            for pf in (f.get("pii") or {}).get("findings", []):
                self._db.execute(cur,
                    "INSERT INTO pii_findings(scan_id,file,pii_type,label,count,severity,samples) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(scan_id,file,pii_type) DO UPDATE SET "
                    "count=EXCLUDED.count,severity=EXCLUDED.severity,samples=EXCLUDED.samples",
                    (scan_id, f["file"], pf["type"], pf["label"], pf["count"], pf["severity"],
                     _json.dumps(pf["samples"])))
            self._db.execute(cur, _UPSERT_INV,
                (f["file"], completed_at, completed_at, f["status"], f["score"]))

    def bump_files_done(self, scan_id: str) -> tuple[int, int]:
        """Atomically increment the done counter; returns (done, total enqueued)."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE scan_runs SET files_done=COALESCE(files_done,0)+1 WHERE id=%s "
                "RETURNING files_done, files", (scan_id,))
            row = self._db.fetchone(cur)
        return (row["files_done"], row["files"]) if row else (0, 0)

    def finalize_scan_run(self, scan_id: str, completed_at: str) -> dict:
        """Aggregate per-file results into the scan_runs summary — matches
        Rubric.aggregate (certifiable=Σcompliant, uncertain/error by status,
        avg=mean of scored). 'files' becomes the count actually analysed."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE scan_runs SET status='done', completed_at=%s, "
                "files=(SELECT COUNT(*) FROM file_records WHERE scan_id=%s), "
                "certifiable=(SELECT COALESCE(SUM(compliant),0) FROM file_records WHERE scan_id=%s), "
                "uncertain=(SELECT COUNT(*) FROM file_records WHERE scan_id=%s AND status='uncertain'), "
                "error=(SELECT COUNT(*) FROM file_records WHERE scan_id=%s AND status='error'), "
                "avg_score=(SELECT ROUND(AVG(score)) FROM file_records WHERE scan_id=%s AND score IS NOT NULL) "
                "WHERE id=%s",
                (completed_at, scan_id, scan_id, scan_id, scan_id, scan_id, scan_id))
            self._db.execute(cur,
                "SELECT files,certifiable,uncertain,error,avg_score FROM scan_runs WHERE id=%s", (scan_id,))
            return self._db.fetchone(cur) or {}

    def pii_summary(self, sid: str | None = None) -> dict:
        """Sensitive-data rollup: docs affected, total items, and per-type counts.
        Scoped to one scan when sid is given, else across all scans."""
        where, params = ("WHERE scan_id=%s", (sid,)) if sid else ("", ())
        with self._db.cursor() as cur:
            self._db.execute(cur,
                f"SELECT COUNT(DISTINCT file) AS docs, COALESCE(SUM(count),0) AS items "
                f"FROM pii_findings {where}", params)
            roll = self._db.fetchone(cur) or {"docs": 0, "items": 0}
            self._db.execute(cur,
                f"SELECT pii_type, label, COALESCE(SUM(count),0) AS count, "
                f"COUNT(DISTINCT file) AS docs FROM pii_findings {where} "
                f"GROUP BY pii_type, label ORDER BY count DESC", params)
            by_type = self._db.fetchall(cur)
        return {"documents": roll["docs"], "items": roll["items"], "by_type": by_type}

    def list_pii(self, sid: str) -> list[dict]:
        """Per-document sensitive-data findings for one scan (masked samples)."""
        import json as _json
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT file, pii_type, label, count, severity, samples "
                "FROM pii_findings WHERE scan_id=%s ORDER BY file, count DESC", (sid,))
            rows = self._db.fetchall(cur)
        for r in rows:
            try:
                r["samples"] = _json.loads(r["samples"]) if r.get("samples") else []
            except Exception:
                r["samples"] = []
        return rows

    # Tables holding scan results / activity (what the dashboards chart). Cleared by
    # reset_analytics. Deliberately EXCLUDES app_settings + schedule_config so a
    # reset wipes data but keeps configuration (worker count, AI mode, schedule).
    _ANALYTICS_TABLES = ["scan_runs", "file_records", "issue_records", "scan_rule_traces",
                         "scan_file_manifests", "pii_findings", "hitl_queue",
                         "decision_log", "inventory", "jobs"]

    def reset_analytics(self) -> list[str]:
        """Clear all scan results / activity so the Grafana + in-app charts start
        fresh. Keeps settings + schedule. Returns the cleared table names."""
        with self._db.cursor() as cur:
            for t in self._ANALYTICS_TABLES:
                self._db.execute(cur, f"DELETE FROM {t}")
        return list(self._ANALYTICS_TABLES)

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
                "SELECT file,engine,status,score,compliant,skipped_rules,remediated_at,drive_write_url "
                "FROM file_records WHERE scan_id=%s ORDER BY file", (sid,))
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

    def get_schedule(self) -> dict:
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT key, value FROM schedule_config")
            rows = {r["key"]: r["value"] for r in self._db.fetchall(cur)}
        return {
            "enabled": rows.get("enabled", "false") == "true",
            "interval_minutes": int(rows.get("interval_minutes", "60")),
        }

    def save_schedule(self, enabled: bool, interval_minutes: int) -> None:
        with self._db.cursor() as cur:
            for k, v in [("enabled", str(enabled).lower()), ("interval_minutes", str(interval_minutes))]:
                self._db.execute(cur,
                    "INSERT INTO schedule_config(key,value) VALUES(%s,%s) "
                    "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value", (k, v))

    def get_scan_traces(self, scan_id: str, file: str | None = None) -> list[dict]:
        with self._db.cursor() as cur:
            if file:
                self._db.execute(cur,
                    "SELECT rule_id,rule_name,plain_name,level,fix_mode,outcome,finding_count "
                    "FROM scan_rule_traces WHERE scan_id=%s AND file=%s ORDER BY rule_id",
                    (scan_id, file))
            else:
                self._db.execute(cur,
                    "SELECT file,rule_id,rule_name,plain_name,level,fix_mode,outcome,finding_count "
                    "FROM scan_rule_traces WHERE scan_id=%s ORDER BY file,rule_id",
                    (scan_id,))
            return self._db.fetchall(cur)

    def get_trace_row(self, scan_id: str, file: str, rule_id: str) -> dict | None:
        """Return a single scan_rule_traces row for the AI explain endpoint."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT rule_id,rule_name,level,fix_mode,outcome,finding_count "
                "FROM scan_rule_traces WHERE scan_id=%s AND file=%s AND rule_id=%s",
                (scan_id, file, rule_id))
            rows = self._db.fetchall(cur)
        return rows[0] if rows else None

    def get_issue_rule_ids(self, scan_id: str, file: str, wcag_sc: str) -> list[str]:
        """Return the engine-level ruleIds (e.g. HTML_MISSING_LANG) for a given
        WCAG SC in a specific file, so the AI prompt can cite concrete check names."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT DISTINCT rule_id FROM issue_records "
                "WHERE scan_id=%s AND file=%s AND wcag LIKE %s",
                (scan_id, file, f"{wcag_sc}%"))
            rows = self._db.fetchall(cur)
        return [r["rule_id"] for r in rows]

    def get_file_drive_id(self, scan_id: str, file: str) -> str | None:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT drive_file_id FROM file_records WHERE scan_id=%s AND file=%s",
                (scan_id, file))
            row = self._db.fetchone(cur)
        return row["drive_file_id"] if row else None

    def record_remediation(self, scan_id: str, file: str, drive_write_url: str | None = None) -> str:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE file_records SET remediated_at=%s, drive_write_url=%s "
                "WHERE scan_id=%s AND file=%s",
                (now, drive_write_url, scan_id, file))
        return now

    def _full_catalog_rules(self) -> dict[str, list[dict]]:
        """Load rule-catalog.json grouped by engine (docx/pptx/xlsx/pdf/html)."""
        import json as _json
        cat = _json.loads(
            (Path(__file__).resolve().parent.parent / "config" / "rule-catalog.json").read_text()
        )
        return {k: v for k, v in cat.items() if isinstance(v, list)}

    def get_scan_manifest(self, scan_id: str) -> dict:
        """Return per-file rule-execution manifest for a scan.

        Each file lists every catalog rule and an explicit status:
          PASS / FAIL / ERROR  — the rule applies to this file's format and ran
          NOT_APPLICABLE       — the rule belongs to a different format (e.g. a
                                 PPTX rule against a .docx). Recorded explicitly so
                                 an auditor can see a rule was *considered*, not
                                 silently omitted. N/A does not count against
                                 completeness (completeness = checked / applicable).
        """
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT file, rule_id, status, finding_count "
                "FROM scan_file_manifests WHERE scan_id=%s ORDER BY file, rule_id",
                (scan_id,))
            rows = self._db.fetchall(cur)
            # File extensions in this scan (to know each file's applicable rule set).
            self._db.execute(cur,
                "SELECT DISTINCT file FROM scan_file_manifests WHERE scan_id=%s", (scan_id,))
            scan_files = [r["file"] for r in self._db.fetchall(cur)]

        catalog = self._full_catalog_rules()
        # Map every engine rule_id → its engine, for NOT_APPLICABLE derivation.
        all_rule_ids = {r["id"]: eng for eng, rules in catalog.items() for r in rules}

        by_file: dict[str, list[dict]] = {}
        for r in rows:
            by_file.setdefault(r["file"], []).append({
                "rule_id": r["rule_id"],
                "status": r["status"],
                "finding_count": r["finding_count"],
            })
        files = []
        total_expected = total_checked = total_errored = total_na = 0
        for fname in sorted(scan_files):
            rules = by_file.get(fname, [])
            applied_ids = {r["rule_id"] for r in rules}
            # Rules from other formats → explicit NOT_APPLICABLE.
            na = [{"rule_id": rid, "status": "NOT_APPLICABLE", "finding_count": 0}
                  for rid in sorted(all_rule_ids) if rid not in applied_ids]
            expected = len(rules)
            errored = sum(1 for r in rules if r["status"] == "ERROR")
            checked = expected - errored
            total_expected += expected
            total_checked += checked
            total_errored += errored
            total_na += len(na)
            files.append({
                "file": fname,
                "rules_expected": expected,
                "rules_checked": checked,
                "rules_errored": errored,
                "rules_not_applicable": len(na),
                "completeness_pct": round(checked / expected * 100) if expected else 100,
                "complete": errored == 0,
                "rules": rules + na,
            })
        return {
            "scan_id": scan_id,
            "files_total": len(files),
            "rules_expected_total": total_expected,
            "rules_checked_total": total_checked,
            "rules_errored_total": total_errored,
            "rules_not_applicable_total": total_na,
            "completeness_pct": (
                round(total_checked / total_expected * 100) if total_expected else 100
            ),
            "complete": total_errored == 0,
            "files": files,
        }

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

    def queue_hitl_items(self, scan_id: str) -> list[dict]:
        """Auto-populate HITL queue from ai-assisted FAILs in a saved scan.

        Idempotent: skips (scan_id, file, rule_id) combos already queued.
        Returns the list of newly created items for webhook notification.
        """
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT file, rule_id, rule_name, finding_count "
                "FROM scan_rule_traces "
                "WHERE scan_id=%s AND fix_mode='ai-assisted' AND outcome='FAIL'",
                (scan_id,))
            candidates = self._db.fetchall(cur)
            # Build set of already-queued (file, rule_id) pairs for this scan.
            self._db.execute(cur,
                "SELECT file, rule_id FROM hitl_queue WHERE scan_id=%s", (scan_id,))
            already = {(r["file"], r["rule_id"]) for r in self._db.fetchall(cur)}

        created: list[dict] = []
        for c in candidates:
            if (c["file"], c["rule_id"]) in already:
                continue  # idempotent — skip already-queued items
            item_id = uuid.uuid4().hex[:12]
            with self._db.cursor() as cur:
                self._db.execute(cur,
                    "INSERT INTO hitl_queue(id,created_at,scan_id,file,rule_id,rule_name,finding_count,status) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,'pending')",
                    (item_id, now, scan_id, c["file"], c["rule_id"], c["rule_name"], c["finding_count"]))
            created.append({"id": item_id, "scan_id": scan_id, "file": c["file"],
                             "rule_id": c["rule_id"], "rule_name": c["rule_name"],
                             "finding_count": c["finding_count"], "status": "pending", "created_at": now})
        return created

    def list_hitl_queue(self, status: str | None = None, scan_id: str | None = None) -> list[dict]:
        with self._db.cursor() as cur:
            if status and scan_id:
                self._db.execute(cur,
                    "SELECT * FROM hitl_queue WHERE status=%s AND scan_id=%s ORDER BY created_at DESC",
                    (status, scan_id))
            elif status:
                self._db.execute(cur,
                    "SELECT * FROM hitl_queue WHERE status=%s ORDER BY created_at DESC", (status,))
            elif scan_id:
                self._db.execute(cur,
                    "SELECT * FROM hitl_queue WHERE scan_id=%s ORDER BY created_at DESC", (scan_id,))
            else:
                self._db.execute(cur,
                    "SELECT * FROM hitl_queue ORDER BY created_at DESC")
            return self._db.fetchall(cur)

    def get_hitl_item(self, item_id: str) -> dict | None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT * FROM hitl_queue WHERE id=%s", (item_id,))
            return self._db.fetchone(cur)

    def update_hitl_item(self, item_id: str, status: str, reviewer_note: str | None = None) -> dict | None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE hitl_queue SET status=%s, reviewed_at=%s, reviewer_note=%s WHERE id=%s",
                (status, now, reviewer_note, item_id))
        return self.get_hitl_item(item_id)

    # ── Admin settings (persisted; survives restarts) ─────────────────────────
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT value FROM app_settings WHERE key=%s", (key,))
            row = self._db.fetchone(cur)
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO app_settings(key,value) VALUES(%s,%s) "
                "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
                (key, value))

    def get_ai_enabled(self) -> bool:
        """Platform AI mode. Defaults to enabled; admin can hard-disable it
        (deterministic-only mode) — which overrides any per-scan ?ai=true."""
        return self.get_setting("ai_enabled", "true") != "false"

    def set_ai_enabled(self, enabled: bool) -> None:
        self.set_setting("ai_enabled", "true" if enabled else "false")

    # ── Immutable decision audit log ──────────────────────────────────────────
    def log_decision(self, actor: str, action: str, *, scan_id: str | None = None,
                     file: str | None = None, rule_id: str | None = None,
                     detail: str | None = None) -> None:
        """Append one row to the immutable decision log. Never updated/deleted."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO decision_log(id,ts,actor,action,scan_id,file,rule_id,detail) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                (uuid.uuid4().hex[:12], now, actor, action, scan_id, file, rule_id, detail))

    def list_decisions(self, scan_id: str | None = None, limit: int = 500) -> list[dict]:
        with self._db.cursor() as cur:
            if scan_id:
                self._db.execute(cur,
                    "SELECT * FROM decision_log WHERE scan_id=%s ORDER BY ts DESC LIMIT %s",
                    (scan_id, limit))
            else:
                self._db.execute(cur,
                    "SELECT * FROM decision_log ORDER BY ts DESC LIMIT %s", (limit,))
            return self._db.fetchall(cur)

    # ── Durable job queue (ADR 0004) ──────────────────────────────────────────
    # A worker claims the next eligible job, runs it, and marks it done — or, on
    # failure, requeues it with backoff until max_attempts, then dead-letters it.
    # Step-1 claim is optimistic (conditional UPDATE on status='queued'), which is
    # correct for one worker and portable across Postgres + SQLite. Postgres
    # `FOR UPDATE SKIP LOCKED` is the throughput optimization for the multi-worker
    # step (ADR 0004, step 2).

    @staticmethod
    def _now() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()

    def enqueue_job(self, type: str, payload: dict | None = None, *,
                    priority: int = 100, max_attempts: int = 5,
                    run_after: str | None = None, scan_id: str | None = None,
                    campaign_id: str | None = None, batch_id: str | None = None) -> str:
        import json as _json
        now = self._now()
        job_id = uuid.uuid4().hex[:16]
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO jobs(id,type,payload,status,priority,attempts,max_attempts,"
                "run_after,campaign_id,batch_id,scan_id,created_at,updated_at) "
                "VALUES(%s,%s,%s,'queued',%s,0,%s,%s,%s,%s,%s,%s,%s)",
                (job_id, type, _json.dumps(payload or {}), priority, max_attempts,
                 run_after or now, campaign_id, batch_id, scan_id, now, now))
        return job_id

    def get_job(self, job_id: str) -> dict | None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT * FROM jobs WHERE id=%s", (job_id,))
            row = self._db.fetchone(cur)
        if row and isinstance(row.get("payload"), str):
            import json as _json
            try:
                row["payload"] = _json.loads(row["payload"])
            except Exception:
                pass
        return row

    def claim_job(self, worker_id: str) -> dict | None:
        """Atomically claim the next eligible job. Returns the claimed job (with
        attempts already incremented), or None if the queue is empty."""
        now = self._now()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT id FROM jobs WHERE status='queued' AND run_after<=%s "
                "ORDER BY priority, run_after LIMIT 1", (now,))
            row = self._db.fetchone(cur)
            if not row:
                return None
            jid = row["id"]
            # Conditional update: only one worker can flip status from 'queued'.
            self._db.execute(cur,
                "UPDATE jobs SET status='running', locked_at=%s, locked_by=%s, "
                "attempts=attempts+1, updated_at=%s "
                "WHERE id=%s AND status='queued'",
                (now, worker_id, now, jid))
            claimed = getattr(cur, "rowcount", 1) == 1
        return self.get_job(jid) if claimed else None

    def complete_job(self, job_id: str) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE jobs SET status='done', updated_at=%s, last_error=NULL WHERE id=%s",
                (self._now(), job_id))

    def dead_letter_breakdown(self) -> dict:
        """Diagnostic: dead-lettered jobs grouped by type + the most common errors."""
        out: dict = {}
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT type, COUNT(*) AS n FROM jobs WHERE status='dead' GROUP BY type")
            out["by_type"] = {r["type"]: r["n"] for r in self._db.fetchall(cur)}
            self._db.execute(cur,
                "SELECT type, SUBSTR(last_error,1,200) AS err, COUNT(*) AS n FROM jobs "
                "WHERE status='dead' GROUP BY type, SUBSTR(last_error,1,200) ORDER BY n DESC LIMIT 15")
            out["top_errors"] = [{"type": r["type"], "n": r["n"], "error": r["err"]}
                                 for r in self._db.fetchall(cur)]
        return out

    def purge_dead_jobs(self) -> int:
        """Delete dead-lettered jobs (unrecoverable). Returns how many were removed."""
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT COUNT(*) AS n FROM jobs WHERE status='dead'")
            n = self._db.fetchone(cur)["n"]
            self._db.execute(cur, "DELETE FROM jobs WHERE status='dead'")
        return n

    def touch_job(self, job_id: str) -> None:
        """Heartbeat: extend a running job's lease so the stuck-job sweeper won't
        reclaim a slow-but-alive job (e.g. a long PII scan). Called periodically by
        the worker while the handler runs."""
        now = self._now()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE jobs SET locked_at=%s, updated_at=%s WHERE id=%s AND status='running'",
                (now, now, job_id))

    def fail_job(self, job_id: str, error: str, backoff_seconds: float = 0.0,
                 force_dead: bool = False) -> str:
        """Requeue a failed job with backoff, or dead-letter it once attempts are
        exhausted (or immediately when force_dead). Returns 'queued' or 'dead'."""
        from datetime import datetime, timezone, timedelta
        job = self.get_job(job_id)
        if job is None:
            return "missing"
        now = datetime.now(timezone.utc)
        if force_dead or job["attempts"] >= job["max_attempts"]:
            with self._db.cursor() as cur:
                self._db.execute(cur,
                    "UPDATE jobs SET status='dead', last_error=%s, updated_at=%s WHERE id=%s",
                    (error[:2000], now.isoformat(), job_id))
            return "dead"
        run_after = (now + timedelta(seconds=backoff_seconds)).isoformat()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE jobs SET status='queued', run_after=%s, locked_at=NULL, "
                "locked_by=NULL, last_error=%s, updated_at=%s WHERE id=%s",
                (run_after, error[:2000], now.isoformat(), job_id))
        return "queued"

    def reclaim_stuck_jobs(self, lease_seconds: int = 600) -> int:
        """Requeue jobs stuck in 'running' past the lease (worker died mid-job)."""
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=lease_seconds)).isoformat()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE jobs SET status='queued', locked_at=NULL, locked_by=NULL, updated_at=%s "
                "WHERE status='running' AND locked_at<%s",
                (self._now(), cutoff))
            return getattr(cur, "rowcount", 0) or 0

    def job_stats(self) -> dict:
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
            return {r["status"]: r["n"] for r in self._db.fetchall(cur)}

    def list_jobs(self, status: str | None = None, limit: int = 200) -> list[dict]:
        with self._db.cursor() as cur:
            if status:
                self._db.execute(cur,
                    "SELECT * FROM jobs WHERE status=%s ORDER BY updated_at DESC LIMIT %s",
                    (status, limit))
            else:
                self._db.execute(cur,
                    "SELECT * FROM jobs ORDER BY updated_at DESC LIMIT %s", (limit,))
            return self._db.fetchall(cur)
