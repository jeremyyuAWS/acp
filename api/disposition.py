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

FIELDS = {"department", "business_criticality", "regulatory_tags", "triage_score",
         "source", "owner", "age_days",
         # Folder/path + lifecycle conditions (Discover/Assess Lifecycle PRD, Phase B1).
         "path", "parent_folder", "modified_age_days", "modified_at", "created_at",
         # File type/size (Lifecycle Rules build-plan item #3). doc_class is the same
         # ADR-0020-stage-2 classification Discover already shows ("pdf-document",
         # "spreadsheet", "image", ...); size_kb is the scanner's own inventory size,
         # newly threaded through to `documents` by upsert_document alongside it.
         "doc_class", "size_kb"}


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
        if cond["field"] not in FIELDS:
            raise ValueError(f"unknown field: {cond['field']!r} (allowed: {sorted(FIELDS)})")
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


def matches(doc: dict, match: list[dict]) -> bool:
    """True iff `doc` satisfies every condition (AND) in `match`. Assumes
    validate_match already passed — does not re-check field/op safety."""
    # source_modified is a documents-table column other work is adding; read it
    # only via .get() so this module never assumes it exists.
    values = {
        **doc,
        "age_days": _days_since(doc.get("created_at")),
        "modified_age_days": _days_since(doc.get("source_modified")),
        "modified_at": doc.get("source_modified"),
        "parent_folder": _parent_folder(doc.get("path")),
    }
    for cond in match:
        if not _OPS[cond["op"]](values.get(cond["field"]), cond.get("value")):
            return False
    return True


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


def execute_action(doc: dict, action: str, action_config: dict | None, svc) -> tuple[str, str]:
    """Apply `action` to `doc`. Returns (result, detail) with result applied|failed.

    svc is an authenticated Drive client (may be None for 'leave'). Exceptions are
    converted to a 'failed' result — one bad file must not abort a policy run.
    """
    cfg = action_config or {}
    if action == "leave":
        return "applied", "left in place — decision recorded"
    if action == "tag":
        # Metadata-only: attaches tags to the document, never touches Drive — so it
        # works for any source and needs no svc (unlike archive/rename/move/delete).
        # The actual persistence (store.add_file_tags) is the route's job, keyed to
        # the caller's tenant/scan grain; here we only decide applied/failed + detail.
        tags = tag_list(cfg)
        if not tags:
            return "failed", "tag action has no tags configured"
        return "applied", "tagged: " + ", ".join(tags)
    fid = _drive_file_id(doc)
    if not fid:
        return "failed", (f"unsupported source '{doc.get('source')}' — only Drive-backed "
                          "documents can be actioned")
    if svc is None:
        return "failed", "no Drive connection — connect Google Drive and retry"
    try:
        if action == "delete":
            # Trash, never permanent: recoverable from Drive for ~30 days.
            svc.files().update(fileId=fid, body={"trashed": True}).execute()
            return "applied", "moved to Drive trash (recoverable ~30 days)"
        if action == "rename":
            template = cfg.get("template") or "{name} [ARCHIVED {date}]"
            meta = svc.files().get(fileId=fid, fields="name").execute()
            from datetime import datetime, timezone as _tz
            new_name = (template.replace("{name}", meta.get("name", doc.get("path", "document")))
                                .replace("{date}", datetime.now(_tz.utc).strftime("%Y-%m-%d")))
            svc.files().update(fileId=fid, body={"name": new_name}).execute()
            return "applied", f"renamed to '{new_name}'"
        if action in ("archive", "move"):
            folder_id = cfg.get("target_folder_id") or _ensure_folder(svc, ARCHIVE_FOLDER)
            meta = svc.files().get(fileId=fid, fields="parents").execute()
            svc.files().update(fileId=fid, addParents=folder_id,
                               removeParents=",".join(meta.get("parents", [])),
                               fields="id").execute()
            dest = cfg.get("target_folder_id") and "configured folder" or f"'{ARCHIVE_FOLDER}'"
            return "applied", f"moved to {dest} ({folder_id})"
        return "failed", f"unknown action '{action}'"
    except Exception as e:  # HttpError, network, permission — record, don't raise
        return "failed", f"{type(e).__name__}: {e}"[:300]
