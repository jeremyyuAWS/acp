"""File-centric Langfuse spans must carry DETERMINISTIC ids.

Langfuse upserts observations and scores by id, so a deterministic id is what
makes re-running Assess (another click, a worker retry, the trace-chip rebuild)
update the existing span instead of appending an identical sibling — the
"four 'Assess · WCAG 2.1 AA' spans, score 85.00 × 4" trace pollution.
"""
from __future__ import annotations
import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import lf  # noqa: E402


class FakeSpan:
    """Captures the kwargs of every child span created on it."""
    def __init__(self, **kw):
        self.kw = kw
        self.id = kw.get("id")
        self.children = []

    def span(self, **kw):
        child = FakeSpan(**kw)
        self.children.append(child)
        return child

    def end(self, **_):
        return self

    def update(self, **_):
        return self


class FakeTrace(FakeSpan):
    def __init__(self, trace_id):
        super().__init__(id=trace_id)


RULES = [
    {"id": "1.1.1", "name": "Non-text Content", "plain": "Images have alt text", "level": "A", "severity": "critical"},
    {"id": "1.4.3", "name": "Contrast (Minimum)", "plain": "Text has enough contrast", "level": "AA", "severity": "major"},
]


def test_assess_span_id_is_stable_across_reruns():
    t = FakeTrace("scan1::a.docx")
    s1 = lf.assess_span(t, "AA")
    s2 = lf.assess_span(t, "AA")
    assert s1.id and s1.id == s2.id


def test_assess_span_id_differs_by_level_and_file():
    t = FakeTrace("scan1::a.docx")
    assert lf.assess_span(t, "AA").id != lf.assess_span(t, "AAA").id
    t2 = FakeTrace("scan1::b.docx")
    assert lf.assess_span(t, "AA").id != lf.assess_span(t2, "AA").id


def test_discover_span_id_is_stable():
    t = FakeTrace("scan1::a.docx")
    assert lf.discover_span(t, "axe").id == lf.discover_span(t, "axe").id


def test_rule_spans_children_stable_and_unique():
    parent = FakeSpan(id="assess-span-id")
    lf.rule_spans(parent, {"1.1.1": 2}, RULES)
    first = [c.id for c in parent.children]
    assert len(first) == len(RULES) and len(set(first)) == len(RULES)
    parent2 = FakeSpan(id="assess-span-id")
    lf.rule_spans(parent2, {"1.1.1": 2}, RULES)
    assert [c.id for c in parent2.children] == first


def test_pii_span_id_is_stable():
    pinfo = {"severity": "critical", "total": 1, "types": {"ssn": 1},
             "findings": [{"type": "ssn", "label": "SSNs", "count": 1, "samples": ["***-**-1234"]}]}
    p1, p2 = FakeSpan(id="discover-span-id"), FakeSpan(id="discover-span-id")
    lf.pii_span(p1, pinfo, filename="a.docx")
    lf.pii_span(p2, pinfo, filename="a.docx")
    assert p1.children[0].id and p1.children[0].id == p2.children[0].id


def test_file_score_passes_deterministic_id(monkeypatch):
    calls = []

    class FakeClient:
        def score(self, **kw):
            calls.append(kw)

    monkeypatch.setattr(lf, "_ENABLED", True)
    monkeypatch.setattr(lf, "_client", FakeClient())
    lf.file_score("scan1", "a.docx", 85.0)
    lf.file_score("scan1", "a.docx", 85.0)
    assert len(calls) == 2
    assert calls[0]["id"] == calls[1]["id"]
    assert calls[0]["trace_id"] == "scan1::a.docx"
    assert calls[0]["value"] == 85.0
