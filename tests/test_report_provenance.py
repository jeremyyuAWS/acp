"""How this result was produced — method / pipeline / reproduce / supersedes (backlog R11/R12/R-D/R-E).

Every figure is counted from the same facts the rest of the report uses; the reproduce line renders
only with a stamped rubric hash and the supersedes line only when a previous scan exists — otherwise
each is omitted rather than shown empty or fabricated (ADR 0016).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))


def _text(facts, meta=None, diff=None, cert=1, total=1) -> str:
    import report
    from reportlab.lib.styles import getSampleStyleSheet
    ss = getSampleStyleSheet()
    el = report._provenance_section({"id": "s1"}, facts, meta, diff, cert, total,
                                    ss["Heading2"], ss["BodyText"], ss["BodyText"], ss["BodyText"])
    return " ".join(str(getattr(e, "text", "") or "") for e in el)


def _facts(evaluated=6, findings=2, auto=4, ai=2, approvals=1, remediated=1, docs=1):
    return {"documents": [{"evaluated": evaluated // docs, "findings": findings // docs}
                          for _ in range(docs)],
            "scope": {"by_mode": {"auto": auto, "ai-assisted": ai}},
            "approvals_total": approvals, "remediated_total": remediated}


def test_method_and_pipeline_carry_the_real_counts():
    t = _text(_facts(evaluated=6, findings=2, auto=4, ai=2, approvals=1, remediated=1))
    assert "How this result was produced" in t
    assert "<b>6</b> criteria evaluated" in t          # R11 method count
    assert "<b>4</b> by the deterministic engine" in t
    assert "Pipeline." in t and "finding(s)" in t      # R12 pipeline
    assert "certifiable" in t


def test_reproduce_line_renders_only_with_a_rubric_hash():
    with_hash = _text(_facts(), meta={"hash": "abc123def456"})
    assert "Reproduce." in with_hash and "abc123def456" in with_hash
    without = _text(_facts(), meta={})
    assert "Reproduce." not in without


def test_supersedes_renders_only_with_a_previous_scan():
    sup = _text(_facts(), diff={"prev_at": "2026-08-01T00:00:00Z"})
    assert "Supersedes." in sup and "2026-08-01" in sup
    assert "Supersedes." not in _text(_facts(), diff=None)


def test_nothing_measured_renders_no_section():
    assert _text(_facts(evaluated=0, findings=0)) == ""
    assert _text(None) == ""
