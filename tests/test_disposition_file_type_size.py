"""File type (doc_class) and size (size_kb) as lifecycle-rule conditions.

Lifecycle Rules build-plan item #3 (condition builder). Two of the fields the request asked for
— "file type" and "size" — genuinely did not exist as a documents-table column before this:

  * doc_class: DID exist (ADR 0020 stage 2), and is already scan-derived and populated via
    upsert_document's `classify` dict — just never added to disposition.FIELDS, so
    validate_match rejected a rule that tried to use it.
  * size_kb: did NOT exist on `documents` at all. The scanner already computes it per file
    (api/scanner.py's _inv_size_kb) and stores it on scan_inventory, but `documents` — the table
    the disposition matcher actually reads via list_all_documents() — never received it.
    upsert_document now takes size_kb explicitly (not bundled into `classify`, since it's a plain
    scan-derived fact like path or last_seen, not an ADR-0020 classification) and always
    overwrites it on conflict, unlike the classify-conditional columns.

department/business_criticality/regulatory_tags are deliberately NOT part of this change even
though they're valid disposition.FIELDS too — nothing anywhere writes those three columns (see
lifecycleRules.js's comment on the same finding), so exposing them as a rule condition would
create a rule that silently matches nothing, forever. Out of scope for this PR on purpose.
"""
from __future__ import annotations
import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import disposition  # noqa: E402


def test_size_kb_is_a_valid_match_field():
    disposition.validate_match([{"field": "size_kb", "op": "gt", "value": 10000}])


def test_doc_class_is_a_valid_match_field():
    disposition.validate_match([{"field": "doc_class", "op": "eq", "value": "pdf-document"}])


def test_matches_filters_on_doc_class_and_size_together():
    big_pdf = {"doc_id": "d1", "doc_class": "pdf-document", "size_kb": 15000}
    small_pdf = {"doc_id": "d2", "doc_class": "pdf-document", "size_kb": 200}
    spreadsheet = {"doc_id": "d3", "doc_class": "spreadsheet", "size_kb": 15000}
    match = [{"field": "doc_class", "op": "eq", "value": "pdf-document"},
             {"field": "size_kb", "op": "gt", "value": 10000}]
    assert disposition.matches(big_pdf, match) is True
    assert disposition.matches(small_pdf, match) is False    # right type, too small
    assert disposition.matches(spreadsheet, match) is False  # right size, wrong type


def test_upsert_document_persists_size_kb(isolated_store):
    st = isolated_store
    st.upsert_document("d1", source="drive", path="Finance/report.pdf", content_hash="h1",
                       owner="alex", created_at="2026-01-01T00:00:00+00:00",
                       last_seen="2026-01-01T00:00:00+00:00", triage_score=0,
                       triage_rationale="", size_kb=15000)
    doc = st.get_document("d1")
    assert doc["size_kb"] == 15000


def test_upsert_document_overwrites_size_kb_on_a_later_scan(isolated_store):
    """size_kb is a plain scan-derived fact, like last_seen — a later scan's number replaces the
    earlier one, unlike the classify-conditional columns which are left alone when classify is
    absent. A file that grew (or a corrected estimate) should not keep reporting its old size."""
    st = isolated_store
    st.upsert_document("d1", source="drive", path="a.pdf", content_hash="h1", owner="alex",
                       created_at="2026-01-01T00:00:00+00:00", last_seen="2026-01-01T00:00:00+00:00",
                       triage_score=0, triage_rationale="", size_kb=100)
    st.upsert_document("d1", source="drive", path="a.pdf", content_hash="h1", owner="alex",
                       created_at="2026-01-01T00:00:00+00:00", last_seen="2026-02-01T00:00:00+00:00",
                       triage_score=0, triage_rationale="", size_kb=250)
    assert st.get_document("d1")["size_kb"] == 250


def test_upsert_document_persists_doc_class_via_classify(isolated_store):
    st = isolated_store
    st.upsert_document("d1", source="drive", path="a.pdf", content_hash="h1", owner="alex",
                       created_at="2026-01-01T00:00:00+00:00", last_seen="2026-01-01T00:00:00+00:00",
                       triage_score=0, triage_rationale="",
                       classify={"doc_class": "pdf-document"})
    assert st.get_document("d1")["doc_class"] == "pdf-document"
