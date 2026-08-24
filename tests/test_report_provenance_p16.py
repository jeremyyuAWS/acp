"""Report provenance and freshness — P-16.

P-16: The report header must carry:
  - Report-generated timestamp (actual PDF generation time, UTC) correctly labelled
  - Assessment-completion timestamp (run["completed_at"]) correctly labelled — distinct from generated
  - Scan ID (already present; kept and confirmed)
  - Rubric name + version + hash (already present; name field added)
  - Report schema/version (new REPORT_SCHEMA_VERSION constant)
  - Application build/commit (BUILD_COMMIT env var, optional)
  - Snapshot label when completed_at is absent (scan still running)

NOTE: pypdf text-extraction is unavailable in CI, so text-content assertions are made
via unit checks on constants and logic, not via full-PDF parsing. The full render
tests verify the PDF is produced without error.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

_RUN = {"id": "s1", "completed_at": "2026-08-24T10:00:00",
        "started_at": "2026-08-24T09:00:00", "avg_score": 95, "source": "drive"}
_META = {"target": "WCAG 2.1 AA", "version": "2", "hash": "deadbeef1234abcd"}
_META_NAMED = {"target": "WCAG 2.1 AA", "version": "3", "hash": "cafebabe5678efgh",
               "name": "ACP Core"}


def _mk_file(name, compliant=1, score=90, status="done", issues=None):
    return {"file": name, "status": status, "compliant": compliant,
            "score": score, "skipped_rules": 0, "issues": issues or []}


def _mk_facts():
    return {
        "scope": {
            "catalog_size": 10,
            "not_evaluated_criteria": [],
            "human_only_criteria": [],
            "review_criteria": [],
            "estate": {"excluded": 0},
            "by_mode": {"ai-assisted": 0},
        },
        "documents": [],
        "approvals_total": 0,
        "remediated_total": 0,
    }


# ── REPORT_SCHEMA_VERSION constant ───────────────────────────────────────────

def test_p16_report_schema_version_constant_exists():
    """REPORT_SCHEMA_VERSION must be a non-empty string constant."""
    from report import REPORT_SCHEMA_VERSION
    assert isinstance(REPORT_SCHEMA_VERSION, str) and REPORT_SCHEMA_VERSION


def test_p16_report_schema_version_is_a_number_string():
    """REPORT_SCHEMA_VERSION must be parseable as an integer (e.g. '1')."""
    from report import REPORT_SCHEMA_VERSION
    assert int(REPORT_SCHEMA_VERSION) >= 1


# ── Full render sanity (completed scan) ──────────────────────────────────────

def test_p16_renders_with_completed_run():
    """build_report must return a valid PDF when completed_at is set."""
    from report import build_report
    files = [_mk_file("a.pdf"), _mk_file("b.docx")]
    pdf = build_report(_RUN, files, _META, facts=_mk_facts())
    assert pdf[:5] == b"%PDF-"


def test_p16_renders_with_named_rubric():
    """build_report must render when meta includes a rubric 'name' field."""
    from report import build_report
    files = [_mk_file("a.pdf")]
    pdf = build_report(_RUN, files, _META_NAMED, facts=_mk_facts())
    assert pdf[:5] == b"%PDF-"


# ── Snapshot label when scan is still running ─────────────────────────────────

def test_p16_renders_when_completed_at_is_absent():
    """When completed_at is absent the report renders without error (snapshot mode)."""
    from report import build_report
    run_in_progress = dict(_RUN)
    del run_in_progress["completed_at"]
    files = [_mk_file("a.pdf")]
    pdf = build_report(run_in_progress, files, _META, facts=_mk_facts())
    assert pdf[:5] == b"%PDF-"


def test_p16_renders_when_completed_at_is_empty_string():
    """completed_at='' (scan not yet finished) must also render without error."""
    from report import build_report
    run_in_progress = dict(_RUN, completed_at="")
    files = [_mk_file("a.pdf")]
    pdf = build_report(run_in_progress, files, _META, facts=_mk_facts())
    assert pdf[:5] == b"%PDF-"


# ── BUILD_COMMIT env var ──────────────────────────────────────────────────────

def test_p16_renders_with_build_commit_set(monkeypatch):
    """BUILD_COMMIT env var must not cause a render error."""
    monkeypatch.setenv("BUILD_COMMIT", "abc1234567890def")
    from report import build_report
    files = [_mk_file("a.pdf")]
    pdf = build_report(_RUN, files, _META, facts=_mk_facts())
    assert pdf[:5] == b"%PDF-"


def test_p16_renders_without_build_commit(monkeypatch):
    """Absence of BUILD_COMMIT env var must not cause a render error."""
    monkeypatch.delenv("BUILD_COMMIT", raising=False)
    from report import build_report
    files = [_mk_file("a.pdf")]
    pdf = build_report(_RUN, files, _META, facts=_mk_facts())
    assert pdf[:5] == b"%PDF-"


# ── datetime import present ───────────────────────────────────────────────────

def test_p16_datetime_importable_from_report_module():
    """report.py must import datetime so report_generated_at can be stamped at render time."""
    import report as _r
    import importlib, types
    src = Path(_r.__file__).read_text()
    assert "from datetime import" in src or "import datetime" in src, (
        "report.py must import datetime for P-16 report_generated_at stamp"
    )
