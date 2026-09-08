"""Presentation-only waterfall telemetry; existing execution policy is unchanged."""
from fastapi import APIRouter, HTTPException, Request, Response

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
