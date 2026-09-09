"""One explicit Release intent, inspectable and resumable across browser sessions."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
import core
import release_continuation as service
import release_continuation_store as persistence
from routes.scans import _release_destination, _preflight_release_destination

router = APIRouter()


def public_state(row):
    """Inspection needs eligible proposals and blockers, not old applied content.

    Full frozen inputs remain server-side for every authorization check. The
    client only submits the immutable intent ID, never this display projection.
    """
    if row is None:
        return None
    intent = row['intent']
    return {**row, 'intent': {**intent, 'files': {
        file: {**entry, 'rows': [item for item in entry['rows'] if item['authorize']]}
        for file, entry in intent['files'].items()}}}


class PlanRequest(BaseModel):
    files: list[str]
    destination: dict | None = None
    release_folder_name: str | None = None


def owner_scan(sid, request):
    owner = getattr(request.state, 'user_email', None)
    if not owner:
        raise HTTPException(401, 'Sign in required')
    scan = core.store.get_scan(sid, owner=owner)
    if not scan:
        raise HTTPException(404, 'scan not found')
    return owner, scan


def credentials(sid, request):
    core.register_scan_tokens(sid, drive=request.headers.get('x-drive-token'),
                              sp=request.headers.get('x-sp-token'), require_shared=True)


@router.post('/scans/{sid}/release/continuation/plan')
def plan(sid: str, body: PlanRequest, request: Request):
    owner, scan = owner_scan(sid, request)
    import publish
    destination = _release_destination(scan['run'].get('source') or 'local', body.destination)
    try:
        folder_name = publish.normalize_release_name(body.release_folder_name, field='Release folder name')
        return public_state(service.plan(core.store, sid, owner, body.files, destination, folder_name))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get('/scans/{sid}/release/continuation')
def status(sid: str, request: Request):
    owner, _ = owner_scan(sid, request)
    return public_state(persistence.latest(core.store, sid, owner))


@router.post('/scans/{sid}/release/continuation/{intent_id}/authorize')
def authorize(sid: str, intent_id: str, request: Request):
    owner, _ = owner_scan(sid, request)
    row = persistence.get(core.store, intent_id, owner)
    if not row or row['scan_id'] != sid:
        raise HTTPException(404, 'Release plan not found')
    credentials(sid, request)
    if not _preflight_release_destination(request, row['intent']['destination'])['ready']:
        raise HTTPException(409, 'Destination is unavailable. Check access before authorizing.')
    try:
        return public_state(service.authorize(core.store, intent_id, owner))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/scans/{sid}/release/continuation/{intent_id}/resume')
def resume(sid: str, intent_id: str, request: Request):
    owner, _ = owner_scan(sid, request)
    row = persistence.get(core.store, intent_id, owner)
    if not row or row['scan_id'] != sid:
        raise HTTPException(404, 'Release plan not found')
    credentials(sid, request)
    try:
        return public_state(service.resume(core.store, intent_id, owner))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
