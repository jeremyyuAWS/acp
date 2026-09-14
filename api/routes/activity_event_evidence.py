"""Protected content lookup; lifecycle narration itself remains content-free."""
from fastapi import APIRouter, HTTPException, Request, Response
import core
from activity_event_evidence import read, exact_copy

router = APIRouter()


def _owner(request):
    return getattr(request.state, 'user_email', None) or 'demo'


@router.get('/scans/{sid}/remediation/activity/{seq}/evidence')
def activity_evidence(sid: str, seq: int, request: Request, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    try:
        return read(core.store, sid, seq, _owner(request))
    except LookupError:
        raise HTTPException(404, 'activity not found')


@router.get('/scans/{sid}/remediation/activity/{seq}/copy')
def activity_copy(sid: str, seq: int, request: Request):
    import blob
    try:
        data = exact_copy(core.store, sid, seq, _owner(request), blob.download_remediated)
    except LookupError:
        raise HTTPException(404, 'activity copy not found')
    except ValueError:
        raise HTTPException(409, 'The recorded saved version is no longer available')
    return Response(data, media_type='application/octet-stream',
                    headers={'Cache-Control': 'no-store', 'Content-Disposition': 'attachment'})
