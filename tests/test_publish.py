"""Archive-copy publish (api/publish.py) — pure-logic unit tests with a fake Drive svc.

No network / no real Drive: a fake service records calls and returns canned results, so
we verify the upsert branch, the folder find-vs-create branch, and the graceful
record-only fallbacks (no svc / no Blob copy).
"""
import io
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

import publish  # noqa: E402


def test_release_folder_name_uses_selected_us_or_india_timezone():
    from datetime import datetime, timezone
    at = datetime(2026, 9, 6, 14, 46, tzinfo=timezone.utc)
    assert publish.release_folder_name(at, "Asia/Kolkata") == "2026-09-06 20-16 IST"
    assert publish.release_folder_name(at, "America/Los_Angeles") == "2026-09-06 07-46 PDT"


def test_release_folder_name_rejects_arbitrary_timezones():
    with pytest.raises(ValueError, match="unsupported release timezone"):
        publish.release_folder_name(timezone_name="Europe/London")


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
        if media_body is not None:
            self._fake.data = media_body.getbytes(0, media_body.size())
        return _Exec({"id": "new-id", "webViewLink": "https://drive/new"})

    # `body` carries the provenance stamp on an upsert — the real Drive API takes it
    # alongside media_body, and dropping it here would hide an unstamped update.
    def update(self, fileId=None, body=None, media_body=None, fields=None):
        self._fake.calls.append(("update", fileId))
        self._fake.props.append((body or {}).get("properties"))
        if media_body is not None:
            self._fake.data = media_body.getbytes(0, media_body.size())
        return _Exec({"id": fileId, "webViewLink": "https://drive/updated"})

    def get_media(self, fileId=None):
        return _Exec(self._fake.data)


class _FakeSvc:
    def __init__(self, list_result=None):
        self.list_result = list_result or []
        self.calls = []
        self.data = b""
        self.props = []          # `properties` dict passed on each create/update

    def files(self):
        return _Files(self)


def test_mime_for():
    assert publish._mime_for("a.pdf") == "application/pdf"
    assert publish._mime_for("b.DOCX").endswith("wordprocessingml.document")
    assert publish._mime_for("c.pptx").endswith("presentationml.presentation")
    assert publish._mime_for("d.unknown") == "application/octet-stream"


def test_release_names_allow_human_labels_but_reject_paths():
    assert publish.normalize_release_name(
        "  Q3 Accessibility Release  ", field="Release folder name") == "Q3 Accessibility Release"
    assert publish.normalize_release_name("", field="ZIP filename") is None
    try:
        publish.normalize_release_name("Q3/exports", field="ZIP filename")
    except publish.UnsafeReleasePath as exc:
        assert "ZIP filename" in str(exc)
    else:
        raise AssertionError("a path must not be accepted as a release name")
    with pytest.raises(publish.UnsafeReleasePath, match="cannot end"):
        publish.normalize_release_name("Q3 release.", field="Release folder name")


def test_ensure_folder_reuses_existing():
    svc = _FakeSvc(list_result=[{"id": "folder-1"}])
    assert publish.ensure_published_folder(svc) == "folder-1"
    assert svc.calls[0][0] == "list"  # no create when one exists


def test_ensure_folder_creates_when_absent():
    svc = _FakeSvc(list_result=[])
    assert publish.ensure_published_folder(svc) == "new-id"
    assert any(c[0] == "create" for c in svc.calls)


def test_ensure_release_folder_uses_the_reviewed_custom_name():
    svc = _FakeSvc(list_result=[])
    details = publish.ensure_published_folder(
        svc, "release-1", folder_name="Q3 Accessibility Release", return_details=True)
    assert details["name"] == "Q3 Accessibility Release"
    assert ("create", "Q3 Accessibility Release") in svc.calls


def test_drive_release_root_is_created_under_the_selected_parent():
    svc = _FakeSvc(list_result=[])
    publish.ensure_published_folder(
        svc, "release-1", folder_name="Release", parent_id="finance",
        return_details=True)
    assert any("'finance' in parents" in (call[1] or "")
               for call in svc.calls if call[0] == "list")


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
    svc.data = b"fixed"
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


def test_sharepoint_release_root_reuses_its_durably_claimed_name(monkeypatch):
    import scanner
    folder_calls = []
    monkeypatch.setattr(publish, "_sp_ensure_folder",
                        lambda token, drive, parent_id, name:
                        folder_calls.append((name, parent_id)) or
                        ("root" if not parent_id else "release-folder"))
    monkeypatch.setattr(scanner, "_sp_base", lambda drive: "https://graph")
    pages = {
        "https://graph/items/release-folder?$select=id,name,webUrl": {
            "id": "release-folder", "name": "2026-09-05 10-00 UTC",
            "webUrl": "https://sp/release",
        },
    }
    monkeypatch.setattr(scanner, "_sp_get", lambda token, url: pages[url])

    result = publish.ensure_sharepoint_release_folder(
        "token", "drive", "abcdef123456", "2026-09-05 10-00 UTC")

    assert folder_calls[-1] == ("2026-09-05 10-00 UTC", "root")
    assert result["id"] == "release-folder"


def test_sharepoint_release_root_is_created_under_the_selected_parent(monkeypatch):
    import scanner
    folder_calls = []
    monkeypatch.setattr(publish, "_sp_ensure_folder",
                        lambda token, drive, parent_id, name:
                        folder_calls.append((name, parent_id)) or
                        ("root" if name == "Remediated" else "release-folder"))
    monkeypatch.setattr(scanner, "_sp_base", lambda drive: "https://graph")
    monkeypatch.setattr(scanner, "_sp_get", lambda token, url: {
        "id": "release-folder", "name": "Release", "webUrl": "https://sp/release"})
    publish.ensure_sharepoint_release_folder(
        "token", "drive", "release-1", "Release", parent_id="finance")
    assert folder_calls[0] == ("Remediated", "finance")


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
    assert writes[0]["conflict_behavior"] == "fail"
    assert writes[0]["force_session"] is True


def test_sharepoint_publish_uses_original_name_but_internal_blob_identity(monkeypatch):
    downloaded = []
    monkeypatch.setattr(publish._blob, "download_remediated",
                        lambda owner, scan, name: downloaded.append(name) or b"corrected")
    monkeypatch.setattr(publish, "_sp_child", lambda *a, **k: None)
    monkeypatch.setattr(publish, "_sp_content_matches", lambda *a, **k: True)
    monkeypatch.setattr(publish, "_sp_ensure_folder", lambda *a, **k: "parent")
    import scanner
    monkeypatch.setattr(scanner, "_sp_base", lambda drive: "https://graph/drive")
    writes = []
    monkeypatch.setattr(scanner, "_sp_write",
                        lambda token, **kwargs: writes.append(kwargs) or
                        {"id": "created", "webUrl": "https://sp/created"})

    result = publish.archive_copy_publish_sharepoint(
        "token", "drive", "release", "owner", "rel", "scan", "report (1).pdf",
        "/drives/drive/root:/Legal", "source-2", source_filename="report.pdf")

    assert downloaded == ["report (1).pdf"]
    assert writes[0]["put_url"].endswith("/report.pdf:/content")
    assert result["filename"] == "report.pdf"


def test_sharepoint_publish_uses_atomic_fail_on_conflict_even_for_small_files(monkeypatch):
    """The child lookup is advisory. A sibling can appear after it, so a path PUT must never
    silently replace that new file; every release copy uses Graph's atomic session contract."""
    monkeypatch.setattr(publish._blob, "download_remediated", lambda *a, **k: b"small")
    monkeypatch.setattr(publish, "_sp_child", lambda *a, **k: None)
    monkeypatch.setattr(publish, "_sp_content_matches", lambda *a, **k: True)
    monkeypatch.setattr(publish, "_sp_ensure_folder", lambda *a, **k: "parent")
    import scanner
    monkeypatch.setattr(scanner, "_sp_base", lambda drive: "https://graph/drive")
    seen = {}

    def write(token, **kwargs):
        seen.update(kwargs)
        return {"id": "created", "webUrl": "https://sp/created"}

    monkeypatch.setattr(scanner, "_sp_write", write)
    publish.archive_copy_publish_sharepoint(
        "token", "drive", "release", "owner", "rel", "scan", "report.pdf",
        None, "source")

    assert seen["conflict_behavior"] == "fail"
    assert seen["force_session"] is True


def test_sharepoint_name_requires_timestamp_and_authenticated_email_even_with_custom_label():
    from datetime import datetime, timezone
    at = datetime(2026, 9, 9, 22, 30, tzinfo=timezone.utc)
    assert publish.sharepoint_release_name(None, 'reviewer@example.com', at=at) == '2026-09-09 22-30 UTC - reviewer@example.com'
    assert publish.sharepoint_release_name('Board packet', 'reviewer@example.com', at=at) == '2026-09-09 22-30 UTC - reviewer@example.com - Board packet'
    spoofed = publish.sharepoint_release_name('2026-09-09 22-30 UTC - other@example.com', 'reviewer@example.com', at=at)
    assert spoofed.startswith('2026-09-09 22-30 UTC - reviewer@example.com - ')


def test_sharepoint_reviewed_name_is_stable_across_minutes_and_timezone_changes():
    from datetime import datetime, timezone, timedelta
    at = datetime(2026, 9, 9, 22, 30, tzinfo=timezone.utc)
    name = publish.sharepoint_release_name('Board packet', 'reviewer@example.com', at=at, timezone_name='America/Los_Angeles')
    assert name == '2026-09-09 15-30 PDT - reviewer@example.com - Board packet'
    assert publish.sharepoint_release_name(name, 'reviewer@example.com', at=at + timedelta(minutes=5)) == name


def test_release_identity_is_one_safe_segment_and_obeys_length_limit():
    from datetime import datetime, timezone
    at = datetime(2026, 9, 9, tzinfo=timezone.utc)
    name = publish.sharepoint_release_name(None, 'bad/path\\name:*?<>|@example.com', at=at)
    assert publish.normalize_release_name(name, field='folder') == name
    assert '/' not in name and '\\' not in name
    long_owner = 'x' * 150 + '@example.com'
    name = publish.sharepoint_release_name('Label', long_owner, at=at)
    assert len(name) <= 100
    assert publish.sharepoint_release_name(name, long_owner, at=at) == name
