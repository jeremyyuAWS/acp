"""The scope-of-assertion section names the documents the scan never opened.

WHY THIS IS NOT COSMETIC. `_scope_section` is the report's guard against its own headline
number, and every narrowing it states is by CRITERION: "no check was run for 2.4.3 on a PDF."
None of it is by DOCUMENT. Once the file-type scope gates what gets read, a whole class of files
is absent from the report entirely — not failing, not passing, not evaluated, never opened.

A conformance report that lists the criteria it skipped but not the documents it never saw
understates its own boundary in the flattering direction, which is precisely the failure the rest
of that section exists to prevent. The auditor asking "does this cover the estate?" gets "yes"
from silence.

The facts come from the SCAN'S OWN recorded scope, not the live setting — a report is a statement
about what happened, and the operator may have changed the scope since. Reading the current
setting would let a report re-describe its own past.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

DOCX_ONLY = {"1.1.1": ["docx"], "1.3.1": ["docx"]}


@pytest.fixture
def store(isolated_store):
    return isolated_store


def _scan(st, sid, scope_dict):
    st.init_scan_run(sid, "drive", 1, "2026-08-08T00:00:00Z", "default", "rh",
                     owner="a@example.com", status="running", scope=scope_dict)
    st.save_file_result(sid, {"file": "a.docx", "engine": ".net/office", "status": "analysed",
                              "score": 90, "compliant": 1, "skipped_rules": 0, "issues": []},
                        "2026-08-08T00:00:00Z")


# ── the facts ─────────────────────────────────────────────────────────────────

def test_facts_carry_what_was_not_read(store):
    _scan(store, "s1", {"kind": "drive", "kept": 1, "scan_scope": DOCX_ONLY,
                        "skipped_out_of_scope": 47})
    scope = store.get_certification_facts("s1")["scope"]
    assert scope["unread_documents"] == 47
    assert scope["formats_read"] == ["docx"]


def test_no_claim_when_nothing_was_excluded(store):
    """An unscoped scan must add no sentence — a boundary stated where none exists is noise, and
    noise in this section is how the real narrowings stop being read."""
    _scan(store, "s2", {"kind": "drive", "kept": 1})
    scope = store.get_certification_facts("s2")["scope"]
    assert "unread_documents" not in scope
    assert "formats_read" not in scope


def test_the_scan_is_described_by_its_OWN_scope_not_the_current_one(store, monkeypatch):
    """A report is a statement about what happened. If it read the live setting, changing the
    scope afterwards would silently rewrite what an already-issued report claims to cover."""
    _scan(store, "s3", {"kind": "drive", "kept": 1, "scan_scope": DOCX_ONLY,
                        "skipped_out_of_scope": 47})
    import assessment_policy as pol
    monkeypatch.setattr(pol, "_scope_override", {"1.1.1": frozenset({"pdf"})}, raising=False)
    scope = store.get_certification_facts("s3")["scope"]
    assert scope["formats_read"] == ["docx"], "the report described the CURRENT scope, not its own"


def test_a_missing_scope_column_does_not_break_the_facts(store):
    """History predating the field must still produce a report."""
    store.init_scan_run("s4", "drive", 1, "2026-08-08T00:00:00Z", "default", "rh",
                        owner="a@example.com", status="running")
    store.save_file_result("s4", {"file": "a.docx", "engine": ".net/office", "status": "analysed",
                                  "score": 90, "compliant": 1, "skipped_rules": 0, "issues": []},
                           "2026-08-08T00:00:00Z")
    scope = store.get_certification_facts("s4")["scope"]
    assert "unread_documents" not in scope


# ── the rendered text ─────────────────────────────────────────────────────────

def _section_text(facts) -> str:
    """Render _scope_section and flatten it to text.

    Rendered rather than asserted on the facts dict, because "the store computes it and the
    report never prints it" is the same defect with a unit test in front of it.
    """
    import report
    from reportlab.lib.styles import getSampleStyleSheet
    ss = getSampleStyleSheet()
    el = report._scope_section(
        [{"file": "a.docx"}], facts, ss["Heading2"], ss["BodyText"], ss["BodyText"], ss["BodyText"])
    out = []
    for e in el:
        t = getattr(e, "text", None)
        if t:
            out.append(str(t))
    return " ".join(out)


def _facts(**scope_extra):
    return {"documents": [{"file": "a.docx", "evaluated": 4, "not_evaluated": 11,
                           "by_mode": {"auto": 4}}],
            "scope": {"catalog_size": 15, "by_mode": {"auto": 4},
                      "not_evaluated_criteria": [], "review_criteria": [],
                      "human_only_criteria": [], **scope_extra}}


def test_the_report_states_the_documents_it_never_opened():
    t = _section_text(_facts(unread_documents=47, formats_read=["docx"]))
    assert "47" in t
    assert "not read at all" in t
    assert ".docx" in t


def test_it_says_no_statement_rather_than_implying_conformance():
    """The load-bearing wording. "Excluded" or "filtered" would leave a reader assuming the
    documents were seen and set aside; they were never opened, and the report must not be
    readable as covering them."""
    t = _section_text(_facts(unread_documents=47, formats_read=["docx"]))
    assert "makes no statement about them" in t
    assert "neither conformant nor failing" in t


def test_it_agrees_with_itself_in_the_singular():
    # The count is bolded, so the number and the noun are not adjacent in the source string.
    # Asserted around the markup rather than dropping the emphasis from the report — a count an
    # auditor is meant to notice should be emphasised.
    t = _section_text(_facts(unread_documents=1, formats_read=["docx"]))
    assert "<b>1</b> document of other file types was not read" in t
    plural = _section_text(_facts(unread_documents=2, formats_read=["docx"]))
    assert "<b>2</b> documents of other file types were not read" in plural


def test_an_unscoped_report_adds_no_boundary_sentence():
    t = _section_text(_facts())
    assert "not read at all" not in t


def test_the_existing_criterion_level_disclosure_survives():
    """The new sentence must be additive. The criteria-level negative assurance is the part an
    auditor already relies on."""
    t = _section_text(_facts(unread_documents=47, formats_read=["docx"]))
    assert "not evaluated" in t.lower()
    assert "must not be represented as such" in t
