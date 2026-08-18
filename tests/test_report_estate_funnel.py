"""The scope-of-assertion section states the whole-estate coverage funnel (audit E2).

WHY THIS IS NOT COSMETIC. `_scope_section` already narrows the report's assertion by CRITERION
("no check for 2.4.3 on a PDF") and by unread file-type ("47 documents of other types were never
opened"). Neither states the WIDEST boundary: of everything discovery found, how much was ever an
assessable format at all. A hospital estate is mostly images, scans and media — a conformance
report that shows only the scanned subset lets an auditor read that subset as the estate, the exact
"yes from silence" failure the rest of this section exists to prevent.

The numbers are the three honest denominators (discovered ≥ assessable ≥ scored), read from the
SCAN'S OWN recorded inventory (scanner wrote it onto scan_runs.scope), never from the live estate —
a report is a statement about what happened.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import estate_inventory as ei  # noqa: E402

DOCX_ONLY = {"1.1.1": ["docx"], "1.3.1": ["docx"]}
# An inventory block exactly as scanner._list writes it onto scan_runs.scope.
INV = {"discovered": 100, "assessment_eligible": 60,
       "by_status": {"assessable": 60, "metadata_only": 25, "unsupported": 13, "excluded": 2},
       "truncated": False}


# ── the pure helper (runs anywhere, no DB / no reportlab) ──────────────────────
def test_funnel_facts_splits_the_estate_into_three_honest_denominators():
    f = ei.funnel_facts(INV)
    assert f["discovered"] == 100 and f["assessable"] == 60
    assert f["not_assessable"] == 40                       # counted as discovered − assessable
    assert (f["metadata_only"], f["unsupported"], f["excluded"]) == (25, 13, 2)
    assert f["truncated"] is False


def test_funnel_facts_carries_truncation_as_a_floor():
    f = ei.funnel_facts({"discovered": 30000, "assessment_eligible": 8000,
                         "by_status": {"assessable": 8000, "metadata_only": 22000}, "truncated": True})
    assert f["not_assessable"] == 22000 and f["truncated"] is True


def test_funnel_facts_is_none_when_there_is_no_inventory():
    # A local scan / a scan predating the field → no funnel rather than a row of zeros.
    assert ei.funnel_facts(None) is None
    assert ei.funnel_facts({}) is None
    assert ei.funnel_facts({"discovered": 0}) is None


# ── the facts, from the scan's own recorded scope ──────────────────────────────
@pytest.fixture
def store(isolated_store):
    return isolated_store


def _scan(st, sid, scope_dict):
    st.init_scan_run(sid, "drive", 1, "2026-08-08T00:00:00Z", "default", "rh",
                     owner="a@example.com", status="running", scope=scope_dict)
    st.save_file_result(sid, {"file": "a.docx", "engine": ".net/office", "status": "analysed",
                              "score": 90, "compliant": 1, "skipped_rules": 0, "issues": []},
                        "2026-08-08T00:00:00Z")


def test_facts_carry_the_recorded_estate_funnel(store):
    _scan(store, "e1", {"kind": "drive", "kept": 60, "scan_scope": DOCX_ONLY, "inventory": INV})
    estate = store.get_certification_facts("e1")["scope"]["estate"]
    assert estate["discovered"] == 100 and estate["assessable"] == 60 and estate["not_assessable"] == 40


def test_no_estate_key_when_the_scan_recorded_no_inventory(store):
    # A scan with a scope but no inventory (older scans, local source) adds no funnel.
    _scan(store, "e2", {"kind": "drive", "kept": 1})
    assert "estate" not in store.get_certification_facts("e2")["scope"]


def test_a_missing_scope_column_does_not_break_the_facts(store):
    store.init_scan_run("e3", "drive", 1, "2026-08-08T00:00:00Z", "default", "rh",
                        owner="a@example.com", status="running")
    store.save_file_result("e3", {"file": "a.docx", "engine": ".net/office", "status": "analysed",
                                  "score": 90, "compliant": 1, "skipped_rules": 0, "issues": []},
                           "2026-08-08T00:00:00Z")
    assert "estate" not in store.get_certification_facts("e3")["scope"]


# ── the rendered text (the store computing it and the report never printing it is the same bug) ──
def _section_text(facts) -> str:
    import report
    from reportlab.lib.styles import getSampleStyleSheet
    ss = getSampleStyleSheet()
    el = report._scope_section(
        [{"file": "a.docx"}], facts, ss["Heading2"], ss["BodyText"], ss["BodyText"], ss["BodyText"])
    return " ".join(str(getattr(e, "text", "") or "") for e in el)


def _facts(estate=None, remediated_total=0, docs=1):
    return {"documents": [{"file": f"d{i}.docx", "evaluated": 4, "not_evaluated": 11,
                           "by_mode": {"auto": 4}} for i in range(docs)],
            "remediated_total": remediated_total,
            "scope": {"catalog_size": 15, "by_mode": {"auto": 4}, "not_evaluated_criteria": [],
                      "review_criteria": [], "human_only_criteria": [],
                      **({"estate": estate} if estate else {})}}


def test_the_report_states_the_estate_funnel():
    t = _section_text(_facts(estate=ei.funnel_facts(INV), docs=60, remediated_total=12))
    assert "Estate coverage" in t
    assert "<b>100</b>" in t and "<b>60</b>" in t and "<b>40</b>" in t      # discovered / assessable / not
    assert "outside any automated accessibility assertion" in t
    assert "three separate denominators, not one percentage" in t
    assert "25 image, audio or video" in t                                 # the non-assessable is broken out
    assert "<b>12</b> of which the platform remediated" in t


def test_a_truncated_estate_is_marked_a_floor():
    est = ei.funnel_facts({"discovered": 30000, "assessment_eligible": 8000,
                           "by_status": {"assessable": 8000, "metadata_only": 22000}, "truncated": True})
    assert "found at least <b>30000</b>" in _section_text(_facts(estate=est, docs=8000))


def test_no_funnel_sentence_when_there_is_no_inventory():
    assert "Estate coverage" not in _section_text(_facts())


def test_the_existing_unread_disclosure_survives_the_addition():
    # The funnel is additive: the criterion-level negative assurance an auditor already relies on
    # must still render alongside it.
    facts = _facts(estate=ei.funnel_facts(INV))
    facts["scope"].update({"unread_documents": 47, "formats_read": ["docx"]})
    t = _section_text(facts)
    assert "Estate coverage" in t and "not read at all" in t
    assert "must not be represented as such" in t
