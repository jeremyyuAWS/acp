"""Human review & assurance — R9 KPI + R10 ratios.

Two load-bearing facts:
  1. get_certification_facts["review"] counts approved / rejected / skipped from the IMMUTABLE
     decision_log, deduped per (file, criterion) — the same source the approvals figure uses, so the
     KPI can never disagree with the sign-off shown elsewhere.
  2. The report renders only ratios with a real denominator (deterministic ÷ evaluated,
     fixes-cleared ÷ findings), never a modelled "effort saved" or a "cleared ÷ attempted" whose
     denominator the platform does not track.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))


def _seed_file(s, sid, f, fails):
    issues = [{"ruleId": sc, "wcag": w, "severity": "SERIOUS", "detail": "d"} for sc, w in fails]
    s.save_file_result(sid, {"file": f, "engine": "office", "status": "pass", "score": 70,
                             "compliant": 0, "skipped_rules": 0, "issues": issues},
                       "2026-08-19T00:00:00Z")


def test_review_outcomes_counted_from_the_immutable_log(isolated_store):
    s = isolated_store
    _seed_file(s, "a1", "a.docx", [("1.1.1", "SC_1_1_1"), ("2.4.2", "SC_2_4_2")])
    s.log_decision("rev@x.com", "hitl.approved", scan_id="a1", file="a.docx", rule_id="1.1.1")
    s.log_decision("rev@x.com", "hitl.approved", scan_id="a1", file="a.docx", rule_id="1.1.1")  # re-approve = 1
    s.log_decision("rev@x.com", "hitl.rejected", scan_id="a1", file="a.docx", rule_id="2.4.2")
    review = s.get_certification_facts("a1")["review"]
    assert review["approved"] == 1        # deduped per (file, criterion)
    assert review["rejected"] == 1
    assert review["skipped"] == 0
    assert review["reviewed"] == 2


def test_no_reviews_is_all_zero_not_missing(isolated_store):
    s = isolated_store
    _seed_file(s, "a2", "b.docx", [])
    review = s.get_certification_facts("a2")["review"]
    assert review == {"approved": 0, "rejected": 0, "skipped": 0, "reviewed": 0}


# ── the rendered section ──────────────────────────────────────────────────────

def _els(facts, hitl=None):
    import report
    from reportlab.lib.styles import getSampleStyleSheet
    ss = getSampleStyleSheet()
    return report._assurance_section(facts, ss["Heading2"], ss["BodyText"], ss["BodyText"], ss["BodyText"],
                                     hitl=hitl)


def _text(facts, hitl=None) -> str:
    # Top-level Paragraph text only — the KPI band is a nested Table, asserted separately.
    return " ".join(str(getattr(e, "text", "") or "") for e in _els(facts, hitl=hitl))


def _facts(reviewed=3, approved=2, rejected=1, evaluated=10, findings=4, auto=7, remediated=3):
    return {"documents": [{"evaluated": evaluated, "findings": findings}],
            "scope": {"by_mode": {"auto": auto}},
            "remediated_total": remediated,
            "review": {"reviewed": reviewed, "approved": approved, "rejected": rejected, "skipped": 0}}


def test_renders_kpi_and_ratios_with_real_denominators():
    from reportlab.platypus import Table
    els = _els(_facts(evaluated=10, auto=7, findings=4, remediated=3))
    t = " ".join(str(getattr(e, "text", "") or "") for e in els)
    assert "Human review" in t and "assurance" in t
    assert any(isinstance(e, Table) for e in els)                                 # the R9 KPI band
    assert "Assurance." in t and "<b>7</b> of <b>10</b>" in t and "70%" in t      # deterministic ÷ evaluated
    assert "Effort." in t and "<b>3</b> of <b>4</b>" in t                          # cleared ÷ findings, basis named
    assert "fixes-cleared ÷ findings" in t
    assert "saved" not in t.replace("hours-saved", "")                            # no modelled time-saving claim


def test_ratios_omitted_when_their_denominator_is_zero():
    t = _text(_facts(evaluated=0, findings=0, reviewed=1, remediated=0))
    assert "Assurance." not in t and "Effort." not in t     # no divide-by-zero, no fabricated 0%
    assert "Human review" in t                              # but the block still renders (a review happened)


def test_nothing_to_report_renders_no_section():
    assert _text(_facts(reviewed=0, evaluated=0, findings=0, remediated=0)) == ""
    assert _text(None) == ""


def test_edited_count_appears_in_effort_clause_when_nonzero():
    """R9: human-edited draft count from hitl_analytics surfaces in the effort paragraph so
    auditors see how often the AI's proposal needed correction before approval."""
    hitl = {"by_action": {"approve": 3, "edit": 2, "reject": 1}, "avg_review_ms": None}
    t = _text(_facts(findings=6, remediated=5), hitl=hitl)
    assert "2" in t and "edits" in t or "edited" in t    # edited count present
    assert "human edits to the AI draft" in t


def test_edited_clause_absent_when_zero():
    """R9: when no reviews involved edits, the edited-draft clause is omitted — not shown as '0 edited'."""
    hitl = {"by_action": {"approve": 3, "edit": 0, "reject": 0}, "avg_review_ms": None}
    t = _text(_facts(findings=4, remediated=3), hitl=hitl)
    assert "human edits to the AI draft" not in t


def test_avg_review_time_shown_when_timestamps_exist():
    """R9: avg review time rendered only when real timestamps were recorded (avg_review_ms not None)."""
    hitl = {"by_action": {}, "avg_review_ms": 4500}
    t = _text(_facts(), hitl=hitl)
    assert "Avg review time" in t and "4.5 s" in t
    assert "measured from reviewer action timestamps" in t


def test_avg_review_time_absent_when_no_timestamps():
    """R9: avg review time omitted entirely when avg_review_ms is None — never invented."""
    hitl = {"by_action": {}, "avg_review_ms": None}
    t = _text(_facts(), hitl=hitl)
    assert "Avg review time" not in t


def test_avg_review_time_absent_when_hitl_not_passed():
    """R9: backward-compatible — passing no hitl arg renders the section without review-time."""
    t = _text(_facts())
    assert "Avg review time" not in t
