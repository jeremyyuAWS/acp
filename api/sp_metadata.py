"""SharePoint-native metadata: what a document carries in SharePoint's own terms, normalized.

Google Drive gives a file a name, a size, an owner and a folder. SharePoint gives it a CONTENT
TYPE, the managed columns that content type defines, a retention label, a sensitivity label, a
version, a check-out state, and a place in a site and a library. That is the difference between
"we found a spreadsheet" and "we found a Research Data Management Plan under a 7-year retention
label in the Regulatory library" — and it is what makes a lifecycle rule an operator can defend.

THE ONE CONTRACT THIS MODULE EXISTS FOR: a field is never reported as "the tenant does not set
this" when the truth is "we could not read it".

Those two look identical downstream — both render as an empty cell, both make a rule that keys on
the field match nothing — and they call for opposite responses. "Not configured" is a fact about
the customer's SharePoint and an answer: no retention labels are applied, stop looking. "Unavailable"
is a fact about ACP and a task: the scope is missing, the expansion was refused, this Graph version
does not offer the field. Collapsing them produces the worst outcome available here — an operator
concludes their estate has no sensitivity labels when in fact nobody ever asked Graph for them.

So every field resolves to one of four states, and `not_configured` is only ever claimable when
the CONTAINER that would have carried the value was read successfully:

    present         a value was read; `value` holds it
    not_configured  the container was read and the field was absent or empty  → about the TENANT
    unavailable     the container could not be read, with `reason`            → about ACP
    not_applicable  the field cannot exist for this item — a OneDrive file has no site, a
                    document library item has no page identity                → about the ITEM

`resolve()` is the only way to build a field, and it takes the container's own read outcome, so a
caller cannot accidentally mint `not_configured` out of a container it never obtained. That is the
whole safety property; the rest of this module is field mapping.

VERIFICATION STATUS, said plainly rather than implied. The Graph shapes below are drawn from the
documented v1.0 surface, and the ones marked UNVERIFIED have not been confirmed against a live
tenant — this repo has been bitten before by a plausible shape that was reasoned about instead of
run (see CLAUDE.md on the .pdf ground-truth corpus). `scripts/sp_metadata_probe.py` is the
instrument that settles each of them against a real tenant and prints the evidence table the
Phase 2 exit gate asks for. Until that has been run somewhere, treat an `unavailable` from this
module as "not yet proven either way", not as "Graph does not have it".
"""
from __future__ import annotations

import os

PRESENT = "present"
NOT_CONFIGURED = "not_configured"
UNAVAILABLE = "unavailable"
NOT_APPLICABLE = "not_applicable"


class Container:
    """The read outcome of one Graph payload several fields are sourced from.

    Fields do not each make their own Graph call; they are read out of a shared blob — the
    driveItem, its expanded listItem `fields` bag, its permissions collection. Whether that blob
    arrived is the fact that decides `not_configured` versus `unavailable` for every field in it,
    so it is modelled once, here, rather than re-derived per field from whether a lookup returned
    None (which cannot tell the two apart — that is the bug).
    """

    __slots__ = ("data", "reason")

    def __init__(self, data: dict | None, reason: str | None = None):
        #: The payload, or None when it could not be read. An EMPTY dict is a successful read of
        #: a container with nothing in it — a real answer, and not the same as None.
        self.data = data
        #: Why it could not be read. Required when data is None; ignored otherwise.
        self.reason = reason

    @property
    def ok(self) -> bool:
        return self.data is not None

    @classmethod
    def missing(cls, reason: str) -> "Container":
        return cls(None, reason)

    def get(self, key, default=None):
        return (self.data or {}).get(key, default)


def resolve(container: Container, value, *, applicable: bool = True) -> dict:
    """One field's state, derived from its container's read outcome and the value found in it.

    The ordering is the contract. `not_applicable` first (a OneDrive file has no site however the
    read went), then `unavailable` (we never got the container, so we know nothing about the
    tenant), and only then may an absent value be called `not_configured`.
    """
    if not applicable:
        return {"value": None, "state": NOT_APPLICABLE, "reason": None}
    if not container.ok:
        return {"value": None, "state": UNAVAILABLE, "reason": container.reason}
    if value is None or value == "" or value == [] or value == {}:
        return {"value": None, "state": NOT_CONFIGURED, "reason": None}
    return {"value": value, "state": PRESENT, "reason": None}


# ── which columns are the CUSTOMER's, and which are SharePoint's plumbing ─────────────────────
#
# A listItem `fields` bag mixes the managed columns an information architect defined with a large
# set of system columns SharePoint maintains itself. Reporting the plumbing as "managed metadata"
# would bury the handful of columns a governance rule is actually about under thirty rows of
# GUIDs and lookup ids, and an operator scanning for "Records Category" would not find it.
#
# Filtered by NAME rather than by an allow-list of expected columns, because the whole point of
# managed metadata is that ACP cannot know in advance what a tenant calls its columns.
_SYSTEM_FIELD_NAMES = frozenset({
    "id", "ContentType", "Created", "Modified", "AuthorLookupId", "EditorLookupId",
    "_ComplianceFlags", "_ComplianceTag", "_ComplianceTagWrittenTime",
    "_ComplianceTagUserId", "_IsRecord", "_CommentCount", "_LikeCount",
    "_UIVersionString", "_DisplayName", "_ExtendedDescription", "_ModerationStatus",
    "AppAuthorLookupId", "AppEditorLookupId", "ContentTypeId", "FileLeafRef",
    "FileSizeDisplay", "FolderChildCount", "ItemChildCount", "LinkFilename",
    "LinkFilenameNoMenu", "LinkTitle", "LinkTitleNoMenu", "MediaServiceImageTags",
    "ParentVersionStringLookupId", "ParentLeafNameLookupId", "SharedWithUsers",
    "CheckoutUserLookupId", "Title", "Edit", "DocIcon", "ServerRedirectedEmbedUrl",
})


def managed_columns(fields: dict) -> dict:
    """The customer-defined columns in a listItem `fields` bag, in Graph's own order.

    Drops SharePoint's system columns (above) and every OData annotation — `@odata.etag` and the
    `FooLookupId` / `FooStringId` shadows Graph emits beside a person or lookup column, which
    carry the same fact as an id nobody can read. The visible column is kept; its shadow is not.
    """
    out = {}
    for k, v in (fields or {}).items():
        if k.startswith("@") or k in _SYSTEM_FIELD_NAMES:
            continue
        if k.endswith("LookupId") or k.endswith("StringId"):
            # The readable sibling ("ManagerLookupId" → "Manager") is kept when Graph sent it;
            # keeping the id as well would double-count the column in every export.
            continue
        if v is None or v == "" or v == []:
            continue
        out[k] = v
    return out


def _person(node: dict | None) -> str | None:
    """A Graph identitySet's human name. displayName first, email as the fallback — an audit
    record naming "a.b@contoso.com" is worse than one naming "Alice Brown" and better than one
    naming nobody."""
    user = (node or {}).get("user") or {}
    return user.get("displayName") or user.get("email") or None


#: How a collaborator count was arrived at. The count means different things under each, and a
#: rule that cannot tell them apart would read "1 collaborator" off a file nobody has looked at in
#: five years the same way it reads it off a file shared with the whole organisation.
BASIS_PERMISSIONS = "permissions"
BASIS_AUTHORSHIP = "authorship"


def _authorship_people(di: "Container") -> set[str]:
    """Everyone the LISTING PAGE itself names on an item: its creator and its last editor.

    Free — `createdBy` and `lastModifiedBy` are in the walk's base `$select`, so this costs
    nothing on any tier, including the bare one a refusing tenant falls back to. It is also a
    FLOOR and never a total: a document twelve people edited names exactly two of them here,
    because Graph's driveItem records the first and the most recent and nothing between.

    That is why `collaborator_basis` exists beside the count. "One person made this and nobody
    else ever touched it" is a sound archival signal and is exactly what a floor of 1 says; "this
    has two collaborators" is a claim this data cannot support, and a caller that reads the count
    without the basis will make it.
    """
    return {p for p in (_person(di.get("createdBy")), _person(di.get("lastModifiedBy"))) if p}


def _permission_people(perms: list | None) -> set[str]:
    """Distinct identities with access, from an item's permissions collection.

    A Graph permission grants to `grantedToV2` (one identity) or `grantedToIdentitiesV2` (several,
    for a sharing link), and the older singular `grantedTo` is still what some tenants answer
    with. All three are read: counting only the documented-current shape would report a widely
    shared file as having nobody on it, which is the wrong answer in the direction that archives
    a live document.

    A LINK WITH NO IDENTITIES IS NOT A PERSON and is not counted here — an anonymous or
    organisation-wide link grants access to people this collection cannot name. `sharing_scope`
    is the field that says so, and it is already read for free; conflating the two would turn
    "shared with everyone" into "nobody has access", which is precisely backwards.
    """
    out: set[str] = set()
    for perm in perms or []:
        if not isinstance(perm, dict):
            continue
        nodes = [perm.get("grantedToV2"), perm.get("grantedTo")]
        nodes += list(perm.get("grantedToIdentitiesV2") or [])
        nodes += list(perm.get("grantedToIdentities") or [])
        for node in nodes:
            who = _person(node)
            if who:
                out.add(who)
    return out


def _is_page(item: dict, content_type: str | None) -> bool:
    """A SharePoint PAGE, not a document. Both are list items in a library and both come back
    from the same walk, but a page is authored in SharePoint and has no downloadable source
    document to assess — treating one as a document produces a WCAG finding about a file that
    does not exist in the form the report claims.

    Two independent signals because either alone is wrong somewhere: the content type is
    authoritative when the tenant uses the stock names, and `.aspx` catches a tenant that renamed
    them (as tenants do).
    """
    name = (item.get("name") or "").lower()
    ct = (content_type or "").strip().lower()
    return name.endswith(".aspx") or ct in {"site page", "wiki page", "web part page", "page"}


def normalize(item: dict, *, list_item: Container, drive_item: Container | None = None,
              rich: Container | None = None, permissions: Container | None = None,
              site_id: str | None = None, site_name: str | None = None,
              library_name: str | None = None) -> dict:
    """One document's SharePoint-native metadata, normalized, with per-field availability.

    `item` is the raw Graph driveItem. `list_item` is its expanded `listItem` — the container for
    every column-sourced field, and the one that is routinely absent (a personal OneDrive has no
    backing list at all, and a tenant can refuse the expansion). `drive_item` defaults to a
    successful container wrapping `item` itself, which is the ordinary case: the walk got the
    driveItem or it would not be here.

    `rich` is a SEPARATE container for the driveItem properties that are not in the walk's base
    `$select` — today the retention label. They need their own container because they fail
    independently: a tenant can answer the base select perfectly and reject the wider one, at
    which point `createdBy` is `present` and `retention_label` must be `unavailable`, not
    `not_configured`. One container for both would have to pick a single answer for a question
    with two different ones. Defaults to `drive_item`, for a caller that got everything at once.

    Returns {"fields": {name: {"value","state","reason"}}, ...} — never a bare value map, because
    a bare value map is exactly the shape that cannot tell "unset" from "unread".
    """
    di = drive_item if drive_item is not None else Container(item or {})
    ri = rich if rich is not None else di
    li = list_item
    perms = permissions if permissions is not None else Container.missing(
        "permissions not requested — one Graph call per item; set ACP_SP_PERMISSIONS=1 to read them")

    lf = li.get("fields") or {} if li.ok else {}
    # `listItem.contentType.name` is the v1.0 shape; `fields.ContentType` is the column every list
    # item has carried since CSOM and is what the pre-Phase-2 code read. Both are tried because a
    # tenant that answers one and not the other is exactly the case the probe exists to find.
    ct = ((li.get("contentType") or {}).get("name") if li.ok else None) or lf.get("ContentType")
    ct = str(ct) if ct else None

    on_a_site = bool(site_id)
    is_page = _is_page(item or {}, ct)

    fields = {
        # ── where it lives (Phase 1 gave the walk this; here it becomes a first-class field) ──
        "site_id": resolve(Container({} if on_a_site else None,
                                     "OneDrive has no SharePoint site"),
                           site_id, applicable=on_a_site),
        "site_name": resolve(Container({} if on_a_site else None,
                                       "OneDrive has no SharePoint site"),
                             site_name, applicable=on_a_site),
        "library_name": resolve(Container({} if on_a_site else None,
                                          "OneDrive has no document library"),
                                library_name, applicable=on_a_site),

        # ── the content type and the columns it defines ──────────────────────────────────────
        "content_type": resolve(li, ct),
        "managed_columns": resolve(li, managed_columns(lf)),

        # ── governance labels ────────────────────────────────────────────────────────────────
        # UNVERIFIED SHAPE. driveItem.retentionLabel is documented on v1.0; whether a tenant
        # answers it under the wider $select is exactly what the probe settles — hence the `rich`
        # container, which is missing when that select was refused and the walk fell back.
        "retention_label": resolve(ri, ((ri.get("retentionLabel") or {}) or {}).get("name")),
        # NOT REQUESTED, and said so rather than guessed at. Sensitivity labels are on driveItem
        # in Graph BETA and reachable on v1.0 only through the extractSensitivityLabels action —
        # neither is the endpoint this walk uses, so asking for the property in a v1.0 $select
        # would 400 the whole listing for a field that would not have arrived anyway.
        #
        # Reported `unavailable` with that reason on every item, permanently, until the beta
        # surface or the action is wired. That is the honest state: an estate whose sensitivity
        # labels ACP has never asked for must not read as an estate with no sensitivity labels,
        # which is precisely the conclusion an empty column invites.
        "sensitivity_label": resolve(
            Container(item, None) if "sensitivityLabel" in (item or {}) else Container.missing(
                "not requested — Graph exposes driveItem.sensitivityLabel on beta only, and on "
                "v1.0 through the extractSensitivityLabels action; ACP walks v1.0 driveItems"),
            ((item or {}).get("sensitivityLabel") or {}).get("displayName")),
        # _ComplianceTag is the record-declaration column behind a retention label. Read from the
        # LIST container, so it carries that container's availability, not the driveItem's.
        "compliance_tag": resolve(li, lf.get("_ComplianceTag")),
        "is_record": resolve(li, bool(lf.get("_IsRecord")) if "_IsRecord" in lf else None),

        # ── people ───────────────────────────────────────────────────────────────────────────
        "created_by": resolve(di, _person(di.get("createdBy"))),
        "modified_by": resolve(di, _person(di.get("lastModifiedBy"))),

        # ── sharing ──────────────────────────────────────────────────────────────────────────
        # `shared.scope` is "anonymous" | "organization" | "users" and comes free on the walk's
        # own $select. The full permissions collection does not: it is one Graph call per item.
        "sharing_scope": resolve(di, ((di.get("shared") or {}) or {}).get("scope")),
        "permissions": resolve(perms, perms.get("value") if perms.ok else None),

        # ── who is still working on this ─────────────────────────────────────────────────────
        #
        # SMART ARCHIVAL's input. "Archive anything older than seven years" is a rule that
        # eventually archives something a team is still using, and the SOW asks for the check
        # that stops it: before flagging, look at whether anybody is actually involved.
        #
        # ALWAYS ANSWERABLE, at two very different precisions, and the count alone cannot tell
        # them apart — so it never travels without `collaborator_basis`:
        #
        #   permissions — everyone with access, from the item's permissions collection. Accurate,
        #                 and one Graph call per document (ACP_SP_PERMISSIONS, budgeted).
        #   authorship  — the creator and the last editor, off the listing page. Free, and a
        #                 FLOOR: a document a dozen people edited names two of them.
        #
        # A floor of 1 is the useful signal and is sound: one person made it, nobody else ever
        # touched it, nothing else is known. A floor of 2 says almost nothing. Reporting either
        # as a total is the overstatement this pair of fields exists to prevent — and a rule
        # written as "collaborators <= 1" is correct under both bases, which is why the floor is
        # worth shipping rather than withholding until permissions are on.
        "collaborator_count": resolve(
            di, len(_permission_people(perms.get("value")) if perms.ok
                    else _authorship_people(di))),
        "collaborator_basis": resolve(
            di, BASIS_PERMISSIONS if perms.ok else BASIS_AUTHORSHIP),

        # ── version and lock state ───────────────────────────────────────────────────────────
        "version": resolve(li, lf.get("_UIVersionString")),
        # A checked-out file is one a remediation write-back would silently fail against, so this
        # is not decoration — it is the precondition Phase 5 has to check.
        "checked_out_by": resolve(li, lf.get("CheckoutUser") or lf.get("CheckoutUserLookupId")),

        # ── what KIND of thing this is ───────────────────────────────────────────────────────
        # Derived, not read, so it has no container of its own: it is a fact about the item that
        # is always answerable once the item exists.
        "item_kind": {"value": "page" if is_page else "document", "state": PRESENT, "reason": None},
    }
    return {"fields": fields}


def values(meta: dict) -> dict:
    """Just the present values, flattened — for a rule evaluator or an export column.

    A field that is not `present` is ABSENT from this map rather than None, so a caller cannot
    read a missing key as "the tenant set nothing". Anything that needs to tell the states apart
    reads `meta["fields"]` directly; this is the convenience for the callers that genuinely only
    want the values (`disposition.matches` treats a missing field as no-match either way).
    """
    return {k: f["value"] for k, f in (meta.get("fields") or {}).items()
            if f.get("state") == PRESENT}


def availability(meta: dict) -> dict:
    """{field: state} — the audit-evidence shape. This is what makes an empty cell in an export
    interpretable: the reader can see whether ACP asked and got nothing, or never asked."""
    return {k: f.get("state") for k, f in (meta.get("fields") or {}).items()}


def summarize_availability(metas: list[dict]) -> dict:
    """Per-field state counts across an estate — the Phase 2 exit gate's evidence table.

    "Every supported field is proven against the tenant, with unavailable distinguished from not
    configured" is a claim about a POPULATION, not about one document: one file with no retention
    label proves nothing, and 6,000 files where the field is `unavailable` on every single one is
    a scope problem wearing the costume of an unlabelled estate. This aggregates so the difference
    is legible at a glance.
    """
    out: dict[str, dict[str, int]] = {}
    for m in metas:
        for name, f in (m.get("fields") or {}).items():
            bucket = out.setdefault(name, {PRESENT: 0, NOT_CONFIGURED: 0,
                                           UNAVAILABLE: 0, NOT_APPLICABLE: 0})
            state = f.get("state")
            if state in bucket:
                bucket[state] += 1
    return out


def expand_enabled() -> bool:
    """Whether the walk asks Graph to expand `listItem($expand=fields)` alongside each page.

    ON by default: it is the only shape that reads managed columns without one Graph call per
    document, and the fallback below means a tenant that refuses it loses the metadata, never the
    listing. ACP_SP_LIST_FIELDS=0 turns it off for an operator who needs the leanest possible
    walk, matching ACP_SP_ENUMERATE's precedent.
    """
    return os.environ.get("ACP_SP_LIST_FIELDS", "1").strip() != "0"


def permissions_enabled() -> bool:
    """Whether to read each item's permissions collection. OFF by default: it is one Graph call
    per document on top of the walk, which against a 30-site estate is the difference between a
    scan and an outage. An operator who needs external-sharing evidence turns it on knowingly."""
    return os.environ.get("ACP_SP_PERMISSIONS", "0").strip() == "1"
