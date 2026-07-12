"""Reviewer Feedback Intelligence v1 (maturity Phase 2).

Every rejection captures WHY (a fixed enum), and hitl_analytics rolls decisions up per-rule and
per-format with a reject-reason histogram — so "which rules are weakest / which document types
fail most / where should engineering invest" is answered by real reviewer behaviour. Every figure
is a count of recorded decisions, never a fabricated score (ADR 0016).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def _ev(s, rule, file, action, reason=None, ms=1000, edited=False):
    s.record_hitl_event("s1", file, rule, f"i-{rule}-{file}-{action}-{reason}", action,
                        edited=edited, review_ms=ms, reject_reason=reason)


def test_reject_reason_roundtrips(isolated_store):
    s = isolated_store
    _ev(s, "SC_1_1_1", "deck.pptx", "reject", reason="hallucinated")
    a = s.hitl_analytics("s1")
    assert a["reject_reasons"] == {"hallucinated": 1}


def test_per_rule_and_per_format_rollups_rank_weakest_first(isolated_store):
    s = isolated_store
    # 1.1.1 on pptx: 2 rejections (one hallucinated, one too_vague) + 1 approve
    _ev(s, "SC_1_1_1", "deck.pptx", "reject", reason="hallucinated")
    _ev(s, "SC_1_1_1", "deck.pptx", "reject", reason="too_vague")
    _ev(s, "SC_1_1_1", "deck.pptx", "approve", ms=4000)
    # 2.4.4 on docx: clean approvals
    _ev(s, "2.4.4", "policy.docx", "approve", ms=2000)
    _ev(s, "2.4.4", "policy.docx", "approve", ms=3000)
    a = s.hitl_analytics("s1")

    by_rule = {r["key"]: r for r in a["by_rule"]}
    assert by_rule["1.1.1"]["rejected"] == 2 and by_rule["1.1.1"]["approved"] == 1
    assert by_rule["1.1.1"]["reject_reasons"] == {"hallucinated": 1, "too_vague": 1}
    assert by_rule["2.4.4"]["approval_rate"] == 1.0
    # weakest (most rejected) first — the "where should engineering invest" ordering
    assert a["by_rule"][0]["key"] == "1.1.1"

    by_fmt = {r["key"]: r for r in a["by_format"]}
    assert by_fmt["pptx"]["rejected"] == 2 and by_fmt["docx"]["approved"] == 2
    # avg review time is a real mean of recorded ms
    assert by_fmt["docx"]["avg_review_ms"] == 2500


def test_existing_headline_keys_unchanged(isolated_store):
    s = isolated_store
    _ev(s, "SC_1_1_1", "a.docx", "approve", ms=1000)
    a = s.hitl_analytics("s1")
    for k in ("total", "by_action", "reviewed", "approval_rate", "edit_rate", "avg_review_ms"):
        assert k in a          # backward compatibility for existing consumers


def test_route_validates_reason_enum():
    src = (Path(__file__).resolve().parent.parent / "api" / "routes" / "hitl.py").read_text()
    assert "REJECT_REASONS" in src
    assert "incorrect_object" in src and "hallucinated" in src and "org_preference" in src
    # reason recorded only on rejection, and rejected without a reason is still accepted
    assert 'reject_reason=(body.reject_reason if body.status == "rejected" else None)' in src


def test_frontend_captures_reason_on_reject():
    fe = Path(__file__).resolve().parent.parent / "frontend" / "src"
    card = (fe / "EvidenceCard.jsx").read_text()
    assert "askReject" in card and "incorrect_object" in card and "Hallucinated" in card
    assert "decide('rejected', k)" in card                    # a chip click submits with its reason
    api = (fe / "api.js").read_text()
    assert "reject_reason: opts.rejectReason" in api
    rc = (fe / "ReviewCenter.jsx").read_text()
    assert "rejectReason: 'unspecified'" in rc                # bulk/keyboard path never drops the signal


def test_frontend_surfaces_the_quality_rollup():
    # The loop is only closed when someone SEES the answer: the Remediate review section renders
    # the weakest-rules list + top reject reasons from the extended analytics payload.
    fe = Path(__file__).resolve().parent.parent / "frontend" / "src"
    rem = (fe / "Remediate.jsx").read_text()
    assert "AI quality · weakest rules first" in rem
    assert "reviewStats.by_rule" in rem
    assert "reviewStats.reject_reasons" in rem
    assert "top reject reasons" in rem
