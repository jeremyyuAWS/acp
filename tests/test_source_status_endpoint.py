"""GET /scans/{sid}/source-status — end to end through the real gate, with a FAKE Drive service
(monkeypatched core.drive_service) so no network or credentials are involved. Pins the four
states, the counts, owner isolation (404), and that a non-Drive scan never touches Drive."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "jeremyyu.movate@gmail.com"
NON_OWNER = "devamovate@gmail.com"


# ── a fake Drive service: svc.files().get(fileId=...).execute() → {"modifiedTime": ...} ──────────
class _FakeGet:
    def __init__(self, result=None, exc=None):
        self._result, self._exc = result, exc

    def execute(self):
        if self._exc:
            raise self._exc
        return self._result


class _FakeFiles:
    def __init__(self, current, errors):
        self._current, self._errors = current, errors

    def get(self, fileId=None, **_kw):
        if fileId in self._errors:
            return _FakeGet(exc=self._errors[fileId])
        return _FakeGet(result={"modifiedTime": self._current.get(fileId)})


class _FakeSvc:
    def __init__(self, current=None, errors=None):
        self._files = _FakeFiles(current or {}, errors or {})

    def files(self):
        return self._files


def _http_error(status):
    from googleapiclient.errors import HttpError

    class _Resp:
        def __init__(self, s):
            self.status = s
            self.reason = "err"

    return HttpError(_Resp(status), b"{}")


def _f(name, drive_id, source_modified):
    return {"file": name, "engine": "office", "status": "PASS", "score": 90,
            "compliant": 1, "skipped_rules": 0, "issues": [],
            "drive_file_id": drive_id, "source_modified": source_modified}


def _seed(store, sid, owner, files, source="drive"):
    store.save_scan({
        "_scan_id": sid, "started_at": "2026-08-01T10:00:00+00:00",
        "completed_at": "2026-08-01T10:01:00+00:00", "source": source, "owner": owner,
        "rubric": {"name": "wcag-aa", "hash": "h"},
        "summary": {"files": len(files), "certifiable": len(files), "uncertain": 0, "error": 0, "avg_score": 90},
        "files": files,
    })


@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: e in (OWNER, NON_OWNER))

    client = TestClient(app)

    def as_user(email):
        client.headers.update({"Authorization": f"Bearer {email}"})
        return client

    return as_user


def test_classifies_stale_unchanged_untracked_unavailable(gated_client, isolated_store, monkeypatch):
    import core
    _seed(isolated_store, "scan1", OWNER, [
        _f("stale.docx", "1stale", "2026-08-01T09:00:00.000Z"),
        _f("same.docx", "1same", "2026-08-01T09:00:00.000Z"),
        _f("legacy.docx", None, None),                       # no id + no baseline → untracked
        _f("gone.docx", "1gone", "2026-08-01T09:00:00.000Z"),
    ])
    current = {"1stale": "2026-08-05T00:00:00.000Z", "1same": "2026-08-01T09:00:00.000Z"}
    errors = {"1gone": _http_error(404)}
    monkeypatch.setattr(core, "drive_service", lambda request=None: _FakeSvc(current, errors))

    res = gated_client(OWNER).get("/scans/scan1/source-status")
    assert res.status_code == 200
    body = res.json()
    states = {r["file"]: r["state"] for r in body["files"]}
    assert states == {"stale.docx": "stale", "same.docx": "unchanged",
                      "legacy.docx": "untracked", "gone.docx": "unavailable"}
    assert (body["stale_count"], body["untracked_count"], body["unavailable_count"]) == (1, 1, 1)
    assert next(r for r in body["files"] if r["file"] == "gone.docx")["error"] == "not_found"


def test_non_owner_gets_404(gated_client, isolated_store, monkeypatch):
    import core
    _seed(isolated_store, "scan2", OWNER, [_f("x.docx", "1x", "2026-08-01T09:00:00.000Z")])
    monkeypatch.setattr(core, "drive_service", lambda request=None: _FakeSvc())
    assert gated_client(NON_OWNER).get("/scans/scan2/source-status").status_code == 404


def test_sharepoint_scan_is_all_untracked_and_never_calls_drive(gated_client, isolated_store, monkeypatch):
    import core
    _seed(isolated_store, "scan3", OWNER,
          [_f("policy.docx", "1p", "2026-08-01T09:00:00.000Z")], source="sharepoint")

    def _must_not_call(request=None):
        raise AssertionError("drive_service must not be called for a non-Drive scan")

    monkeypatch.setattr(core, "drive_service", _must_not_call)
    res = gated_client(OWNER).get("/scans/scan3/source-status")
    assert res.status_code == 200
    assert all(r["state"] == "untracked" for r in res.json()["files"])
