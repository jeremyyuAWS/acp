"""Writing remediated copies back to SharePoint, and not re-ingesting them next scan.

The write itself is the easy half. The half that matters is the one provenance.py exists for:
"Discovery must never re-ingest ACP's own output. A remediated copy re-discovered as a source
document inflates the file count, produces a phantom duplicate, and shows up as `remediated ✓`
on a scan that remediated nothing."

Drive solves it by stamping the ARTIFACT. Graph has no equivalent of Drive's arbitrary
`properties`, so this ships FOLDER-scoped — the approach provenance.py explicitly rejects for
Drive, chosen here with the limitation written down. These tests pin what it does and does not
cover, so the gap stays a known one rather than becoming an assumed solution.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import scanner  # noqa: E402


class _Resp:
    def __init__(self, payload=None, status=200, content=b""):
        self._payload = payload if payload is not None else {}
        self.status_code = status
        self.content = content or (b"{}" if payload is not None else b"")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _item(iid, name, parent_path):
    """A Graph search hit, with the parentReference path the exclusion reads."""
    return {"id": iid, "name": name, "file": {},
            "parentReference": {"path": f"/drive/root:{parent_path}"}}


def _stub_search(monkeypatch, items, mirror="Remediated"):
    import httpx
    import types

    monkeypatch.setattr(httpx, "get", lambda url, **kw: _Resp({"value": items}))
    # `_sp_list` does `import core` INSIDE the function, so patching scanner.core would do
    # nothing — the name is resolved from sys.modules at call time. Replacing the module there
    # is the only thing that reaches it, and it also keeps the test off a real database.
    fake = types.ModuleType("core")
    fake.store = types.SimpleNamespace(get_drive_mirror_folder=lambda: mirror)
    monkeypatch.setitem(sys.modules, "core", fake)


def test_files_in_the_mirror_folder_are_not_re_ingested(monkeypatch):
    """The whole point. A remediated copy must not come back as a source document."""
    _stub_search(monkeypatch, [
        _item("i1", "policy.docx", "/Policies"),
        _item("i2", "policy.docx", "/Remediated"),
    ])
    out = scanner._sp_list("tok", 50, exclude_remediated=True)
    assert [f["id"] for f in out] == ["i1"]


def test_nested_under_the_mirror_is_also_excluded(monkeypatch):
    """Drive's own exclusion missed this: `not '<id>' in parents` only excluded files sitting
    DIRECTLY in the folder, so anything one level down was re-ingested. Matching a path segment
    catches the nested case that bug was about."""
    _stub_search(monkeypatch, [_item("i1", "deep.docx", "/Remediated/2026-08")])
    assert scanner._sp_list("tok", 50, exclude_remediated=True) == []


def test_a_similarly_named_library_is_still_scanned(monkeypatch):
    """"Remediated Policies" is a different folder. Substring matching would silently stop
    scanning it, and an estate that quietly shrinks is the failure mode nobody reports."""
    _stub_search(monkeypatch, [_item("i1", "a.docx", "/Remediated Policies")])
    assert [f["id"] for f in scanner._sp_list("tok", 50, exclude_remediated=True)] == ["i1"]


def test_exclusion_is_off_unless_asked(monkeypatch):
    """Default behaviour is unchanged — the flag is opt-in, exactly as the Drive path's is."""
    _stub_search(monkeypatch, [_item("i2", "policy.docx", "/Remediated")])
    assert len(scanner._sp_list("tok", 50)) == 1


def test_small_files_use_a_single_put(monkeypatch):
    seen: list[tuple[str, str]] = []
    import httpx
    monkeypatch.setattr(httpx, "get", lambda url, **kw: _Resp(
        {"value": [{"id": "F", "name": "Remediated", "folder": {}}]}))
    monkeypatch.setattr(httpx, "put", lambda url, **kw: seen.append(("put", url)) or
                        _Resp({"webUrl": "https://x/f.docx"}, content=b"{}"))
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: pytest.fail("no session for a small file"))

    out = scanner._sp_upload("tok", "d1", "Remediated", "f.docx", b"x" * 10)
    assert out["webUrl"] == "https://x/f.docx"
    assert seen[0][1] == ("https://graph.microsoft.com/v1.0/drives/d1/items/F:/f.docx:/content")


def test_large_files_use_a_resumable_session_in_320k_multiples(monkeypatch):
    """Graph rejects a simple PUT past 4 MiB, and requires every chunk but the last to be a
    multiple of 320 KiB — with a message that says neither."""
    import httpx
    chunks: list[str] = []
    monkeypatch.setattr(httpx, "get", lambda url, **kw: _Resp(
        {"value": [{"id": "F", "name": "Remediated", "folder": {}}]}))
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _Resp({"uploadUrl": "https://up/session"}))

    def put(url, headers=None, **kw):
        chunks.append(headers["Content-Range"])
        # The session URL carries its own credential; sending the bearer token is REJECTED.
        assert "Authorization" not in headers, "bearer token sent to the upload session URL"
        return _Resp({"webUrl": "https://x/big.pptx"}, content=b"{}")

    monkeypatch.setattr(httpx, "put", put)
    size = 5 * 1024 * 1024
    out = scanner._sp_upload("tok", "d1", "Remediated", "big.pptx", b"y" * size)
    assert out["webUrl"] == "https://x/big.pptx"
    assert len(chunks) > 1, "a 5 MiB file went up in one chunk"
    # "bytes 0-3276799/5242880" — drop the "/total" before reading the end offset.
    first = int(chunks[0].split()[1].split("/")[0].split("-")[1]) + 1
    assert first % (320 * 1024) == 0, f"first chunk {first} is not a 320 KiB multiple"


def test_a_write_scope_failure_names_the_permission(monkeypatch):
    """403 on write is a missing WRITE scope. Sites.Read.All does not grant it, and an operator
    who just obtained that consent will otherwise assume it should have worked."""
    import httpx
    monkeypatch.setattr(httpx, "get", lambda url, **kw: _Resp(
        {"value": [{"id": "F", "name": "Remediated", "folder": {}}]}))
    monkeypatch.setattr(httpx, "put", lambda url, **kw: _Resp({}, status=403))
    with pytest.raises(PermissionError) as e:
        scanner._sp_upload("tok", "d1", "Remediated", "f.docx", b"x")
    assert "Sites.ReadWrite.All" in str(e.value)


def test_the_mirror_folder_is_found_not_recreated(monkeypatch):
    """Creating unconditionally is how Drive grew duplicate mirror folders. Look first."""
    import httpx
    monkeypatch.setattr(httpx, "get", lambda url, **kw: _Resp(
        {"value": [{"id": "EXISTING", "name": "Remediated", "folder": {}}]}))
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: pytest.fail("created an existing folder"))
    assert scanner._sp_folder_id("tok", "d1", "Remediated") == "EXISTING"


def test_a_concurrent_create_is_re_read_not_failed(monkeypatch):
    """Two workers remediating one library at once is normal; 409 means the other won."""
    import httpx
    calls = {"n": 0}

    def get(url, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Resp({"value": []})                      # not there yet
        return _Resp({"value": [{"id": "RACED", "name": "Remediated", "folder": {}}]})

    monkeypatch.setattr(httpx, "get", get)
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: _Resp({}, status=409))
    assert scanner._sp_folder_id("tok", "d1", "Remediated") == "RACED"


def test_the_upload_route_is_registered():
    from routes import sharepoint

    paths = {r.path for r in sharepoint.router.routes}
    assert "/sharepoint/upload" in paths


# ── replace-in-place ──────────────────────────────────────────────────────────────────────────
#
# The write-back button used to PUT to Graph from the browser. Routing it through this route
# moves four things server-side: the archive-before-overwrite and its fail-closed behaviour, the
# >4 MiB resumable session the browser path never had, Graph's permission errors translated into
# the consent that would fix them, and record_remediation for any caller that has a scan.

def test_the_archive_folder_is_never_scanned(monkeypatch):
    """Unconditional, unlike the mirror — and a LIVE defect before this change, since the browser
    button has been archiving into that folder all along.

    These are displaced ORIGINALS: byte-identical copies of documents that still exist at their
    own paths. Counting one counts the same document twice and reports failures the file at the
    real path no longer has, and the pile grows by one per save."""
    _stub_search(monkeypatch, [
        _item("i1", "policy.docx", "/Policies"),
        _item("i2", "policy.docx", f"/{scanner.SP_ARCHIVE_FOLDER}/2026-08-07"),
    ])
    assert [f["id"] for f in scanner._sp_list("tok", 50, exclude_remediated=True)] == ["i1"]


def test_the_archive_is_skipped_even_with_exclusion_off(monkeypatch):
    """No flag, deliberately. `exclude_remediated` is a judgement about ACP's OUTPUT; a backup of
    the user's own file is never an estate document under any setting."""
    _stub_search(monkeypatch, [_item("i2", "p.docx", f"/{scanner.SP_ARCHIVE_FOLDER}/2026-08-07")])
    assert scanner._sp_list("tok", 50) == []


def test_a_folder_named_like_the_archive_is_still_scanned(monkeypatch):
    """Segment matching, the same rule the mirror gets."""
    _stub_search(monkeypatch, [_item("i1", "a.docx", "/_mova-originals-archive")])
    assert [f["id"] for f in scanner._sp_list("tok", 50)] == ["i1"]


def test_the_original_is_archived_before_it_is_overwritten(monkeypatch):
    """Ordering is the whole guarantee. A copy issued after the PUT archives the REMEDIATED bytes
    and calls it a backup."""
    import httpx
    seen: list[str] = []
    monkeypatch.setattr(httpx, "get", lambda url, **kw: _Resp(
        {"value": [{"id": "ARCH", "name": scanner.SP_ARCHIVE_FOLDER, "folder": {}},
                   {"id": "DATED", "name": "2026-08-07", "folder": {}}]}))
    monkeypatch.setattr(httpx, "post", lambda url, **kw: seen.append(url) or _Resp({}, status=202))
    monkeypatch.setattr(httpx, "put", lambda url, **kw: seen.append(url) or
                        _Resp({"webUrl": "https://x/p.docx"}, content=b"{}"))

    scanner._sp_archive_original("tok", "d1", "i1", "2026-08-07")
    scanner._sp_replace("tok", "d1", "i1", b"x" * 10, "application/vnd.ms-word")

    copy = next(i for i, u in enumerate(seen) if "/copy" in u)
    put = next(i for i, u in enumerate(seen) if u.endswith("/items/i1/content"))
    assert copy < put, f"the overwrite ran before the backup: {seen}"


def test_a_failed_archive_raises_so_the_caller_cannot_overwrite(monkeypatch):
    """Fail-closed. The worst outcome must be "your file was not remediated" — visible and
    retryable — never "your file was replaced and the original is gone"."""
    import httpx
    monkeypatch.setattr(httpx, "get", lambda url, **kw: _Resp(
        {"value": [{"id": "ARCH", "name": scanner.SP_ARCHIVE_FOLDER, "folder": {}},
                   {"id": "DATED", "name": "2026-08-07", "folder": {}}]}))
    monkeypatch.setattr(httpx, "post", lambda url, **kw: _Resp({}, status=507))
    with pytest.raises(RuntimeError, match="nothing was overwritten"):
        scanner._sp_archive_original("tok", "d1", "i1", "2026-08-07")


def test_a_refused_archive_names_the_write_scope(monkeypatch):
    import httpx
    monkeypatch.setattr(httpx, "get", lambda url, **kw: _Resp(
        {"value": [{"id": "ARCH", "name": scanner.SP_ARCHIVE_FOLDER, "folder": {}},
                   {"id": "DATED", "name": "2026-08-07", "folder": {}}]}))
    monkeypatch.setattr(httpx, "post", lambda url, **kw: _Resp({}, status=403))
    with pytest.raises(PermissionError, match="ReadWrite"):
        scanner._sp_archive_original("tok", "d1", "i1", "2026-08-07")


def test_the_archive_folder_is_never_replaced_on_create(monkeypatch):
    """`conflictBehavior: replace` on the archive would destroy the backups this path exists to
    keep, so the lookup comes first and create is only the miss path."""
    import httpx
    monkeypatch.setattr(httpx, "get", lambda url, **kw: _Resp(
        {"value": [{"id": "ARCH", "name": scanner.SP_ARCHIVE_FOLDER, "folder": {}}]}))
    monkeypatch.setattr(httpx, "post",
                        lambda *a, **kw: pytest.fail("created a folder that already existed"))
    assert scanner._sp_folder_id("tok", "d1", scanner.SP_ARCHIVE_FOLDER) == "ARCH"


def test_a_onedrive_item_with_no_drive_id_resolves_to_me_drive(monkeypatch):
    """An item listed from OneDrive carries NO driveId (_sp_list), and _sp_download has always
    read that as /me/drive. Requiring one on the write side would break every OneDrive
    write-back while reading like a safety check."""
    assert scanner._sp_base(None).endswith("/me/drive")
    assert scanner._sp_base("d1").endswith("/drives/d1")

    import httpx
    seen: list[str] = []
    monkeypatch.setattr(httpx, "put", lambda url, **kw: seen.append(url) or
                        _Resp({"webUrl": "https://x/p.docx"}, content=b"{}"))
    scanner._sp_replace("tok", None, "i1", b"x" * 10)
    assert seen == ["https://graph.microsoft.com/v1.0/me/drive/items/i1/content"]


def test_a_large_replace_uses_a_resumable_session(monkeypatch):
    """The browser path had no session at all: a simple PUT past 4 MiB is a 413 that says nothing
    about chunking, so a big remediated deck failed with an error naming no cause."""
    import httpx
    size = scanner._SP_SIMPLE_MAX + 1024
    ranges: list[str] = []
    monkeypatch.setattr(httpx, "post", lambda url, **kw: _Resp({"uploadUrl": "https://up/1"}))

    def put(url, **kw):
        assert url == "https://up/1", f"simple PUT for a {size}-byte file: {url}"
        ranges.append(kw["headers"]["Content-Range"])
        return _Resp({"webUrl": "https://x/big.pptx"}, content=b"{}")

    monkeypatch.setattr(httpx, "put", put)
    out = scanner._sp_replace("tok", "d1", "i1", b"y" * size)
    assert out["webUrl"] == "https://x/big.pptx"
    assert ranges, "no chunk was sent"
    for r in ranges[:-1]:
        span = r.split(" ", 1)[1].split("/")[0]
        lo, hi = (int(x) for x in span.split("-"))
        assert (hi - lo + 1) % (320 * 1024) == 0, f"chunk {r} is not a 320 KiB multiple"


def test_a_description_failure_never_fails_a_successful_write(monkeypatch):
    """The bytes are the deliverable. A label is not worth turning a completed replace into an
    error the user reads as "it did not save"."""
    import httpx

    def boom(*a, **kw):
        raise RuntimeError("graph down")

    monkeypatch.setattr(httpx, "patch", boom)
    scanner._sp_describe("tok", "d1", "i1", "note")      # must not raise
