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


def test_normalize_relative_path_preserves_hierarchy_and_normalizes_separators():
    folders, leaf = publish.normalize_relative_path(
        r"HR\Policies\Leave Policy.docx", "Leave Policy.docx")
    assert folders == ["HR", "Policies"]
    assert leaf == "Leave Policy.docx"


def test_normalize_relative_path_rejects_traversal_absolute_and_controls():
    import pytest
    for unsafe in ("../secret/report.pdf", "/etc/report.pdf", "C:/tmp/report.pdf",
                   "HR//report.pdf", "HR/\x00/report.pdf"):
        with pytest.raises(publish.UnsafeReleasePath):
            publish.normalize_relative_path(unsafe, "report.pdf")


def test_provider_invalid_characters_are_normalized_without_flattening():
    assert publish.normalize_relative_path("HR:West/Forms?/a.pdf", "a.pdf") == \
        (["HR_West", "Forms_"], "a.pdf")


def test_publication_key_changes_with_content_version_and_source_identity():
    one = publish.publication_key("release", "source-a", "checksum-1")
    assert one == publish.publication_key("release", "source-a", "checksum-1")
    assert one != publish.publication_key("release", "source-a", "checksum-2")
    assert one != publish.publication_key("release", "source-b", "checksum-1")


def test_idempotent_upload_reuses_existing_document_without_overwrite():
    svc = _FakeSvc(list_result=[{
        "id": "published-1", "webViewLink": "https://drive/existing"
    }])
    result = publish.upload_published(
        svc, "release-folder", "report.pdf", b"fixed",
        idempotency_key="stable-key", return_details=True)
    assert result["id"] == "published-1"
    assert result["created"] is False
    assert not any(call[0] in ("create", "update") for call in svc.calls)


def test_sharepoint_relative_path_removes_graph_locator_and_preserves_hierarchy():
    folders, leaf = publish.sharepoint_relative_path(
        "/drives/library/root:/HR/Policies", "Leave Plan.docx")
    assert folders == ["HR", "Policies"]
    assert leaf == "Leave Plan.docx"


def test_sharepoint_child_lookup_follows_nextlink_before_deciding_name_is_free(monkeypatch):
    import scanner
    pages = {
        "https://graph/items/folder/children?$select=id,name,file,size,webUrl&$top=200": {
            "value": [{"id": str(i), "name": f"other-{i}.pdf"} for i in range(200)],
            "@odata.nextLink": "https://graph/second",
        },
        "https://graph/second": {
            "value": [{"id": "existing", "name": "report.pdf", "webUrl": "https://sp/report"}]
        },
    }
    calls = []
    monkeypatch.setattr(scanner, "_sp_get",
                        lambda token, url: calls.append(url) or pages[url])
    monkeypatch.setattr(scanner, "_sp_base", lambda drive: "https://graph")

    found = publish._sp_child("token", "drive", "folder", "report.pdf")

    assert found["id"] == "existing"
    assert calls == [
        "https://graph/items/folder/children?$select=id,name,file,size,webUrl&$top=200",
        "https://graph/second",
    ]


def test_sharepoint_folder_reuse_follows_every_page_and_does_not_create(monkeypatch):
    import httpx
    import scanner
    pages = {
        "https://graph/items/parent/children?$select=id,name,folder&$top=200": {
            "value": [{"id": str(i), "name": f"folder-{i}", "folder": {}} for i in range(200)],
            "@odata.nextLink": "https://graph/folders-page-2",
        },
        "https://graph/folders-page-2": {
            "value": [{"id": "winner", "name": "Policies", "folder": {}}]
        },
    }
    monkeypatch.setattr(scanner, "_sp_base", lambda drive: "https://graph")
    monkeypatch.setattr(scanner, "_sp_get", lambda token, url: pages[url])
    monkeypatch.setattr(httpx, "post",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not create")))

    assert publish._sp_ensure_folder("token", "drive", "parent", "Policies") == "winner"


def test_sharepoint_release_root_collision_on_later_page_gets_stable_suffix(monkeypatch):
    import scanner
    folder_calls = []
    monkeypatch.setattr(publish, "_sp_ensure_folder",
                        lambda token, drive, parent_id, name:
                        folder_calls.append((name, parent_id)) or
                        ("root" if not parent_id else "release-folder"))
    monkeypatch.setattr(scanner, "_sp_base", lambda drive: "https://graph")
    pages = {
        "https://graph/items/root/children?$select=id,name,folder,webUrl&$top=200": {
            "value": [{"id": str(i), "name": f"older-{i}", "folder": {}} for i in range(200)],
            "@odata.nextLink": "https://graph/roots-page-2",
        },
        "https://graph/roots-page-2": {
            "value": [{"id": "same-minute", "name": "2026-09-05 10-00 UTC", "folder": {}}]
        },
        "https://graph/items/release-folder?$select=id,name,webUrl": {
            "id": "release-folder", "name": "2026-09-05 10-00 UTC · abcdef12",
            "webUrl": "https://sp/release",
        },
    }
    monkeypatch.setattr(scanner, "_sp_get", lambda token, url: pages[url])

    result = publish.ensure_sharepoint_release_folder(
        "token", "drive", "abcdef123456", "2026-09-05 10-00 UTC")

    assert folder_calls[-1] == ("2026-09-05 10-00 UTC · abcdef12", "root")
    assert result["id"] == "release-folder"


def test_sharepoint_publish_reuses_identical_copy_without_writing(monkeypatch):
    data = b"corrected"
    digest = __import__("hashlib").sha256(data).hexdigest()
    monkeypatch.setattr(publish._blob, "download_remediated", lambda *a, **k: data)
    monkeypatch.setattr(publish, "_sp_child", lambda *a, **k: {
        "id": "existing", "name": "report.pdf", "webUrl": "https://sp/existing"
    })
    monkeypatch.setattr(publish, "_sp_content_matches",
                        lambda token, drive, item, expected: expected == digest)
    import scanner
    monkeypatch.setattr(publish, "_sp_ensure_folder", lambda *a, **k: "unused")
    monkeypatch.setattr(scanner, "_sp_write",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not write")))

    result = publish.archive_copy_publish_sharepoint(
        "token", "drive", "release", "owner", "rel", "scan", "report.pdf",
        None, "source")
    assert result == {"id": "existing", "url": "https://sp/existing",
                      "checksum": digest, "verified": True, "created": False,
                      "filename": "report.pdf"}


def test_sharepoint_publish_preserves_hierarchy_and_never_overwrites_collision(monkeypatch):
    data = b"new corrected bytes"
    monkeypatch.setattr(publish._blob, "download_remediated", lambda *a, **k: data)
    children = {
        "report.pdf": {"id": "source-name", "name": "report.pdf", "webUrl": "old"},
    }
    monkeypatch.setattr(publish, "_sp_child",
                        lambda token, drive, parent, name: children.get(name))
    monkeypatch.setattr(publish, "_sp_content_matches",
                        lambda token, drive, item, expected: item == "uploaded")
    import scanner
    folders = []
    monkeypatch.setattr(publish, "_sp_ensure_folder",
                        lambda token, drive, parent_id, name:
                        folders.append((parent_id, name)) or f"folder-{name}")
    monkeypatch.setattr(scanner, "_sp_base", lambda drive: "https://graph/drive")
    writes = []
    def _write(token, **kwargs):
        writes.append(kwargs)
        return {"id": "uploaded", "webUrl": "https://sp/uploaded"}
    monkeypatch.setattr(scanner, "_sp_write", _write)

    result = publish.archive_copy_publish_sharepoint(
        "token", "drive", "release", "owner", "rel", "scan", "report.pdf",
        "/drives/drive/root:/HR/Policies", "source")

    assert folders == [("release", "HR"), ("folder-HR", "Policies")]
    assert result["created"] is True
    assert result["filename"].startswith("report (")
    assert writes[0]["put_url"].endswith(f"/{result['filename'].replace(' ', '%20').replace('(', '%28').replace(')', '%29')}:/content")
