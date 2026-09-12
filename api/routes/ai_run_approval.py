"""Explicit approval-only control for one current remediation run."""
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, StrictBool, StrictInt, StrictStr, Field
import core
import ai_run_approval_override as service
router = APIRouter()


class ApprovalChange(BaseModel):
    enabled: StrictBool
    expected_revision: StrictInt = Field(ge=0)
    expected_source_revision: StrictStr = Field(min_length=1, max_length=256)


def owner_scan(sid, request):
    owner = getattr(request.state, 'user_email', None) or 'demo'
    if core.store.get_scan(sid, owner=owner) is None:
        raise HTTPException(404, 'scan not found')
    return owner


@router.get('/scans/{sid}/remediation/ai-approval/{run_id}')
def read(sid: str, run_id: str, request: Request, response: Response):
    owner = owner_scan(sid, request)
    response.headers['Cache-Control'] = 'no-store'
    try:
        return service.read(core.store, owner, sid, run_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/scans/{sid}/remediation/ai-approval/{run_id}')
def save(sid: str, run_id: str, body: ApprovalChange, request: Request, response: Response):
    owner = owner_scan(sid, request)
    response.headers['Cache-Control'] = 'no-store'
    try:
        return service.save(core.store, owner, sid, run_id, body.enabled,
                            body.expected_revision, body.expected_source_revision)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
