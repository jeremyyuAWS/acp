"""hitl_queue.evidence — the images a 1.1.1 row asks a human to describe.

Evidence is NOT a proposal: there is no value to approve. It must round-trip as a list, and
it must find the row whether alt text was queued as '1.1.1' or as the deferral's
'1.1.1/deferred' — the deferral is exactly the case that most needs the picture.
"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

_EV = [{"locator": "ppt/slides/slide1.xml#rId2", "thumb": "data:image/png;base64,AAAA"},
       {"locator": "ppt/slides/slide3.xml#rId7", "thumb": "data:image/png;base64,BBBB"}]


@pytest.fixture()
def st(monkeypatch):
    import store as store_mod
    monkeypatch.setattr(store_mod, "_SQLITE_PATH", Path(tempfile.mkdtemp()) / "ev.db")
    return store_mod.Store()


def _deferral(st, sid="s1", f="deck.pptx", n=19):
    st.init_scan_run(sid, "drive", 1, "t0", "r", "h")
    st.queue_hitl_deferral(sid, f, f"{n} image(s) lack a faithful alt source", n)


def test_evidence_attaches_to_the_deferral_row_and_round_trips(st):
    _deferral(st)
    assert st.attach_hitl_evidence("s1", "deck.pptx", "1.1.1", _EV) is not None
    item = next(i for i in st.list_hitl_queue(scan_id="s1"))
    assert item["evidence"] == _EV                       # a real list, not a JSON string
    assert item["rule_id"] == "1.1.1/deferred"           # matched across the suffix


def test_evidence_does_not_masquerade_as_a_proposal(st):
    """The whole reason evidence has its own column: proposals[] drives confidence + the
    prefilled value. A picture is neither."""
    _deferral(st)
    st.attach_hitl_evidence("s1", "deck.pptx", "1.1.1", _EV)
    item = st.list_hitl_queue(scan_id="s1")[0]
    assert not item.get("proposals")


def test_evidence_attaches_to_a_plain_1_1_1_row(st):
    st.init_scan_run("s1", "drive", 1, "t0", "r", "h")
    st.queue_hitl_review_for_file("s1", "deck.pptx",
                                  [{"rule_id": "1.1.1", "rule_name": "Non-text Content"}])
    assert st.attach_hitl_evidence("s1", "deck.pptx", "1.1.1", _EV) is not None
    assert st.list_hitl_queue(scan_id="s1")[0]["evidence"] == _EV


def test_repeat_remediate_replaces_evidence_rather_than_appending(st):
    _deferral(st)
    st.attach_hitl_evidence("s1", "deck.pptx", "1.1.1", _EV)
    st.attach_hitl_evidence("s1", "deck.pptx", "1.1.1", _EV[:1])
    assert st.list_hitl_queue(scan_id="s1")[0]["evidence"] == _EV[:1]


def test_empty_evidence_is_a_noop(st):
    _deferral(st)
    assert st.attach_hitl_evidence("s1", "deck.pptx", "1.1.1", []) is None
    assert not st.list_hitl_queue(scan_id="s1")[0].get("evidence")


def test_no_matching_row_is_a_noop_not_a_crash(st):
    st.init_scan_run("s1", "drive", 1, "t0", "r", "h")
    assert st.attach_hitl_evidence("s1", "absent.pptx", "1.1.1", _EV) is None


def test_legacy_row_without_evidence_still_reads(st):
    _deferral(st)
    item = st.list_hitl_queue(scan_id="s1")[0]
    assert item.get("evidence") in (None, "", [])
