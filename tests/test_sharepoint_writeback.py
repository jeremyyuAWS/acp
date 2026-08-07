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
