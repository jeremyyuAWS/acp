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
