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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


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

def test_evidence_joins_value_thumbnail_and_signoff_across_rule_id_spellings(isolated_store):
    s = isolated_store
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


def test_deterministic_fix_has_no_ai_value_and_no_human_decision(isolated_store):
    s = isolated_store
    sid, _ = _seed(s)
    link = {a["sc"]: a for a in s.get_remediation_evidence(sid)[0]["applied"]}["2.4.4"]
    assert link["value"] is None and link["thumb"] is None   # no AI wrote it
    assert link["decision"] is None                          # auto-applied, no human needed
    assert link["validated"] is True                         # but it DID clear the re-scan


def test_pending_proposal_is_never_in_applied(isolated_store):
    s = isolated_store
    sid, _ = _seed(s)
    ev = s.get_remediation_evidence(sid)[0]
    assert "1.3.3" not in {a["sc"] for a in ev["applied"]}   # not a fix
    proposed = {p["sc"]: p for p in ev["proposed"]}
    assert proposed["1.3.3"]["validated"] is False
    assert proposed["1.3.3"]["proposals"][0]["proposed_value"] == "Select the Submit button"


def test_evidence_empty_for_scan_with_no_remediation(isolated_store):
    s = isolated_store
    assert s.get_remediation_evidence("nothing-here") == []


# ── report rendering ──────────────────────────────────────────────────────────

_RUN = {"id": "scan-abc", "completed_at": "2026-07-09T21:00:00", "avg_score": 100, "owner_email": None}
_FILES = [{"file": "deck.pptx", "compliant": 1, "score": 100, "status": "ok", "issues": []}]
_META = {"target": "AA", "version": "1.2", "hash": "deadbeef"}


def _pdf_text(pdf: bytes) -> str:
    from pypdf import PdfReader
    return "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)


def _flat(pdf: bytes) -> str:
    """PDF text with line wrapping collapsed — reportlab breaks prose mid-sentence, so a
    sentence-level assertion must not depend on where the column happened to wrap."""
    import re
    return re.sub(r"\s+", " ", _pdf_text(pdf))


def test_report_renders_without_evidence():
    from report import build_report
    pdf = build_report(_RUN, _FILES, _META)          # back-compat: evidence is optional
    assert pdf[:4] == b"%PDF"
    assert "Remediation evidence" not in _pdf_text(pdf)


def test_report_renders_evidence_with_before_after_value_and_signoff(isolated_store):
    from report import build_report
    s = isolated_store
    sid, _ = _seed(s)
    pdf = build_report(_RUN, _FILES, _META, evidence=s.get_remediation_evidence(sid))
    assert pdf[:4] == b"%PDF"
    t = _pdf_text(pdf)
    for expected in ["Remediation evidence", "validated on re-scan", "(no alt text)",
                     "Bar chart of 2026 sales", "AI vision model (llava)",
                     "approved by reviewer", "Download Annual Report (PDF)",
                     "auto-applied"]:
        assert expected in t, expected


def test_report_never_presents_a_pending_proposal_as_remediated(isolated_store):
    """The report's core honesty guarantee: a proposal awaiting approval is labelled
    'not remediated' and never carries the 'validated on re-scan' mark."""
    from report import build_report
    s = isolated_store
    sid, _ = _seed(s)
    t = _pdf_text(build_report(_RUN, _FILES, _META, evidence=s.get_remediation_evidence(sid)))
    assert "proposed" in t and "not remediated" in t
    # the sensory proposal's block must not claim validation
    start = t.find("Sensory Characteristics")
    assert start != -1
    block = t[start:start + 160]
    assert "validated on re-scan" not in block


def test_report_attributes_the_signoff_to_the_authenticated_reviewer(isolated_store):
    """Chain of custody: the appendix names WHO approved, straight from decision_log.actor."""
    from report import build_report
    s = isolated_store
    sid, f = "s2", "deck.pptx"
    s.record_remediation_diffs(sid, f, [
        {"rule_id": "1.1.1", "before": "(no alt)", "after": "A bar chart", "note": None}])
    s.log_decision("ada@movate.com", "hitl.approved", scan_id=sid, file=f, rule_id="1.1.1")
    ev = s.get_remediation_evidence(sid)
    assert ev[0]["applied"][0]["reviewer"] == "ada@movate.com"
    assert "approved by ada@movate.com" in _pdf_text(build_report(_RUN, _FILES, _META, evidence=ev))


# ── Certification decision / scope of assertion (R2 / R3 / R6 / R-A) ──────────

def _seed_traces(s, sid="s3", f="deck.pptx"):
    issues = [{"ruleId": "A", "wcag": "SC_1_1_1", "severity": "SERIOUS", "detail": "d"},
              {"ruleId": "B", "wcag": "SC_2_4_4", "severity": "MODERATE", "detail": "d"}]
    s.save_file_result(sid, {"file": f, "engine": "office", "status": "pass", "score": 72,
                             "compliant": 0, "skipped_rules": 0, "issues": issues},
                       "2026-07-08T00:00:00Z")
    s.record_remediation_diffs(sid, f, [
        {"rule_id": "1.1.1", "before": "(no alt)", "after": "A bar chart", "note": None}])
    s.log_decision("ada@movate.com", "hitl.approved", scan_id=sid, file=f, rule_id="1.1.1")
    return sid, f, issues


def test_certification_facts_counts_are_grounded_and_add_up(isolated_store):
    s = isolated_store
    sid, _, _ = _seed_traces(s)
    facts = s.get_certification_facts(sid)
    d = facts["documents"][0]
    # every catalog criterion is either evaluated for this format or explicitly not applicable
    assert d["evaluated"] + d["not_applicable"] == facts["scope"]["catalog_size"]
    assert d["failing"] == 2 and d["remediated"] == 1 and d["remaining"] == 1
    assert d["approvals"] == 1
    # not_applicable means NEVER EVALUATED — pptx has no validator for these
    assert "1.4.10" in d["na_criteria"]          # Reflow: web-only
    assert sum(d["by_mode"].values()) == d["evaluated"]


def test_approvals_are_deduped_and_read_from_the_immutable_log(isolated_store):
    s = isolated_store
    sid, f, _ = _seed_traces(s)
    s.log_decision("ada@movate.com", "hitl.approved", scan_id=sid, file=f, rule_id="1.1.1")
    # re-approving the same finding is one approval, not two — and it agrees with the
    # evidence appendix, which also reads decision_log.
    assert s.get_certification_facts(sid)["approvals_total"] == 1


def test_content_digest_is_deterministic_and_tamper_evident():
    from report import _content_digest
    a = _content_digest(_RUN, _FILES, _META)
    assert a == _content_digest(_RUN, list(_FILES), _META)        # stable across re-export
    tampered = [{**_FILES[0], "score": 41}]
    assert _content_digest(_RUN, tampered, _META) != a            # a changed result changes it


def test_report_never_calls_the_digest_a_signature(isolated_store):
    """A bare hash has no key and no non-repudiation. Calling it a 'digital signature' would
    over-claim — the report must say what it is and what it is not."""
    from report import build_report
    s = isolated_store
    sid, _, issues = _seed_traces(s)
    files = [{"file": "deck.pptx", "compliant": 0, "score": 72, "status": "pass", "issues": issues}]
    t = _flat(build_report(_RUN, files, _META, facts=s.get_certification_facts(sid)))
    assert "Content digest" in t
    assert "not a digital signature" in t


def test_decision_block_and_scope_of_assertion_are_honest(isolated_store):
    from report import build_report
    s = isolated_store
    sid, _, issues = _seed_traces(s)
    files = [{"file": "deck.pptx", "compliant": 0, "score": 72, "status": "pass", "issues": issues}]
    t = _flat(build_report(_RUN, files, _META, facts=s.get_certification_facts(sid)))
    assert "Certification decision" in t
    assert "NOT CERTIFIABLE" in t                               # a failing estate is NOT certifiable
    assert "Scope of assertion" in t
    # R-A: the guard against reading 100/100 as full conformance
    assert "does not mean the document is fully WCAG 2.1 AA conformant" in t
    assert "This report makes no assertion about" in t
    # never claims the platform validates the whole standard
    assert "automated validator for 37 success criteria" in t


def test_a_fully_conformant_estate_reads_certifiable(isolated_store):
    """The decision card's status is three-valued; a clean estate is the green one. The
    plain-language WHY lives in the executive verdict below the card, not in the card."""
    from report import build_report
    s = isolated_store
    files = [{"file": "ok.docx", "compliant": 1, "score": 100, "status": "pass", "issues": []}]
    t = _flat(build_report(_RUN, files, _META, facts=s.get_certification_facts("none")))
    assert "CERTIFIABLE" in t
    assert "NOT CERTIFIABLE" not in t and "PARTIALLY CERTIFIABLE" not in t
    assert "certifiable" in t                                # the executive verdict's WHY


def test_inventory_never_reads_clear_while_findings_remain(isolated_store):
    """R6: a document with findings still failing must never be presented as done. The
    inventory shows its open findings and its status, and never labels it certifiable."""
    from report import build_report
    s = isolated_store
    sid, _, issues = _seed_traces(s)
    files = [{"file": "deck.pptx", "compliant": 0, "score": 72, "status": "pass", "issues": issues}]
    facts = s.get_certification_facts(sid)
    assert facts["documents"][0]["remaining"] == 1           # one criterion still failing
    t = _flat(build_report(_RUN, files, _META, facts=facts))
    assert "open finding(s)" in t                            # main's Findings cell
    assert "NOT CERTIFIABLE" in t                            # and the decision reflects it


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
