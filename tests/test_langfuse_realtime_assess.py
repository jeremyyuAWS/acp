"""Two Langfuse observability improvements:

  1. per-file assessment lands on the trace AS a scan runs (handlers._emit_realtime_file_assess),
     not only in one batch at finalize — so a mid-run scan shows scores instead of empty traces;
  2. file-level SEVERITY — the Assess span is ERROR for a non-conformant file / WARNING for one
     with non-blocking findings / DEFAULT when clean (lf.assess_span), and a file that couldn't be
     assessed gets an ERROR span (lf.file_error_span) — so problems stand out in the trace list.

The finalize pass and the real-time path share `_emit_file_assess`, so they cannot diverge."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

API = Path(__file__).resolve().parent.parent / "api"
sys.path.insert(0, str(API))
import lf  # noqa: E402
import handlers  # noqa: E402


# ── lf.assess_span level + lf.file_error_span ─────────────────────────────────
class _Trace:
    """A fake trace/span that records only the kwargs passed to .span() (not construction)."""
    id = "scan::doc-x.docx"

    def __init__(self, sink):
        self._sink = sink

    def span(self, **kw):
        self._sink.append(kw)
        return _Trace(self._sink)

    def end(self, **kw):
        return self


def test_assess_span_level_reflects_the_file_verdict():
    sink = []
    lf.assess_span(_Trace(sink), "AA", blocking=True, findings=True)
    assert sink[0]["level"] == "ERROR"          # a blocking failure → ERROR
    sink = []
    lf.assess_span(_Trace(sink), "AA", blocking=False, findings=True)
    assert sink[0]["level"] == "WARNING"        # findings but none blocking → WARNING
    sink = []
    lf.assess_span(_Trace(sink), "AA")
    assert sink[0]["level"] == "DEFAULT"        # clean → DEFAULT


def test_file_error_span_is_error_level_and_carries_only_a_reason():
    sink = []
    lf.file_error_span(_Trace(sink), "exceeded per-file limit 600s")
    span = sink[0]
    assert span["level"] == "ERROR" and "Could not assess" in span["name"]
    assert span["status_message"] == "exceeded per-file limit 600s"


# ── handlers._file_assess_from_traces (pure reduction) ────────────────────────
def test_file_assess_from_traces_counts_and_blocking():
    rows = [
        {"rule_id": "1.1.1", "outcome": "FAIL", "level": "A", "finding_count": 3},
        {"rule_id": "1.4.3", "outcome": "FAIL", "level": "AA", "finding_count": 1},
        {"rule_id": "2.4.6", "outcome": "PASS", "level": "AA"},
        {"rule_id": "1.4.9", "outcome": "FAIL", "level": "AAA", "finding_count": 2},  # above AA → not blocking
        {"rule_id": "3.1.1", "outcome": "REVIEW", "level": "A"},
    ]
    sc, oc, conformant = handlers._file_assess_from_traces(rows, "AA")
    assert sc == {"1.1.1": 3, "1.4.3": 1, "1.4.9": 2}
    assert oc == {"FAIL": 3, "PASS": 1, "REVIEW": 1}
    assert conformant is False                  # 1.1.1 / 1.4.3 fail at/below AA

    # only the AAA failure remains → not blocking at an AA target → conformant
    sc2, _, conf2 = handlers._file_assess_from_traces([rows[3]], "AA")
    assert sc2 == {"1.4.9": 2} and conf2 is True


# ── handlers._emit_realtime_file_assess wiring + guards ───────────────────────
class _FakeStore:
    def __init__(self, rows, rec):
        self._rows, self._rec = rows, rec

    def get_scan_traces(self, scan_id, file=None):
        return self._rows

    def get_file_record(self, scan_id, file):
        return self._rec


@pytest.fixture()
def cap_lf(monkeypatch):
    """Capture the per-file assessment lf calls, and force tracing 'enabled'."""
    calls = {"result": [], "score": []}
    monkeypatch.setattr(lf, "enabled", lambda: True)
    monkeypatch.setattr(lf, "file_trace", lambda *a, **k: _Trace([]))
    monkeypatch.setattr(lf, "assess_span", lambda *a, **k: _Trace([]))
    monkeypatch.setattr(lf, "rule_spans", lambda *a, **k: None)
    monkeypatch.setattr(lf, "file_score", lambda sid, f, s: calls["score"].append((f, s)))
    monkeypatch.setattr(lf, "file_assessment_result",
                        lambda sid, f, **k: calls["result"].append({"file": f, **k}))
    return calls


def test_realtime_emit_writes_the_files_score_as_it_completes(cap_lf, monkeypatch):
    rows = [{"rule_id": "1.4.3", "outcome": "FAIL", "level": "AA", "finding_count": 2},
            {"rule_id": "2.4.6", "outcome": "PASS", "level": "AA"}]
    monkeypatch.setattr(handlers.core, "store", _FakeStore(rows, {"score": 74, "remediated_at": None}))
    handlers._emit_realtime_file_assess("scan-1", "doc-x.docx", "AA", user="u@x")
    assert cap_lf["score"] == [("doc-x.docx", 74)]
    r = cap_lf["result"][0]
    assert r["score"] == 74 and r["conformant"] is False
    assert r["failing_criteria"] == {"1.4.3": 2}
    assert r["outcomes"] == {"FAIL": 1, "PASS": 1}
    assert r["pii"] is None                      # PII is filled by the finalize pass, not real-time


def test_realtime_emit_is_a_noop_when_the_file_isnt_scored_yet(cap_lf, monkeypatch):
    monkeypatch.setattr(handlers.core, "store", _FakeStore([], {"score": None}))
    handlers._emit_realtime_file_assess("scan-1", "doc-x.docx", "AA")
    assert cap_lf["result"] == [] and cap_lf["score"] == []


def test_realtime_emit_does_no_db_work_when_tracing_is_off(monkeypatch):
    monkeypatch.setattr(lf, "enabled", lambda: False)

    class _Boom:
        def get_scan_traces(self, *a, **k):
            raise AssertionError("must not touch the store when tracing is off")

    monkeypatch.setattr(handlers.core, "store", _Boom())
    handlers._emit_realtime_file_assess("scan-1", "doc-x.docx", "AA")   # must not raise
