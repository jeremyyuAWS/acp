"""Presentation-only waterfall telemetry; existing execution policy is unchanged."""
from fastapi import APIRouter, HTTPException, Request, Response, Query

router = APIRouter()


@router.get('/scans/{sid}/remediation/waterfall/{batch_id}')
def waterfall_status(sid: str, batch_id: str, request: Request, response: Response):
    import core
    from remediation_waterfall_view import read_waterfall
    owner = getattr(request.state, 'user_email', None) or 'demo'
    response.headers['Cache-Control'] = 'no-store'
    try:
        return read_waterfall(core.store, owner, sid, batch_id)
    except LookupError as exc:
        raise HTTPException(404, 'scan not found') from exc


@router.get('/scans/{sid}/remediation/insights/{batch_id}')
def run_insights(sid: str, batch_id: str, request: Request, response: Response,
                 offset: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=200)):
    import core
    from remediation_run_insights import read_insights
    owner = getattr(request.state, 'user_email', None) or 'demo'
    response.headers['Cache-Control'] = 'no-store'
    if core.store.get_scan(sid, owner=owner) is None:
        raise HTTPException(404, 'scan not found')
    try:
        return read_insights(core.store, owner, sid, batch_id, offset=offset, limit=limit)
    except (PermissionError, LookupError) as exc:
        raise HTTPException(404, 'remediation run not found') from exc


@router.get('/scans/{sid}/remediation/activity')
def recent_activity(sid: str, request: Request, response: Response):
    import core
    from routes.scans import _owner
    from remediation_activity_history import read_recent_activity
    response.headers['Cache-Control'] = 'no-store'
    return read_recent_activity(core.store, sid, _owner(request))


@router.get('/scans/{sid}/remediation/waterfall/{batch_id}/metrics')
def drawer_metrics(sid: str, batch_id: str, request: Request, response: Response,
                   stage: str | None = Query(default=None), provider: str | None = Query(default=None, max_length=256),
                   model: str | None = Query(default=None, max_length=256)):
    import core
    from waterfall_drawer_metrics import read_metrics
    from routes.scans import _owner
    response.headers['Cache-Control'] = 'no-store'
    try:
        return read_metrics(core.store, _owner(request), sid, batch_id, stage=stage, provider=provider, model=model)
    except LookupError as exc:
        raise HTTPException(404, 'remediation run not found') from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
