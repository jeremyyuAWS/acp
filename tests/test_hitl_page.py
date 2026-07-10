"""A queued review item must say WHERE the criterion fails.

hitl_queue.rule_id is an SC ('1.1.1'); issue_records keys pages by the ENGINE rule id and
carries the SC in `wcag`. A raw rule_id comparison finds nothing and every item silently shows
no page — which looks exactly like "the analyser attributed none".
"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "hp.db")
    s = store_mod.Store()
    s.init_scan_run("s1", "drive", total=1, started_at="t0", rubric_name="r", rubric_hash="h")
    return s


def _file(issues):
    return {"file": "deck.pptx", "engine": "dotnet/office", "status": "analysed", "score": 40,
            "compliant": 0, "skipped_rules": 0, "issues": issues}


def _issue(rule, wcag, page):
    d = {"ruleId": rule, "wcag": wcag, "severity": "CRITICAL"}
    if page is not None:
        d["page"] = page
    return d


def test_pages_join_goes_through_the_sc_not_the_raw_rule_id(st):
    # engine rule id 'PPTX-ALT-001' never equals the SC '1.1.1'
    st.save_file_result("s1", _file([
        _issue("PPTX-ALT-001", "1.1.1 Non-text Content", 3),
        _issue("PPTX-ALT-001", "SC_1_1_1", 1),
        _issue("PPTX-ORDER-001", "1.3.2 Meaningful Sequence", 7),   # different criterion
    ]), "t1")
    with st._db.cursor() as cur:
        assert st._pages_for(cur, "s1", "deck.pptx", "1.1.1") == [1, 3]
        assert st._pages_for(cur, "s1", "deck.pptx", "1.3.2") == [7]


def test_deferral_rule_id_with_a_suffix_still_resolves(st):
    st.save_file_result("s1", _file([_issue("PPTX-ALT-001", "1.1.1", 5)]), "t1")
    with st._db.cursor() as cur:
        assert st._pages_for(cur, "s1", "deck.pptx", "1.1.1/deferred") == [5]


def test_unattributed_findings_yield_no_pages(st):
    st.save_file_result("s1", _file([_issue("PPTX-ALT-001", "1.1.1", None)]), "t1")
    with st._db.cursor() as cur:
        assert st._pages_for(cur, "s1", "deck.pptx", "1.1.1") == []


def test_queue_item_carries_first_page_and_every_page(st):
    st.save_file_result("s1", _file([
        _issue("PPTX-ALT-001", "1.1.1", 7),
        _issue("PPTX-ALT-001", "1.1.1", 3),
        _issue("PPTX-ALT-001", "1.1.1", 3),      # duplicate slide -> one entry
    ]), "t1")
    item_id = st.queue_hitl_deferral("s1", "deck.pptx", "no faithful alt source", count=3)
    item = st.get_hitl_item(item_id)
    assert item["page"] == 3                    # lowest — enough to jump to
    assert item["pages"] == "3,7"               # a criterion failing on 2 slides isn't one slide


def test_item_with_no_attributed_page_stores_null(st):
    st.save_file_result("s1", _file([_issue("PPTX-ALT-001", "1.1.1", None)]), "t1")
    item_id = st.queue_hitl_deferral("s1", "deck.pptx", "no faithful alt source")
    item = st.get_hitl_item(item_id)
    assert item["page"] is None and item["pages"] is None   # show no page, never a wrong one
