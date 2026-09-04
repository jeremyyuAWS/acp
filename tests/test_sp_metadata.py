"""SharePoint-native metadata, and the one distinction the whole of Phase 2 turns on.

A field is never reported as "the tenant does not set this" when the truth is "we could not read
it". Those two produce an identical empty cell in every report ACP renders, an identical
no-match in every lifecycle rule, and they call for OPPOSITE responses:

  * not_configured — a fact about the customer's SharePoint, and an answer. No retention labels
    are applied; stop building for them.
  * unavailable — a fact about ACP, and a task. A missing scope, a Graph version, a $select this
    tenant refuses.

Collapsing them produces the worst outcome available here: an operator concludes their estate
carries no sensitivity labels when nobody ever asked Graph for them. So `not_configured` is
claimable ONLY from a container that was read successfully, and that is enforced at the one
constructor (`resolve`) rather than left to each call site to remember.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import sp_metadata as M  # noqa: E402


# ── the contract ─────────────────────────────────────────────────────────────────────────────

def test_a_read_container_with_no_value_is_NOT_CONFIGURED():
    """The tenant was asked and answered nothing. An answer, and the only case that may say so."""
    assert M.resolve(M.Container({"a": 1}), None)["state"] == M.NOT_CONFIGURED


def test_an_unread_container_is_UNAVAILABLE_and_carries_why():
    """THE case. Same empty value, opposite meaning, and the reason is what makes it actionable."""
    got = M.resolve(M.Container.missing("Graph refused the listItem expansion"), None)
    assert got["state"] == M.UNAVAILABLE
    assert "refused" in got["reason"]


def test_an_unread_container_cannot_produce_NOT_CONFIGURED_even_with_a_value():
    """Belt and braces: a caller that somehow has a value from a container it never read is
    confused, and the honest answer is still "we did not read this"."""
    assert M.resolve(M.Container.missing("boom"), "a value")["state"] == M.UNAVAILABLE


def test_an_EMPTY_container_is_a_successful_read():
    """`{}` is a library with no columns set — a real answer. Only None means "never obtained",
    and conflating the two is how `not_configured` would start lying."""
    assert M.Container({}).ok is True
    assert M.Container(None).ok is False
    assert M.resolve(M.Container({}), None)["state"] == M.NOT_CONFIGURED


def test_not_applicable_beats_everything():
    """A OneDrive file has no site however the read went. Reporting that as `unavailable` would
    put a permanent task on a list for a field that cannot exist."""
    assert M.resolve(M.Container.missing("x"), None, applicable=False)["state"] == M.NOT_APPLICABLE


@pytest.mark.parametrize("empty", [None, "", [], {}])
def test_every_empty_shape_reads_as_absent(empty):
    """Graph returns absence four different ways depending on the field's type. A column that
    said `present` with an empty list would put a blank in an export beside a "present" state,
    which is worse than either alone."""
    assert M.resolve(M.Container({}), empty)["state"] == M.NOT_CONFIGURED


# ── managed columns: the customer's, not SharePoint's plumbing ───────────────────────────────

def test_system_columns_are_not_reported_as_managed_metadata():
    """Thirty rows of GUIDs and lookup ids would bury the two columns a governance rule is about,
    and an operator scanning for "Records Category" would not find it."""
    got = M.managed_columns({
        "@odata.etag": "x", "id": "1", "ContentType": "Document", "Created": "2020-01-01",
        "AuthorLookupId": "9", "_UIVersionString": "3.0", "LinkTitle": "a",
        "Records Category": "Superseded", "Retention Owner": "Records Office",
    })
    assert got == {"Records Category": "Superseded", "Retention Owner": "Records Office"}


def test_the_lookup_shadow_of_a_person_column_is_dropped():
    """Graph emits "Manager" and "ManagerLookupId" for the same fact. Keeping both double-counts
    the column in every export and offers a rule an id nobody can read."""
    assert M.managed_columns({"Manager": "Alice", "ManagerLookupId": 12}) == {"Manager": "Alice"}


def test_managed_columns_survive_a_tenant_naming_a_column_like_an_acp_field():
    """Managed metadata means the CUSTOMER names the columns. A tenant column called "owner" is
    theirs and must come through — the `managed:` namespace is what keeps it from colliding."""
    assert M.managed_columns({"owner": "Records Office"}) == {"owner": "Records Office"}


# ── normalization ────────────────────────────────────────────────────────────────────────────

def _item(**kw):
    base = {"id": "i1", "name": "policy.docx", "file": {"mimeType": "application/msword"},
            "createdBy": {"user": {"displayName": "Alice Brown"}},
            "lastModifiedBy": {"user": {"email": "bob@contoso.com"}},
            "shared": {"scope": "organization"}}
    base.update(kw)
    return base


def _list_item(fields=None, content_type="Policy Document"):
    return M.Container({"contentType": {"name": content_type}, "fields": fields or {}})


def test_a_full_read_reports_the_tenants_own_vocabulary():
    meta = M.normalize(_item(retentionLabel={"name": "Retain 7 Years"}),
                       list_item=_list_item({"Records Category": "Active",
                                             "_UIVersionString": "4.0"}),
                       site_id="c,1,1", site_name="Regulatory", library_name="Policies")
    v = M.values(meta)
    assert v["content_type"] == "Policy Document"
    assert v["retention_label"] == "Retain 7 Years"
    assert v["managed_columns"] == {"Records Category": "Active"}
    assert v["version"] == "4.0"
    assert v["site_name"] == "Regulatory" and v["library_name"] == "Policies"
    assert v["created_by"] == "Alice Brown" and v["modified_by"] == "bob@contoso.com"
    assert v["sharing_scope"] == "organization"


def test_a_refused_expansion_makes_every_column_field_unavailable_not_unset(monkeypatch):
    """THE regression this module exists to prevent. With no listItem, a report that said
    "no content types, no managed columns, no versions" would be describing ACP, not the tenant.
    """
    meta = M.normalize(_item(), list_item=M.Container.missing("Graph refused the expansion"),
                       site_id="c,1,1", site_name="Regulatory", library_name="Policies")
    states = M.availability(meta)
    for field in ("content_type", "managed_columns", "version", "checked_out_by",
                  "compliance_tag", "is_record"):
        assert states[field] == M.UNAVAILABLE, f"{field} claimed to know the tenant's mind"
    # …while the fields that came off the driveItem are unaffected: one container failing must
    # not blank the others.
    assert states["created_by"] == M.PRESENT
    assert states["sharing_scope"] == M.PRESENT


def test_a_library_that_simply_sets_nothing_is_NOT_CONFIGURED():
    """The other direction, and the one that makes the first meaningful: a successful read of an
    unconfigured library is an ANSWER, and must not be reported as a failure to read."""
    meta = M.normalize(_item(), list_item=_list_item({}, content_type=None),
                       site_id="c,1,1", site_name="S", library_name="L")
    states = M.availability(meta)
    assert states["content_type"] == M.NOT_CONFIGURED
    assert states["managed_columns"] == M.NOT_CONFIGURED
    assert states["retention_label"] == M.NOT_CONFIGURED


def test_the_wider_driveItem_select_fails_independently_of_the_expansion():
    """A tenant can answer the base select perfectly and refuse the wider one. One container for
    both would have to give a single answer to a question with two."""
    meta = M.normalize(_item(), list_item=_list_item({"Records Category": "Active"}),
                       rich=M.Container.missing("the wider $select was refused"))
    states = M.availability(meta)
    assert states["retention_label"] == M.UNAVAILABLE
    assert states["managed_columns"] == M.PRESENT, "the expansion worked and was thrown away"
    assert states["created_by"] == M.PRESENT


def test_sensitivity_labels_are_reported_as_NOT_REQUESTED_rather_than_absent():
    """ACP walks v1.0 driveItems and Graph exposes sensitivityLabel on beta. An estate whose
    labels have never been asked for must not read as an estate with no labels — which is exactly
    what an empty column invites a reader to conclude."""
    meta = M.normalize(_item(), list_item=_list_item({}))
    f = meta["fields"]["sensitivity_label"]
    assert f["state"] == M.UNAVAILABLE
    assert "not requested" in f["reason"] and "beta" in f["reason"]


def test_onedrive_has_no_site_and_says_so_as_NOT_APPLICABLE():
    """Not `unavailable`: there is nothing to fix. A permanent task for a field that cannot exist
    is noise that trains an operator to ignore the column."""
    meta = M.normalize(_item(), list_item=M.Container.missing("no backing list"))
    states = M.availability(meta)
    assert states["site_id"] == M.NOT_APPLICABLE
    assert states["library_name"] == M.NOT_APPLICABLE


def test_permissions_are_off_by_default_and_say_how_to_turn_them_on():
    """One Graph call per document is the difference between a scan and an outage across a
    30-site estate, so this is opt-in — and an operator who needs external-sharing evidence has
    to be able to find the switch from the report itself."""
    meta = M.normalize(_item(), list_item=_list_item({}))
    f = meta["fields"]["permissions"]
    assert f["state"] == M.UNAVAILABLE and "ACP_SP_PERMISSIONS=1" in f["reason"]


# ── pages are not documents ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,ct", [("home.aspx", None), ("x.docx", "Site Page"),
                                     ("y.docx", "Wiki Page")])
def test_a_page_is_identified_as_a_page(name, ct):
    """A SharePoint page is authored in SharePoint and has no downloadable source document, so
    assessing one as a document produces a WCAG finding about a file that does not exist in the
    form the report claims. Two signals because either alone is wrong somewhere: the content type
    is authoritative until a tenant renames it, and `.aspx` catches the tenant that did."""
    meta = M.normalize(_item(name=name), list_item=_list_item({}, content_type=ct))
    assert M.values(meta)["item_kind"] == "page"


def test_an_ordinary_document_is_not_mistaken_for_a_page():
    meta = M.normalize(_item(), list_item=_list_item({}))
    assert M.values(meta)["item_kind"] == "document"


# ── the shapes downstream reads ──────────────────────────────────────────────────────────────

def test_values_omits_anything_not_present_rather_than_setting_it_None():
    """A None in a value map is indistinguishable from a tenant that set nothing — the same
    collapse this module exists to stop, reintroduced by the convenience accessor."""
    meta = M.normalize(_item(), list_item=M.Container.missing("refused"))
    v = M.values(meta)
    assert "content_type" not in v
    assert "created_by" in v


def test_the_availability_summary_counts_states_across_an_estate():
    """The exit gate is a claim about a POPULATION: one file with no retention label proves
    nothing, and 6,000 files where the field is `unavailable` on every one is a scope problem
    wearing the costume of an unlabelled estate."""
    metas = [M.normalize(_item(), list_item=_list_item({"A": "1"})),
             M.normalize(_item(), list_item=M.Container.missing("refused"))]
    table = M.summarize_availability(metas)
    assert table["managed_columns"][M.PRESENT] == 1
    assert table["managed_columns"][M.UNAVAILABLE] == 1
    assert table["content_type"][M.PRESENT] == 1
    assert table["content_type"][M.UNAVAILABLE] == 1


def test_the_expansion_and_permissions_switches_read_the_environment(monkeypatch):
    monkeypatch.delenv("ACP_SP_LIST_FIELDS", raising=False)
    monkeypatch.delenv("ACP_SP_PERMISSIONS", raising=False)
    assert M.expand_enabled() is True and M.permissions_enabled() is False
    monkeypatch.setenv("ACP_SP_LIST_FIELDS", "0")
    monkeypatch.setenv("ACP_SP_PERMISSIONS", "1")
    assert M.expand_enabled() is False and M.permissions_enabled() is True
