"""Tests for the per-issue remediation evidence appendix (backlog R1).

Two things are load-bearing and each has a dedicated test:

  1. `store.get_remediation_evidence` joins four sources — remediation_diff (the ONLY
     source of verified fixes), applied_fixes (the concrete AI value + thumbnail),
     hitl_queue (proposals + status), decision_log (the immutable sign-off) — across two
     different rule_id spellings ('SC_1_1_1' vs '1.1.1').
  2. An AI proposal awaiting approval is NEVER presented as remediated or validated. If
     that separation ever breaks, the report claims work the platform has not done.
"""
import io
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def _store():
    os.environ["ACP_SQLITE_PATH"] = tempfile.mktemp(suffix=".db")
    import importlib
    import store as _store
    importlib.reload(_store)
    return _store.Store()


def _png_data_url() -> str:
    import base64
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (60, 40), (10, 120, 200)).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _seed(s, sid="s1", f="deck.pptx"):
    # a verified-cleared AI alt fix + the concrete value/thumbnail it wrote
    s.record_remediation_diffs(sid, f, [
        {"rule_id": "1.1.1", "before": "(no alt text)", "after": "Bar chart of 2026 sales",
         "note": "AI vision description"},
        {"rule_id": "2.4.4", "before": "click here", "after": "Download Annual Report (PDF)",
         "note": "derived from the download target"},
    ])
    s.record_applied_fix(sid, f, "SC_1_1_1", "Bar chart of 2026 sales",
                         source="AI vision model (llava)", thumb=_png_data_url(), seq=0)
    s.log_decision("reviewer", "hitl.approved", scan_id=sid, file=f, rule_id="1.1.1",
                   detail="approved: Bar chart of 2026 sales")
    # a PENDING proposal — must never be counted as remediated
    s.enqueue_proposals(sid, f, "1.3.3", [{
        "locator": "p1", "before": "click the green button",
        "proposed_value": "Select the Submit button",
        "rationale": "instruction relies on colour", "source": "AI text model"}],
        validated=False, rule_name="Sensory Characteristics")
    return sid, f


# ── store.get_remediation_evidence ────────────────────────────────────────────

def test_evidence_joins_value_thumbnail_and_signoff_across_rule_id_spellings():
    s = _store()
    sid, f = _seed(s)
    ev = s.get_remediation_evidence(sid)
    assert len(ev) == 1 and ev[0]["file"] == f
    applied = {a["sc"]: a for a in ev[0]["applied"]}

    alt = applied["1.1.1"]
    assert alt["criterion"] == "Non-text Content"
    assert alt["after"] == "Bar chart of 2026 sales"
    # applied_fixes stores 'SC_1_1_1'; remediation_diff stores '1.1.1' — the join normalises
    assert alt["value"] == "Bar chart of 2026 sales"
    assert alt["source"] == "AI vision model (llava)"
    assert alt["thumb"].startswith("data:image/png;base64,")
    # sign-off derived from the immutable decision_log ('hitl.approved' -> 'approved')
    assert alt["decision"] == "approved"
    assert alt["reviewer"] == "reviewer"
    assert alt["validated"] is True


def test_deterministic_fix_has_no_ai_value_and_no_human_decision():
    s = _store()
    sid, _ = _seed(s)
    link = {a["sc"]: a for a in s.get_remediation_evidence(sid)[0]["applied"]}["2.4.4"]
    assert link["value"] is None and link["thumb"] is None   # no AI wrote it
    assert link["decision"] is None                          # auto-applied, no human needed
    assert link["validated"] is True                         # but it DID clear the re-scan


def test_pending_proposal_is_never_in_applied():
    s = _store()
    sid, _ = _seed(s)
    ev = s.get_remediation_evidence(sid)[0]
    assert "1.3.3" not in {a["sc"] for a in ev["applied"]}   # not a fix
    proposed = {p["sc"]: p for p in ev["proposed"]}
    assert proposed["1.3.3"]["validated"] is False
    assert proposed["1.3.3"]["proposals"][0]["proposed_value"] == "Select the Submit button"


def test_evidence_empty_for_scan_with_no_remediation():
    s = _store()
    assert s.get_remediation_evidence("nothing-here") == []


# ── report rendering ──────────────────────────────────────────────────────────

_RUN = {"id": "scan-abc", "completed_at": "2026-07-09T21:00:00", "avg_score": 100, "owner_email": None}
_FILES = [{"file": "deck.pptx", "compliant": 1, "score": 100, "status": "ok", "issues": []}]
_META = {"target": "AA", "version": "1.2", "hash": "deadbeef"}


def _pdf_text(pdf: bytes) -> str:
    from pypdf import PdfReader
    return "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)


def test_report_renders_without_evidence():
    from report import build_report
    pdf = build_report(_RUN, _FILES, _META)          # back-compat: evidence is optional
    assert pdf[:4] == b"%PDF"
    assert "Remediation evidence" not in _pdf_text(pdf)


def test_report_renders_evidence_with_before_after_value_and_signoff():
    from report import build_report
    s = _store()
    sid, _ = _seed(s)
    pdf = build_report(_RUN, _FILES, _META, evidence=s.get_remediation_evidence(sid))
    assert pdf[:4] == b"%PDF"
    t = _pdf_text(pdf)
    for expected in ["Remediation evidence", "validated on re-scan", "(no alt text)",
                     "Bar chart of 2026 sales", "AI vision model (llava)",
                     "approved by reviewer", "Download Annual Report (PDF)",
                     "auto-applied"]:
        assert expected in t, expected


def test_report_never_presents_a_pending_proposal_as_remediated():
    """The report's core honesty guarantee: a proposal awaiting approval is labelled
    'not remediated' and never carries the 'validated on re-scan' mark."""
    from report import build_report
    s = _store()
    sid, _ = _seed(s)
    t = _pdf_text(build_report(_RUN, _FILES, _META, evidence=s.get_remediation_evidence(sid)))
    assert "proposed" in t and "not remediated" in t
    # the sensory proposal's block must not claim validation
    start = t.find("Sensory Characteristics")
    assert start != -1
    block = t[start:start + 160]
    assert "validated on re-scan" not in block


def test_report_attributes_the_signoff_to_the_authenticated_reviewer():
    """Chain of custody: the appendix names WHO approved, straight from decision_log.actor."""
    from report import build_report
    s = _store()
    sid, f = "s2", "deck.pptx"
    s.record_remediation_diffs(sid, f, [
        {"rule_id": "1.1.1", "before": "(no alt)", "after": "A bar chart", "note": None}])
    s.log_decision("ada@movate.com", "hitl.approved", scan_id=sid, file=f, rule_id="1.1.1")
    ev = s.get_remediation_evidence(sid)
    assert ev[0]["applied"][0]["reviewer"] == "ada@movate.com"
    assert "approved by ada@movate.com" in _pdf_text(build_report(_RUN, _FILES, _META, evidence=ev))


def test_undecodable_thumbnail_never_breaks_the_report():
    from report import build_report
    ev = [{"file": "x.docx", "proposed": [], "applied": [{
        "sc": "1.1.1", "criterion": "Non-text Content", "before": "a", "after": "b",
        "note": None, "value": "b", "source": "AI", "thumb": "data:image/png;base64,!!notreal!!",
        "decision": None, "approved_value": None, "reviewer": None, "reviewed_at": None,
        "validated": True}]}]
    pdf = build_report(_RUN, _FILES, _META, evidence=ev)
    assert pdf[:4] == b"%PDF"
    assert "Non-text Content" in _pdf_text(pdf)
