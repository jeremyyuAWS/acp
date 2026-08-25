"""Tests for the three Power BI read-only views (vw_scan_summary, vw_finding_detail,
vw_rule_coverage).

The views are defined in store._PG_VIEWS as CREATE OR REPLACE VIEW (Postgres).  SQLite
does not support that syntax, so these tests translate each definition to
`CREATE VIEW IF NOT EXISTS` and run them against the isolated_store SQLite database.
The column set and join logic is identical; only the CREATE prefix differs.

The structural tests (column names, row counts) run on every checkout without any
external service.  The static-definition tests verify that each view name and its
expected output columns are declared in _PG_VIEWS — a guard that catches a typo or
an accidental deletion of a view without breaking a Postgres connection.
"""
from __future__ import annotations

import re
import sqlite3
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import store as store_mod


# ── helpers ──────────────────────────────────────────────────────────────────

def _sqlite_views(db_path: str) -> None:
    """Create the three Power BI views in a SQLite database.

    SQLite doesn't support CREATE OR REPLACE VIEW, so we replace that prefix
    with CREATE VIEW IF NOT EXISTS before executing each definition.
    """
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        for pg_sql in store_mod._PG_VIEWS:
            sqlite_sql = re.sub(
                r"CREATE\s+OR\s+REPLACE\s+VIEW",
                "CREATE VIEW IF NOT EXISTS",
                pg_sql,
                count=1,
                flags=re.IGNORECASE,
            )
            cur.execute(sqlite_sql)
        conn.commit()
    finally:
        conn.close()


def _query(db_path: str, sql: str) -> list[dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(sql)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


@pytest.fixture()
def views_db(isolated_store, monkeypatch):
    """An isolated SQLite store with schema + Power BI views initialised."""
    db_path = str(store_mod._SQLITE_PATH)
    _sqlite_views(db_path)
    return db_path


def _seed(db_path: str) -> None:
    """Insert one complete scan with two files, two findings, one PII hit,
    and two rule-trace rows — enough for every view to return meaningful rows."""
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO scan_runs (id, owner_email, completed_at, source, rubric_name, "
            "avg_score, files, certifiable, uncertain, error) VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("s1", "alice@example.com", "2026-08-01T00:00:00", "drive", "default",
             75, 2, 1, 0, 0),
        )
        cur.execute(
            "INSERT INTO file_records (scan_id, file, engine, status, score, compliant) "
            "VALUES (?,?,?,?,?,?)",
            ("s1", "report.pdf", "pdf", "analysed", 50, 0),
        )
        cur.execute(
            "INSERT INTO file_records (scan_id, file, engine, status, score, compliant) "
            "VALUES (?,?,?,?,?,?)",
            ("s1", "policy.docx", "office", "analysed", 100, 1),
        )
        cur.execute(
            "INSERT INTO issue_records (scan_id, file, rule_id, wcag, severity, detail) "
            "VALUES (?,?,?,?,?,?)",
            ("s1", "report.pdf", "pdf.tagged", "SC_1_3_1", "CRITICAL", "No structure tree"),
        )
        cur.execute(
            "INSERT INTO issue_records (scan_id, file, rule_id, wcag, severity, detail) "
            "VALUES (?,?,?,?,?,?)",
            ("s1", "report.pdf", "pdf.document-language", "SC_3_1_1", "SERIOUS", "No /Lang"),
        )
        cur.execute(
            "INSERT INTO pii_findings (scan_id, file, pii_type, count, severity) "
            "VALUES (?,?,?,?,?)",
            ("s1", "report.pdf", "EMAIL", 3, "HIGH"),
        )
        cur.execute(
            "INSERT INTO scan_rule_traces "
            "(scan_id, file, rule_id, rule_name, plain_name, level, fix_mode, outcome, finding_count) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("s1", "report.pdf", "pdf.tagged", "TaggedPdfRule", "PDF must be tagged",
             "AA", "ASSISTED", "FAIL", 1),
        )
        cur.execute(
            "INSERT INTO scan_rule_traces "
            "(scan_id, file, rule_id, rule_name, plain_name, level, fix_mode, outcome, finding_count) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            ("s1", "policy.docx", "DOCX-TITLE-001", "DocumentTitleRule",
             "Document must have a title", "AA", "AUTO", "PASS", 0),
        )
        conn.commit()
    finally:
        conn.close()


# ── static definition tests ──────────────────────────────────────────────────

def test_pg_views_defines_three_views():
    names = [re.search(r"VIEW\s+(\w+)", v, re.I).group(1) for v in store_mod._PG_VIEWS]
    assert set(names) == {"vw_scan_summary", "vw_finding_detail", "vw_rule_coverage"}


def test_pg_views_summary_columns():
    sql = next(v for v in store_mod._PG_VIEWS if "vw_scan_summary" in v)
    for col in ("scan_id", "owner_email", "completed_at", "avg_score",
                "certifiable", "critical_findings", "pii_docs_affected", "audit_ready_pct"):
        assert col in sql, f"vw_scan_summary missing column alias: {col}"


def test_pg_views_finding_detail_columns():
    sql = next(v for v in store_mod._PG_VIEWS if "vw_finding_detail" in v)
    for col in ("scan_id", "owner_email", "wcag_criterion", "severity",
                "plain_name", "detail", "page", "location"):
        assert col in sql, f"vw_finding_detail missing column alias: {col}"


def test_pg_views_rule_coverage_columns():
    sql = next(v for v in store_mod._PG_VIEWS if "vw_rule_coverage" in v)
    for col in ("scan_id", "owner_email", "rule_id", "plain_name", "outcome", "finding_count"):
        assert col in sql, f"vw_rule_coverage missing column alias: {col}"


# ── functional query tests ───────────────────────────────────────────────────

def test_vw_scan_summary_row_count(views_db):
    _seed(views_db)
    rows = _query(views_db, "SELECT * FROM vw_scan_summary")
    assert len(rows) == 1
    r = rows[0]
    assert r["scan_id"] == "s1"
    assert r["owner_email"] == "alice@example.com"
    assert r["total_files"] == 2
    assert r["certifiable"] == 1


def test_vw_scan_summary_finding_counts(views_db):
    _seed(views_db)
    r = _query(views_db, "SELECT * FROM vw_scan_summary")[0]
    assert r["critical_findings"] == 1
    assert r["serious_findings"] == 1
    assert r["moderate_findings"] == 0
    assert r["minor_findings"] == 0


def test_vw_scan_summary_pii_docs(views_db):
    _seed(views_db)
    r = _query(views_db, "SELECT * FROM vw_scan_summary")[0]
    assert r["pii_docs_affected"] == 1


def test_vw_scan_summary_audit_ready_pct(views_db):
    _seed(views_db)
    r = _query(views_db, "SELECT * FROM vw_scan_summary")[0]
    # 1 certifiable out of 2 files → 50 %
    assert r["audit_ready_pct"] == 50


def test_vw_finding_detail_row_count(views_db):
    _seed(views_db)
    rows = _query(views_db, "SELECT * FROM vw_finding_detail")
    assert len(rows) == 2


def test_vw_finding_detail_columns_present(views_db):
    _seed(views_db)
    r = _query(views_db, "SELECT * FROM vw_finding_detail WHERE rule_id = 'pdf.tagged'")[0]
    assert r["scan_id"] == "s1"
    assert r["wcag_criterion"] == "SC_1_3_1"
    assert r["severity"] == "CRITICAL"
    assert r["plain_name"] == "PDF must be tagged"
    assert r["engine"] == "pdf"


def test_vw_finding_detail_falls_back_to_rule_id_when_no_trace(views_db):
    """When no scan_rule_trace row exists plain_name falls back to rule_id."""
    _seed(views_db)
    # Insert a finding with no matching trace row.
    conn = sqlite3.connect(views_db)
    try:
        conn.execute(
            "INSERT INTO issue_records (scan_id, file, rule_id, wcag, severity) "
            "VALUES ('s1','report.pdf','pdf.unknown-rule','SC_1_1_1','MODERATE')"
        )
        conn.commit()
    finally:
        conn.close()
    rows = _query(views_db, "SELECT * FROM vw_finding_detail WHERE rule_id='pdf.unknown-rule'")
    assert rows[0]["plain_name"] == "pdf.unknown-rule"


def test_vw_rule_coverage_row_count(views_db):
    _seed(views_db)
    rows = _query(views_db, "SELECT * FROM vw_rule_coverage")
    assert len(rows) == 2


def test_vw_rule_coverage_outcome_values(views_db):
    _seed(views_db)
    outcomes = {r["rule_id"]: r["outcome"] for r in _query(views_db, "SELECT * FROM vw_rule_coverage")}
    assert outcomes["pdf.tagged"] == "FAIL"
    assert outcomes["DOCX-TITLE-001"] == "PASS"


def test_vw_rule_coverage_plain_name_fallback(views_db):
    """Rows whose trace has NULL plain_name fall back to rule_id."""
    _seed(views_db)
    conn = sqlite3.connect(views_db)
    try:
        conn.execute(
            "INSERT INTO scan_rule_traces "
            "(scan_id, file, rule_id, rule_name, plain_name, level, fix_mode, outcome, finding_count) "
            "VALUES ('s1','policy.docx','DOCX-LANG-001','LanguageRule',NULL,'AA','AUTO','PASS',0)"
        )
        conn.commit()
    finally:
        conn.close()
    rows = _query(views_db, "SELECT * FROM vw_rule_coverage WHERE rule_id='DOCX-LANG-001'")
    assert rows[0]["plain_name"] == "DOCX-LANG-001"


def test_vw_scan_summary_empty_when_no_scans(views_db):
    rows = _query(views_db, "SELECT * FROM vw_scan_summary")
    assert rows == []


def test_vw_finding_detail_empty_when_no_findings(views_db):
    _seed(views_db)
    rows = _query(views_db, "SELECT * FROM vw_finding_detail WHERE scan_id='nonexistent'")
    assert rows == []
