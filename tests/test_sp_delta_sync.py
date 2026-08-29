"""PRD Phase 3 — SharePoint incremental sync via Microsoft Graph's delta query.

scanner.sp_delta_since lets the scheduled sweep ask "what changed since a prior checkpoint" for
one Graph drive, mirroring scanner.drive_changes_since's Drive-side contract. Hermetic: a fake
`httpx.get` stands in for the real Graph client, so these prove the paging loop, the deleted/
folder/OS-metadata filtering, and the deltaLink handling without any real API access.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import scanner  # noqa: E402

PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code, self._payload = status, payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


def _pages_by_url(pages: dict[str, dict], calls: list | None = None):
    def fake_get(url, **kw):
        if calls is not None:
            calls.append(url)
        return _Resp(200, pages[url])
    return fake_get


def _inject_httpx(monkeypatch, get_impl):
    m = types.ModuleType("httpx")
    m.get = get_impl
    monkeypatch.setitem(sys.modules, "httpx", m)


def _item(iid, name, mime=PPTX):
    return {"id": iid, "name": name, "file": {"mimeType": mime}}


SEED_URL = f"{scanner.GRAPH}/drives/drv-1/root/delta?$select={scanner._SP_ITEM_SELECT}"


# ── single page ────────────────────────────────────────────────────────────────────────────

def test_a_single_page_of_changed_items_is_raw(monkeypatch):
    resp = {"value": [_item("I1", "deck.pptx")], "@odata.deltaLink": "https://delta/2"}
    _inject_httpx(monkeypatch, _pages_by_url({"https://delta/1": resp}))
    items, removed, new_link = scanner.sp_delta_since("tok", "drv-1", "https://delta/1")
    assert items == [_item("I1", "deck.pptx")]
    assert removed == set()
    assert new_link == "https://delta/2"


def test_no_changes_returns_an_empty_list_and_the_new_link(monkeypatch):
    resp = {"value": [], "@odata.deltaLink": "https://delta/2"}
    _inject_httpx(monkeypatch, _pages_by_url({"https://delta/1": resp}))
    items, removed, new_link = scanner.sp_delta_since("tok", "drv-1", "https://delta/1")
    assert items == [] and removed == set() and new_link == "https://delta/2"


def test_a_seed_call_uses_the_configured_drive_root(monkeypatch):
    resp = {"value": [], "@odata.deltaLink": "https://delta/seeded"}
    calls: list = []
    _inject_httpx(monkeypatch, _pages_by_url({SEED_URL: resp}, calls))
    items, removed, new_link = scanner.sp_delta_since("tok", "drv-1", None)
    assert calls == [SEED_URL]
    assert new_link == "https://delta/seeded"


# ── deleted / folder / OS metadata filtering ──────────────────────────────────────────────────

def test_a_deleted_item_yields_its_drive_scoped_key(monkeypatch):
    resp = {"value": [{"id": "GONE", "deleted": {"state": "deleted"}}],
           "@odata.deltaLink": "https://delta/2"}
    _inject_httpx(monkeypatch, _pages_by_url({"https://delta/1": resp}))
    items, removed, _ = scanner.sp_delta_since("tok", "drv-1", "https://delta/1")
    assert items == [] and removed == {("drv-1", "GONE")}


def test_a_folder_entry_never_reaches_the_changed_list(monkeypatch):
    resp = {"value": [{"id": "F1", "name": "Subfolder", "folder": {"childCount": 3}}],
           "@odata.deltaLink": "https://delta/2"}
    _inject_httpx(monkeypatch, _pages_by_url({"https://delta/1": resp}))
    items, removed, _ = scanner.sp_delta_since("tok", "drv-1", "https://delta/1")
    assert items == [] and removed == set()


def test_os_metadata_is_dropped(monkeypatch):
    resp = {"value": [_item("I1", ".DS_Store")], "@odata.deltaLink": "https://delta/2"}
    _inject_httpx(monkeypatch, _pages_by_url({"https://delta/1": resp}))
    items, removed, _ = scanner.sp_delta_since("tok", "drv-1", "https://delta/1")
    assert items == []


def test_mixed_changed_deleted_and_folder_in_one_page(monkeypatch):
    resp = {"value": [
                _item("I1", "keep.pptx"),
                {"id": "I2", "deleted": {"state": "deleted"}},
                {"id": "F1", "name": "Sub", "folder": {}},
            ],
           "@odata.deltaLink": "https://delta/2"}
    _inject_httpx(monkeypatch, _pages_by_url({"https://delta/1": resp}))
    items, removed, _ = scanner.sp_delta_since("tok", "drv-1", "https://delta/1")
    assert [i["name"] for i in items] == ["keep.pptx"]
    assert removed == {("drv-1", "I2")}


# ── paging ─────────────────────────────────────────────────────────────────────────────────

def test_pages_through_nextLink_until_deltaLink(monkeypatch):
    page1 = {"value": [_item("I1", "a.pptx")], "@odata.nextLink": "https://delta/page2"}
    page2 = {"value": [_item("I2", "b.pptx")], "@odata.deltaLink": "https://delta/final"}
    calls: list = []
    _inject_httpx(monkeypatch, _pages_by_url(
        {"https://delta/1": page1, "https://delta/page2": page2}, calls))
    items, removed, new_link = scanner.sp_delta_since("tok", "drv-1", "https://delta/1")
    assert sorted(i["name"] for i in items) == ["a.pptx", "b.pptx"]
    assert new_link == "https://delta/final"
    assert calls == ["https://delta/1", "https://delta/page2"]


# ── propagates real failures ───────────────────────────────────────────────────────────────

def test_missing_sites_read_all_raises_permission_error(monkeypatch):
    def fake_get(url, **kw):
        return _Resp(403, {})
    _inject_httpx(monkeypatch, fake_get)
    with pytest.raises(PermissionError, match="Sites.Read.All"):
        scanner.sp_delta_since("tok", "drv-1", "https://delta/1")


def test_an_invalidated_delta_link_raises(monkeypatch):
    def fake_get(url, **kw):
        return _Resp(410, {})   # Graph 410 Gone — the real invalid-delta-link status
    _inject_httpx(monkeypatch, fake_get)
    with pytest.raises(RuntimeError):
        scanner.sp_delta_since("tok", "drv-1", "https://delta/1")
