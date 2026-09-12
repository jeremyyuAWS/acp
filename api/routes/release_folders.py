"""Create a user-named delivery folder using the selected provider's write grant."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, StrictStr
import core
import scanner
import publish

router = APIRouter()


class NewFolderRequest(BaseModel):
    provider: StrictStr
    parent: StrictStr = Field(min_length=1, max_length=500)
    name: StrictStr = Field(min_length=1, max_length=255)


@router.post('/release/folders')
def create_folder(body: NewFolderRequest, request: Request):
    try:
        name = publish.normalize_release_name(body.name, field='Folder name')
    except publish.UnsafeReleasePath as exc:
        raise HTTPException(422, str(exc)) from exc
    if not name:
        raise HTTPException(422, 'Enter a folder name')
    if body.provider == 'drive':
        from routes.drive import _drive_error
        try:
            service = core.drive_service(request)
            folder = service.files().create(body={'name':name, 'mimeType':'application/vnd.google-apps.folder', 'parents':[body.parent]}, fields='id,name', supportsAllDrives=True).execute()
            return dict(id=folder['id'], name=folder['name'])
        except HTTPException:
            raise
        except Exception as exc:
            raise _drive_error(exc) from exc
    if body.provider != 'sharepoint' or '/' not in body.parent or body.parent.startswith('release-site:'):
        raise HTTPException(422, 'Choose a document library or folder first')
    from routes.sharepoint import _token
    import httpx
    drive, _, parent = body.parent.partition('/')
    try:
        segment = 'root' if parent == 'root' else f'items/{parent}'
        response = httpx.post(f'{scanner._sp_base(drive)}/{segment}/children', headers={'Authorization':f'Bearer {_token(request)}'}, json={'name':name,'folder':{},'@microsoft.graph.conflictBehavior':'fail'}, timeout=30)
        if response.status_code == 409:
            raise HTTPException(409, 'A folder with this name already exists. Choose it or enter a different name.')
        response.raise_for_status()
        folder = response.json()
        return dict(id=f"{drive}/{folder['id']}", name=folder['name'])
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(502, 'The folder could not be confirmed. Refresh the folder list before creating another.') from exc
