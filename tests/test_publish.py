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
        self._fake.props.append((body or {}).get("properties"))
        return _Exec({"id": "new-id", "webViewLink": "https://drive/new"})

    # `body` carries the provenance stamp on an upsert — the real Drive API takes it
    # alongside media_body, and dropping it here would hide an unstamped update.
    def update(self, fileId=None, body=None, media_body=None, fields=None):
        self._fake.calls.append(("update", fileId))
        self._fake.props.append((body or {}).get("properties"))
        return _Exec({"id": fileId, "webViewLink": "https://drive/updated"})


class _FakeSvc:
    def __init__(self, list_result=None):
        self.list_result = list_result or []
        self.calls = []
        self.props = []          # `properties` dict passed on each create/update

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


def test_upload_published_stamps_acp_provenance_on_create_and_update():
    """Every copy ACP writes must identify itself, so a later scan skips it by provenance
    rather than by which folder it happens to sit in."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
    import provenance

    created = _FakeSvc(list_result=[])                       # no existing copy -> create
    publish.upload_published(created, "fid", "deck.pptx", b"x")
    assert created.calls[-1][0] == "create"
    assert provenance.is_acp_generated({"properties": created.props[-1]})

    updated = _FakeSvc(list_result=[{"id": "old"}])           # existing copy -> update
    publish.upload_published(updated, "fid", "deck.pptx", b"x")
    assert updated.calls[-1][0] == "update"
    assert provenance.is_acp_generated({"properties": updated.props[-1]})
