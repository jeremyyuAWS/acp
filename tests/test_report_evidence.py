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


# ── store.get_remediation_evidence ──────────────────────────────────────────────

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


def test_report_groups_fixes_by_human_category_before_the_wcag_appendix(isolated_store):
    """The certification report leads with what a person reads — Images, Hyperlinks — not WCAG
    ids, and only then drops into the per-finding detail. The counts are the SAME verified
    evidence the appendix lists, so the two can never disagree, and the WCAG id is kept as a
    parenthetical for the auditor rather than deleted."""
    from report import build_report
    s = isolated_store
    sid, _ = _seed(s)
    t = _flat(build_report(_RUN, _FILES, _META, evidence=s.get_remediation_evidence(sid)))

    # the human-task summary exists and LEADS the per-finding appendix
    assert "What we fixed" in t
    assert t.index("What we fixed") < t.index("Remediation evidence")
    # grouped by the category a person finds in the document, in plain language…
    assert "Images" in t and "Missing image description" in t
    assert "Hyperlinks" in t and "Link text is unclear" in t
    # …with the WCAG id kept, demoted to a parenthetical, never removed
    assert "WCAG 1.1.1" in t and "2.4.4" in t
    # a PENDING proposal (1.3.3, Instructions) is NOT counted as fixed anywhere — its human
    # name must never appear in the "what we fixed" roll-up. (The appendix still lists it under
    # 'proposed', by its WCAG rule name, not this human category name.)
    assert "Directions depend on shape or position" not in t


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


# ── Outcome decision / what the report covers (R2 / R3 / R6 / R-A) ──────────────
#
# The vocabulary here changed with the report's: ACP reports what it detected, changed and
# re-verified, and does not assert that a document conforms. The INVARIANTS these guards hold
# are unchanged — an estate with open findings must never render as clear, and the report must
# always bound what it covers. Only the words being matched moved.

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
    # every catalog criterion is evaluated, explicitly not-evaluated, or 🟡 review-recommended
    # (ADR 0023) — the three buckets partition the catalog exactly.
    assert d["evaluated"] + d["not_evaluated"] + d["review"] == facts["scope"]["catalog_size"]
    assert d["failing"] == 2 and d["remediated"] == 1 and d["remaining"] == 1
    assert d["approvals"] == 1
    # not_evaluated means NEVER RUN — pptx has no validator for these. It is deliberately NOT
    # called "not applicable": that would assert the criterion is out of scope, which we
    # never determined. The report says only what we know.
    assert "1.4.10" in d["not_evaluated_criteria"]          # Reflow: no validator on pptx
    assert sum(d["by_mode"].values()) == d["evaluated"]


def test_review_recommended_is_its_own_bucket_and_not_certified(isolated_store):
    """A 🟡 Review criterion (ADR 0023) lands in the `review` bucket — assessed-for-review,
    NOT certified: neither counted as evaluated (we didn't verify pass/fail) nor as not_evaluated
    (we looked). Both a control-review finding (4.1.2) AND a clean review-lane criterion (1.1.1
    with no missing-alt: ACP can't certify alt adequacy — audit #174) belong here, never a pass."""
    s = isolated_store
    # A pptx with a real fail (1.3.1) plus an advisory control-review finding on 4.1.2. 1.1.1 has
    # NO finding — a 🟡 review-lane criterion, so it must land in review, not a green pass.
    issues = [
        {"ruleId": "A", "wcag": "SC_1_3_1", "severity": "SERIOUS", "detail": "d"},
        {"ruleId": "OFFICE_INTERACTIVE_CONTROL_NAME_ROLE",
         "wcag": "4.1.2 Name, Role, Value", "severity": "REVIEW", "detail": "2 ActiveX controls"},
    ]
    s.save_file_result("rev", {"file": "deck.pptx", "engine": "office", "status": "pass",
                               "score": 85, "compliant": 0, "skipped_rules": 0, "issues": issues},
                       "2026-07-14T00:00:00Z")
    facts = s.get_certification_facts("rev")
    d = facts["documents"][0]
    # Both the control-review (4.1.2) and the clean review-lane (1.1.1) criteria are in review.
    assert {"4.1.2", "1.1.1"} <= set(d["review_criteria"])
    assert "1.1.1" not in d["not_evaluated_criteria"] and "4.1.2" not in d["not_evaluated_criteria"]
    assert d["review"] >= 2
    # The three buckets still partition the catalog exactly.
    assert d["evaluated"] + d["not_evaluated"] + d["review"] == facts["scope"]["catalog_size"]
    # Scope lists them explicitly as review-recommended (not certified).
    assert any(r["sc"] == "4.1.2" for r in facts["scope"]["review_criteria"])
    assert any(r["sc"] == "1.1.1" for r in facts["scope"]["review_criteria"])


def test_a_scan_stored_before_the_rename_still_adds_up(isolated_store):
    """Rows written by an older image (or by a rolled-back one) say NOT_APPLICABLE.

    If the reader only matched the new token those criteria would be counted as neither
    evaluated nor skipped, and `evaluated + not_evaluated == catalog_size` would quietly
    stop holding — a certification report that silently under-reports its own scope.
    """
    s = isolated_store
    sid, f, _ = _seed_traces(s, sid="legacy")
    with s._db.cursor() as cur:
        s._db.execute(cur,
            "UPDATE scan_rule_traces SET outcome='NOT_APPLICABLE' "
            "WHERE scan_id=%s AND outcome='NOT_EVALUATED'", (sid,))
    facts = s.get_certification_facts(sid)
    d = facts["documents"][0]
    assert d["not_evaluated"] > 0, "the fixture must contain criteria with no validator"
    assert d["evaluated"] + d["not_evaluated"] + d["review"] == facts["scope"]["catalog_size"]
    assert "1.4.10" in d["not_evaluated_criteria"]


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
    assert "What ACP checked, fixed and verified" in t
    assert "OPEN FINDINGS" in t                                 # a failing estate says so
    assert "What this report covers" in t
    # R-A: the guard against reading 100/100 as full conformance. The wording moved with the
    # vocabulary change; the INVARIANT did not — the report must always disclaim the conformance
    # reading in the same breath as the score, not leave it to be inferred.
    assert "not a statement that the document conforms to WCAG 2.1 AA" in t
    assert "must not be represented as such" in t
    assert "This report makes no assertion about" in t
    # The not-evaluated criteria are actually LISTED, and framed as "we didn't check", never
    # "doesn't apply" — a pptx has no reflow validator, but the report must not assert reflow
    # is inapplicable. (Guards against the scope section silently reading a renamed-away key
    # and rendering empty.)
    assert "Not evaluated for these file formats" in t
    assert "not a statement that the criterion does not apply" in t
    assert "1.4.10" in t                                       # Reflow: listed, not omitted
    # The word "applicable" may appear — but only to DISTINGUISH from it ("not the same as not
    # applicable"), never to report a criterion AS not-applicable.
    assert "reported as not applicable" not in t.lower()
    assert "deliberately not the same as not applicable" in t.lower()
    # never claims the platform validates the whole standard
    assert "automated validator for 38 success criteria" in t   # +2.1.2 No Keyboard Trap (#187)


def test_a_clean_estate_reads_no_blocking_findings(isolated_store):
    """The decision card's status is three-valued; a clean estate is the green one. The
    plain-language WHY lives in the executive verdict below the card, not in the card."""
    from report import build_report
    s = isolated_store
    files = [{"file": "ok.docx", "compliant": 1, "score": 100, "status": "pass", "issues": []}]
    t = _flat(build_report(_RUN, files, _META, facts=s.get_certification_facts("none")))
    assert "NO BLOCKING FINDINGS" in t
    assert "OPEN FINDINGS" not in t and "PARTIALLY CLEARED" not in t
    assert "no blocking findings" in t                       # the executive verdict's WHY
    # The claim ACP must never make, even on a spotless estate. This is the assertion the
    # whole vocabulary change exists for: a clean scan is a record of what was checked, not a
    # conformance determination, and the report must not read as one.
    assert "may be certified" not in t
    assert "conform to" not in t


def test_inventory_never_reads_clear_while_findings_remain(isolated_store):
    """R6: a document with findings still failing must never be presented as done. The
    inventory shows its open findings and its status, and never labels it clear."""
    from report import build_report
    s = isolated_store
    sid, _, issues = _seed_traces(s)
    files = [{"file": "deck.pptx", "compliant": 0, "score": 72, "status": "pass", "issues": issues}]
    facts = s.get_certification_facts(sid)
    assert facts["documents"][0]["remaining"] == 1           # one criterion still failing
    t = _flat(build_report(_RUN, files, _META, facts=facts))
    assert "Open" in t                                       # P-15 per-finding status label
    assert "OPEN FINDINGS" in t                              # and the decision reflects it


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


# ── the vocabulary itself (2026-08-09) ────────────────────────────────────────────
#
# ACP reports what it detected, what it changed and what it re-verified. It does not determine
# conformance. That was already true of the BEHAVIOUR and already argued at length in the scope
# section — but the report's own words said otherwise: it was titled a Conformance Report, its
# headline verdict was CERTIFIABLE, and its closing section was a "Conformance statement". Each
# of those was a claim the paragraphs underneath spent their length walking back.
#
# These guard the words, because the words are what a customer quotes. A phrase-by-phrase rename
# is exactly the kind of change that leaves half a document in the old register, and nothing else
# in this suite would notice.

def _clean_estate_report(isolated_store):
    import core
    from report import build_report
    files = [{"file": f, "engine": ".net/office", "status": "analysed", "score": 100,
              "compliant": 1, "skipped_rules": 0, "issues": []}
             for f in ("benefits.docx", "policy.docx")]
    core.store = isolated_store
    return _flat(build_report(
        {"id": "s-vocab", "completed_at": "2026-08-09T09:00:00", "avg_score": 100,
         "owner_email": None},
        files, {"target": "WCAG 2.1 AA", "version": "1.2", "hash": "deadbeef"}))


def test_the_scan_report_does_not_call_itself_a_conformance_report(isolated_store):
    """The title was the largest claim in the document. ACP's OWN VPAT-style ACR keeps that name
    — it is a real conformance report about the mova.io product — but a report about a customer's
    documents is a record of work, not a determination about their estate."""
    t = _clean_estate_report(isolated_store)
    assert "Accessibility Assessment Report" in t
    assert "Accessibility Conformance Report" not in t


def test_a_spotless_estate_never_claims_conformance(isolated_store):
    """The case where the temptation is greatest and the claim is least checked: two documents,
    zero findings, and the report must still say only what it measured."""
    t = _clean_estate_report(isolated_store)
    for forbidden in ("CERTIFIABLE", "may be certified", "conform to", "Conformance statement"):
        assert forbidden not in t, f"a clean report still says {forbidden!r}"


def test_the_verdict_names_what_was_checked_rather_than_asserting_a_standard(isolated_store):
    """"meets WCAG 2.1 AA" asserts a property of the DOCUMENT. "came back with zero open blocking
    findings among the criteria ACP checked" asserts a property of the SCAN, which is the only
    one ACP can support."""
    t = _clean_estate_report(isolated_store)
    assert "criteria ACP checked" in t
    assert "document(s) meet" not in t


def test_the_disclaimer_is_stated_not_implied(isolated_store):
    """The scope section has always argued this; now the headline sentence says it too, so a
    reader who stops after the first card still gets it."""
    t = _clean_estate_report(isolated_store)
    assert "not a statement that the document conforms to WCAG" in t
    assert "not a conformance determination" in t


# ── R5: AI reasoning inline (why_review + source on proposals) ───────────────────────

def test_proposal_source_rendered_in_evidence_appendix(isolated_store):
    """R5: the model/method that produced a proposal appears in the PDF next to the
    proposed value — auditors see how the draft was made, not just what it says."""
    from report import build_report
    s = isolated_store
    sid, f = "r5s", "r5.pptx"
    s.enqueue_proposals(sid, f, "1.1.1", [{
        "locator": "slide1#r1", "before": "(no alt text)",
        "proposed_value": "A pie chart of Q1 revenue by region",
        "rationale": "vision description only — no text in the image",
        "source": "AI vision model (llava-3)",
    }], validated=False, rule_name="Non-text Content")
    ev = s.get_remediation_evidence(sid)
    t = _pdf_text(build_report(_RUN, _FILES, _META, evidence=ev))
    assert "AI vision model (llava-3)" in t


def test_proposal_why_review_rendered_as_basis_in_evidence_appendix(isolated_store):
    """R5: the 'why this needed human review' reasoning (confidence basis, not a number)
    appears as a 'Basis' line so reviewers see what the platform could not verify automatically."""
    from report import build_report
    s = isolated_store
    sid, f = "r5w", "r5.pptx"
    s.enqueue_proposals(sid, f, "1.1.1", [{
        "locator": "slide1#r2", "before": "(no alt text)",
        "proposed_value": "A company logo",
        "rationale": "vision description only — no text in the image to anchor it",
        "source": "AI vision model (llava-3)",
        "why_review": ("The image contains no readable text, so nothing in the document "
                       "can corroborate this description."),
    }], validated=False, rule_name="Non-text Content")
    ev = s.get_remediation_evidence(sid)
    t = _pdf_text(build_report(_RUN, _FILES, _META, evidence=ev))
    assert "Basis" in t
    assert "The image contains no readable text" in t
