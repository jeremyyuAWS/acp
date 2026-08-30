"""ACP Managed Content Workspace (ADR 0044, PRD Phase 1) — workspace create/list/get.

Named `content_workspaces`, not `workspaces`, to stay unambiguous next to the existing,
unrelated `api/routes/workspace.py` (`GET /workspace/bootstrap` — the app-shell initial-load
optimization; nothing to do with this PRD).

This is the FIRST slice of Phase 1 only: the workspace container itself. Upload, staging/
verification, and the document/version tables it will attach to are a separate, later PR (see
ADR 0044's schema section for the agreed shape they'll implement against).

Owner-scoped throughout: `owner_email` is the tenant boundary this whole app already uses
(ADR 0044). `GET /content-workspaces/{id}` 404s — never 403 — for a foreign id, matching
`test_foreign_scan_404.py`'s established "an id is never an existence oracle across owners"
contract.
"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

import core

router = APIRouter()


def _owner(request: Request) -> str:
    """Matches api/routes/workspace.py's identical helper — the gate-verified email, or
    'demo' for the keyless/demo path."""
    return getattr(request.state, "user_email", None) or "demo"


def _serialize(ws: dict) -> dict:
    """store.py's content_workspaces rows carry permitted_file_types as a JSON-encoded TEXT
    column (same reasoning as campaign.scope) — decoded here, at the API boundary, so callers
    get a real list rather than a string they'd have to json.loads themselves."""
    out = dict(ws)
    raw = out.get("permitted_file_types")
    out["permitted_file_types"] = json.loads(raw) if raw else None
    return out


class ContentWorkspaceCreate(BaseModel):
    name: str
    purpose: str | None = None
    business_owner: str | None = None
    department: str | None = None
    wcag_standard: str | None = None
    retention_policy: str | None = None
    permitted_file_types: list[str] | None = None
    due_date: str | None = None
    project: str | None = None
    processing_region: str | None = None
    external_ai_policy: str | None = None


@router.post("/content-workspaces")
def create_content_workspace(body: ContentWorkspaceCreate, request: Request):
    if not body.name.strip():
        raise HTTPException(422, "name is required")
    owner = _owner(request)
    workspace_id = uuid.uuid4().hex[:12]
    core.store.create_content_workspace(
        workspace_id, owner_email=owner, name=body.name.strip(), purpose=body.purpose,
        business_owner=body.business_owner, department=body.department,
        wcag_standard=body.wcag_standard, retention_policy=body.retention_policy,
        permitted_file_types=body.permitted_file_types, due_date=body.due_date,
        project=body.project, processing_region=body.processing_region,
        external_ai_policy=body.external_ai_policy)
    core.store.log_decision(owner, "content_workspace.created", detail=body.name.strip())
    return get_content_workspace(workspace_id, request)


@router.get("/content-workspaces")
def list_content_workspaces(request: Request):
    rows = core.store.list_content_workspaces(_owner(request))
    return {"workspaces": [_serialize(r) for r in rows]}


@router.get("/content-workspaces/{workspace_id}")
def get_content_workspace(workspace_id: str, request: Request):
    ws = core.store.get_content_workspace(workspace_id, owner_email=_owner(request))
    if ws is None:
        raise HTTPException(404, "workspace not found")
    return _serialize(ws)
