"""Per-document selection carries through the verdict facts (PRD §6.1).

An operator can mark a SUBSET of documents in-scope in Remediate (triage='inscope'). That selection
is the per-document twin of scan_scope, and — like criteria/formats — it must carry through to the
certification facts the Assess status card and the conformance report read, not only the
Remediate/Publish ACTIONS (which already honour it via an explicit file list). The carry-through is
OPT-IN and READ-TIME: `get_certification_facts(apply_document_selection=True)` narrows to the marked
set; with no selection, or without opting in, behaviour is byte-for-byte unchanged — the safety
property that keeps every unscoped run, and the per-file cards, seeing the whole estate.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import assessment_policy as ap        # noqa: E402
import accessibility_status as accst  # noqa: E402


def _seed(s, sid, f):
    """One assessed file → a per-file trace row get_certification_facts will group on."""
    s.save_file_result(sid, {"file": f, "engine": "office", "status": "pass", "score": 80,
                             "compliant": 0, "skipped_rules": 0,
                             "issues": [{"ruleId": "A", "wcag": "SC_1_1_1", "severity": "SERIOUS", "detail": "d"}]},
                       "2026-08-19T00:00:00Z")


# ── the pure semantic — mirrors the frontend remediableScope.hasDocumentSelection ──
def test_selected_documents_semantics():
    assert ap.selected_documents(None) is None
    assert ap.selected_documents({}) is None
    # other triage kinds are NOT a selection — no file in-scope ⇒ no restriction
    assert ap.selected_documents({"a.docx": {"triage": "na"}, "b.pdf": {"triage": "defer"}}) is None
    # once ANY file is in-scope, ONLY in-scope files remain
    assert ap.selected_documents({"a.docx": {"triage": "inscope"}, "b.pdf": {"triage": "na"}}) == frozenset({"a.docx"})
    assert ap.selected_documents({"a.docx": {"triage": "inscope"}, "b.pdf": {"triage": "inscope"}}) == frozenset({"a.docx", "b.pdf"})
    # an 'action' decision is not a document selection
    assert ap.selected_documents({"a.docx": {"action": "approved"}}) is None


# ── the carry-through, end to end over a real store ──
def test_facts_narrow_to_the_selection_only_when_opted_in(isolated_store):
    s = isolated_store
    sid = "sel1"
    _seed(s, sid, "a.docx")
    _seed(s, sid, "b.pdf")

    # default read: both documents, unchanged
    assert {d["file"] for d in s.get_certification_facts(sid)["documents"]} == {"a.docx", "b.pdf"}

    # operator marks a.docx in-scope in Remediate
    s.save_decision(sid, "a.docx", "triage", "inscope", None, "2026-08-19T01:00:00Z")

    # opted-in read narrows to the selection…
    narrowed = s.get_certification_facts(sid, apply_document_selection=True)
    assert {d["file"] for d in narrowed["documents"]} == {"a.docx"}

    # …but the default read (per-file cards, coverage matrix) still sees the whole estate
    assert {d["file"] for d in s.get_certification_facts(sid)["documents"]} == {"a.docx", "b.pdf"}


def test_scan_status_inherits_the_selection(isolated_store):
    s = isolated_store
    sid = "sel2"
    _seed(s, sid, "a.docx")
    _seed(s, sid, "b.pdf")

    full = accst.scan_status(s, sid)
    s.save_decision(sid, "a.docx", "triage", "inscope", None, "2026-08-19T01:00:00Z")
    narrowed = accst.scan_status(s, sid)

    # the scan-level Accessibility Status now sums over one document, not two
    assert 0 < narrowed["in_scope"] < full["in_scope"]


def test_no_selection_is_the_identity(isolated_store):
    s = isolated_store
    sid = "sel3"
    _seed(s, sid, "a.docx")
    _seed(s, sid, "b.pdf")
    # opting in with NO marks made == the default: unscoped runs are untouched
    optin = s.get_certification_facts(sid, apply_document_selection=True)
    default = s.get_certification_facts(sid)
    assert {d["file"] for d in optin["documents"]} == {d["file"] for d in default["documents"]} == {"a.docx", "b.pdf"}
    assert accst.scan_status(s, sid)["in_scope"] == accst.scan_status(s, sid)["in_scope"]
