"""P-16 — Report provenance and freshness in the PDF report.

Additions to the Assessment scope block:
  - Report generated: timestamp (when the PDF was rendered)
  - Scan ID: run['id']
  - Report schema: v{REPORT_SCHEMA_VERSION}
  - Build: ACP_BUILD_SHA env var (or '—')

Plus a snapshot notice near the top when run['status'] indicates
the scan was still in progress at render time.
"""
import io
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

from pypdf import PdfReader

_RUN_DONE = {"id": "scan-p16-001", "completed_at": "2026-08-24T12:00:00",
             "avg_score": 95, "owner_email": "ada@example.com"}
_RUN_RUNNING = {**_RUN_DONE, "status": "running"}
_META = {"target": "WCAG 2.1 AA", "version": "3.1", "hash": "deadbeef1234abcd"}
_FILES = [{"file": "report.docx", "compliant": 1, "score": 95, "status": "pass", "issues": []}]
_FACTS = {
    "documents": [{"file": "report.docx", "evaluated": 20, "findings": 0,
                   "not_evaluated": 2, "remediated": 0, "remaining": 0,
                   "approvals": 0, "not_evaluated_criteria": [], "review_criteria": [],
                   "by_mode": {"auto": 20}}],
    "scope": {
        "catalog_size": 22,
        "by_mode": {"auto": 20},
        "not_evaluated_criteria": [],
        "review_criteria": [],
        "human_only_criteria": [],
        "formats_not_opened": [],
    },
    "remediated_total": 0,
    "approvals_total": 0,
    "review": {"reviewed": 0, "approved": 0, "rejected": 0, "skipped": 0},
}


def _flat(pdf: bytes) -> str:
    text = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)
    return re.sub(r"\s+", " ", text)


# ── Report-generated timestamp ────────────────────────────────────────────────

def test_report_generated_timestamp_appears_in_scope_block():
    """P-16: 'Report generated' label appears in the assessment scope table."""
    from report import build_report
    t = _flat(build_report(_RUN_DONE, _FILES, _META, facts=_FACTS))
    assert "Report generated" in t


def test_report_generated_value_is_a_date():
    """P-16: the rendered timestamp looks like a YYYY-MM-DD date."""
    from report import build_report
    t = _flat(build_report(_RUN_DONE, _FILES, _META, facts=_FACTS))
    assert re.search(r"20\d\d-\d\d-\d\d", t), "expected a date in YYYY-MM-DD format"


# ── Scan ID ───────────────────────────────────────────────────────────────────

def test_scan_id_appears_in_scope_block():
    """P-16: 'Scan ID' label and the actual scan ID appear in the scope table."""
    from report import build_report
    t = _flat(build_report(_RUN_DONE, _FILES, _META, facts=_FACTS))
    assert "Scan ID" in t
    assert "scan-p16-001" in t


# ── Report schema version ─────────────────────────────────────────────────────

def test_report_schema_appears_in_scope_block():
    """P-16: 'Report schema' label and 'v1.0' appear in the scope table."""
    from report import build_report
    t = _flat(build_report(_RUN_DONE, _FILES, _META, facts=_FACTS))
    assert "Report schema" in t
    assert "v1.0" in t


# ── Build commit ──────────────────────────────────────────────────────────────

def test_build_shows_dash_when_env_absent():
    """P-16: Build shows '—' when ACP_BUILD_SHA is not set."""
    from report import build_report
    env = os.environ.copy()
    env.pop("ACP_BUILD_SHA", None)
    old = os.environ.get("ACP_BUILD_SHA")
    try:
        if "ACP_BUILD_SHA" in os.environ:
            del os.environ["ACP_BUILD_SHA"]
        t = _flat(build_report(_RUN_DONE, _FILES, _META, facts=_FACTS))
        assert "Build" in t
        assert "—" in t
    finally:
        if old is not None:
            os.environ["ACP_BUILD_SHA"] = old


def test_build_sha_appears_when_env_set():
    """P-16: abbreviated build SHA appears in the scope table when ACP_BUILD_SHA is set."""
    from report import build_report
    old = os.environ.get("ACP_BUILD_SHA")
    try:
        os.environ["ACP_BUILD_SHA"] = "abc123def456789"
        t = _flat(build_report(_RUN_DONE, _FILES, _META, facts=_FACTS))
        assert "abc123def456" in t  # first 12 chars
    finally:
        if old is None:
            del os.environ["ACP_BUILD_SHA"]
        else:
            os.environ["ACP_BUILD_SHA"] = old


# ── Snapshot notice ───────────────────────────────────────────────────────────

def test_no_snapshot_notice_when_scan_done():
    """P-16: snapshot notice is absent when scan status is None (completed)."""
    from report import build_report
    t = _flat(build_report(_RUN_DONE, _FILES, _META, facts=_FACTS))
    assert "Snapshot only" not in t


def test_snapshot_notice_when_scan_running():
    """P-16: snapshot notice appears near the top when scan is still running."""
    from report import build_report
    t = _flat(build_report(_RUN_RUNNING, _FILES, _META, facts=_FACTS))
    assert "Snapshot only" in t
    assert "running" in t
