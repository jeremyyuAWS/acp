"""SharePoint SITES, not just the signed-in user's OneDrive.

Before this, `_sp_list` hardcoded `/me/drive` and `_sp_download` hardcoded it too, so the
"SharePoint" source could only ever reach one person's OneDrive — while `store._SOURCE_LABEL`
called it "SharePoint / OneDrive" and the UI offered it as a source. Team-site document
libraries, which is what a customer means by SharePoint, were unreachable.

THE LOAD-BEARING TEST HERE IS `test_download_uses_the_drive_the_item_came_from`. Graph item ids
are unique only WITHIN a drive, so listing from a site and downloading from /me/drive does not
reliably fail — it can return a DIFFERENT document that happens to share the id. A scan that
reports a site's file names while analysing somebody's OneDrive is the worst outcome available
here, because every number it produces looks plausible.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import scanner  # noqa: E402


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.content = b"file-bytes"

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _fake_graph(routes: dict, seen: list | None = None):
    """A Graph stand-in keyed by URL prefix. Records every URL so a test can assert WHICH drive
    was asked, which is the only way to catch the /me/drive bug — the response shape is identical
    either way."""
    def get(url, headers=None, timeout=None, follow_redirects=None):
        if seen is not None:
            seen.append(url)
        for prefix, payload in routes.items():
            if url.startswith(prefix):
                return _Resp(payload() if callable(payload) else payload)
        raise AssertionError(f"unexpected Graph URL: {url}")
    return get


def test_sites_are_listed_with_a_wildcard_not_an_empty_search(monkeypatch):
    """`search=` empty returns nothing in Graph; `search=*` returns everything visible.

    An empty query must not read as "this tenant has no sites" — that is a wrong answer that
    looks like a correct one, and it would send an operator to their admin for consent they
    already have.
    """
    seen: list[str] = []
    import httpx
    # `httpx.get` globally: scanner imports httpx INSIDE each function, so there is no
    # module-level attribute to patch and setattr(scanner, "httpx", ...) would do nothing.
    monkeypatch.setattr(httpx, "get", _fake_graph(
        {"https://graph.microsoft.com/v1.0/sites": {"value": [
            {"id": "host,g1,g2", "displayName": "Policies", "webUrl": "https://x/sites/policies"}]}},
        seen))

    out = scanner._sp_sites("tok")
    assert out == [{"id": "host,g1,g2", "name": "Policies", "url": "https://x/sites/policies"}]
    assert "search=*" in seen[0], f"expected a wildcard search, got {seen[0]}"


def test_a_missing_scope_names_the_consent_that_would_fix_it(monkeypatch):
    """403 from Graph is a missing scope, and the message has to say WHICH.

    Sites.Read.All is admin-consent territory in most tenants. "Access denied" sends the operator
    nowhere; naming the permission sends them to the one person who can grant it.
    """
    import httpx

    def denied(url, **kw):
        return _Resp({"error": {"message": "Access denied"}}, status=403)

    monkeypatch.setattr(httpx, "get", denied)
    with pytest.raises(PermissionError) as e:
        scanner._sp_sites("tok")
    assert "Sites.Read.All" in str(e.value)
    assert "admin consent" in str(e.value)


def test_site_listing_covers_every_document_library(monkeypatch):
    """A team site routinely has several libraries. Scanning only the default would under-report
    the estate in a way that looks exactly like a smaller estate."""
    import httpx
    monkeypatch.setattr(httpx, "get", _fake_graph({
        "https://graph.microsoft.com/v1.0/sites/S/drives": {"value": [
            {"id": "d1", "name": "Documents"}, {"id": "d2", "name": "Policies"}]},
        "https://graph.microsoft.com/v1.0/drives/d1/root/search": {"value": [
            {"id": "i1", "name": "a.docx", "file": {}}]},
        "https://graph.microsoft.com/v1.0/drives/d2/root/search": {"value": [
            {"id": "i2", "name": "b.pdf", "file": {}}]},
    }))
    files = scanner._sp_list("tok", 50, site="S")
    assert sorted(f["name"] for f in files) == ["a.docx", "b.pdf"]
    assert {f["driveId"] for f in files} == {"d1", "d2"}


def test_same_item_id_in_two_libraries_is_two_documents(monkeypatch):
    """Identity is (drive, item), not item. Graph ids are unique only within a drive, so a bare-id
    dedup would silently drop one of two genuinely different files."""
    import httpx
    monkeypatch.setattr(httpx, "get", _fake_graph({
        "https://graph.microsoft.com/v1.0/sites/S/drives": {"value": [
            {"id": "d1", "name": "A"}, {"id": "d2", "name": "B"}]},
        "https://graph.microsoft.com/v1.0/drives/d1/root/search": {"value": [
            {"id": "SHARED", "name": "one.docx", "file": {}}]},
        "https://graph.microsoft.com/v1.0/drives/d2/root/search": {"value": [
            {"id": "SHARED", "name": "two.docx", "file": {}}]},
    }))
    files = scanner._sp_list("tok", 50, site="S")
    assert len(files) == 2, "the same id in two drives collapsed into one document"


def test_onedrive_mode_is_unchanged_and_records_no_drive(monkeypatch):
    """No site → exactly the previous behaviour, and NO driveId, because that absence is what
    every item stored before this change looks like. The download path reads it as /me/drive."""
    seen: list[str] = []
    import httpx
    monkeypatch.setattr(httpx, "get", _fake_graph({
        "https://graph.microsoft.com/v1.0/me/drive/root/search": {"value": [
            {"id": "i1", "name": "mine.docx", "file": {}}]},
    }, seen))
    files = scanner._sp_list("tok", 50)
    assert files == [{"name": "mine.docx", "id": "i1", "sp": True}]
    assert all("me/drive" in u for u in seen)


def test_download_uses_the_drive_the_item_came_from(monkeypatch, tmp_path):
    """THE one that matters. An item listed from a site drive must be fetched from that drive.

    Hardcoding /me/drive does not reliably 404 — ids collide across drives — so the failure mode
    is a scan that analyses the wrong document while reporting the right name.
    """
    seen: list[str] = []
    import httpx
    monkeypatch.setattr(httpx, "get", _fake_graph({"https://graph.microsoft.com/v1.0/": {}}, seen))

    scanner._sp_download("tok", {"id": "i9", "name": "x.docx", "driveId": "d7"}, tmp_path)
    assert seen[-1] == "https://graph.microsoft.com/v1.0/drives/d7/items/i9/content"

    # …and an item with no driveId still resolves the old way, so re-running an older scan works.
    scanner._sp_download("tok", {"id": "i9", "name": "y.docx"}, tmp_path)
    assert seen[-1] == "https://graph.microsoft.com/v1.0/me/drive/items/i9/content"


def test_the_scan_dispatcher_treats_root_as_no_site(monkeypatch):
    """`folder` carries the site id, and "root" is Drive's existing sentinel for no narrowing.
    Reusing it means a caller that passes Drive's default does not accidentally ask Graph for a
    site literally named "root"."""
    calls: list = []
    monkeypatch.setattr(scanner, "_sp_list",
                        lambda tok, mx, site=None, exclude_remediated=False:
                        calls.append(site) or [])
    for folder in (None, "", "root"):
        scanner._list("sharepoint", None, folder=folder, sp_token="t", scope_out={})
    assert calls == [None, None, None]

    scanner._list("sharepoint", None, folder="host,g1,g2", sp_token="t", scope_out={})
    assert calls[-1] == "host,g1,g2"


def test_the_route_is_registered():
    """A router nobody mounts is a 404 that looks like a missing feature."""
    from routes import ROUTERS
    from routes import sharepoint

    assert sharepoint.router in ROUTERS
    paths = {r.path for r in sharepoint.router.routes}
    assert "/sharepoint/sites" in paths
    # `:path` on the site id — a Graph site id contains commas and dots, and the default
    # converter would truncate it to the hostname and 404 for reasons invisible in the URL.
    assert any("{site_id:path}" in p for p in paths)
