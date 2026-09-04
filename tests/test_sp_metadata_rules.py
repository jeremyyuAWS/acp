"""SharePoint-native metadata as a LIFECYCLE RULE INPUT, and as audit evidence.

The point of the SharePoint connector is that the customer has already done the information
architecture — content types, retention labels, a records category column — and a rule keyed on
ACP's own guesses ignores all of it. "Archive anything under the Superseded content type" is a
rule a records manager can defend to an auditor; "archive anything older than seven years" is one
they have to justify from scratch.

The trap this file guards is the one #610 already fell into once and CLAUDE.md records: a field
added to `disposition.FIELDS` and to the condition builder, and never wired into the doc dict the
evaluator actually reads. Such a rule validates, saves, previews, and then silently matches
nothing forever — and "matched nothing" is indistinguishable from a correct answer.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import disposition  # noqa: E402


def _doc(**kw):
    base = {"doc_id": "d1", "source": "sharepoint", "path": "/Policies/a.docx",
            "content_type": "Superseded Policy", "retention_label": "Retain 7 Years",
            "sharing_scope": "organization", "item_kind": "document",
            "site_name": "Regulatory", "library_name": "Policies",
            "managed_columns": {"Records Category": "Superseded"}}
    base.update(kw)
    return base


# ── the fields are real rule inputs, not just names in a list ────────────────────────────────

@pytest.mark.parametrize("field,value", [
    ("content_type", "Superseded Policy"), ("retention_label", "Retain 7 Years"),
    ("sharing_scope", "organization"), ("item_kind", "document"),
    ("site_name", "Regulatory"), ("library_name", "Policies"),
])
def test_each_sharepoint_field_actually_matches(field, value):
    """#610's lesson, applied field by field: a name in FIELDS that the evaluator cannot read is
    a rule that saves and then does nothing forever."""
    match = [{"field": field, "op": "eq", "value": value}]
    disposition.validate_match(match)
    assert disposition.matches(_doc(), match) is True
    assert disposition.matches(_doc(**{field: "something else"}), match) is False


def test_a_managed_column_rule_reads_the_tenants_own_column():
    """Managed metadata means the CUSTOMER names the columns, so there is no allow-list to add
    them to and no schema column to store them in. `managed:` is the namespace that lets a rule
    name one without colliding with ACP's own fields."""
    match = [{"field": "managed:Records Category", "op": "eq", "value": "Superseded"}]
    disposition.validate_match(match)
    assert disposition.matches(_doc(), match) is True
    assert disposition.matches(_doc(managed_columns={"Records Category": "Active"}), match) is False


def test_a_managed_column_is_matched_case_insensitively():
    """The name in a rule is typed by a human reading a SharePoint list header; the name in the
    payload is Graph's internal spelling. A rule that matches nothing because of a capital letter
    is indistinguishable from one that correctly matches nothing."""
    match = [{"field": "managed:records category", "op": "eq", "value": "Superseded"}]
    assert disposition.matches(_doc(), match) is True


def test_a_tenant_column_cannot_shadow_an_acp_field():
    """A tenant with a column literally called "owner" is theirs to have. The namespace is what
    keeps `owner` meaning the document's owner and `managed:owner` meaning their column."""
    doc = _doc(owner="Alice", managed_columns={"owner": "Records Office"})
    assert disposition.matches(doc, [{"field": "owner", "op": "eq", "value": "Alice"}]) is True
    assert disposition.matches(
        doc, [{"field": "managed:owner", "op": "eq", "value": "Records Office"}]) is True


def test_a_managed_rule_on_a_document_with_no_columns_matches_nothing_without_raising():
    assert disposition.matches({"doc_id": "x"},
                               [{"field": "managed:Anything", "op": "eq", "value": "v"}]) is False


def test_an_unknown_field_is_still_rejected():
    """The namespace must not become a hole: `managed:` is a prefix, not "anything goes"."""
    with pytest.raises(ValueError):
        disposition.validate_match([{"field": "nonsense", "op": "eq", "value": "x"}])
    with pytest.raises(ValueError):
        disposition.validate_match([{"field": "managed:", "op": "eq", "value": "x"}])


def test_the_error_names_the_managed_namespace_so_an_author_can_find_it():
    with pytest.raises(ValueError) as e:
        disposition.validate_match([{"field": "Records Category", "op": "eq", "value": "x"}])
    assert "managed:" in str(e.value)


# ── the evidence: unread is not unset ────────────────────────────────────────────────────────

def test_evidence_says_a_field_was_NOT_READ_rather_than_not_recorded():
    """THE audit-evidence case. A rule matches nothing whether the tenant applies no retention
    labels or Graph refused to hand them over — so the rule cannot tell them apart, and the human
    reading WHY it did not match has to be able to."""
    doc = _doc(retention_label=None,
               sp_availability={"retention_label": "unavailable"},
               sp_reasons={"retention_label": "Graph refused the wider driveItem $select"})
    result = disposition.evaluate(doc, [{"field": "retention_label", "op": "eq",
                                         "value": "Retain 7 Years"}])
    reason = result["conditions"][0]["reason"]
    assert "NOT READ" in reason
    assert "refused the wider driveItem $select" in reason
    assert result["matched"] is False


def test_evidence_says_the_tenant_records_nothing_when_that_is_what_happened():
    """The opposite conclusion, from the same empty value. This is the one an operator can act on
    by changing their SharePoint, not by changing ACP."""
    doc = _doc(retention_label=None, sp_availability={"retention_label": "not_configured"})
    reason = disposition.evaluate(doc, [{"field": "retention_label", "op": "eq",
                                         "value": "Retain 7 Years"}])["conditions"][0]["reason"]
    assert "SharePoint records no 'retention_label'" in reason
    assert "NOT READ" not in reason


def test_a_managed_condition_reports_the_bags_availability():
    """The whole column set arrives together or not at all, so "Records Category was not read" is
    a fact about the listItem expansion — recorded once, under the bag."""
    doc = _doc(managed_columns={},
               sp_availability={"managed_columns": "unavailable"},
               sp_reasons={"managed_columns": "the listItem expansion was refused"})
    reason = disposition.evaluate(
        doc, [{"field": "managed:Records Category", "op": "eq",
               "value": "Superseded"}])["conditions"][0]["reason"]
    assert "NOT READ" in reason and "expansion was refused" in reason


def test_a_document_with_no_availability_map_reads_exactly_as_it_always_did():
    """Every non-SharePoint source, and every scan recorded before Phase 2. The wording for a
    plain missing field must not change underneath them."""
    reason = disposition.evaluate({"doc_id": "x"},
                                  [{"field": "owner", "op": "eq",
                                    "value": "Alice"}])["conditions"][0]["reason"]
    assert reason == "'owner' not recorded"


# ── the reshaping that feeds all of the above ────────────────────────────────────────────────

def test_the_inventory_row_becomes_rule_inputs_including_the_availability():
    import handlers
    row = {"content_type": "Policy", "retention_label": None, "site_name": "Regulatory",
           "sp_metadata": json.dumps({"managed_columns": {"Records Category": "Superseded"},
                                      "availability": {"retention_label": "unavailable"},
                                      "reasons": {"retention_label": "refused"}})}
    got = handlers._sp_rule_inputs(row)
    assert got["content_type"] == "Policy"
    assert got["managed_columns"] == {"Records Category": "Superseded"}
    assert got["sp_availability"] == {"retention_label": "unavailable"}
    assert got["sp_reasons"] == {"retention_label": "refused"}


@pytest.mark.parametrize("bad", ["not json at all", "[1,2,3]", "", None])
def test_a_malformed_metadata_blob_never_fails_the_evaluation(bad):
    """This JSON is written by a scan and read by a lifecycle evaluation. One written by an older
    build, or by a replica mid-rollout, must cost that row its metadata — never the whole run."""
    import handlers
    got = handlers._sp_rule_inputs({"content_type": "Policy", "sp_metadata": bad})
    assert got["content_type"] == "Policy"
    assert "managed_columns" not in got or got["managed_columns"] == {}


# ── end to end: what a scan writes is what a rule preview reads ──────────────────────────────

def test_a_rule_preview_reads_the_metadata_a_scan_persisted(isolated_store):
    """The seam #610 fell through, closed at the far end.

    A field can be in FIELDS, on the inventory row, and in the Discover-time evaluator, and STILL
    be invisible to the rule PREVIEW — which reads a different query, in a different module. A
    preview that disagrees with the run reports "would match: 0" for a rule that will in fact tag
    the estate, and the author deletes a correct rule believing it does nothing.
    """
    s = isolated_store
    s.init_scan_run("s1", "sharepoint", 0, "2026-01-01T00:00:00Z", "rb", "h",
                    owner="o@example.com", status="discovered", scope={"kind": "sharepoint"})
    s.add_inventory("s1", [{
        "file": "a.docx", "content_type": "Superseded Policy",
        "site_name": "Regulatory", "library_name": "Policies", "retention_label": None,
        "sp_metadata": json.dumps({
            "managed_columns": {"Records Category": "Superseded"},
            "availability": {"retention_label": "unavailable"},
            "reasons": {"retention_label": "Graph refused the wider driveItem $select"}})}])

    [doc] = s.list_pending_disposition_candidates(owner="o@example.com")

    # Every surface the metadata was built for, against one real persisted row.
    assert disposition.matches(doc, [{"field": "content_type", "op": "eq",
                                      "value": "Superseded Policy"}]) is True
    assert disposition.matches(doc, [{"field": "managed:Records Category", "op": "eq",
                                      "value": "Superseded"}]) is True
    assert disposition.matches(doc, [{"field": "library_name", "op": "eq",
                                      "value": "Policies"}]) is True
    reason = disposition.evaluate(doc, [{"field": "retention_label", "op": "eq",
                                         "value": "Retain 7"}])["conditions"][0]["reason"]
    assert "NOT READ" in reason and "wider driveItem $select" in reason
