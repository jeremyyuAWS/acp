from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from routes import release_folders as folders


def request():
    return SimpleNamespace(state=SimpleNamespace(user_email='owner@example.com'))


def test_drive_creates_named_folder_under_selected_parent(monkeypatch):
    calls = []
    class Files:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(execute=lambda: {'id':'created','name':'Accessibility'})
    monkeypatch.setattr(folders.core, 'drive_service', lambda req: SimpleNamespace(files=Files))
    result = folders.create_folder(folders.NewFolderRequest(provider='drive',parent='selected',name='Accessibility'), request())
    assert result == {'id':'created','name':'Accessibility'}
    assert calls[0]['body'] == {'name':'Accessibility','mimeType':'application/vnd.google-apps.folder','parents':['selected']}
    assert calls[0]['supportsAllDrives'] is True


@pytest.mark.parametrize('parent,segment', [('library/root','root'),('library/selected','items/selected')])
def test_sharepoint_creates_in_library_or_selected_folder(monkeypatch, parent, segment):
    import httpx
    from routes import sharepoint
    monkeypatch.setattr(sharepoint,'_token', lambda req: 'test-token')
    calls=[]
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(status_code=201,raise_for_status=lambda:None,json=lambda:{'id':'created','name':'Accessibility'})
    monkeypatch.setattr(httpx,'post',post)
    result=folders.create_folder(folders.NewFolderRequest(provider='sharepoint',parent=parent,name='Accessibility'),request())
    assert result['id']=='library/created'
    assert calls[0][0].endswith(f'/{segment}/children')
    assert calls[0][1]['json']['@microsoft.graph.conflictBehavior']=='fail'


@pytest.mark.parametrize('name', ['../escape', 'unsafe/name', 'unsafe\\name'])
def test_folder_name_cannot_escape_destination(name):
    with pytest.raises(HTTPException) as exc:
        folders.create_folder(folders.NewFolderRequest(provider='drive',parent='root',name=name),request())
    assert exc.value.status_code==422


def test_sharepoint_requires_real_library_parent():
    with pytest.raises(HTTPException) as exc:
        folders.create_folder(folders.NewFolderRequest(provider='sharepoint',parent='release-site:site',name='Accessibility'),request())
    assert exc.value.status_code==422
