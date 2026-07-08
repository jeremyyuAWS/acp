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

# Friendly source labels for the "By source system" breakdown (get_scan). Mirrors
# lf._SOURCE_LABEL; duplicated rather than imported to avoid store.py depending on lf.py
# for 3 strings.
_SOURCE_LABEL = {"drive": "Google Drive", "sharepoint": "SharePoint / OneDrive", "local": "Local upload"}

# Mirrors pii._SEV_RANK; duplicated (not imported) for the same reason as _SOURCE_LABEL —
# find_by_checksum needs it to recompute the rolled-up severity for a copied PII summary.
_PII_SEV_RANK = {"critical": 3, "moderate": 2, "low": 1}

# WCAG issue severity (issue_records.severity / config/rule-catalog.json) — a DIFFERENT
# vocabulary from the PII one above (these are uppercase, PII's are lowercase). Used by
# get_scan_diff to pick the worst severity when a SC's findings are mixed.
_ISSUE_SEV_RANK = {"CRITICAL": 4, "SERIOUS": 3, "MODERATE": 2, "MINOR": 1}

# Schema is identical between SQLite and Postgres (UPSERT syntax is the same).
_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS scan_runs (
      id TEXT PRIMARY KEY, started_at TEXT, completed_at TEXT, source TEXT,
      rubric_name TEXT, rubric_hash TEXT,
      files INT, certifiable INT, uncertain INT, error INT, avg_score INT,
      status TEXT, files_done INT, owner_email TEXT, assessed_at TEXT, finalized_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS file_records (
      scan_id TEXT, file TEXT, engine TEXT, status TEXT, score INT,
      compliant INT, skipped_rules INT,
      drive_file_id TEXT,
      remediated_at TEXT,
      drive_write_url TEXT,
      acp_stamped TEXT,
      checksum TEXT,
      published_at TEXT,
      blob_url TEXT,
      size_kb INT,
      pages INT,
      sheets INT,
      PRIMARY KEY (scan_id, file)
    )""",
    # Per-scan decision snapshots (PRD: time-travel). kind='triage' (value inscope|na|defer)
    # or 'action' (value = JSON {state, action}). Owner-scoped, one row per (scan,file,kind).
    """CREATE TABLE IF NOT EXISTS scan_decisions (
      scan_id TEXT, file TEXT, kind TEXT, value TEXT,
      owner_email TEXT, updated_at TEXT,
      PRIMARY KEY (scan_id, file, kind)
    )""",
    # Fan-out scan pipeline (ADR 0007): scan_runs is created at 'discover' with
    # status=running + a files_done counter, then finalized once all per-file jobs land.
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS status TEXT",
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS files_done INT",
    # Per-user isolation: scans are scoped to the signed-in user's email.
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS owner_email TEXT",
    # Presentation decouple: set when the user runs Assess — results views gate on it.
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS assessed_at TEXT",
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS finalized_at TEXT",  # ADR 0013 finalize-once guard
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS size_kb INT",
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS pages INT",
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS sheets INT",
    # Migrations for existing deployments
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS drive_file_id TEXT",
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS remediated_at TEXT",
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS published_url TEXT",
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS drive_write_url TEXT",
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS acp_stamped TEXT",
    # Drive's md5Checksum (free in the same files().list() call) — lets a scan recognize
    # byte-identical duplicates uploaded under different names/folders and skip re-running
    # the (expensive) engine analysis + PII extraction for the 2nd+ copy. Scoped to ONE
    # scan only (find_by_checksum filters on scan_id) — reusing analysis ACROSS scans is
    # the bigger incremental-fingerprinting feature, not this.
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS checksum TEXT",
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS published_at TEXT",
    # ADR 0010 — the remediated output's durable Blob URL, additive alongside
    # drive_write_url (a file can carry both; Drive is now a best-effort mirror).
    "ALTER TABLE file_records ADD COLUMN IF NOT EXISTS blob_url TEXT",
    """CREATE TABLE IF NOT EXISTS issue_records (
      scan_id TEXT, file TEXT, rule_id TEXT, wcag TEXT, severity TEXT, detail TEXT
    )""",
    "ALTER TABLE issue_records ADD COLUMN IF NOT EXISTS detail TEXT",
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
    # ADR: AI-draft + human-approve lane. The reviewer's final, possibly-edited
    # value for a semantic finding (alt text / link text / title) — durable
    # compliance evidence of what was actually approved, distinct from the
    # ai.py-generated draft (which is regenerated on demand, not persisted).
    "ALTER TABLE hitl_queue ADD COLUMN IF NOT EXISTS approved_value TEXT",
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
    # Column order matches the claim ORDER BY (priority, run_after) so Postgres reads the
    # top queued job index-only instead of sorting all queued rows every poll (audit P2).
    # New name + drop-old so this migrates once, not a rebuild every boot.
    "DROP INDEX IF EXISTS idx_jobs_claim",
    "CREATE INDEX IF NOT EXISTS idx_jobs_claim2 ON jobs(status, priority, run_after)",
    # Sensitive-data (PII) findings per document (ADR 0006). A detection dimension
    # orthogonal to WCAG. samples holds JSON array of MASKED strings only — never
    # raw PII (the masking is enforced in api/pii.py).
    """CREATE TABLE IF NOT EXISTS pii_findings (
      scan_id TEXT, file TEXT, pii_type TEXT, label TEXT,
      count INT, severity TEXT, samples TEXT,
      PRIMARY KEY (scan_id, file, pii_type)
    )""",
    # Document-centric layer (ADR 0003, Phase 1): a long-lived governed object a scan
    # upserts into, distinct from file_records (a per-scan snapshot). doc_id is stable
    # across renames/scans (see api/documents.py:resolve_doc_id).
    """CREATE TABLE IF NOT EXISTS documents (
      doc_id TEXT PRIMARY KEY, source TEXT, path TEXT, content_hash TEXT,
      owner TEXT, department TEXT, created_at TEXT, last_seen TEXT,
      usage_signal INT, regulatory_tags TEXT, business_criticality TEXT,
      triage_score INT, triage_rationale TEXT
    )""",
    # Per-violation remediation state machine (ADR 0003, Phase 2). Keyed by
    # (doc_id, rule_id) so "3 of 5 violations fixed" is first-class -- supersedes the
    # binary file_records.remediated_at as the governing truth (file_records stays the
    # per-scan snapshot; this is the long-lived state). hitl_queue remains the work-list;
    # this is the state hitl_queue resolution (and auto-remediation) write into.
    """CREATE TABLE IF NOT EXISTS remediation_state (
      doc_id TEXT, rule_id TEXT, state TEXT, updated_at TEXT, last_scan_id TEXT,
      PRIMARY KEY (doc_id, rule_id)
    )""",
    # Configurable file disposition (ADR 0003, Phase 3). PREVIEW ONLY as of this
    # migration -- api/disposition.py's matches() tells you which documents a policy
    # would select; nothing executes a real move/rename/archive/delete yet. That
    # execution path (gated on requires_approval + this audit table) is a deliberately
    # separate, later decision, not bundled with the schema.
    """CREATE TABLE IF NOT EXISTS disposition_policy (
      policy_id TEXT PRIMARY KEY, name TEXT, match TEXT, action TEXT,
      action_config TEXT, requires_approval INT, enabled INT
    )""",
    """CREATE TABLE IF NOT EXISTS disposition_audit (
      id TEXT PRIMARY KEY, ts TEXT, doc_id TEXT, policy_id TEXT,
      action TEXT, result TEXT, detail TEXT
    )""",
    # Phased remediation campaigns (ADR 0003, Phase 4). "Remediation Programs" existed
    # only as a client-derived view (Monitor.jsx useProgramBatches, computed fresh from
    # files/decisions props on every render, nothing persisted) -- these tables make a
    # campaign a real, durable object: pause/resume survives a reload, and batch
    # membership is a snapshot taken at creation time, not silently recomputed.
    """CREATE TABLE IF NOT EXISTS campaign (
      campaign_id TEXT PRIMARY KEY, name TEXT, status TEXT, scope TEXT, created_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS campaign_batch (
      batch_id TEXT PRIMARY KEY, campaign_id TEXT, seq INT, status TEXT,
      filter TEXT, deadline TEXT
    )""",
]

# One-time backfill: assign pre-isolation (NULL-owner) scans to a configured owner so
# existing history isn't orphaned when per-user isolation turns on. Idempotent — only
# touches NULL-owner rows, and new scans always carry an owner. Value is validated to
# plain email characters before interpolation (no params in DDL-style _SCHEMA execution).
_LEGACY_OWNER = os.environ.get("ACP_LEGACY_SCAN_OWNER", "").strip().lower()
if _LEGACY_OWNER and "@" in _LEGACY_OWNER and all(c.isalnum() or c in ".+-_@" for c in _LEGACY_OWNER):
    _SCHEMA.append(f"UPDATE scan_runs SET owner_email='{_LEGACY_OWNER}' WHERE owner_email IS NULL")

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
    {"id": "1.2.1",  "name": "Audio-only & Video-only",     "level": "A",   "fix_mode": "human-only",   "plain": "Audio/video with no transcript"},
    {"id": "1.2.2",  "name": "Captions (Prerecorded)",      "level": "A",   "fix_mode": "human-only",   "plain": "Video missing captions"},
    {"id": "1.2.3",  "name": "Audio Description or Alt",     "level": "A",   "fix_mode": "human-only",   "plain": "Video missing audio description or transcript"},
    {"id": "1.3.1",  "name": "Info and Relationships",      "level": "A",   "fix_mode": "auto",         "plain": "Structure not marked up (headings, lists, tables)"},
    {"id": "1.3.2",  "name": "Meaningful Sequence",         "level": "A",   "fix_mode": "auto",         "plain": "Reading order does not match the visual order"},
    {"id": "1.3.3",  "name": "Sensory Characteristics",      "level": "A",   "fix_mode": "human-only",   "plain": "Instructions rely on shape or position alone"},
    {"id": "1.3.4",  "name": "Orientation",                "level": "AA",  "fix_mode": "auto",         "plain": "Content locked to one screen orientation"},
    {"id": "1.3.5",  "name": "Identify Input Purpose",     "level": "AA",  "fix_mode": "auto",         "plain": "Form fields don't declare their purpose"},
    {"id": "1.4.1",  "name": "Use of Color",                "level": "A",   "fix_mode": "auto",         "plain": "Information shown by color alone"},
    {"id": "1.4.2",  "name": "Audio Control",              "level": "A",   "fix_mode": "auto",         "plain": "Autoplaying media that can't be stopped"},
    {"id": "1.4.3",  "name": "Contrast (Minimum)",          "level": "AA",  "fix_mode": "auto",         "plain": "Text with low color contrast"},
    {"id": "1.4.4",  "name": "Resize Text",                 "level": "AA",  "fix_mode": "auto",         "plain": "Text that can't be enlarged"},
    {"id": "1.4.5",  "name": "Images of Text",             "level": "AA",  "fix_mode": "ai-assisted", "plain": "Text baked into an image"},
    {"id": "1.4.6",  "name": "Contrast (Enhanced)",        "level": "AAA", "fix_mode": "auto",         "plain": "Text below the enhanced contrast ratio"},
    {"id": "1.4.8",  "name": "Visual Presentation",         "level": "AAA", "fix_mode": "human-only",   "plain": "Body text set justified (both margins)"},
    {"id": "1.4.9",  "name": "Images of Text (No Exception)", "level": "AAA", "fix_mode": "ai-assisted", "plain": "Any text baked into an image (no exceptions)"},
    {"id": "1.4.10", "name": "Reflow",                      "level": "AA",  "fix_mode": "auto",         "plain": "Content that doesn't reflow on small screens"},
    {"id": "1.4.11", "name": "Non-text Contrast",           "level": "AA",  "fix_mode": "ai-assisted", "plain": "Buttons or icons with low contrast"},
    {"id": "1.4.12", "name": "Text Spacing",                "level": "AA",  "fix_mode": "auto",         "plain": "Text spacing can't be adjusted"},
    {"id": "2.1.1",  "name": "Keyboard",                    "level": "A",   "fix_mode": "auto",         "plain": "Can't be used with a keyboard"},
    {"id": "2.4.1",  "name": "Bypass Blocks",              "level": "A",   "fix_mode": "auto",         "plain": "No way to skip repeated navigation"},
    {"id": "2.4.2",  "name": "Page Titled",                 "level": "A",   "fix_mode": "auto",         "plain": "Missing a page or document title"},
    {"id": "2.4.3",  "name": "Focus Order",                 "level": "A",   "fix_mode": "auto",         "plain": "Illogical keyboard navigation order"},
    {"id": "2.4.4",  "name": "Link Purpose (In Context)",   "level": "A",   "fix_mode": "ai-assisted", "plain": "Unclear link text (e.g. 'click here')"},
    {"id": "2.4.6",  "name": "Headings and Labels",         "level": "AA",  "fix_mode": "auto",         "plain": "Unclear headings or labels"},
    {"id": "2.4.7",  "name": "Focus Visible",               "level": "AA",  "fix_mode": "auto",         "plain": "No visible keyboard focus indicator"},
    {"id": "2.4.9",  "name": "Link Purpose (Link Only)",  "level": "AAA", "fix_mode": "ai-assisted", "plain": "Same link text used for different destinations"},
    {"id": "2.4.10", "name": "Section Headings",           "level": "AAA", "fix_mode": "human-only",   "plain": "Long document has no section headings"},
    {"id": "2.5.3",  "name": "Label in Name",              "level": "A",   "fix_mode": "auto",         "plain": "Control names don't match their visible labels"},
    {"id": "2.5.8",  "name": "Target Size (Minimum)",       "level": "AA",  "fix_mode": "human-only",   "plain": "Touch targets smaller than 24px"},
    {"id": "3.1.1",  "name": "Language of Page",            "level": "A",   "fix_mode": "auto",         "plain": "Document language not set"},
    {"id": "3.1.2",  "name": "Language of Parts",           "level": "AA",  "fix_mode": "ai-assisted", "plain": "A passage's language not marked"},
    {"id": "3.1.4",  "name": "Abbreviations",               "level": "AAA", "fix_mode": "auto",         "plain": "Unexplained abbreviations"},
    {"id": "3.1.5",  "name": "Reading Level",               "level": "AAA", "fix_mode": "human-only",   "plain": "Text reading level well above lower-secondary"},
    {"id": "3.3.2",  "name": "Labels or Instructions",     "level": "A",   "fix_mode": "ai-assisted", "plain": "Required fields with no label or instructions"},
    {"id": "4.1.2",  "name": "Name, Role, Value",           "level": "A",   "fix_mode": "ai-assisted", "plain": "Controls missing names/roles for assistive tech"},
]

# Which document formats each RULE_CATALOG rule actually has a validator for.
# Without this, a rule that only runs for HTML (say) silently reads PASS on a
# PDF/DOCX/PPTX/XLSX file in scan_rule_traces — the check was never evaluated,
# but a zero finding-count looks identical to a real pass. tests/test_rule_formats.py
# derives this same table from source (api/scanner.py + ocr.py + textchecks.py +
# config/rule-catalog.json) and asserts it matches — kept in sync by hand, same
# posture as RULE_CATALOG vs frontend/src/rules/index.js's PLAIN_NAMES, but with
# an automated drift check this time.
_ALL_FORMATS = frozenset({"html", "docx", "pptx", "xlsx", "pdf"})
_OFFICE_PDF = frozenset({"docx", "pptx", "xlsx", "pdf"})
RULE_FORMATS: dict[str, frozenset[str]] = {
    "1.1.1": _ALL_FORMATS, "1.2.1": frozenset({"html"}), "1.2.2": frozenset({"html"}),
    "1.2.3": frozenset({"html"}), "1.3.1": _ALL_FORMATS, "1.3.2": frozenset({"pdf", "pptx", "xlsx"}), "1.3.3": _ALL_FORMATS,
    "1.3.4": frozenset({"html"}), "1.3.5": frozenset({"html"}), "1.4.1": frozenset({"html"}),
    "1.4.2": frozenset({"html"}), "1.4.3": _ALL_FORMATS,
    "1.4.4": frozenset({"html"}), "1.4.5": _OFFICE_PDF, "1.4.6": frozenset({"html", "pdf", "pptx", "xlsx"}),
    "1.4.8": frozenset({"docx"}),
    "1.4.9": _OFFICE_PDF, "1.4.10": frozenset({"html"}), "1.4.11": frozenset({"html"}),
    "1.4.12": frozenset({"html"}), "2.1.1": frozenset({"pptx"}), "2.4.1": frozenset({"html", "pdf"}),
    "2.4.2": _ALL_FORMATS, "2.4.3": frozenset({"html"}), "2.4.4": frozenset({"docx", "html", "pptx"}),
    "2.4.6": frozenset({"docx", "html", "pptx"}), "2.4.7": frozenset({"html"}), "2.4.9": frozenset({"docx", "html", "pptx"}),
    "2.4.10": frozenset({"docx"}),
    "2.5.3": frozenset({"html"}), "2.5.8": frozenset({"html"}), "3.1.1": _ALL_FORMATS,
    "3.1.2": _ALL_FORMATS, "3.1.4": frozenset({"html"}), "3.1.5": _ALL_FORMATS, "3.3.2": frozenset({"docx", "html"}),
    "4.1.2": frozenset({"html"}),
}


def _file_format(filename: str) -> str | None:
    """Canonical format name for a scanned filename, or None if unrecognized."""
    ext = Path(filename).suffix.lower()
    if ext in (".html", ".htm"):
        return "html"
    if ext in (".docx", ".pptx", ".xlsx"):
        return ext.lstrip(".")
    if ext == ".pdf":
        return "pdf"
    return None


def _rule_outcome(rule_id: str, fmt: str | None, count: int) -> str:
    """PASS/FAIL if the rule actually has a validator for this file's format,
    else NOT_APPLICABLE — the rule was never evaluated, not silently passed."""
    if fmt is None or fmt not in RULE_FORMATS.get(rule_id, _ALL_FORMATS):
        return "NOT_APPLICABLE"
    return "FAIL" if count > 0 else "PASS"


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
                # The migration ALTERs use Postgres's ADD COLUMN IF NOT EXISTS,
                # which SQLite rejects as a syntax error — a fresh checkout could
                # not boot in SQLite mode at all. Translate to plain ADD COLUMN
                # and treat "duplicate column" (already migrated) as success.
                if stmt.strip().upper().startswith("ALTER TABLE"):
                    try:
                        cur.execute(stmt.replace("ADD COLUMN IF NOT EXISTS", "ADD COLUMN"))
                    except sqlite3.OperationalError as e:
                        if "duplicate column" not in str(e).lower():
                            raise
                else:
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
                "files,certifiable,uncertain,error,avg_score,status,files_done,owner_email) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'done',%s,%s)",
                (sid, report["started_at"], report["completed_at"], report["source"],
                 report["rubric"]["name"], report["rubric"]["hash"],
                 s["files"], s["certifiable"], s["uncertain"], s["error"], s["avg_score"], s["files"],
                 report.get("owner")))
            for f in report["files"]:
                self._db.execute(cur,
                    "INSERT INTO file_records(scan_id,file,engine,status,score,compliant,skipped_rules,drive_file_id,acp_stamped,checksum,size_kb,pages,sheets) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (sid, f["file"], f["engine"], f["status"], f["score"],
                     int(f["compliant"]), f["skipped_rules"], f.get("drive_file_id"), f.get("acp_stamped"),
                     f.get("checksum"), f.get("size_kb"), f.get("pages"), f.get("sheets")))
                for i in f["issues"]:
                    self._db.execute(cur,
                        "INSERT INTO issue_records(scan_id,file,rule_id,wcag,severity,detail) "
                        "VALUES(%s,%s,%s,%s,%s,%s)",
                        (sid, f["file"], i["ruleId"], i["wcag"], i["severity"], i.get("detail")))
                # Per-rule trace: one row per catalog rule per file — PASS/FAIL/NOT_APPLICABLE.
                sc_counts: dict[str, int] = {}
                for i in f["issues"]:
                    sc = _extract_sc(i.get("wcag", ""))
                    if sc:
                        sc_counts[sc] = sc_counts.get(sc, 0) + 1
                fmt = _file_format(f["file"])
                for rule in RULE_CATALOG:
                    rid = rule["id"]
                    count = sc_counts.get(rid, 0)
                    outcome = _rule_outcome(rid, fmt, count)
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
        # Document-centric layer (ADR 0003 Phase 1) for the MONOLITHIC path — the
        # fan-out path upserts per file in handlers._analyse_and_persist_one, but a
        # plain (non-queued / non-fanout) scan used to skip the documents table
        # entirely, leaving disposition/triage blind after a monolithic run.
        # Defensively wrapped like its fan-out twin: never fail the scan save.
        try:
            import datetime as _dt

            from documents import compute_triage_score, resolve_doc_id
            now = report["completed_at"]
            for f in report["files"]:
                doc_id = resolve_doc_id(report["source"], f.get("drive_file_id"),
                                        f["file"], f.get("checksum"))
                prior = self.get_document(doc_id)
                created_at = (prior or {}).get("created_at") or now
                age_days = ((_dt.datetime.fromisoformat(now) - _dt.datetime.fromisoformat(created_at)).days
                            if prior and prior.get("created_at") else None)
                tscore, rationale = compute_triage_score(
                    compliance_score=f.get("score"), pii_severity=(f.get("pii") or {}).get("severity"),
                    pii_total=(f.get("pii") or {}).get("total", 0), age_days=age_days,
                    skipped_rules=f.get("skipped_rules", 0))
                self.upsert_document(doc_id, source=report["source"], path=f["file"],
                                     content_hash=f.get("checksum"), owner=report.get("owner"),
                                     created_at=created_at, last_seen=now,
                                     triage_score=tscore, triage_rationale=rationale)
        except Exception:
            pass
        return sid

    # ── Fan-out scan pipeline (ADR 0007) ──────────────────────────────────────
    def init_scan_run(self, scan_id: str, source: str, total: int, started_at: str,
                      rubric_name: str, rubric_hash: str, owner: str | None = None) -> None:
        """Create the scan_runs row at discover time (status=running, counter=0)."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO scan_runs(id,started_at,source,rubric_name,rubric_hash,files,files_done,status,owner_email) "
                "VALUES(%s,%s,%s,%s,%s,%s,0,'running',%s) ON CONFLICT(id) DO NOTHING",
                (scan_id, started_at, source, rubric_name, rubric_hash, total, owner))

    def save_file_result(self, scan_id: str, f: dict, completed_at: str) -> None:
        """Persist one assessed file (same shape save_scan writes). Idempotent so a
        retried scan_file job doesn't double-insert."""
        import json as _json
        catalog = _json.loads(
            (Path(__file__).resolve().parent.parent / "config" / "rule-catalog.json").read_text())
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO file_records(scan_id,file,engine,status,score,compliant,skipped_rules,drive_file_id,acp_stamped,checksum,size_kb,pages,sheets) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(scan_id,file) DO UPDATE SET "
                "engine=EXCLUDED.engine,status=EXCLUDED.status,score=EXCLUDED.score,"
                "compliant=EXCLUDED.compliant,skipped_rules=EXCLUDED.skipped_rules,"
                "drive_file_id=EXCLUDED.drive_file_id,acp_stamped=EXCLUDED.acp_stamped,checksum=EXCLUDED.checksum,"
                "size_kb=EXCLUDED.size_kb,pages=EXCLUDED.pages,sheets=EXCLUDED.sheets",
                (scan_id, f["file"], f["engine"], f["status"], f["score"],
                 int(f["compliant"]), f["skipped_rules"], f.get("drive_file_id"), f.get("acp_stamped"),
                 f.get("checksum"), f.get("size_kb"), f.get("pages"), f.get("sheets")))
            self._db.execute(cur, "DELETE FROM issue_records WHERE scan_id=%s AND file=%s", (scan_id, f["file"]))
            for i in f.get("issues", []):
                self._db.execute(cur,
                    "INSERT INTO issue_records(scan_id,file,rule_id,wcag,severity,detail) VALUES(%s,%s,%s,%s,%s,%s)",
                    (scan_id, f["file"], i["ruleId"], i["wcag"], i["severity"], i.get("detail")))
            sc_counts: dict[str, int] = {}
            for i in f.get("issues", []):
                sc = _extract_sc(i.get("wcag", ""))
                if sc:
                    sc_counts[sc] = sc_counts.get(sc, 0) + 1
            fmt = _file_format(f["file"])
            for rule in RULE_CATALOG:
                rid = rule["id"]; count = sc_counts.get(rid, 0)
                outcome = _rule_outcome(rid, fmt, count)
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

    def find_by_checksum(self, scan_id: str, checksum: str) -> dict | None:
        """Look up an already-analysed file in THIS scan with the same Drive md5Checksum —
        i.e. a byte-identical duplicate uploaded under a different name/folder. Returns a
        dict shaped for save_file_result (ruleId-keyed issues, pii in detect_file's shape)
        so the caller can copy it forward under the new file's name instead of re-running
        the engine + PII extraction. None if no match (first occurrence, or checksum-less
        source like SharePoint/local)."""
        import json as _json
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT file,engine,status,score,compliant,skipped_rules,acp_stamped "
                "FROM file_records WHERE scan_id=%s AND checksum=%s LIMIT 1",
                (scan_id, checksum))
            row = self._db.fetchone(cur)
            if not row:
                return None
            self._db.execute(cur,
                "SELECT rule_id,wcag,severity,detail FROM issue_records WHERE scan_id=%s AND file=%s",
                (scan_id, row["file"]))
            issues = [{"ruleId": r["rule_id"], "wcag": r["wcag"], "severity": r["severity"], "detail": r["detail"]}
                      for r in self._db.fetchall(cur)]
            self._db.execute(cur,
                "SELECT pii_type,label,count,severity,samples FROM pii_findings "
                "WHERE scan_id=%s AND file=%s", (scan_id, row["file"]))
            pii_rows = self._db.fetchall(cur)
        pii = None
        if pii_rows:
            findings = [{"type": p["pii_type"], "label": p["label"], "count": p["count"],
                        "severity": p["severity"],
                        "samples": _json.loads(p["samples"]) if p.get("samples") else []}
                       for p in pii_rows]
            total = sum(p["count"] for p in findings)
            sev = None
            for p in findings:
                if sev is None or _PII_SEV_RANK.get(p["severity"], 0) > _PII_SEV_RANK.get(sev, 0):
                    sev = p["severity"]
            pii = {"types": {p["type"]: p["count"] for p in findings}, "total": total,
                  "severity": sev, "findings": findings}
        return {"engine": row["engine"], "status": row["status"], "score": row["score"],
               "compliant": row["compliant"], "skipped_rules": row["skipped_rules"],
               "acp_stamped": row["acp_stamped"], "issues": issues, "pii": pii,
               "dedup_of": row["file"]}

    def find_prior_analysis(self, owner: str | None, drive_file_id: str | None,
                            checksum: str | None, rubric_hash: str | None) -> dict | None:
        """ADR 0011: reuse a file's analysis from an EARLIER scan (not just this one --
        see find_by_checksum above for the narrower within-scan version). Gated on the
        SAME owner + SAME drive_file_id (stable Drive identity, survives rename) + SAME
        checksum (byte-identical) + SAME rubric_hash -- the last one is the correctness-
        critical piece: a stale analysis under an old rubric is not valid evidence once
        the rule set has changed, so a rubric_hash mismatch always falls through to a
        real re-analysis. Returns the most recently completed match, same shape as
        find_by_checksum (ruleId-keyed issues, pii in detect_file's shape)."""
        if not (owner and drive_file_id and checksum and rubric_hash):
            return None
        import json as _json
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT fr.scan_id, fr.file, fr.engine, fr.status, fr.score, fr.compliant, "
                "fr.skipped_rules, fr.acp_stamped FROM file_records fr "
                "JOIN scan_runs sr ON sr.id = fr.scan_id "
                "WHERE sr.owner_email=%s AND fr.drive_file_id=%s AND fr.checksum=%s "
                "AND sr.rubric_hash=%s AND sr.completed_at IS NOT NULL "
                "ORDER BY sr.completed_at DESC LIMIT 1",
                (owner, drive_file_id, checksum, rubric_hash))
            row = self._db.fetchone(cur)
            if not row:
                return None
            prior_scan_id = row["scan_id"]
            self._db.execute(cur,
                "SELECT rule_id,wcag,severity,detail FROM issue_records WHERE scan_id=%s AND file=%s",
                (prior_scan_id, row["file"]))
            issues = [{"ruleId": r["rule_id"], "wcag": r["wcag"], "severity": r["severity"], "detail": r["detail"]}
                      for r in self._db.fetchall(cur)]
            self._db.execute(cur,
                "SELECT pii_type,label,count,severity,samples FROM pii_findings "
                "WHERE scan_id=%s AND file=%s", (prior_scan_id, row["file"]))
            pii_rows = self._db.fetchall(cur)
        pii = None
        if pii_rows:
            findings = [{"type": p["pii_type"], "label": p["label"], "count": p["count"],
                        "severity": p["severity"],
                        "samples": _json.loads(p["samples"]) if p.get("samples") else []}
                       for p in pii_rows]
            total = sum(p["count"] for p in findings)
            sev = None
            for p in findings:
                if sev is None or _PII_SEV_RANK.get(p["severity"], 0) > _PII_SEV_RANK.get(sev, 0):
                    sev = p["severity"]
            pii = {"types": {p["type"]: p["count"] for p in findings}, "total": total,
                  "severity": sev, "findings": findings}
        return {"engine": row["engine"], "status": row["status"], "score": row["score"],
               "compliant": row["compliant"], "skipped_rules": row["skipped_rules"],
               "acp_stamped": row["acp_stamped"], "issues": issues, "pii": pii,
               "reused_from_scan": prior_scan_id}

    def bump_files_done(self, scan_id: str, n: int = 1) -> tuple[int, int]:
        """Atomically increment the done counter by n (default 1; a scan_batch bumps by
        its chunk size — ADR 0008); returns (done, total enqueued)."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE scan_runs SET files_done=COALESCE(files_done,0)+%s WHERE id=%s "
                "RETURNING files_done, files", (n, scan_id))
            row = self._db.fetchone(cur)
        return (row["files_done"], row["files"]) if row else (0, 0)

    def count_files_done(self, scan_id: str) -> tuple[int, int]:
        """(distinct files persisted, total enqueued) — the idempotent finalize trigger
        (ADR 0013). save_file_result upserts, so a retried scan_file re-saving the same row
        can't inflate the count; unlike the running counter (bump_files_done) this never
        overshoots or finalizes a scan early after a crash/retry."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT (SELECT COUNT(*) FROM file_records WHERE scan_id=%s) AS done, files "
                "FROM scan_runs WHERE id=%s", (scan_id, scan_id))
            row = self._db.fetchone(cur)
        return (row["done"], row["files"]) if row else (0, 0)

    def mark_finalized(self, scan_id: str) -> bool:
        """Claim the finalize exactly once: set finalized_at iff still unset. Returns True for
        the single caller that won (it emits HITL routing + audit); False for duplicate/
        concurrent scan_finalize runs, which then no-op (ADR 0013). The summary recompute
        (finalize_scan_run) stays idempotent and runs regardless."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE scan_runs SET finalized_at=%s WHERE id=%s AND finalized_at IS NULL",
                (now, scan_id))
            return getattr(cur, "rowcount", 1) == 1

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

    def list_scans(self, owner: str | None = None) -> list[dict]:
        # Completed scans only — in-flight (status='running', no completed_at) scans
        # are excluded so they don't appear as bogus entries in the scan picker.
        # Scoped to the signed-in user (per-user isolation): a user sees only their scans.
        where, params = "completed_at IS NOT NULL", ()
        if owner:
            where += " AND owner_email=%s"; params = (owner,)
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT id,completed_at,source,rubric_hash,files,certifiable,uncertain,error,avg_score,assessed_at "
                f"FROM scan_runs WHERE {where} ORDER BY completed_at DESC", params)
            return self._db.fetchall(cur)

    def mark_assessed(self, scan_id: str, when: str) -> None:
        """Stamp the scan as assessed (the user ran Assess). Results views gate on this."""
        with self._db.cursor() as cur:
            self._db.execute(cur, "UPDATE scan_runs SET assessed_at=%s WHERE id=%s AND assessed_at IS NULL",
                             (when, scan_id))

    # ── Per-scan decision snapshots (PRD: time-travel) ──
    def get_decisions(self, scan_id: str, owner: str | None = None) -> dict:
        """All decisions for a scan as {file: {kind: value}} (kind = 'triage' | 'action').
        Owner-scoped to match the scan's per-user isolation."""
        where, params = "scan_id=%s", [scan_id]
        if owner:
            where += " AND owner_email=%s"; params.append(owner)
        with self._db.cursor() as cur:
            self._db.execute(cur, f"SELECT file,kind,value FROM scan_decisions WHERE {where}", tuple(params))
            rows = self._db.fetchall(cur)
        out: dict = {}
        for r in rows:
            out.setdefault(r["file"], {})[r["kind"]] = r["value"]
        return out

    def save_decision(self, scan_id: str, file: str, kind: str, value: str,
                      owner: str | None, when: str) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO scan_decisions(scan_id,file,kind,value,owner_email,updated_at) "
                "VALUES(%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(scan_id,file,kind) DO UPDATE SET value=EXCLUDED.value, updated_at=EXCLUDED.updated_at",
                (scan_id, file, kind, value, owner, when))

    def delete_decision(self, scan_id: str, file: str, kind: str) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "DELETE FROM scan_decisions WHERE scan_id=%s AND file=%s AND kind=%s",
                             (scan_id, file, kind))

    def active_scan(self, owner: str | None = None) -> dict | None:
        """The most recent in-flight scan (for reconnecting after a page reload), or None.
        Scoped to the signed-in user so reconnect never picks up someone else's scan."""
        where, params = "status='running'", ()
        if owner:
            where += " AND owner_email=%s"; params = (owner,)
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT id,started_at,source,files,files_done FROM scan_runs "
                f"WHERE {where} ORDER BY started_at DESC LIMIT 1", params)
            return self._db.fetchone(cur)

    def get_scan(self, sid: str, owner: str | None = None) -> dict | None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT * FROM scan_runs WHERE id=%s", (sid,))
            run = self._db.fetchone(cur)
            if not run:
                return None
            # Per-user isolation: a user can only read their own scan (legacy/None owner
            # scans are not shown to anyone once isolation is on).
            if owner is not None and run.get("owner_email") != owner:
                return None
            self._db.execute(cur,
                "SELECT file,engine,status,score,compliant,skipped_rules,remediated_at,drive_write_url,acp_stamped,published_at,size_kb,pages,sheets "
                "FROM file_records WHERE scan_id=%s ORDER BY file", (sid,))
            files = self._db.fetchall(cur)
            # file_records has no per-file source column (every file in one scan shares the
            # scan's single source) — derive the friendly sourceName here, at the single read
            # path, so every consumer (Overview/Dashboard/FileDrawer/Monitor/Publish/...) gets
            # it without a schema change. Was previously unset on real scans (SIM-only field),
            # which silently blanked any "by source" chart.
            src_label = _SOURCE_LABEL.get(run.get("source"), run.get("source"))
            for f in files:
                f["sourceName"] = src_label
                self._db.execute(cur,
                    "SELECT rule_id,wcag,severity,detail FROM issue_records WHERE scan_id=%s AND file=%s",
                    (sid, f["file"]))
                f["issues"] = self._db.fetchall(cur)
            return {"run": run, "files": files}

    def get_scan_diff(self, cur_id: str, prev_id: str, owner: str | None = None) -> dict | None:
        """Diff two scans (ADR 0009) → per-file score regressions / improvements + the WCAG
        criteria that flipped pass→fail. Owner-scoped: both scans must belong to the caller."""
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT id, owner_email, completed_at FROM scan_runs WHERE id IN (%s,%s)", (cur_id, prev_id))
            runs = {r["id"]: r for r in self._db.fetchall(cur)}
            if cur_id not in runs or prev_id not in runs:
                return None
            if owner is not None and (runs[cur_id].get("owner_email") != owner or runs[prev_id].get("owner_email") != owner):
                return None

            def _files(sid):
                self._db.execute(cur, "SELECT file, score FROM file_records WHERE scan_id=%s", (sid,))
                return {r["file"]: r.get("score") for r in self._db.fetchall(cur)}

            def _traces(sid):
                self._db.execute(cur, "SELECT file, rule_id, plain_name, outcome FROM scan_rule_traces WHERE scan_id=%s", (sid,))
                out: dict = {}
                for r in self._db.fetchall(cur):
                    out.setdefault(r["file"], {})[r["rule_id"]] = (str(r["outcome"]).upper(), r["plain_name"])
                return out

            def _severities(sid):
                # scan_rule_traces has no severity column (it's an SC-level rollup); the
                # real per-finding severity lives on issue_records, keyed by the raw
                # ruleId. Roll up to (file, SC) → worst severity, since a "broke" entry
                # is reported at the SC level and a SC can carry findings of mixed
                # severity (rare, but the regression card should show the worst case).
                self._db.execute(cur, "SELECT file, wcag, severity FROM issue_records WHERE scan_id=%s", (sid,))
                out: dict = {}
                for r in self._db.fetchall(cur):
                    sc = _extract_sc(r.get("wcag", ""))
                    if not sc:
                        continue
                    cell = out.setdefault(r["file"], {})
                    sev = r.get("severity")
                    if sev and _ISSUE_SEV_RANK.get(sev, 0) > _ISSUE_SEV_RANK.get(cell.get(sc), 0):
                        cell[sc] = sev
                return out

            fp, fc = _files(prev_id), _files(cur_id)
            tp, tc = _traces(prev_id), _traces(cur_id)
            sevs = _severities(cur_id)

        regressed, improved, new, removed = [], [], [], []
        for f, cs in fc.items():
            if f not in fp:
                new.append({"file": f, "score": cs}); continue
            ps = fp[f]
            if ps is None or cs is None:
                continue
            delta = cs - ps
            if delta < 0:
                broke = [{"sc": rid, "name": name, "severity": sevs.get(f, {}).get(rid)}
                         for rid, (outcome, name) in tc.get(f, {}).items()
                         if outcome == "FAIL" and tp.get(f, {}).get(rid, ("",))[0] == "PASS"]
                broke.sort(key=lambda b: -_ISSUE_SEV_RANK.get(b["severity"], 0))
                regressed.append({"file": f, "prev": ps, "cur": cs, "delta": delta, "broke": broke[:6]})
            elif delta > 0:
                improved.append({"file": f, "prev": ps, "cur": cs, "delta": delta})
        removed = [{"file": f, "score": fp[f]} for f in fp if f not in fc]
        regressed.sort(key=lambda x: x["delta"])          # worst (most negative) first
        improved.sort(key=lambda x: -x["delta"])
        return {
            "cur_id": cur_id, "prev_id": prev_id,
            "cur_at": runs[cur_id].get("completed_at"), "prev_at": runs[prev_id].get("completed_at"),
            "summary": {"regressed": len(regressed), "improved": len(improved), "new": len(new), "removed": len(removed)},
            "regressed": regressed[:50], "improved": improved[:50], "new": new[:50], "removed": removed[:50],
        }

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
            "owner_email": rows.get("owner_email") or None,   # who scheduled it (scans attributed here)
            "source": rows.get("source") or "drive",          # background sweeps default to Drive (ADC)
        }

    def save_schedule(self, enabled: bool, interval_minutes: int,
                      owner: str | None = None, source: str | None = None) -> None:
        pairs = [("enabled", str(enabled).lower()), ("interval_minutes", str(interval_minutes))]
        if owner:
            pairs.append(("owner_email", owner))
        if source:
            pairs.append(("source", source))
        with self._db.cursor() as cur:
            for k, v in pairs:
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

    def remediation_status(self, scan_id: str) -> dict:
        """Live progress for an in-flight remediation batch: how many remediate_file
        jobs are still queued/running for this scan, plus the most recently fixed file."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT COUNT(*) AS n FROM jobs WHERE scan_id=%s AND type='remediate_file' "
                "AND status IN ('queued','running')", (scan_id,))
            in_flight = self._db.fetchone(cur)["n"]
            self._db.execute(cur,
                "SELECT COUNT(*) AS n FROM jobs WHERE scan_id=%s AND type='remediate_file' "
                "AND status='dead'", (scan_id,))
            failed = self._db.fetchone(cur)["n"]
            self._db.execute(cur,
                "SELECT file,drive_write_url FROM file_records WHERE scan_id=%s "
                "AND remediated_at IS NOT NULL ORDER BY remediated_at DESC LIMIT 1", (scan_id,))
            latest = self._db.fetchone(cur)
        return {"in_flight": in_flight, "failed": failed,
                "latest_file": latest["file"] if latest else None,
                "latest_url": latest["drive_write_url"] if latest else None}

    def get_file_drive_id(self, scan_id: str, file: str) -> str | None:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT drive_file_id FROM file_records WHERE scan_id=%s AND file=%s",
                (scan_id, file))
            row = self._db.fetchone(cur)
        return row["drive_file_id"] if row else None

    def record_publish(self, scan_id: str, file: str, published_url: str | None = None) -> str:
        """Mark a file published (ADR 0010 archive-copy). Stores the Drive URL of the
        published fixed copy when one was written; COALESCE keeps a prior URL if this
        publish was record-only."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE file_records SET published_at=%s, published_url=COALESCE(%s, published_url) "
                "WHERE scan_id=%s AND file=%s",
                (now, published_url, scan_id, file))
        return now

    def refresh_scan_aggregate(self, scan_id: str) -> dict:
        """Re-compute avg_score and certifiable from current file_records — called after
        a single-file rescore so the scan summary stays consistent without a full finalize."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE scan_runs SET "
                "certifiable=(SELECT COALESCE(SUM(compliant),0) FROM file_records WHERE scan_id=%s), "
                "avg_score=(SELECT ROUND(AVG(score)) FROM file_records WHERE scan_id=%s AND score IS NOT NULL) "
                "WHERE id=%s",
                (scan_id, scan_id, scan_id))
            self._db.execute(cur,
                "SELECT files,certifiable,uncertain,error,avg_score FROM scan_runs WHERE id=%s", (scan_id,))
            return self._db.fetchone(cur) or {}

    def get_file_record(self, scan_id: str, file: str) -> dict | None:
        """Return the full file_records row for one file in a scan."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT file,engine,status,score,compliant,drive_file_id,remediated_at,published_at "
                "FROM file_records WHERE scan_id=%s AND file=%s",
                (scan_id, file))
            return self._db.fetchone(cur)

    def record_remediation(self, scan_id: str, file: str, drive_write_url: str | None = None,
                           blob_url: str | None = None) -> str:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with self._db.cursor() as cur:
            if blob_url is not None:
                self._db.execute(cur,
                    "UPDATE file_records SET remediated_at=%s, drive_write_url=%s, blob_url=%s "
                    "WHERE scan_id=%s AND file=%s",
                    (now, drive_write_url, blob_url, scan_id, file))
            else:
                # Blob not configured (e.g. local dev) — leave blob_url untouched rather
                # than clobbering a prior value with NULL.
                self._db.execute(cur,
                    "UPDATE file_records SET remediated_at=%s, drive_write_url=%s "
                    "WHERE scan_id=%s AND file=%s",
                    (now, drive_write_url, scan_id, file))
        return now

    def get_remediation_urls(self, scan_id: str, file: str) -> dict | None:
        """blob_url + drive_write_url for a remediated file's download route."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT blob_url, drive_write_url FROM file_records WHERE scan_id=%s AND file=%s",
                (scan_id, file))
            return self._db.fetchone(cur)

    def find_remediation_for_file(self, owner: str | None, scan_id: str, file: str) -> dict | None:
        """Most-recent recorded remediation of the SAME document across this owner's scans.

        Both the file_records remediation row AND the Blob object are keyed by scan_id,
        but an ADR 0011 incremental re-scan mints a NEW scan_id and, for an unchanged
        file, reuses the prior analysis WITHOUT re-remediating — so the fixed copy stays
        under the scan_id that actually ran the remediation. When the download route can't
        find a remediation on the scan the user is viewing, resolve the document's stable
        identity (Drive id first — survives rename; else byte-identical checksum; else the
        file name) and return the newest COMPLETED scan that DID record one, so the fixed
        bytes remain reachable from a later scan's drawer. Returns {scan_id, file, blob_url,
        drive_write_url} — scan_id/file identify where the Blob object actually lives (the
        caller downloads from there, not the viewed scan). None if no prior remediation."""
        with self._db.cursor() as cur:
            # Identity of the file as seen in the scan the user is viewing.
            self._db.execute(cur,
                "SELECT drive_file_id, checksum FROM file_records WHERE scan_id=%s AND file=%s",
                (scan_id, file))
            cur_row = self._db.fetchone(cur)
            if not cur_row:
                return None
            drive_file_id = cur_row.get("drive_file_id")
            checksum = cur_row.get("checksum")
            if drive_file_id:
                match_sql, match_val = "fr.drive_file_id=%s", drive_file_id
            elif checksum:
                match_sql, match_val = "fr.checksum=%s", checksum
            else:
                match_sql, match_val = "fr.file=%s", file
            self._db.execute(cur,
                "SELECT fr.scan_id, fr.file, fr.blob_url, fr.drive_write_url "
                "FROM file_records fr JOIN scan_runs sr ON sr.id = fr.scan_id "
                f"WHERE sr.owner_email=%s AND {match_sql} "
                "AND (fr.blob_url IS NOT NULL OR fr.drive_write_url IS NOT NULL) "
                "AND sr.completed_at IS NOT NULL "
                "ORDER BY sr.completed_at DESC LIMIT 1",
                (owner, match_val))
            return self._db.fetchone(cur)

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

    def queue_hitl_deferral(self, scan_id: str, file: str, note: str, count: int = 1,
                            rule_id: str = "1.1.1/deferred") -> str | None:
        """Queue ONE human-review item for a remediation deferral — e.g. Office images
        with no faithful alt source (remediate_office). Those findings carry fix_mode
        'auto', so queue_hitl_items' ai-assisted pull never sees them; without this
        the deferral is reported in the job result and then silently dropped.
        Idempotent per (scan, file, rule) like queue_hitl_items."""
        from datetime import datetime, timezone
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT 1 FROM hitl_queue WHERE scan_id=%s AND file=%s AND rule_id=%s",
                (scan_id, file, rule_id))
            if self._db.fetchone(cur):
                return None
            item_id = uuid.uuid4().hex[:12]
            self._db.execute(cur,
                "INSERT INTO hitl_queue(id,created_at,scan_id,file,rule_id,rule_name,finding_count,status) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,'pending')",
                (item_id, datetime.now(timezone.utc).isoformat(), scan_id, file, rule_id,
                 note[:200], count))
        return item_id

    def queue_hitl_review_for_file(self, scan_id: str, file: str,
                                   rules: list[dict]) -> list[dict]:
        """Queue HITL review items for specific FAILing rules of ONE file — the human-
        judgment findings a remediate_file run could NOT verifiably auto-clear (contrast
        sign-off, link purpose, structure, or an auto fix that didn't take on re-scan).
        Without this the residual routes to nobody: queue_hitl_items only pulls
        fix_mode='ai-assisted' scan-wide, so a fix_mode='auto' finding the remediator
        couldn't clear (e.g. 1.4.3 contrast needing design sign-off) silently vanishes and
        the file can never re-validate to compliant. `rules` = [{rule_id, rule_name,
        finding_count}]. Idempotent per (scan, file, rule) like queue_hitl_items /
        queue_hitl_deferral — repeat remediate clicks never duplicate. Returns new items."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        created: list[dict] = []
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT rule_id FROM hitl_queue WHERE scan_id=%s AND file=%s", (scan_id, file))
            already = {r["rule_id"] for r in self._db.fetchall(cur)}
            for r in rules:
                rid = r.get("rule_id")
                if not rid or rid in already:
                    continue
                item_id = uuid.uuid4().hex[:12]
                name = r.get("rule_name") or rid
                count = r.get("finding_count") or 1
                self._db.execute(cur,
                    "INSERT INTO hitl_queue(id,created_at,scan_id,file,rule_id,rule_name,finding_count,status) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,'pending')",
                    (item_id, now, scan_id, file, rid, name, count))
                already.add(rid)
                created.append({"id": item_id, "scan_id": scan_id, "file": file,
                                "rule_id": rid, "rule_name": name, "finding_count": count,
                                "status": "pending", "created_at": now})
        return created

    def mark_file_compliant_if_reviewed(self, scan_id: str, file: str) -> bool:
        """After a HITL resolution: a REMEDIATED file whose every HITL item is 'approved'
        (none pending / rejected / skipped) is fully conformant — its auto fixes verified
        and its human-judgment findings signed off. Flip file_records.compliant=1 and set
        score=100 so it advances to Publish (Publish gates on f.compliant), then refresh
        the scan aggregate (certifiable = Σcompliant). Composite by design: a plain re-scan
        of the fixed copy can't clear a finding whose resolution IS the human approval
        (e.g. an approved link-text rewrite), so approval — not re-analysis — is the gate.
        Idempotent: an already-compliant file, an un-remediated file, or one with any
        item still pending / rejected / skipped returns False and changes nothing."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT compliant, remediated_at FROM file_records WHERE scan_id=%s AND file=%s",
                (scan_id, file))
            rec = self._db.fetchone(cur)
            if not rec or not rec.get("remediated_at") or rec.get("compliant"):
                return False
            self._db.execute(cur,
                "SELECT status, COUNT(*) AS n FROM hitl_queue WHERE scan_id=%s AND file=%s "
                "GROUP BY status", (scan_id, file))
            counts = {r["status"]: r["n"] for r in self._db.fetchall(cur)}
        total = sum(counts.values())
        if total == 0 or counts.get("approved", 0) != total:
            return False   # still items pending / rejected / skipped — not fully resolved
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE file_records SET compliant=1, score=100, status='pass' "
                "WHERE scan_id=%s AND file=%s", (scan_id, file))
        self.refresh_scan_aggregate(scan_id)
        return True

    def list_hitl_queue(self, status: str | None = None, scan_id: str | None = None,
                        owner: str | None = None) -> list[dict]:
        """List HITL items. `owner` scopes to the signed-in user's own documents (joined via
        the scan's owner_email) — the inbox must not show another tenant's review items."""
        conds, params = [], []
        if status:
            conds.append("status=%s"); params.append(status)
        if scan_id:
            conds.append("scan_id=%s"); params.append(scan_id)
        if owner:
            conds.append("scan_id IN (SELECT id FROM scan_runs WHERE owner_email=%s)"); params.append(owner)
        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        with self._db.cursor() as cur:
            self._db.execute(cur, f"SELECT * FROM hitl_queue{where} ORDER BY created_at DESC", tuple(params))
            return self._db.fetchall(cur)

    def get_hitl_item(self, item_id: str) -> dict | None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT * FROM hitl_queue WHERE id=%s", (item_id,))
            return self._db.fetchone(cur)

    def update_hitl_item(self, item_id: str, status: str, reviewer_note: str | None = None,
                         approved_value: str | None = None) -> dict | None:
        """approved_value: the reviewer's final (AI-drafted or hand-edited) text for a
        semantic finding — e.g. alt text / link text. COALESCE so a reject/skip call
        (which never passes one) never clobbers a value set by an earlier approve."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE hitl_queue SET status=%s, reviewed_at=%s, reviewer_note=%s, "
                "approved_value=COALESCE(%s, approved_value) WHERE id=%s",
                (status, now, reviewer_note, approved_value, item_id))
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

    def get_allowlist(self) -> list[str]:
        """Runtime-editable allowed emails (managed from Settings), lowercased."""
        raw = self.get_setting("allowed_emails", "") or ""
        return [e.strip().lower() for e in raw.split(",") if e.strip()]

    def set_allowlist(self, emails: list[str]) -> list[str]:
        clean = sorted({e.strip().lower() for e in (emails or []) if e and "@" in e})
        self.set_setting("allowed_emails", ",".join(clean))
        return clean

    def get_ai_enabled(self) -> bool:
        """Platform AI mode. Defaults to enabled; admin can hard-disable it
        (deterministic-only mode) — which overrides any per-scan ?ai=true."""
        return self.get_setting("ai_enabled", "true") != "false"

    def set_ai_enabled(self, enabled: bool) -> None:
        self.set_setting("ai_enabled", "true" if enabled else "false")

    def get_drive_mirror_enabled(self) -> bool:
        """ADR 0010: whether a successful Blob remediation is also auto-mirrored to
        Drive. Defaults to enabled (the original ADR 0010 behavior). Off = Blob-only;
        a Drive copy can still be produced on demand elsewhere (e.g. FileDrawer's own
        upload-to-drive action), just not automatically after every remediation."""
        return self.get_setting("drive_mirror_enabled", "true") != "false"

    def set_drive_mirror_enabled(self, enabled: bool) -> None:
        self.set_setting("drive_mirror_enabled", "true" if enabled else "false")

    def get_drive_mirror_folder(self) -> str:
        """Drive folder name remediated copies are mirrored into. Defaults to the
        original hardcoded 'Remediated'."""
        return self.get_setting("drive_mirror_folder", "Remediated")

    def set_drive_mirror_folder(self, folder: str) -> None:
        self.set_setting("drive_mirror_folder", folder)

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

    _SECRET_PAYLOAD_KEYS = ("drive_token", "sp_token", "token")

    def _scrub_payload_secrets(self, job_id: str) -> str | None:
        """Payload JSON with short-lived auth tokens removed — so a TERMINAL (done/dead)
        job row doesn't persist a plaintext Drive/Graph token in Postgres (dead-lettered
        rows otherwise linger until purge). In-flight (queued/running) jobs keep the
        token: it's the deliberate cross-replica/restart durability path (see
        handlers._remediate_file), and it's short-lived (~1h) anyway. Returns None when
        there's no payload or nothing to scrub, so the caller leaves payload untouched."""
        import json as _j
        job = self.get_job(job_id)
        if not job:
            return None
        payload = job.get("payload")
        try:
            data = payload if isinstance(payload, dict) else _j.loads(payload or "{}")
        except Exception:
            return None
        if not isinstance(data, dict) or not any(k in data for k in self._SECRET_PAYLOAD_KEYS):
            return None
        for k in self._SECRET_PAYLOAD_KEYS:
            data.pop(k, None)
        return _j.dumps(data)

    def complete_job(self, job_id: str) -> None:
        scrubbed = self._scrub_payload_secrets(job_id)
        with self._db.cursor() as cur:
            if scrubbed is not None:
                self._db.execute(cur,
                    "UPDATE jobs SET status='done', updated_at=%s, last_error=NULL, payload=%s WHERE id=%s",
                    (self._now(), scrubbed, job_id))
            else:
                self._db.execute(cur,
                    "UPDATE jobs SET status='done', updated_at=%s, last_error=NULL WHERE id=%s",
                    (self._now(), job_id))

    def dead_letter_breakdown(self, owner: str | None = None) -> dict:
        """Diagnostic: dead-lettered jobs grouped by type + the most common errors.
        owner scopes to the caller's own jobs so error text (which can name a file)
        never leaks across tenants."""
        scope = " AND scan_id IN (SELECT id FROM scan_runs WHERE owner_email=%s)" if owner else ""
        sp = (owner,) if owner else ()
        out: dict = {}
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT type, COUNT(*) AS n FROM jobs WHERE status='dead'" + scope + " GROUP BY type", sp)
            out["by_type"] = {r["type"]: r["n"] for r in self._db.fetchall(cur)}
            self._db.execute(cur,
                "SELECT type, SUBSTR(last_error,1,200) AS err, COUNT(*) AS n FROM jobs "
                "WHERE status='dead'" + scope + " GROUP BY type, SUBSTR(last_error,1,200) ORDER BY n DESC LIMIT 15", sp)
            out["top_errors"] = [{"type": r["type"], "n": r["n"], "error": r["err"]}
                                 for r in self._db.fetchall(cur)]
        return out

    def purge_dead_jobs(self, owner: str | None = None) -> int:
        """Delete dead-lettered jobs (unrecoverable). owner scopes the purge to the
        caller's own jobs so one tenant can't clear another's. Returns how many removed."""
        scope = " AND scan_id IN (SELECT id FROM scan_runs WHERE owner_email=%s)" if owner else ""
        sp = (owner,) if owner else ()
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT COUNT(*) AS n FROM jobs WHERE status='dead'" + scope, sp)
            n = self._db.fetchone(cur)["n"]
            self._db.execute(cur, "DELETE FROM jobs WHERE status='dead'" + scope, sp)
        return n

    def purge_done_jobs(self, older_than_hours: int = 24) -> int:
        """Delete completed ('done') jobs older than the cutoff so the jobs table (and the
        claim index) don't grow unbounded — done rows were previously never purged (audit
        P2). Dead jobs are retained for diagnostics; purge_dead_jobs handles those."""
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=older_than_hours)).isoformat()
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT COUNT(*) AS n FROM jobs WHERE status='done' AND updated_at<%s", (cutoff,))
            n = self._db.fetchone(cur)["n"]
            self._db.execute(cur, "DELETE FROM jobs WHERE status='done' AND updated_at<%s", (cutoff,))
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
            scrubbed = self._scrub_payload_secrets(job_id)
            with self._db.cursor() as cur:
                if scrubbed is not None:
                    self._db.execute(cur,
                        "UPDATE jobs SET status='dead', last_error=%s, updated_at=%s, payload=%s WHERE id=%s",
                        (error[:2000], now.isoformat(), scrubbed, job_id))
                else:
                    self._db.execute(cur,
                        "UPDATE jobs SET status='dead', last_error=%s, updated_at=%s WHERE id=%s",
                        (error[:2000], now.isoformat(), job_id))
            # One greppable stdout line per dead-letter — the platform alert
            # (Log Analytics scheduled query) keys on 'job dead-lettered'.
            print(f"[acp] job dead-lettered: id={job_id} type={job.get('type')} error={error[:160]}", flush=True)
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

    def job_stats(self, owner: str | None = None) -> dict:
        # owner → only this user's jobs (scoped via their scans), so the queue view
        # doesn't leak other tenants' activity. None = global (operator/admin context).
        scope = " WHERE scan_id IN (SELECT id FROM scan_runs WHERE owner_email=%s)" if owner else ""
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT status, COUNT(*) AS n FROM jobs" + scope + " GROUP BY status",
                             (owner,) if owner else ())
            return {r["status"]: r["n"] for r in self._db.fetchall(cur)}

    def list_jobs(self, status: str | None = None, limit: int = 200, owner: str | None = None) -> list[dict]:
        clauses, params = [], []
        if status:
            clauses.append("status=%s"); params.append(status)
        if owner:                                      # scope to the caller's own jobs
            clauses.append("scan_id IN (SELECT id FROM scan_runs WHERE owner_email=%s)"); params.append(owner)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT * FROM jobs" + where + " ORDER BY updated_at DESC LIMIT %s", tuple(params))
            return self._db.fetchall(cur)

    # ── Document-centric layer (ADR 0003, Phase 1) ─────────────────────────────
    def upsert_document(self, doc_id: str, *, source: str, path: str, content_hash: str | None,
                        owner: str | None, created_at: str, last_seen: str,
                        triage_score: int, triage_rationale: str) -> None:
        """Upsert a document's scan-derived fields. department/regulatory_tags/
        business_criticality/usage_signal aren't set here (no real-scan source for them
        yet — ADR 0003's own noted gap) and are left for an admin/connector to populate
        later; the ON CONFLICT clause deliberately doesn't touch those columns."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO documents(doc_id,source,path,content_hash,owner,created_at,"
                "last_seen,triage_score,triage_rationale) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT(doc_id) DO UPDATE SET path=EXCLUDED.path, "
                "content_hash=EXCLUDED.content_hash, last_seen=EXCLUDED.last_seen, "
                "triage_score=EXCLUDED.triage_score, triage_rationale=EXCLUDED.triage_rationale",
                (doc_id, source, path, content_hash, owner, created_at, last_seen,
                 triage_score, triage_rationale))

    def get_document(self, doc_id: str) -> dict | None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT * FROM documents WHERE doc_id=%s", (doc_id,))
            return self._db.fetchone(cur)

    # ── Per-violation remediation state (ADR 0003, Phase 2) ────────────────────
    def list_file_identities(self, scan_id: str) -> list[dict]:
        """{file, drive_file_id, checksum} for every file in a scan -- the inputs
        resolve_doc_id needs, kept as its own narrow query so get_scan's broader
        (widely-called) SELECT doesn't grow just for this."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT file, drive_file_id, checksum FROM file_records WHERE scan_id=%s",
                (scan_id,))
            return self._db.fetchall(cur)

    def seed_remediation_state(self, doc_id: str, rule_id: str, scan_id: str) -> None:
        """Create a 'not_started' row for a newly-seen violation. Never overwrites an
        existing row -- state only ever moves forward via an explicit transition
        (upsert_remediation_state), so a violation still failing on a later scan doesn't
        get silently reset if it had already progressed."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO remediation_state(doc_id,rule_id,state,updated_at,last_scan_id) "
                "VALUES(%s,%s,'not_started',%s,%s) ON CONFLICT(doc_id,rule_id) DO NOTHING",
                (doc_id, rule_id, self._now(), scan_id))

    def upsert_remediation_state(self, doc_id: str, rule_id: str, state: str, scan_id: str) -> None:
        """Explicit forward transition (HITL resolution, auto-remediation applied)."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO remediation_state(doc_id,rule_id,state,updated_at,last_scan_id) "
                "VALUES(%s,%s,%s,%s,%s) ON CONFLICT(doc_id,rule_id) DO UPDATE SET "
                "state=EXCLUDED.state, updated_at=EXCLUDED.updated_at, last_scan_id=EXCLUDED.last_scan_id",
                (doc_id, rule_id, state, self._now(), scan_id))

    def get_remediation_state(self, doc_id: str) -> list[dict]:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT rule_id, state, updated_at, last_scan_id FROM remediation_state "
                "WHERE doc_id=%s ORDER BY rule_id", (doc_id,))
            return self._db.fetchall(cur)

    def get_remediation_state_for_file(self, scan_id: str, file: str) -> list[dict]:
        """Same as get_remediation_state, but keyed by (scan_id, file) — what the UI
        actually has on hand — instead of doc_id, which it doesn't."""
        from documents import resolve_doc_id
        drive_file_id = self.get_file_drive_id(scan_id, file)
        doc_id = resolve_doc_id("drive", drive_file_id, file, None)
        return self.get_remediation_state(doc_id)

    def list_auto_fail_rules(self, scan_id: str, file: str) -> list[str]:
        """rule_ids that FAILed for this file and are deterministically auto-fixable --
        what a successful remediate_file run actually addresses."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT rule_id FROM scan_rule_traces "
                "WHERE scan_id=%s AND file=%s AND fix_mode='auto' AND outcome='FAIL'",
                (scan_id, file))
            return [r["rule_id"] for r in self._db.fetchall(cur)]

    # ── Configurable disposition (ADR 0003, Phase 3 — preview only) ────────────
    def create_disposition_policy(self, policy_id: str, *, name: str, match: str, action: str,
                                  action_config: str, requires_approval: bool, enabled: bool) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO disposition_policy(policy_id,name,match,action,action_config,"
                "requires_approval,enabled) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (policy_id, name, match, action, action_config, int(requires_approval), int(enabled)))

    def list_disposition_policies(self) -> list[dict]:
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT * FROM disposition_policy ORDER BY name")
            return self._db.fetchall(cur)

    def get_disposition_policy(self, policy_id: str) -> dict | None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT * FROM disposition_policy WHERE policy_id=%s", (policy_id,))
            return self._db.fetchone(cur)

    def set_disposition_policy_enabled(self, policy_id: str, enabled: bool) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "UPDATE disposition_policy SET enabled=%s WHERE policy_id=%s",
                             (int(enabled), policy_id))

    def list_all_documents(self) -> list[dict]:
        """Every document row -- used only by the disposition preview evaluator, which
        needs the full set to run a predicate in Python (see api/disposition.py)."""
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT * FROM documents")
            return self._db.fetchall(cur)

    # ── Disposition audit (ADR 0003 Phase 3 — execute path) ─────────────────────
    def create_disposition_audit(self, audit_id: str, *, doc_id: str, policy_id: str,
                                 action: str, result: str, detail: str) -> None:
        """Append-only, like decision_log: rows are inserted and their result may move
        forward (pending_approval → applied/failed/rejected) but never deleted."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO disposition_audit(id,ts,doc_id,policy_id,action,result,detail) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (audit_id, self._now(), doc_id, policy_id, action, result, detail))

    def get_disposition_audit(self, audit_id: str) -> dict | None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT * FROM disposition_audit WHERE id=%s", (audit_id,))
            return self._db.fetchone(cur)

    def list_disposition_audit(self, result: str | None = None,
                               policy_id: str | None = None, limit: int = 500) -> list[dict]:
        q, params = "SELECT * FROM disposition_audit", []
        conds = []
        if result:
            conds.append("result=%s"); params.append(result)
        if policy_id:
            conds.append("policy_id=%s"); params.append(policy_id)
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY ts DESC LIMIT %s"; params.append(limit)
        with self._db.cursor() as cur:
            self._db.execute(cur, q, tuple(params))
            return self._db.fetchall(cur)

    def set_disposition_audit_result(self, audit_id: str, result: str, detail: str) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "UPDATE disposition_audit SET result=%s, detail=%s WHERE id=%s",
                (result, detail, audit_id))

    def doc_has_disposition(self, doc_id: str, policy_id: str) -> bool:
        """True if this policy already produced a live outcome for this doc — used to
        make execute idempotent (rejected/failed rows don't block a re-run)."""
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT 1 FROM disposition_audit WHERE doc_id=%s AND policy_id=%s "
                "AND result IN ('pending_approval','applied') LIMIT 1",
                (doc_id, policy_id))
            return self._db.fetchone(cur) is not None

    # ── Phased remediation campaigns (ADR 0003, Phase 4) ────────────────────────
    def create_campaign(self, campaign_id: str, *, name: str, status: str, scope: str) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO campaign(campaign_id,name,status,scope,created_at) VALUES(%s,%s,%s,%s,%s)",
                (campaign_id, name, status, scope, self._now()))

    def list_campaigns(self, scan_id: str | None = None) -> list[dict]:
        """scan_id filters in Python (scope is opaque JSON) -- campaign counts are
        small, not worth a JSON-path query across the sqlite/postgres split."""
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT * FROM campaign ORDER BY created_at DESC")
            rows = self._db.fetchall(cur)
        if scan_id is None:
            return rows
        import json as _json
        return [r for r in rows if _json.loads(r["scope"] or "{}").get("scan_id") == scan_id]

    def get_campaign(self, campaign_id: str) -> dict | None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT * FROM campaign WHERE campaign_id=%s", (campaign_id,))
            return self._db.fetchone(cur)

    def update_campaign_status(self, campaign_id: str, status: str) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "UPDATE campaign SET status=%s WHERE campaign_id=%s", (status, campaign_id))

    def create_campaign_batch(self, batch_id: str, *, campaign_id: str, seq: int, status: str,
                              filter: str, deadline: str | None) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "INSERT INTO campaign_batch(batch_id,campaign_id,seq,status,filter,deadline) "
                "VALUES(%s,%s,%s,%s,%s,%s)",
                (batch_id, campaign_id, seq, status, filter, deadline))

    def list_campaign_batches(self, campaign_id: str) -> list[dict]:
        with self._db.cursor() as cur:
            self._db.execute(cur,
                "SELECT * FROM campaign_batch WHERE campaign_id=%s ORDER BY seq", (campaign_id,))
            return self._db.fetchall(cur)

    def update_campaign_batch_status(self, batch_id: str, status: str) -> None:
        with self._db.cursor() as cur:
            self._db.execute(cur, "UPDATE campaign_batch SET status=%s WHERE batch_id=%s", (status, batch_id))

    def list_scan_severities(self, scan_id: str) -> list[dict]:
        """{file, severity} for every finding in a scan -- the input compute_batches
        (api/campaigns.py) buckets by, kept as its own narrow query like
        list_file_identities (Phase 2) rather than widening get_scan's SELECT."""
        with self._db.cursor() as cur:
            self._db.execute(cur, "SELECT file, severity FROM issue_records WHERE scan_id=%s", (scan_id,))
            return self._db.fetchall(cur)
