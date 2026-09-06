"""Deriving supersession evidence from what a scan already recorded — pure, and mostly refusals.

WHERE THE EVIDENCE COMES FROM. Nothing here asks a tenant anything new. Every signal is read off
`scan_inventory` rows the discovery walk already wrote — the tenant's own managed columns
(`sp_metadata`), SharePoint's moderation state, the stable Graph item id — or off the policy's
administrator-confirmed mappings. That is deliberate: an evidence type that needed a new read
would also need a new permission, and a feature that asks for more access in order to move files
unattended is a harder thing to justify than one that reads what is already there.

THE DISQUALIFIED SIGNAL, stated once so it is not re-litigated per function: FILENAMES. Nothing
in this module compares names, stems, or version-looking suffixes, and `family_field` explicitly
refuses to be pointed at a name column (`_FAMILY_FIELD_REFUSED`). `Clinical-Access-v2.docx` and
`Clinical-Access-v3.docx` are the motivating example in both directions — they are usually a
version pair, and when they are not, they are two unrelated documents in two unrelated libraries
and one of them is about to be moved out from under its owner.

WHAT A CANDIDATE ROW LOOKS LIKE HERE. A `scan_inventory` dict: `file`, `path`, `drive_file_id`
(the Graph item id), `drive_id`, `site_id`, `content_type`, `sp_version`, `source_modified`, and
`sp_metadata` — a JSON blob carrying the tenant's own managed columns plus the per-field
availability map. Siblings are the other rows from the same scan.

AVAILABILITY IS NOT ABSENCE, and this module inherits that from sp_metadata rather than
re-deciding it. A managed column that Graph refused to hand over reads as missing, and missing
here means NO EVIDENCE — which is the safe direction, because no evidence means recommendation
only. The unsafe direction would be treating an unreadable column as a link; nothing does.
"""
from __future__ import annotations

import json

import archive_autofire as af

#: Managed-column names that assert "this newer item replaces that older one" outright. Matched
#: case- and separator-insensitively because a tenant's column can be `RetentionOf`,
#: `retention_of` or `Retention Of` and all three mean the same thing to the records manager who
#: created it.
_LINK_KEYS = ("retentionof", "supersedes", "supersedesdocument", "supersededdocument")

#: Managed-column names that assert a replacement relationship SharePoint itself tracks as part
#: of publication. Kept apart from `_LINK_KEYS` because this evidence type additionally requires
#: the replacement to be approved — a link to an unapproved draft is a link to a document nobody
#: has published, and archiving the live version in favour of it is the wrong direction.
_VERSION_KEYS = ("replaces", "replacesdocument", "predecessorid", "previousversionid")

#: SharePoint's moderation status column, and the value that means approved. `_ModerationStatus`
#: is 0 for Approved; a library with no content approval returns nothing at all, which is why an
#: absent value is NOT read as approved — see `_approved`.
_MODERATION_KEYS = ("_moderationstatus", "moderationstatus", "odatamoderationstatus")
_APPROVED_VALUES = {"0", "approved", "published"}

#: Columns a document family may be keyed on. All three are tenant-authored groupings that
#: survive a rename, which is the property that makes them usable and a filename unusable.
_FAMILY_FIELDS = ("content_type", "parent_folder", "site_id")

#: Refused explicitly rather than by omission, because "family_field": "file" is the exact
#: misconfiguration this feature must not permit, and a silent fallback to "no evidence" would
#: read to an administrator as "the rule is not matching anything" rather than "that is not
#: allowed".
_FAMILY_FIELD_REFUSED = {
    "file": "a filename", "path": "a file path", "name": "a filename",
    "checksum": "a content hash, which changes on every edit",
}


def _norm(key: str) -> str:
    return "".join(ch for ch in str(key or "").lower() if ch.isalnum())


def managed(row: dict) -> dict:
    """The tenant's own managed columns for a row, normalized by key. `{}` when unreadable.

    An unparseable `sp_metadata` blob yields no columns rather than raising: the row still has a
    path and an id, and the correct outcome for a document whose metadata cannot be read is that
    it produces no evidence, not that the whole evaluation fails.
    """
    blob = row.get("sp_metadata")
    if isinstance(blob, str):
        try:
            blob = json.loads(blob or "{}")
        except (TypeError, ValueError):
            return {}
    if not isinstance(blob, dict):
        return {}
    # sp_metadata.values() is `{column: value}` with an availability map alongside; a plain dict
    # of columns is accepted too so a caller can pass a fields bag directly.
    columns = blob.get("values") if isinstance(blob.get("values"), dict) else blob
    return {_norm(k): v for k, v in columns.items() if not isinstance(v, (dict, list))}


def _text(value) -> str:
    return str(value if value is not None else "").strip()


def _approved(row: dict) -> bool:
    """Is this item approved/published in its library?

    Absence is NOT approval. A library without content approval simply has no moderation column,
    and reading that as approved would let every item in every ordinary library satisfy the one
    condition that distinguishes `sp_version` evidence from a bare metadata link.
    """
    cols = managed(row)
    for key in _MODERATION_KEYS:
        if key in cols:
            return _text(cols[key]).lower() in _APPROVED_VALUES
    return False


def _identifies(value: str, candidate: dict) -> bool:
    """Does this managed-column value point at `candidate`?

    Only a STABLE identifier counts: the Graph item id, or the full source path, which is stable
    enough to be a durable reference a records manager can type but is checked exactly rather
    than fuzzily. A value that merely contains the file's name matches nothing here.
    """
    target = _text(value)
    if not target:
        return False
    item_id = _text(candidate.get("drive_file_id"))
    path = _text(candidate.get("path"))
    if item_id and target == item_id:
        return True
    # A managed lookup often arrives as a compound value ("12;#<guid>") — split on Graph's and
    # SharePoint's own separators before comparing, never substring-match.
    for part in target.replace("#", ";").replace(",", ";").split(";"):
        part = part.strip()
        if item_id and part == item_id:
            return True
        if path and part.rstrip("/") == path.rstrip("/"):
            return True
    return False


def _record(kind: str, candidate: dict, replacement: dict, detail: str, **extra) -> dict:
    """One evidence record in archive_autofire's shape, with the stable identifiers filled in."""
    out = {
        "type": kind,
        "source_item_id": _text(candidate.get("drive_file_id")),
        "replacement_item_id": _text(replacement.get("drive_file_id")),
        "replacement_drive_id": _text(replacement.get("drive_id")) or None,
        "replacement_path": _text(replacement.get("path")) or _text(replacement.get("file")),
        "replacement_modified": _text(replacement.get("source_modified")),
        "source_modified": _text(candidate.get("source_modified")),
        "detail": detail,
    }
    out.update(extra)
    return out


def from_metadata_link(candidate: dict, siblings: list[dict]) -> list[dict]:
    """Evidence type 1 — the replacement's own metadata names this document.

    The strongest of the four, because the assertion is the tenant's rather than ACP's: somebody
    filled in a `Supersedes` or `RetentionOf` column on the newer document, on purpose.
    """
    out = []
    for sibling in siblings:
        if _text(sibling.get("drive_file_id")) == _text(candidate.get("drive_file_id")):
            continue
        cols = managed(sibling)
        for key in _LINK_KEYS:
            if key in cols and _identifies(cols[key], candidate):
                out.append(_record(
                    af.METADATA_LINK, candidate, sibling,
                    f"{sibling.get('file') or sibling.get('path')} carries a '{key}' value naming "
                    f"this document."))
                break
    return out


def from_sharepoint_version(candidate: dict, siblings: list[dict]) -> list[dict]:
    """Evidence type 3 — SharePoint's version/publication metadata names an APPROVED replacement.

    Two conditions, and the second is the one that earns this its own type: the link must exist
    AND the replacement must be approved in its library. An unapproved draft that claims to
    replace a published document is a work in progress, and retiring the published document for
    it would take the live version away from readers in favour of something nobody signed off.
    """
    out = []
    for sibling in siblings:
        if _text(sibling.get("drive_file_id")) == _text(candidate.get("drive_file_id")):
            continue
        cols = managed(sibling)
        linked = any(key in cols and _identifies(cols[key], candidate) for key in _VERSION_KEYS)
        if not linked:
            continue
        out.append(_record(
            af.SP_VERSION, candidate, sibling,
            f"SharePoint records {sibling.get('file') or sibling.get('path')} as replacing this "
            f"document" + (" and it is approved in its library." if _approved(sibling)
                           else ", but it is not approved in its library."),
            replacement_approved=_approved(sibling)))
    return out


def family_config(action_config) -> dict:
    """The `auto_archive` block of a lifecycle rule's action_config, or `{}`.

    Returns `{"family_field", "version_field", "problem"}`. `problem` is non-empty when the
    configuration exists but may not be used — a refusal an administrator can read, rather than a
    rule that silently matches nothing.
    """
    cfg = action_config
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg or "{}")
        except (TypeError, ValueError):
            return {}
    if not isinstance(cfg, dict):
        return {}
    block = cfg.get("auto_archive")
    if not isinstance(block, dict):
        return {}
    field = _text(block.get("family_field"))
    version = _text(block.get("version_field")) or "sp_version"
    if field in _FAMILY_FIELD_REFUSED:
        return {"family_field": "", "version_field": version,
                "problem": (f"A document family cannot be keyed on {_FAMILY_FIELD_REFUSED[field]}. "
                            f"Choose one of: {', '.join(_FAMILY_FIELDS)}.")}
    if field not in _FAMILY_FIELDS:
        return {"family_field": "", "version_field": version,
                "problem": (f"'{field or 'not set'}' is not a document-family column. Choose one "
                            f"of: {', '.join(_FAMILY_FIELDS)}.")}
    return {"family_field": field, "version_field": version, "problem": ""}


def from_rule_family(candidate: dict, siblings: list[dict], action_config) -> list[dict]:
    """Evidence type 2 — a configured rule groups these into one family and orders the versions.

    The weakest of the four, and treated as such: the grouping is ACP's configuration rather than
    the tenant's assertion, so archive_autofire.evidence_problem additionally requires the record
    to show a STRICTLY newer version of the same family before it will accept it. Anything whose
    versions cannot be ordered produces no evidence at all — see `af._strictly_newer`, which
    refuses to guess rather than treating "unorderable" as "newer".
    """
    cfg = family_config(action_config)
    field = cfg.get("family_field")
    if not field:
        return []
    version_field = cfg.get("version_field") or "sp_version"
    family = _text(candidate.get(field))
    if not family:
        return []
    out = []
    for sibling in siblings:
        if _text(sibling.get("drive_file_id")) == _text(candidate.get("drive_file_id")):
            continue
        if _text(sibling.get(field)) != family:
            continue
        record = _record(
            af.RULE_FAMILY, candidate, sibling,
            f"Both documents are in the '{family}' family ({field.replace('_', ' ')}), and "
            f"{sibling.get('file') or sibling.get('path')} is a newer version of it.",
            family=family,
            source_version=_text(candidate.get(version_field)),
            replacement_version=_text(sibling.get(version_field)))
        # Filtered here rather than left for the caller: an unordered pair is not weak evidence,
        # it is no evidence, and returning it would put a "rejected" line in front of a reader
        # for every unrelated document that happens to share a content type.
        if not af.evidence_problem(record):
            out.append(record)
    return out


def from_confirmed_mapping(candidate: dict, siblings: list[dict], policy: dict) -> list[dict]:
    """Evidence type 4 — an administrator already confirmed this document-family mapping.

    The mapping names both item ids, so this does not search: it looks up the candidate and, if a
    mapping exists, finds the named replacement among the siblings. A mapping whose replacement is
    not in this scan produces nothing — the replacement has to be a document ACP can actually
    check, not an id somebody typed.
    """
    item_id = _text(candidate.get("drive_file_id"))
    if not item_id:
        return []
    by_id = {_text(s.get("drive_file_id")): s for s in siblings if _text(s.get("drive_file_id"))}
    out = []
    for mapping in af.normalize_confirmed_families(policy.get("confirmed_families")):
        if mapping["source_item_id"] != item_id:
            continue
        replacement = by_id.get(mapping["replacement_item_id"])
        if replacement is None:
            continue
        out.append(_record(
            af.ADMIN_MAPPING, candidate, replacement,
            f"{mapping['confirmed_by']} confirmed that {replacement.get('file') or replacement.get('path')} "
            f"replaces this document in the '{mapping['family']}' family.",
            family=mapping["family"], confirmed_by=mapping["confirmed_by"],
            confirmed_at=mapping.get("confirmed_at") or ""))
    return out


def derive(candidate: dict, siblings: list[dict], *, policy: dict,
           action_config=None) -> list[dict]:
    """Every approved signal, in one call, deduplicated by (type, replacement).

    Order is stable — the order EVIDENCE_TYPES declares — so two runs over the same estate
    produce the same evidence list and therefore the same audit record, which is what makes a
    stored decision re-checkable rather than merely re-derivable.
    """
    found = (from_metadata_link(candidate, siblings)
             + from_rule_family(candidate, siblings, action_config)
             + from_sharepoint_version(candidate, siblings)
             + from_confirmed_mapping(candidate, siblings, policy))
    rank = {kind: i for i, kind in enumerate(af.EVIDENCE_TYPES)}
    seen, out = set(), []
    for record in sorted(found, key=lambda r: (rank.get(r["type"], 99), r["replacement_item_id"])):
        key = (record["type"], record["replacement_item_id"])
        if key in seen:
            continue
        seen.add(key)
        out.append(record)
    return out


def summarize(evidence: list[dict]) -> str:
    """One line naming what was proven and by which signals — for an audit row and a UI subtitle.

    Says "no supersession evidence" explicitly rather than returning an empty string, because an
    empty subtitle beside a recommendation reads as "nothing to say" rather than as the reason
    the document is a recommendation.
    """
    if not evidence:
        return "No supersession evidence."
    kinds = sorted({e.get("type") for e in evidence})
    names = ", ".join(af.EVIDENCE_LABELS.get(k, str(k)) for k in kinds)
    targets = sorted({e.get("replacement_path") or e.get("replacement_item_id") for e in evidence})
    return f"{names}. Replacement: {'; '.join(t for t in targets if t)}."
