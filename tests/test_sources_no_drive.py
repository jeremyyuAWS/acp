"""/sources must not 401 a signed-in user who has no Google Drive (e.g. a Microsoft sign-in).

/sources is Google-Drive-specific; SharePoint sources come from /sharepoint/sites. In GIS mode with
no X-Drive-Token, core.drive_service raises 401 "sign in with Google" — and the SPA reads ANY 401 as
an expired session, so it bounced an otherwise-authenticated Microsoft user off the app AND cleared
their token, cascading a second 401 onto the concurrent /scans/active call. Found live 2026-08-11.

These pin that /sources returns an empty list instead, that the cascade victim stays authenticated,
and that a real Drive token still lists Drive.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

USER = "jeremy_acp@fgxlxj.onmicrosoft.com"


@pytest.fixture()
def gated(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient

    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "verify_ms_token", lambda tok: USER)
    monkeypatch.setattr(core, "email_allowed", lambda e: True)
    return TestClient(app)


def _ms():
    return {"Authorization": "Bearer t", "X-Auth-Provider": "microsoft"}


def test_sources_without_drive_token_is_empty_not_401(gated):
    r = gated.get("/sources", headers=_ms())
    assert r.status_code == 200          # NOT 401 — the bounce that stranded every Microsoft user
    assert r.json() == []


def test_scans_active_stays_authenticated(gated):
    # The cascade victim: /sources no longer 401s, so it never clears the token, so this stays 200.
    r = gated.get("/scans/active", headers=_ms())
    assert r.status_code == 200


def test_sources_with_drive_token_still_lists_drive(gated, monkeypatch):
    import core
    svc = MagicMock()
    svc.about.return_value.get.return_value.execute.return_value = {"user": {"displayName": "Jer"}}
    svc.files.return_value.list.return_value.execute.return_value = {"files": [{"id": "1"}, {"id": "2"}]}
    monkeypatch.setattr(core, "drive_service", lambda request=None: svc)
    r = gated.get("/sources?include_counts=true", headers={**_ms(), "X-Drive-Token": "gd"})
    assert r.status_code == 200
    body = r.json()
    assert body and body[0]["type"] == "google_drive"
    assert body[0]["name"] == "My Drive"
    assert body[0]["files"] == 2


def test_source_connection_does_not_enumerate_files(gated, monkeypatch):
    import core
    svc = MagicMock()
    svc.about.return_value.get.return_value.execute.return_value = {"user": {"displayName": "Jer"}}
    monkeypatch.setattr(core, "drive_service", lambda request=None: svc)
    r = gated.get("/sources", headers={**_ms(), "X-Drive-Token": "gd"})
    assert r.status_code == 200
    assert r.json()[0]["files"] is None
    svc.files.assert_not_called()


def test_folder_name_lookup_is_metadata_only_and_uses_callers_service(gated, monkeypatch):
    import core
    svc = MagicMock()
    svc.files.return_value.get.return_value.execute.return_value = {
        "id": "folder_123", "name": "Clinical Guidelines", "mimeType": "application/vnd.google-apps.folder"}
    monkeypatch.setattr(core, "drive_service", lambda request: svc)
    response = gated.get('/drive/folder-name?id=folder_123', headers=_ms())
    assert response.status_code == 200
    assert response.json()['name'] == 'Clinical Guidelines'
    svc.files.return_value.list.assert_not_called()
    assert svc.files.return_value.get.call_args.kwargs['supportsAllDrives'] is True


def test_folder_name_requires_authentication_and_rejects_nonfolder(gated, monkeypatch):
    import core
    svc = MagicMock()
    svc.files.return_value.get.return_value.execute.return_value = {'name': 'Document', 'mimeType': 'application/pdf'}
    monkeypatch.setattr(core, 'drive_service', lambda request: svc)
    assert gated.get('/drive/folder-name?id=x').status_code == 401
    assert gated.get('/drive/folder-name?id=x', headers=_ms()).status_code == 404
    assert gated.get('/drive/folder-name?id=bad/id', headers=_ms()).status_code == 400
