"""Canonical, owner-scoped workflow stage execution API."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

import core

router = APIRouter()
STAGES = frozenset({"discover", "assess", "remediate", "conformance", "release"})
JOB_TYPES = {"assess": "scan_assess", "remediate": "remediate_file", "release": "publish_file"}


def _owner(request: Request) -> str:
    return getattr(request.state, "user_email", None) or "demo"


class ExecutionSubmission(BaseModel):
    scan_id: str | None = None
    input_snapshot_id: str
    intent: dict = Field(default_factory=dict)
    items: list[dict] = Field(default_factory=list)
    job_type: str | None = None


class RevisionMutation(BaseModel):
    expected_revision: int = Field(ge=1)


def _execution_or_404(execution_id: str, request: Request) -> dict:
    execution = core.store.get_stage_execution(execution_id, owner=_owner(request))
    if not execution:
        raise HTTPException(404, "stage execution not found")
    return execution


@router.post("/workflows/{workflow_id}/stages/{stage}/executions")
def submit_execution(workflow_id: str, stage: str, body: ExecutionSubmission, request: Request,
                     idempotency_key: str | None = Header(default=None)):
    if stage not in STAGES:
        raise HTTPException(422, "unknown workflow stage")
    scan_id = body.scan_id or workflow_id
    workflow = core.store.workflow_for_scan(scan_id, _owner(request))
    if not workflow or workflow.get("id") != workflow_id:
        raise HTTPException(404, "workflow not found")
    job_type = body.job_type or JOB_TYPES.get(stage)
    if not job_type:
        raise HTTPException(422, f"{stage} has no configured worker type")
    # The transport idempotency key is deliberately excluded: identity follows immutable input
    # plus semantic intent, so another browser/session submitting the same request reuses it.
    fingerprint = core.store.canonical_request_fingerprint(body.intent)
    try:
        result = core.store.enqueue_stage_batch(
            scan_id, stage, job_type, body.items, snapshot_id=body.input_snapshot_id,
            request_fingerprint=fingerprint)
    except Exception as exc:
        from store import ActiveStageExecutionError
        if isinstance(exc, ActiveStageExecutionError):
            raise HTTPException(409, detail={"code": "stage_execution_active",
                "current_execution_id": exc.batch_id, "allowed_next_actions": ["cancel", "supersede"]})
        raise
    execution = core.store.get_stage_execution(result["batch_id"], owner=_owner(request)) or {}
    return {"execution_id": result["batch_id"], "accepted": not result["reused"],
            "reused": result["reused"], "resumed": bool(result.get("requeued")),
            "superseded_execution_id": None, "revision": execution.get("revision", 1)}


@router.get("/workflows/{workflow_id}/stages/{stage}/executions/current")
def current_execution(workflow_id: str, stage: str, request: Request):
    result = core.store.current_stage_execution(workflow_id, stage, owner=_owner(request))
    if not result:
        raise HTTPException(404, "current stage execution not found")
    return result


@router.get("/stage-executions/{execution_id}")
def execution_detail(execution_id: str, request: Request):
    return _execution_or_404(execution_id, request)


@router.get("/stage-executions/{execution_id}/snapshot")
def execution_snapshot(execution_id: str, request: Request):
    _execution_or_404(execution_id, request)
    import progress_evidence
    return {**core.store.stage_execution_snapshot(execution_id, owner=_owner(request)),
            **progress_evidence.read(core.store, execution_id, owner=_owner(request))}


@router.get("/stage-executions/{execution_id}/events")
def execution_events(execution_id: str, request: Request):
    _execution_or_404(execution_id, request)
    return {"events": core.store.stage_execution_events(execution_id, owner=_owner(request))}


def _control(execution_id: str, action: str, body: RevisionMutation, request: Request):
    _execution_or_404(execution_id, request)
    try:
        return core.store.control_stage_execution(
            execution_id, action, expected_revision=body.expected_revision, owner=_owner(request))
    except RuntimeError:
        current = core.store.get_stage_execution(execution_id, owner=_owner(request))
        raise HTTPException(409, detail={"code": "revision_conflict",
            "current_execution_id": execution_id, "revision": current.get("revision"),
            "allowed_next_actions": ["pause", "resume", "cancel", "supersede"]})
    except ValueError as exc:
        raise HTTPException(409, detail={"code": "invalid_transition", "message": str(exc)})


@router.post("/stage-executions/{execution_id}/pause")
def pause_execution(execution_id: str, body: RevisionMutation, request: Request):
    return _control(execution_id, "pause", body, request)


@router.post("/stage-executions/{execution_id}/resume")
def resume_execution(execution_id: str, body: RevisionMutation, request: Request):
    return _control(execution_id, "resume", body, request)


@router.post("/stage-executions/{execution_id}/cancel")
def cancel_execution(execution_id: str, body: RevisionMutation, request: Request):
    return _control(execution_id, "cancel", body, request)


@router.post("/stage-executions/{execution_id}/supersede")
def supersede_execution(execution_id: str, body: RevisionMutation, request: Request):
    return _control(execution_id, "supersede", body, request)


@router.get("/stage-executions/{execution_id}/queue")
def execution_queue(execution_id: str, request: Request, bucket: str):
    _execution_or_404(execution_id, request)
    import progress_queues
    try:
        return progress_queues.read(core.store, execution_id, _owner(request), bucket)
    except PermissionError:
        raise HTTPException(404, "queue not found")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
