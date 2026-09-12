"""Explicit automatic release opt-in; read-only inspection never authorizes work."""
from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field, StrictStr, StrictBool
import json
import core
import automatic_release as service
import automatic_release_store as persistence
from routes.release_continuation import owner_scan, credentials
from routes.scans import _preflight_release_destination, _release_destination

router = APIRouter()


class AuthorizationRequest(BaseModel):
    run_id: StrictStr = Field(min_length=1, max_length=256)
    files: list[StrictStr] = Field(min_length=1, max_length=500)
    destination: dict
    request_id: StrictStr = Field(min_length=1, max_length=128)
    allow_remaining_issues: StrictBool = False
    include_reports: StrictBool = False
    expected_source_revision: StrictStr | None = Field(default=None, min_length=1, max_length=256)


@router.get('/scans/{sid}/release/automatic')
def status(sid: str, request: Request, response: Response, files: list[str] = Query(default=[]), destination: str | None = None):
    owner, _ = owner_scan(sid, request)
    response.headers['Cache-Control'] = 'no-store'
    try:
        selected = json.loads(destination) if destination else None
    except ValueError as exc:
        raise HTTPException(422, "Invalid release destination") from exc
    if selected is not None and not isinstance(selected, dict):
        raise HTTPException(422, 'Invalid release destination')
    result = service.preview(core.store, sid, owner, files, selected)
    plan = result['planning']
    if plan.get('available') and plan.get('source') == 'local':
        preflight = _preflight_release_destination(request, plan['destination'])
        if not preflight['ready']:
            plan.update(available=False, reason=preflight.get('message') or 'Connect the selected cloud provider with write access, or choose a download package.')
    return result


@router.post('/scans/{sid}/release/automatic')
def authorize(sid: str, body: AuthorizationRequest, request: Request, response: Response):
    owner, scan = owner_scan(sid, request)
    response.headers['Cache-Control'] = 'no-store'
    destination = _release_destination((scan.get('run') or {}).get('source'), body.destination)
    # Same-request replay is inspection, including when Stop has already won.
    previous = persistence.by_request(core.store, owner, sid, body.request_id)
    if previous is None:
        credentials(sid, request)
        if not _preflight_release_destination(request, destination)['ready']:
            raise HTTPException(409, 'Destination is unavailable. Restore access before enabling automatic release.')
    try:
        return service.public(service.authorize(core.store, sid, owner, body.run_id, body.files,
                                               destination, body.request_id, body.expected_source_revision,
                                               allow_remaining_issues=body.allow_remaining_issues,
                                               include_reports=body.include_reports), core.store)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/scans/{sid}/release/automatic/{authorization_id}/stop')
def stop(sid: str, authorization_id: str, request: Request, response: Response):
    owner, _ = owner_scan(sid, request)
    response.headers['Cache-Control'] = 'no-store'
    row = persistence.get(core.store, authorization_id, owner)
    if not row or row['scan_id'] != sid:
        raise HTTPException(404, 'Automatic release authorization not found')
    return service.public(persistence.stop(core.store, authorization_id, owner), core.store)


@router.post('/scans/{sid}/release/automatic/{authorization_id}/resume')
def resume(sid: str, authorization_id: str, request: Request, response: Response):
    owner, _ = owner_scan(sid, request)
    response.headers['Cache-Control'] = 'no-store'
    row = persistence.get(core.store, authorization_id, owner)
    if not row or row['scan_id'] != sid:
        raise HTTPException(404, 'Automatic release authorization not found')
    credentials(sid, request)
    try:
        return service.public(service.resume(core.store, authorization_id, owner, sid), core.store)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
