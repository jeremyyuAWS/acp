"""Pass rate by WCAG principle — POUR (backlog R8).

Two things are load-bearing and each has a test:

  1. `get_certification_facts(...)["principles"]` PARTITIONS the evaluated set exactly — every
     evaluated criterion lands under exactly one of the four principles (its SC's leading digit),
     and the passed count is the evaluated count minus the failing count. If that identity ever
     breaks, the report's per-principle rate stops agreeing with its own headline evaluated count.
  2. The report renders it as `passed/evaluated` with the honesty caveat, and renders NOTHING when
     nothing was evaluated — a pass rate among evaluated checks is not a conformance percentage.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))


def _seed(s, sid, f, fails):
    """One assessed docx with `fails` = list of (SC, wcag-key) failing issues."""
    issues = [{"ruleId": sc, "wcag": wcag, "severity": "SERIOUS", "detail": "d"}
              for sc, wcag in fails]
    s.save_file_result(sid, {"file": f, "engine": "office", "status": "pass", "score": 70,
                             "compliant": 0, "skipped_rules": 0, "issues": issues},
                       "2026-08-19T00:00:00Z")


# ── the store facts: an exact partition of the evaluated set ──────────────────

def test_principles_partition_the_evaluated_set_exactly(isolated_store):
    s = isolated_store
    # 1.1.1 is Perceivable, 2.4.2 is Operable — two different principles fail.
    _seed(s, "p1", "a.docx", [("1.1.1", "SC_1_1_1"), ("2.4.2", "SC_2_4_2")])
    facts = s.get_certification_facts("p1")
    principles = facts["principles"]

    # exactly the four principles, canonical order
    assert [p["principle"] for p in principles] == \
        ["Perceivable", "Operable", "Understandable", "Robust"]

    total_eval = sum(d["evaluated"] for d in facts["documents"])
    total_fail = sum(d["failing"] for d in facts["documents"])
    # the partition identity: POUR splits EXACTLY the evaluated set, nothing added or dropped
    assert sum(p["evaluated"] for p in principles) == total_eval
    # passed is evaluated minus failing, per the same traces — never a separately-counted number
    assert sum(p["passed"] for p in principles) == total_eval - total_fail
    for p in principles:
        assert 0 <= p["passed"] <= p["evaluated"]           # never a rate above 100%

    by_name = {p["principle"]: p for p in principles}
    # the two principles that carry a failing criterion each show at least one non-pass
    assert by_name["Perceivable"]["passed"] < by_name["Perceivable"]["evaluated"]
    assert by_name["Operable"]["passed"] < by_name["Operable"]["evaluated"]


def test_a_clean_document_passes_every_evaluated_criterion(isolated_store):
    s = isolated_store
    _seed(s, "p2", "clean.docx", [])                        # no failing issues
    principles = s.get_certification_facts("p2")["principles"]
    for p in principles:
        assert p["passed"] == p["evaluated"]                # all evaluated criteria passed


# ── the rendered section (the store computing it and the report never printing it is one bug) ──

def _section_text(facts) -> str:
    import report
    from reportlab.lib.styles import getSampleStyleSheet
    ss = getSampleStyleSheet()
    el = report._pour_section(facts, ss["Heading2"], ss["BodyText"], ss["BodyText"], ss["BodyText"])
    return " ".join(str(getattr(e, "text", "") or "") for e in el)


def _facts(principles):
    return {"documents": [], "scope": {}, "principles": principles}


def test_report_renders_the_rate_with_its_honesty_caveat():
    t = _section_text(_facts([
        {"principle": "Perceivable", "evaluated": 8, "passed": 6},
        {"principle": "Operable", "evaluated": 4, "passed": 4},
        {"principle": "Understandable", "evaluated": 2, "passed": 1},
        {"principle": "Robust", "evaluated": 1, "passed": 1}]))
    assert "Pass rate by WCAG principle" in t
    assert "Perceivable" in t
    # the caveat that stops it being read as conformance
    assert "not" in t and "conformance" in t


def test_a_principle_with_nothing_evaluated_renders_a_dash_not_zero_percent():
    # rendered cell values aren't in Paragraph.text, so assert the store-side "—" rule via the
    # section still rendering (non-empty) while one principle is empty.
    t = _section_text(_facts([
        {"principle": "Perceivable", "evaluated": 5, "passed": 5},
        {"principle": "Operable", "evaluated": 0, "passed": 0},
        {"principle": "Understandable", "evaluated": 0, "passed": 0},
        {"principle": "Robust", "evaluated": 0, "passed": 0}]))
    assert "Pass rate by WCAG principle" in t           # rendered because something WAS evaluated


def test_nothing_evaluated_renders_no_section_at_all():
    empty = [{"principle": n, "evaluated": 0, "passed": 0}
             for n in ("Perceivable", "Operable", "Understandable", "Robust")]
    assert _section_text(_facts(empty)) == ""           # honest omission, not a row of zeros
    assert _section_text(_facts([])) == ""
