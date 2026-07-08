"""Archive-copy publish (api/publish.py) — pure-logic unit tests with a fake Drive svc.

No network / no real Drive: a fake service records calls and returns canned results, so
we verify the upsert branch, the folder find-vs-create branch, and the graceful
record-only fallbacks (no svc / no Blob copy).
"""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

import publish  # noqa: E402


class _Exec:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class _Files:
    def __init__(self, fake):
        self._fake = fake

    def list(self, q=None, fields=None, orderBy=None, pageSize=None):
        self._fake.calls.append(("list", q))
        return _Exec({"files": self._fake.list_result})

    def create(self, body=None, media_body=None, fields=None):
        self._fake.calls.append(("create", body.get("name") if body else None))
        return _Exec({"id": "new-id", "webViewLink": "https://drive/new"})

    def update(self, fileId=None, media_body=None, fields=None):
        self._fake.calls.append(("update", fileId))
        return _Exec({"id": fileId, "webViewLink": "https://drive/updated"})


class _FakeSvc:
    def __init__(self, list_result=None):
        self.list_result = list_result or []
        self.calls = []

    def files(self):
        return _Files(self)


def test_mime_for():
    assert publish._mime_for("a.pdf") == "application/pdf"
    assert publish._mime_for("b.DOCX").endswith("wordprocessingml.document")
    assert publish._mime_for("c.pptx").endswith("presentationml.presentation")
    assert publish._mime_for("d.unknown") == "application/octet-stream"


def test_ensure_folder_reuses_existing():
    svc = _FakeSvc(list_result=[{"id": "folder-1"}])
    assert publish.ensure_published_folder(svc) == "folder-1"
    assert svc.calls[0][0] == "list"  # no create when one exists


def test_ensure_folder_creates_when_absent():
    svc = _FakeSvc(list_result=[])
    assert publish.ensure_published_folder(svc) == "new-id"
    assert any(c[0] == "create" for c in svc.calls)


def test_upload_published_upserts_existing():
    svc = _FakeSvc(list_result=[{"id": "file-9"}])
    url = publish.upload_published(svc, "folder-1", "report.pdf", b"%PDF-1.4 ...")
    assert url == "https://drive/updated"
    assert any(c[0] == "update" and c[1] == "file-9" for c in svc.calls)


def test_upload_published_creates_new():
    svc = _FakeSvc(list_result=[])
    url = publish.upload_published(svc, "folder-1", "new.pdf", b"%PDF-1.4 ...")
    assert url == "https://drive/new"


def test_archive_copy_record_only_without_svc():
    # No Drive service → None (caller still records publish; Blob is durable).
    assert publish.archive_copy_publish(None, None, "o@x.com", "scan1", "f.pdf") is None


def test_archive_copy_none_when_no_blob(monkeypatch):
    monkeypatch.setattr(publish._blob, "download_remediated", lambda *a, **k: None)
    svc = _FakeSvc(list_result=[])
    assert publish.archive_copy_publish(svc, "folder-1", "o@x.com", "scan1", "f.pdf") is None


def test_archive_copy_publishes_when_blob_present(monkeypatch):
    monkeypatch.setattr(publish._blob, "download_remediated", lambda *a, **k: b"%PDF-1.4 fixed")
    svc = _FakeSvc(list_result=[])
    url = publish.archive_copy_publish(svc, "folder-1", "o@x.com", "scan1", "f.pdf")
    assert url == "https://drive/new"
