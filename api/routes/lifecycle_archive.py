"""Safe lifecycle archive auto-fire (R9) — policy, evaluation, execution and the audit trail.

WHY A SEPARATE ROUTER FROM routes/disposition.py. That module's execute path is human-approved,
per-file, and Drive-only; this one is unattended, queued, and Graph-only, and the two have
opposite defaults on every safety question they share. Folding an unattended lane into a module
whose docstring promises "callers gate on requires_approval" would make both harder to read and
would put the wrong assumption one function call away.

THE GATES, and they are not the same gate:

  * READING the policy, the candidates and the audit trail is open to any signed-in user, scoped
    to their own tenant. A person cannot decide whether auto-archive is configured safely without
    being able to see how it is configured.
  * WRITING the policy is `_require_admin` — it decides what may move unattended.
  * The KILL SWITCH is admin too, but deliberately its own endpoint, so turning it on is one call
    that cannot fail on an unrelated validation error in the rest of the policy. An operator
    reaching for it is having a bad day already.
  * RUNNING is `_require_owner`, matching routes/disposition.py's own rule that the routes which
    actually authorise or perform a move on the estate are owner-gated. This one performs moves
    with nobody watching, so it inherits the stricter of the two rather than the looser.

EVERY ROUTE IS TENANT-SCOPED IN ITS QUERY, not by the caller's promise: `_owner(request)` goes
into the WHERE clause, and `store.list_archive_scan_rows` refuses another tenant's scan_id by
returning nothing. disposition_policy shipped with no ownership column at all and every signed-in
user could toggle every other tenant's rules; the same mistake here would move another tenant's
files.

NO CREDENTIAL IS EVER STORED OR RETURNED. The Graph token arrives per request in `x-sp-token`,
exactly as the SharePoint routes take it, is handed to the source adapter, and goes no further —
not into the execution row, not into an event, not into a response.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

import archive_autofire as af
import archive_execution
import archive_sources
import core
from .system import _require_admin, _require_owner

router = APIRouter()


def _owner(request: Request) -> str:
    """The current user for per-user data isolation — same helper as every other lifecycle route."""
    return getattr(request.state, "user_email", None) or "demo"


def _sp_token(request: Request) -> str:
    """The caller's Graph token, or ''. Never logged, never stored, never returned."""
    return request.headers.get("x-sp-token") or ""


class ArchivePolicyIn(BaseModel):
    """The administrator-facing policy. Every field optional — a PUT that names only the fields it
    changes is merged over the stored one, so an administrator toggling dry-run cannot
    accidentally clear the archive root by omitting it."""
    enabled: bool | None = None
    kill_switch: bool | None = None
    dry_run: bool | None = None
    source_connections: list[str] | None = None
    rule_ids: list[str] | None = None
    required_evidence: list[str] | None = None
    confirmed_families: list[dict] | None = None
    min_replacement_age_days: int | None = None
    archive_root: str | None = None
    preserve_hierarchy: bool | None = None
    max_actions_per_run: int | None = None
    max_actions_per_day: int | None = None


class KillSwitchIn(BaseModel):
    on: bool


def _policy_response(store, owner: str) -> dict:
    stored = store.get_archive_policy(owner)
    policy = af.normalize_policy((stored or {}).get("policy"))
    snapshot = af.policy_snapshot(policy)
    return {
        "configured": stored is not None,
        "policy": policy,
        "snapshot_id": snapshot["snapshot_id"],
        "updated_at": (stored or {}).get("updated_at"),
        "updated_by": (stored or {}).get("updated_by"),
        "evidence_types": [{"type": t, "label": af.EVIDENCE_LABELS[t]} for t in af.EVIDENCE_TYPES],
        "auto_sources": list(af.AUTO_SOURCES),
        "problem": af.policy_problem(policy),
        # Stated by the API rather than only by the UI, because an integrator reading this
        # response is owed the same guarantee the screen gives a person.
        "notice": ("Age, filename similarity and inactivity never authorize an automatic move. "
                   "A document is archived automatically only when durable evidence shows a "
                   "newer item supersedes it and this policy permits it."),
    }


@router.get("/lifecycle/archive/policy")
def get_archive_policy(request: Request):
    """This tenant's auto-fire policy. Readable by any signed-in user — see the module docstring."""
    return _policy_response(core.store, _owner(request))


@router.put("/lifecycle/archive/policy")
def put_archive_policy(body: ArchivePolicyIn, request: Request):
    """Merge changes into the stored policy. Admin-gated.

    REFUSES AN ENABLE THAT CANNOT WORK (`af.policy_problem`) rather than storing it: a policy
    enabled with no destination would fail at execution time, on a real file, having already told
    an administrator it was on. Everything else is stored as given, including a half-configured
    DISABLED policy, so the destination can be filled in before the rules.
    """
    _require_admin(request)
    owner = _owner(request)
    stored = core.store.get_archive_policy(owner)
    merged = af.normalize_policy((stored or {}).get("policy"))
    for field, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            merged[field] = value
    merged = af.normalize_policy(merged)
    problem = af.policy_problem(merged)
    if problem:
        raise HTTPException(400, problem)
    core.store.set_archive_policy(owner, merged, actor=owner)
    # The snapshot is saved on every policy WRITE, not only at run time, so the audit trail can
    # resolve a snapshot id an evaluation produced even if no run ever followed it.
    snapshot = af.policy_snapshot(merged)
    core.store.save_archive_snapshot(snapshot["snapshot_id"], owner, snapshot["policy"])
    core.store.log_decision(owner, "archive_autofire.policy_updated",
                            detail=f"enabled={merged['enabled']} dry_run={merged['dry_run']} "
                                   f"snapshot={snapshot['snapshot_id']}")
    return _policy_response(core.store, owner)


@router.post("/lifecycle/archive/kill-switch")
def set_kill_switch(body: KillSwitchIn, request: Request):
    """Stop (or resume) new automatic moves immediately. Admin-gated, and deliberately its own route.

    Takes effect on the NEXT item rather than at the next run: archive_execution.run re-reads this
    value from the store before every move, so a switch thrown mid-run stops the queue rather than
    the next scheduled pass. Work already issued to the provider is finished and recorded — a move
    issued and then abandoned is the one outcome worse than a move that should not have started.
    """
    _require_admin(request)
    owner = _owner(request)
    stored = core.store.get_archive_policy(owner)
    policy = af.normalize_policy((stored or {}).get("policy"))
    policy["kill_switch"] = bool(body.on)
    core.store.set_archive_policy(owner, policy, actor=owner)
    core.store.log_decision(owner, "archive_autofire.kill_switch",
                            detail=f"kill_switch={'on' if body.on else 'off'}")
    return _policy_response(core.store, owner)


@router.get("/lifecycle/archive/candidates")
def list_candidates(request: Request, scan_id: str = Query(...)):
    """Every archive candidate in one scan with its lane, its evidence and its destination.

    Reads only — no file is touched by calling this, which is what makes "inspect the evidence
    before execution" a real affordance rather than a promise. An unknown or other-tenant scan_id
    returns an empty candidate list rather than a 404: the caller is not entitled to learn that
    another tenant's scan exists.
    """
    owner = _owner(request)
    report = archive_execution.evaluate(core.store, owner, scan_id)
    return {"scan_id": scan_id, "snapshot_id": report["snapshot_id"],
            "dry_run": report["dry_run"], "counts": report["counts"],
            "progress": af.run_progress(report["counts"]),
            "state_labels": af.STATE_LABELS, "items": report["items"]}


@router.post("/lifecycle/archive/run")
def run_archive(request: Request, scan_id: str = Query(...)):
    """Execute every eligible candidate in one scan. Owner-gated — this moves customer files.

    Returns the run report, including the executions it created. A repeated call is safe by
    construction rather than by a guard here: every item's idempotency key already exists after
    the first run, so the second call returns the original execution records and touches nothing.
    """
    _require_owner(request)
    owner = _owner(request)
    token = _sp_token(request)

    def source_factory(connection: str):
        """One adapter per source connection, or None when this request carries no credential for it.

        None is not an error: it produces a BLOCKED execution row saying no connection was
        available, which is a truthful audit record. Raising instead would abandon the rest of the
        queue over one unreachable connection.
        """
        if not token or not connection.split(":", 1)[0] in af.AUTO_SOURCES:
            return None
        return archive_sources.GraphArchiveSource(token)

    report = archive_execution.run(core.store, owner, scan_id, source_factory=source_factory,
                                   actor=owner)
    return {"scan_id": scan_id, **{k: v for k, v in report.items() if k != "items"},
            "progress": af.run_progress({"eligible": report["eligible"],
                                         "completed": report["completed"],
                                         "blocked": report["blocked"]})}


@router.get("/lifecycle/archive/executions")
def list_executions(request: Request, scan_id: str | None = Query(None),
                    limit: int = Query(200, ge=1, le=1000)):
    """The audit trail: what ran, under which policy snapshot, on what evidence, and how it ended."""
    owner = _owner(request)
    rows = core.store.list_archive_executions(owner, scan_id=scan_id, limit=limit)
    return {"executions": [_readable(core.store, owner, r) for r in rows]}


@router.get("/lifecycle/archive/executions/{execution_id}")
def get_execution(execution_id: str, request: Request):
    owner = _owner(request)
    row = core.store.get_archive_execution_by_id(execution_id, owner)
    if not row:
        raise HTTPException(404, "no such execution")
    return _readable(core.store, owner, row)


def _readable(store, owner: str, row: dict) -> dict:
    """One execution row as the audit trail a person reads.

    The stored policy snapshot is resolved and returned WITH the row, because "which policy
    authorised this move?" is the first question anybody asks of an unattended action and an
    opaque hash is not an answer. The evidence and preflight blobs are parsed here rather than
    handed over as JSON strings for the same reason.
    """
    snapshot = store.get_archive_snapshot(row.get("snapshot_id") or "", owner)
    return {
        "execution_id": row.get("execution_id"),
        "state": row.get("state"),
        "state_label": af.STATE_LABELS.get(row.get("state"), row.get("state")),
        "detail": row.get("detail"),
        "actor": row.get("actor"),
        "dry_run": bool(row.get("dry_run")),
        "attempts": row.get("attempts"),
        "scan_id": row.get("scan_id"),
        "file": row.get("file"),
        "lifecycle_rule_id": row.get("policy_id"),
        "source_connection": row.get("source_connection"),
        "source_item_id": row.get("source_item_id"),
        "source_path": row.get("source_path"),
        "source_marker": row.get("source_etag"),
        "replacement_item_id": row.get("replacement_item_id"),
        "replacement_path": row.get("replacement_path"),
        "evidence": _json_list(row.get("evidence_json")),
        "preflight": _json_obj(row.get("preflight_json")),
        "destination_path": row.get("destination_path"),
        "destination_item_id": row.get("destination_item_id"),
        "destination_url": row.get("destination_url"),
        "snapshot_id": row.get("snapshot_id"),
        "policy_snapshot": (snapshot or {}).get("policy"),
        "created_at": row.get("created_at"),
        "started_at": row.get("started_at"),
        "completed_at": row.get("completed_at"),
    }


def _json_list(blob):
    try:
        value = json.loads(blob or "[]")
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _json_obj(blob):
    try:
        value = json.loads(blob or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}
