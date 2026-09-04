"""Disposition policy matching (ADR 0003, Phase 3): pure validation + evaluation
logic, no DB access (api/store.py owns persistence, matching this module's
seam with api/documents.py in Phase 1).

PREVIEW ONLY in this phase -- matches() only tells you which documents a
policy WOULD select. It never touches a file. The real move/rename/archive/
delete execution path is a separate, later decision (ADR 0003's own note:
"Disposition that deletes/moves customer files is irreversible — gate behind
requires_approval + the immutable disposition_audit, and never act without an
explicit policy the admin enabled").

Conditions are evaluated in Python over already-fetched document rows, not
interpolated into SQL — this sidesteps building (and having to audit) a
dynamic-SQL predicate compiler for something admin-authored and potentially
complex, at the cost of fetching the full documents table per preview. Fine
at today's scale; revisit if/when that table gets large enough to matter.
"""
from __future__ import annotations
import json
import posixpath
from datetime import datetime, timezone

ACTIONS = {"leave", "archive", "rename", "move", "delete", "tag"}

#: Actions that CHANGE THE SOURCE FILE. Exactly the set execute_action reaches Drive for —
#: `leave` records a decision and `tag` writes metadata, neither touches the document.
#:
#: Named here rather than in a route because it is a fact about what an action DOES, and a second
#: copy in the API layer would drift from this one silently: a new mutating action added to
#: ACTIONS would keep the old approval requirements until somebody remembered the other list.
SOURCE_MUTATING = {"archive", "rename", "move", "delete"}

FIELDS = {"department", "business_criticality", "regulatory_tags", "triage_score",
         "source", "owner", "age_days",
         # Folder/path + lifecycle conditions (Discover/Assess Lifecycle PRD, Phase B1).
         "path", "parent_folder", "modified_age_days", "modified_at", "created_at",
         # File type/size (Lifecycle Rules build-plan item #3). doc_class is the same
         # ADR-0020-stage-2 classification Discover already shows ("pdf-document",
         # "spreadsheet", "image", ...); size_kb is the scanner's own inventory size,
         # newly threaded through to `documents` by upsert_document alongside it.
         "doc_class", "size_kb",
         # SharePoint-NATIVE rule inputs (Phase 2). The point of the SharePoint connector is that
         # the customer has already done the information architecture — content types, retention
         # labels, a records category column — and a rule keyed on ACP's own guesses ignores all
         # of it. "Archive anything under the Superseded content type" is a rule a records
         # manager can defend to an auditor; "archive anything older than 7 years" is one they
         # have to justify from scratch.
         #
         # NULL on every non-SharePoint source, and — the part that matters — NULL is also what a
         # field ACP could not READ looks like here. A rule keyed on retention_label therefore
         # matches nothing on an estate whose labels Graph refused, exactly as it does on an
         # estate with no labels. That is why the availability map is persisted beside the value
         # (scan_inventory.sp_metadata) and surfaced in the export: the rule cannot tell the two
         # apart, so the human reading its output has to be able to.
         "content_type", "retention_label", "sensitivity_label", "sharing_scope",
         "item_kind", "checked_out_by", "site_name", "library_name"}

#: A rule may also key on the tenant's OWN managed columns, written `managed:<Column Name>` —
#: `{"field": "managed:Records Category", "op": "eq", "value": "Superseded"}`.
#:
#: Dynamic by necessity, not by preference: managed metadata means the customer names the
#: columns, so an allow-list of known fields cannot exist and a schema column per column would
#: need a migration per customer. The prefix keeps them namespaced away from ACP's own fields, so
#: a tenant with a column literally called "owner" cannot shadow the built-in one.
MANAGED_PREFIX = "managed:"


def managed_field(field: str) -> str | None:
    """The tenant column a `managed:` field names, or None when it is not one of those."""
    if isinstance(field, str) and field.startswith(MANAGED_PREFIX):
        name = field[len(MANAGED_PREFIX):].strip()
        return name or None
    return None


def _iso_before(a, b) -> bool:
    """True iff ISO-date string a is strictly earlier than b. None or malformed
    on either side yields False (never raises) — an unknown date matches nothing."""
    da, db = _parse_iso(a), _parse_iso(b)
    return da is not None and db is not None and da < db


_OPS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "gt": lambda a, b: a is not None and b is not None and a > b,
    "gte": lambda a, b: a is not None and b is not None and a >= b,
    "lt": lambda a, b: a is not None and b is not None and a < b,
    "lte": lambda a, b: a is not None and b is not None and a <= b,
    "contains": lambda a, b: b is not None and str(b).lower() in str(a or "").lower(),
    # Case-insensitive "starts with" — e.g. target everything under "/Finance/".
    "prefix": lambda a, b: b is not None and str(a or "").lower().startswith(str(b).lower()),
    # ISO-date comparisons for "modified before <date>" style lifecycle rules.
    "before": _iso_before,
    "after": lambda a, b: _iso_before(b, a),
}


def validate_match(match: list[dict]) -> None:
    """Raise ValueError on a malformed or unsafe match predicate. Call before
    persisting a policy — matches() itself doesn't re-validate on every call."""
    if not isinstance(match, list):
        raise ValueError("match must be a list of conditions")
    for cond in match:
        if not isinstance(cond, dict) or "field" not in cond or "op" not in cond:
            raise ValueError(f"malformed condition: {cond!r}")
        if cond["field"] not in FIELDS and managed_field(cond["field"]) is None:
            raise ValueError(
                f"unknown field: {cond['field']!r} (allowed: {sorted(FIELDS)}, or "
                f"{MANAGED_PREFIX}<SharePoint column name>)")
        if cond["op"] not in _OPS:
            raise ValueError(f"unknown op: {cond['op']!r} (allowed: {sorted(_OPS)})")


def tag_list(action_config: dict | None) -> list[str]:
    """The non-empty tags in a tag policy's action_config, in order, deduped.
    Central so the validator, the executor and the persistence path all agree on
    exactly which strings count as tags."""
    seen, out = set(), []
    for t in (action_config or {}).get("tags") or []:
        t = str(t).strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def validate_action_config(action: str, action_config: dict | None) -> None:
    """Raise ValueError when an action's config is malformed. Called on the same
    seam as validate_match (before a policy is persisted). Today only 'tag' has a
    required shape: action_config.tags must be a non-empty list of strings — a tag
    policy with nothing to attach is a no-op that would silently apply to every match."""
    if action == "tag" and not tag_list(action_config):
        raise ValueError("tag action requires a non-empty 'tags' list in action_config")


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO-8601 string to a tz-aware datetime (assume UTC if naive).
    Returns None on empty, non-string, or malformed input — never raises."""
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _days_since(iso: str | None) -> int | None:
    """Whole days between an ISO timestamp and now (UTC), or None if unparseable."""
    dt = _parse_iso(iso)
    if dt is None:
        return None
    return (datetime.now(timezone.utc) - dt).days


def _age_days(created_at: str | None) -> int | None:
    """Age in days from a document's created_at. Thin wrapper over _days_since
    kept for existing callers."""
    return _days_since(created_at)


def _parent_folder(path: str | None) -> str | None:
    """Directory portion of a document path (POSIX-style "/" separators, as the
    documents.path column stores). None when there is no path."""
    if not path:
        return None
    return posixpath.dirname(path)


def _values(doc: dict) -> dict:
    """The doc plus its derived fields — one place, so matches() and evaluate() cannot disagree
    about what a condition was tested against."""
    # source_modified is a documents-table column other work is adding; read it
    # only via .get() so this module never assumes it exists.
    return {
        **doc,
        "age_days": _days_since(doc.get("created_at")),
        "modified_age_days": _days_since(doc.get("source_modified")),
        "modified_at": doc.get("source_modified"),
        "parent_folder": _parent_folder(doc.get("path")),
    }


def _read(values: dict, field: str):
    """One field's observed value, including the tenant's own SharePoint columns.

    A `managed:` field is looked up in `managed_columns` — the bag scanner writes from the
    expanded listItem — rather than in the doc's own keys, so a tenant column can never shadow
    or be shadowed by an ACP field of the same name.

    CASE-INSENSITIVE on the column name, because the name in a rule is typed by a human reading
    it off a SharePoint list header and the name in the payload is Graph's internal spelling;
    a rule that silently matches nothing because of a capital letter is indistinguishable from a
    rule that correctly matches nothing, which is the failure mode this whole module documents.
    """
    name = managed_field(field)
    if name is None:
        return values.get(field)
    cols = values.get("managed_columns")
    if not isinstance(cols, dict):
        return None
    if name in cols:
        return cols[name]
    lowered = name.lower()
    for k, v in cols.items():
        if str(k).lower() == lowered:
            return v
    return None


def matches(doc: dict, match: list[dict]) -> bool:
    """True iff `doc` satisfies every condition (AND) in `match`. Assumes
    validate_match already passed — does not re-check field/op safety."""
    # source_modified is a documents-table column other work is adding; read it
    # only via .get() so this module never assumes it exists.
    values = _values(doc)
    for cond in match:
        if not _OPS[cond["op"]](_read(values, cond["field"]), cond.get("value")):
            return False
    return True


# Derived fields that come from a different source column — used by _condition_reason
# to say "source_modified is not recorded" rather than "modified_age_days is not recorded".
_DERIVED_FROM = {
    "age_days": "created_at",
    "modified_age_days": "source_modified",
    "modified_at": "source_modified",
    "parent_folder": "path",
}

_OP_WORDS = {
    "gt": "greater than", "gte": "at least",
    "lt": "less than",    "lte": "at most",
}


def _condition_reason(op: str, field: str, observed, expected, passed: bool,
                      availability: dict | None = None, reasons: dict | None = None) -> str:
    """Human-readable explanation for one condition's outcome."""
    absent = observed is None
    src = _DERIVED_FROM.get(field)
    absent_label = f"'{src}' not recorded" if src else f"'{field}' not recorded"
    # A SharePoint-native field that was not read says so, instead of borrowing the wording for a
    # field the tenant left unset. Same sentence position, opposite meaning, and the difference is
    # what the reader of this evidence is deciding on.
    # A `managed:` condition's availability is the bag's, not a key of its own: the whole column
    # set arrives together or not at all, so "Records Category was not read" is a fact about the
    # listItem expansion, recorded once.
    state = (availability or {}).get(
        "managed_columns" if managed_field(field) else field)
    if absent and state == "unavailable":
        why = (reasons or {}).get(field) or (reasons or {}).get("managed_columns")
        absent_label = (f"'{field}' was NOT READ from SharePoint, so this rule could not be "
                        f"evaluated against it" + (f" — {why}" if why else ""))
    elif absent and state == "not_configured":
        absent_label = f"SharePoint records no '{field}' on this document"
    elif absent and state == "not_applicable":
        absent_label = f"'{field}' does not apply to this document"

    if not passed:
        if absent and op in ("gt", "gte", "lt", "lte", "before", "after", "eq"):
            return absent_label
        if absent and op in ("contains", "prefix"):
            return f"{absent_label}; treated as empty string, which does not satisfy {op!r} {expected!r}"
        if op == "before":
            return f"'{observed}' is not before '{expected}'"
        if op == "after":
            return f"'{observed}' is not after '{expected}'"
        if op in _OP_WORDS:
            return f"{observed} is not {_OP_WORDS[op]} {expected}"
        if op == "prefix":
            return f"'{observed}' does not start with '{expected}'"
        if op == "contains":
            return f"'{observed}' does not contain '{expected}'"
        if op == "eq":
            return f"'{observed}' does not equal '{expected}'"
        if op == "ne":
            return f"'{observed}' equals '{expected}'"
        return "condition not satisfied"
    # passed
    if absent and op == "ne":
        return f"field not recorded; any absent value is not equal to '{expected}'"
    if op == "before":
        return f"'{observed}' is before '{expected}'"
    if op == "after":
        return f"'{observed}' is after '{expected}'"
    if op in _OP_WORDS:
        return f"{observed} is {_OP_WORDS[op]} {expected}"
    if op == "prefix":
        return f"'{observed}' starts with '{expected}'"
    if op == "contains":
        return f"'{observed}' contains '{expected}'"
    if op in ("eq", "ne"):
        return f"'{observed}' {'equals' if op == 'eq' else 'does not equal'} '{expected}'"
    return "condition satisfied"


def evaluate(doc: dict, match: list[dict]) -> dict:
    """Evaluate `match` conditions against `doc` and return per-condition provenance.

    Returns::

        {
          "matched": bool,
          "conditions": [
            {
              "field": str,
              "op": str,
              "value": <expected>,
              "observed_value": <actual, or None when absent>,
              "outcome": "pass" | "fail",
              "reason": str
            },
            ...
          ]
        }

    ``matched`` is True only when every condition passes — identical to ``matches()``.
    The per-condition rows make it possible to explain to a reviewer exactly why a file
    did or did not satisfy a rule, including when a missing metadata field was the cause.
    """
    values = _values(doc)
    # WHY a SharePoint field was empty, when the row carries it. `sp_availability` is the
    # per-field state scanner recorded at discovery ({"retention_label": "unavailable", ...}) and
    # `sp_reasons` the message that went with it. Without them a rule's evidence says
    # "'retention_label' not recorded" for two situations that mean opposite things — the tenant
    # applies no retention labels (an answer) versus Graph refused to hand them over (a task) —
    # and an auditor reading the evidence cannot tell which conclusion the rule supports.
    availability = doc.get("sp_availability") if isinstance(doc.get("sp_availability"), dict) else {}
    reasons = doc.get("sp_reasons") if isinstance(doc.get("sp_reasons"), dict) else {}
    rows = []
    all_passed = True
    for cond in match:
        field, op, expected = cond["field"], cond["op"], cond.get("value")
        observed = _read(values, field)
        passed = bool(_OPS[op](observed, expected))
        if not passed:
            all_passed = False
        rows.append({
            "field": field,
            "op": op,
            "value": expected,
            "observed_value": observed,
            "outcome": "pass" if passed else "fail",
            "reason": _condition_reason(op, field, observed, expected, passed,
                                        availability=availability, reasons=reasons),
        })
    return {"matched": all_passed, "conditions": rows}


def evaluation_result(evaluation: dict) -> str:
    """Classify a detailed evaluation without changing evaluate()'s long-standing public shape.
    A missing value is required evidence except for ``ne``: that operator explicitly models
    absence as "not equal" and existing policies rely on that documented behavior."""
    missing = any(row.get("observed_value") is None and row.get("op") != "ne"
                  for row in evaluation.get("conditions", []))
    if missing:
        return "unevaluable"
    return "matched" if evaluation.get("matched") else "not_matched"


# ── Candidate precedence (PRD §6) ───────────────────────────────────────────────
# Moved here from api/handlers._evaluate_discover_lifecycle_rules (Lifecycle Rules build-plan
# item #6, "identify which rule wins") so the discover-time evaluator and the conflicts report
# (routes/disposition.list_conflicts) make the SAME decision from the same code, rather than the
# report re-deriving a second copy of this logic that could quietly drift from what discovery
# actually does. Pure — no store access, same contract as matches().

DELETE_OVERRIDE_KEYS = ("override_archive", "supersedes_archive", "supersede_archive")


def delete_supersedes_archive(action_config: dict | None) -> bool:
    """True iff a delete policy's action_config explicitly permits it to win over an archive
    rule that also matched the same file. The default is the safe one — a delete rule does NOT
    silently outrank an archive rule."""
    cfg = action_config or {}
    return any(bool(cfg.get(k)) for k in DELETE_OVERRIDE_KEYS)


def actor_authorized_for_delete(actor: str | None) -> bool:
    """A discover-time actor may let a delete rule supersede an archive rule only when they are a
    real authenticated owner — the keyless 'demo'/anonymous path never produces the
    irreversible-leaning Delete Candidate when an archive rule also matched."""
    return bool(actor) and actor != "demo"


def resolve_candidate(matched: list[dict], actor: str | None) -> tuple[dict | None, str | None, str | None]:
    """Given every policy that matched one document (in PRIORITY order — the order `matched` is
    already in, since list_disposition_policies sorts by priority/name and this function only
    ever sees what the caller already ordered), decide which one WINS and why.

    Returns (chosen_policy, new_status, reason) — chosen_policy is None (and the other two as
    well) when nothing in `matched` produces a candidate status (e.g. only 'tag' policies
    matched; tag is applied separately by the caller, not decided here).

    Archive-vs-delete precedence: a delete rule wins over a co-matching archive rule only when
    its action_config explicitly permits the override AND the actor is a real authenticated
    owner — otherwise the reversible outcome (archive) is kept and the file is flagged for
    review rather than letting a delete rule silently win. Ties within one action type are
    broken by priority order — the FIRST archive (or delete) rule in `matched` — which is why
    the caller's ordering is load-bearing, not incidental.
    """
    archive_p = next((p for p in matched if p.get("action") == "archive"), None)
    delete_p = next((p for p in matched if p.get("action") == "delete"), None)
    if delete_p and archive_p:
        if delete_p.get("priority") is not None and delete_p.get("priority") == archive_p.get("priority"):
            return None, "Conflict — review required", (
                f"equal-priority rules '{archive_p.get('name')}' and '{delete_p.get('name')}' "
                "recommend different destructive actions; neither action was selected")
        try:
            dcfg = json.loads(delete_p.get("action_config") or "{}")
        except Exception:
            dcfg = {}
        if delete_supersedes_archive(dcfg) and actor_authorized_for_delete(actor):
            reason = (f"delete rule '{delete_p.get('name')}' supersedes archive rule "
                      f"'{archive_p.get('name')}' (override permitted, actor authorized)")
            return delete_p, "Delete Candidate", reason
        reason = (f"matched archive rule '{archive_p.get('name')}' — flagged for review: "
                  f"delete rule '{delete_p.get('name')}' also matched but its override is "
                  f"not permitted or the actor is not authorized")
        return archive_p, "Archive Candidate", reason
    if delete_p:
        return delete_p, "Delete Candidate", f"matched delete rule '{delete_p.get('name')}'"
    if archive_p:
        return archive_p, "Archive Candidate", f"matched archive rule '{archive_p.get('name')}'"
    return None, None, None


# ── Execute path (ADR 0003 Phase 3 — approved 2026-07-02) ─────────────────────
# Performs a policy's action against the source system. Safety posture:
#   * delete is ALWAYS Drive trash (30-day recovery) — never files().delete().
#   * only Drive-backed documents (doc_id "drive:<fileId>") can be actioned;
#     everything else fails cleanly rather than guessing.
#   * callers gate on requires_approval + the append-only disposition_audit;
#     this function only ever acts on a doc it was explicitly handed.

ARCHIVE_FOLDER = "ACP Archive"


def _drive_file_id(doc: dict) -> str | None:
    doc_id = doc.get("doc_id") or ""
    if doc.get("source") == "drive" and doc_id.startswith("drive:"):
        return doc_id.split(":", 1)[1]
    return None


def _ensure_folder(svc, name: str) -> str:
    """Find-or-create a Drive folder by name (oldest wins on legacy duplicates)."""
    safe = name.replace("\\", "\\\\").replace("'", "\\'")
    q = f"name='{safe}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    found = svc.files().list(q=q, fields="files(id)", orderBy="createdTime",
                             pageSize=1).execute().get("files", [])
    if found:
        return found[0]["id"]
    return svc.files().create(
        body={"name": name, "mimeType": "application/vnd.google-apps.folder"},
        fields="id").execute()["id"]


def undo_action(doc: dict, before: dict | None, svc) -> tuple[str, str]:
    """Put a file back the way `before` says it was. Returns (result, detail).

    The mirror of execute_action, and deliberately NOT a general "reverse whatever happened"
    — it reverses one recorded before-state and refuses anything it cannot verify. PRD §8's
    undo is only meaningful if it restores the actual prior state, so a missing or unrecognised
    record is a refusal, never a best guess. Restoring a file to a folder nobody recorded is
    indistinguishable, afterwards, from having moved it somewhere new.

    Drive only, for the same reason execute_action is: ACP holds read-only scopes everywhere
    else, so there is nothing there to have undone.
    """
    if not before:
        return "failed", "no before-state was recorded for this action, so it cannot be undone"
    fid = _drive_file_id(doc)
    if not fid:
        return "failed", (f"unsupported source '{doc.get('source')}' — only Drive-backed "
                          "documents can be undone")
    if svc is None:
        return "failed", "no Drive connection — connect Google Drive and retry"
    action = before.get("action")
    try:
        if action == "delete":
            svc.files().update(fileId=fid, body={"trashed": False}).execute()
            return "applied", "restored from Drive trash"
        if action == "rename":
            prior = before.get("name")
            if not prior:
                return "failed", "the previous name was not recorded, so it cannot be restored"
            svc.files().update(fileId=fid, body={"name": prior}).execute()
            return "applied", f"renamed back to '{prior}'"
        if action in ("archive", "move"):
            prior_parents = before.get("parents") or []
            if not prior_parents:
                # A file that genuinely had no parent is not the same as one whose parents were
                # never recorded, and this cannot tell them apart — so it refuses rather than
                # dropping the file into My Drive and calling that a restoration.
                return "failed", ("the previous folder was not recorded, so the file cannot be "
                                  "moved back")
            current = svc.files().get(fileId=fid, fields="parents").execute()
            svc.files().update(fileId=fid, addParents=",".join(prior_parents),
                               removeParents=",".join(current.get("parents", [])),
                               fields="id").execute()
            return "applied", f"moved back to its previous folder ({', '.join(prior_parents)})"
        return "failed", f"nothing recorded for action '{action}' can be undone"
    except Exception as e:  # HttpError, network, permission — record, don't raise
        return "failed", f"{type(e).__name__}: {e}"[:300]


def plan_action(doc: dict, action: str, action_config: dict | None) -> dict:
    """What execute_action WOULD do to `doc`, without doing any of it.

    Takes no Drive client and makes no call, which is the property that matters: a dry run that
    can touch the estate is not a dry run. It is also why the rename preview names the template
    rather than the resulting filename — the current name lives in Drive, and reading it would
    mean a network call this deliberately cannot make.

    Returns {will, target, recoverable, blocked}. `blocked` is a reason the action could not be
    performed at all, and it is stated up front rather than discovered at execution: the whole
    point of showing a reviewer a plan is that they see the refusals BEFORE they authorise
    anything.
    """
    cfg = action_config or {}
    if action == "leave":
        return {"will": "leave the file where it is", "target": None,
                "recoverable": None, "blocked": None}
    if action == "tag":
        tags = tag_list(cfg)
        return {"will": f"tag the document {', '.join(tags)}" if tags else "tag the document",
                "target": None, "recoverable": None,
                "blocked": None if tags else "tag action has no tags configured"}
    if not _drive_file_id(doc):
        return {"will": None, "target": None, "recoverable": None,
                "blocked": (f"unsupported source '{doc.get('source')}' — only Drive-backed "
                            "documents can be actioned")}
    if action == "delete":
        return {"will": "move the file to Google Drive trash", "target": "Drive trash",
                # The same claim api/disposition.py's own detail string makes, and no stronger:
                # nothing here reads a retention policy back from Drive.
                "recoverable": "recoverable from Drive trash for about 30 days",
                "blocked": None}
    if action == "rename":
        template = cfg.get("template") or "{name} [ARCHIVED {date}]"
        return {"will": "rename the file in place", "target": f"pattern {template}",
                "recoverable": "the previous name is recorded, so this can be undone",
                "blocked": None}
    if action in ("archive", "move"):
        folder = cfg.get("target_folder_id")
        return {"will": "move the file out of its current folder",
                "target": (f"folder {folder}" if folder
                           else f"the '{ARCHIVE_FOLDER}' folder (created if it does not exist)"),
                "recoverable": "the current folder is recorded, so this can be undone",
                "blocked": None}
    return {"will": None, "target": None, "recoverable": None,
            "blocked": f"unknown action '{action}'"}


def execute_action(doc: dict, action: str, action_config: dict | None,
                   svc) -> tuple[str, str, dict | None]:
    """Apply `action` to `doc`. Returns (result, detail, before) with result applied|failed.

    svc is an authenticated Drive client (may be None for 'leave'). Exceptions are
    converted to a 'failed' result — one bad file must not abort a policy run.

    `before` is what the file looked like BEFORE the action, and it is the whole reason this
    returns a triple. Until now a move read the file's parents and passed them straight to
    removeParents, and a rename read its name only to build the new one: both were discarded the
    instant they were used, so nothing in the system could ever put the file back. PRD §8 promises
    the reviewer an undo "where the connector supports it" — the connector always supported it;
    ACP simply never wrote down where the file came from.

    Returned rather than written here so this stays a pure Drive operation: persisting it is the
    route's job, at the route's tenant grain, exactly as tag persistence already is. None when
    there is nothing to reverse (leave/tag never move a file) or when the action failed.
    """
    cfg = action_config or {}
    if action == "leave":
        return "applied", "left in place — decision recorded", None
    if action == "tag":
        # Metadata-only: attaches tags to the document, never touches Drive — so it
        # works for any source and needs no svc (unlike archive/rename/move/delete).
        # The actual persistence (store.add_file_tags) is the route's job, keyed to
        # the caller's tenant/scan grain; here we only decide applied/failed + detail.
        tags = tag_list(cfg)
        if not tags:
            return "failed", "tag action has no tags configured", None
        return "applied", "tagged: " + ", ".join(tags), None
    fid = _drive_file_id(doc)
    if not fid:
        return "failed", (f"unsupported source '{doc.get('source')}' — only Drive-backed "
                          "documents can be actioned"), None
    if svc is None:
        return "failed", "no Drive connection — connect Google Drive and retry", None
    try:
        if action == "delete":
            # Trash, never permanent: recoverable from Drive for ~30 days.
            svc.files().update(fileId=fid, body={"trashed": True}).execute()
            # The file was not in the trash a moment ago — that IS the before-state, and it is
            # what an undo restores it to.
            return ("applied", "moved to Drive trash (recoverable ~30 days)",
                    {"action": "delete", "trashed": False})
        if action == "rename":
            template = cfg.get("template") or "{name} [ARCHIVED {date}]"
            meta = svc.files().get(fileId=fid, fields="name").execute()
            from datetime import datetime, timezone as _tz
            new_name = (template.replace("{name}", meta.get("name", doc.get("path", "document")))
                                .replace("{date}", datetime.now(_tz.utc).strftime("%Y-%m-%d")))
            prior_name = meta.get("name")
            svc.files().update(fileId=fid, body={"name": new_name}).execute()
            return ("applied", f"renamed to '{new_name}'",
                    {"action": "rename", "name": prior_name})
        if action in ("archive", "move"):
            folder_id = cfg.get("target_folder_id") or _ensure_folder(svc, ARCHIVE_FOLDER)
            meta = svc.files().get(fileId=fid, fields="parents").execute()
            prior_parents = list(meta.get("parents", []))
            svc.files().update(fileId=fid, addParents=folder_id,
                               removeParents=",".join(prior_parents),
                               fields="id").execute()
            dest = cfg.get("target_folder_id") and "configured folder" or f"'{ARCHIVE_FOLDER}'"
            return ("applied", f"moved to {dest} ({folder_id})",
                    {"action": action, "parents": prior_parents, "moved_to": folder_id})
        return "failed", f"unknown action '{action}'", None
    except Exception as e:  # HttpError, network, permission — record, don't raise
        # No before-state on a failure: the file may or may not have moved, and a recorded
        # "before" that might not be true is worse than none — an undo would act on a guess.
        return "failed", f"{type(e).__name__}: {e}"[:300], None
