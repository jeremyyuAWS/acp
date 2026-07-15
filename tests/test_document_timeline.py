"""Audit trail (maturity Phase 4 v1): per-document chronological provenance.

document_timeline assembles ONE document's history — scanned → AI drafted → human decided →
fix written → published — entirely from rows the pipeline already persists. Nothing is
inferred or fabricated (ADR 0016): every event is a persisted row, ordered by its real
timestamp, and the assembly must never error on partial data (older DBs, mid-scan files).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def _seed(s):
    report = {"started_at": "2026-07-12T10:00:00+00:00",
              "completed_at": "2026-07-12T10:01:00+00:00",
              "source": "drive",
              "rubric": {"name": "WCAG 2.1 AA", "hash": "abc123"},
              "summary": {"files": 1, "certifiable": 1, "uncertain": 0, "error": 0, "avg_score": 90},
              "files": [{"file": "deck.pptx", "engine": "office", "status": "PASS",
                         "score": 90, "compliant": 1, "skipped_rules": 0, "issues": []}]}
    return s.save_scan(report)


def test_events_assemble_in_chronological_order(isolated_store):
    s = _store = isolated_store
    sid = _seed(s)
    # Real writes through the real APIs, out of order on purpose.
    s.record_hitl_event(sid, "deck.pptx", "1.1.1", "i1", "approve",
                        edited=True, review_ms=4000, reviewer="jeremy@acp.io")
    s.record_ai_call(scan_id=sid, file="deck.pptx", surface="vision",
                     provider="ollama", model="llava:13b", zone="local",
                     latency_ms=900, ok=True, cost_usd=0.0)
    s.log_decision("system", "auto_remediate", scan_id=sid, file="deck.pptx",
                   rule_id="1.4.3", detail="contrast recoloured")
    tl = s.document_timeline(sid, "deck.pptx")

    assert len(tl) >= 3
    assert [e["ts"] for e in tl] == sorted(e["ts"] for e in tl)     # chronological
    kinds = {e["kind"] for e in tl}
    assert {"ai", "human", "decision"} <= kinds
    ai = next(e for e in tl if e["kind"] == "ai")
    assert "llava:13b" in ai["title"] and "zone=local" in ai["detail"]
    human = next(e for e in tl if e["kind"] == "human")
    assert human["actor"] == "jeremy@acp.io"
    assert human["detail"] == "reviewer edited the AI draft before approving"


def test_scoped_to_one_file(isolated_store):
    s = isolated_store
    sid = _seed(s)
    s.record_hitl_event(sid, "other.docx", "1.1.1", "i2", "reject", reject_reason="too_vague")
    tl = s.document_timeline(sid, "deck.pptx")
    assert not any(e["kind"] == "human" for e in tl)                # other.docx's event excluded


def test_reject_reason_surfaces_as_detail(isolated_store):
    s = isolated_store
    sid = _seed(s)
    s.record_hitl_event(sid, "deck.pptx", "1.1.1", "i3", "reject", reject_reason="hallucinated")
    tl = s.document_timeline(sid, "deck.pptx")
    human = next(e for e in tl if e["kind"] == "human")
    assert human["detail"] == "reason: hallucinated"


def test_empty_document_returns_empty_not_error(isolated_store):
    assert isolated_store.document_timeline("no-such-scan", "ghost.pdf") == []


def test_route_and_frontend_wiring():
    root = Path(__file__).resolve().parent.parent
    scans = (root / "api" / "routes" / "scans.py").read_text()
    assert '"/scans/{sid}/timeline"' in scans and "document_timeline" in scans
    api = (root / "frontend" / "src" / "api.js").read_text()
    assert "getDocumentTimeline" in api
    drawer = (root / "frontend" / "src" / "FileDrawer.jsx").read_text()
    assert "AuditTimeline" in drawer and "History — audit trail" in drawer
