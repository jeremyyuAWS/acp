"""PRD Phase 3 — Drive incremental sync via the Changes API.

scanner.drive_start_page_token / drive_changes_since let the scheduled sweep ask "what
changed since a prior checkpoint" instead of re-listing Drive's entire estate. Hermetic: a
fake `svc.changes()` stands in for the real Drive client, so these prove the paging loop,
the removed/trashed split, and the normalized item shape without any real API access.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import scanner  # noqa: E402

PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


class _Req:
    def __init__(self, payload):
        self._p = payload

    def execute(self, num_retries=0):
        return self._p


class _Changes:
    def __init__(self, pages: dict[str, dict], start_token: str = "start-tok"):
        # pages: {page_token_used_to_request: response_dict}
        self._pages = pages
        self._start_token = start_token
        self.list_calls: list[str] = []

    def getStartPageToken(self):  # noqa: N802 — matches the real SDK's camelCase method
        return _Req({"startPageToken": self._start_token})

    def list(self, pageToken=None, **kw):  # noqa: N803 — matches the real SDK's kwarg name
        self.list_calls.append(pageToken)
        return _Req(self._pages[pageToken])


class _FakeSvc:
    def __init__(self, changes: _Changes):
        self._changes = changes

    def changes(self):
        return self._changes


def _file(fid, name, checksum="abc"):
    return {"id": fid, "name": name, "mimeType": PPTX, "md5Checksum": checksum}


# ── drive_start_page_token ───────────────────────────────────────────────────────

def test_start_page_token_returns_the_raw_token():
    svc = _FakeSvc(_Changes({}, start_token="fresh-baseline"))
    assert scanner.drive_start_page_token(svc) == "fresh-baseline"


# ── drive_changes_since: single page ─────────────────────────────────────────────

def test_a_single_page_of_changed_files_is_normalized():
    resp = {"changes": [{"fileId": "F1", "removed": False, "file": _file("F1", "deck.pptx")}],
           "newStartPageToken": "tok-2"}
    svc = _FakeSvc(_Changes({"tok-1": resp}))
    items, removed, new_token = scanner.drive_changes_since(svc, "tok-1")
    assert [i["name"] for i in items] == ["deck.pptx"]
    assert removed == 0
    assert new_token == "tok-2"


def test_no_changes_returns_an_empty_list_and_the_new_token():
    resp = {"changes": [], "newStartPageToken": "tok-2"}
    svc = _FakeSvc(_Changes({"tok-1": resp}))
    items, removed, new_token = scanner.drive_changes_since(svc, "tok-1")
    assert items == [] and removed == 0 and new_token == "tok-2"


# ── drive_changes_since: removed / trashed ───────────────────────────────────────

def test_a_removed_change_is_counted_not_normalized():
    resp = {"changes": [{"fileId": "GONE", "removed": True}],   # no `file` at all — real shape
           "newStartPageToken": "tok-2"}
    svc = _FakeSvc(_Changes({"tok-1": resp}))
    items, removed, new_token = scanner.drive_changes_since(svc, "tok-1")
    assert items == [] and removed == 1


def test_a_trashed_file_counts_as_removed_even_though_removed_is_false():
    """Drive's `removed` flag means permanently gone/inaccessible; a file moved to trash still
    has `removed: false` but `file.trashed: true` — both mean 'no longer in the estate'."""
    resp = {"changes": [{"fileId": "F1", "removed": False,
                        "file": {**_file("F1", "old.pptx"), "trashed": True}}],
           "newStartPageToken": "tok-2"}
    svc = _FakeSvc(_Changes({"tok-1": resp}))
    items, removed, new_token = scanner.drive_changes_since(svc, "tok-1")
    assert items == [] and removed == 1


def test_mixed_changed_and_removed_in_one_page():
    resp = {"changes": [
                {"fileId": "F1", "removed": False, "file": _file("F1", "keep.pptx")},
                {"fileId": "F2", "removed": True},
            ],
           "newStartPageToken": "tok-2"}
    svc = _FakeSvc(_Changes({"tok-1": resp}))
    items, removed, new_token = scanner.drive_changes_since(svc, "tok-1")
    assert [i["name"] for i in items] == ["keep.pptx"]
    assert removed == 1


# ── drive_changes_since: paging ───────────────────────────────────────────────────

def test_pages_through_nextPageToken_until_newStartPageToken():
    page1 = {"changes": [{"fileId": "F1", "removed": False, "file": _file("F1", "a.pptx")}],
            "nextPageToken": "tok-2"}
    page2 = {"changes": [{"fileId": "F2", "removed": False, "file": _file("F2", "b.pptx")}],
            "newStartPageToken": "tok-3"}
    changes = _Changes({"tok-1": page1, "tok-2": page2})
    svc = _FakeSvc(changes)
    items, removed, new_token = scanner.drive_changes_since(svc, "tok-1")
    assert sorted(i["name"] for i in items) == ["a.pptx", "b.pptx"]
    assert new_token == "tok-3"
    assert changes.list_calls == ["tok-1", "tok-2"]   # both pages actually requested


# ── drive_changes_since: propagates real failures ────────────────────────────────

def test_an_expired_token_raises_rather_than_silently_returning_nothing():
    """An expired/invalid page token is a 404 from the real SDK — this must propagate, not be
    swallowed, so the caller (core._drive_sync_gate) can fall back to a full scan rather than
    mistaking 'the check itself is broken' for 'nothing changed'."""
    class _BoomChanges(_Changes):
        def list(self, pageToken=None, **kw):  # noqa: N803
            raise RuntimeError("HttpError 404: page token expired")

    svc = _FakeSvc(_BoomChanges({}))
    try:
        scanner.drive_changes_since(svc, "stale-token")
        assert False, "expected the underlying error to propagate"
    except RuntimeError as e:
        assert "404" in str(e)


# ── store.get_sync_cursor / save_sync_cursor ──────────────────────────────────────

def test_a_never_synced_source_has_no_cursor(isolated_store):
    assert isolated_store.get_sync_cursor("drive") is None


def test_save_then_get_round_trips(isolated_store):
    isolated_store.save_sync_cursor("drive", "a@b.c", "tok-1")
    cur = isolated_store.get_sync_cursor("drive")
    assert cur["source"] == "drive"
    assert cur["owner_email"] == "a@b.c"
    assert cur["page_token"] == "tok-1"
    assert cur["updated_at"]


def test_saving_again_advances_the_same_row_not_a_second_one(isolated_store):
    isolated_store.save_sync_cursor("drive", "a@b.c", "tok-1")
    isolated_store.save_sync_cursor("drive", "a@b.c", "tok-2")
    assert isolated_store.get_sync_cursor("drive")["page_token"] == "tok-2"


def test_cursors_are_independent_per_source(isolated_store):
    isolated_store.save_sync_cursor("drive", "a@b.c", "drive-tok")
    assert isolated_store.get_sync_cursor("sharepoint") is None


# ── /monitor/estate: last_skipped is distinct from a zero-file sweep ─────────────

_MONITOR_KEY = "m0nitor-k3y"


@pytest.fixture()
def monitor_client(isolated_store, monkeypatch):
    import core as core_mod
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core_mod, "store", isolated_store)
    monkeypatch.setattr(core_mod, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core_mod, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core_mod, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core_mod, "MONITOR_KEY", _MONITOR_KEY, raising=False)
    return TestClient(app), isolated_store


def test_monitor_estate_reports_last_skipped(monitor_client):
    client, store = monitor_client
    store.record_sweep_outcome(ok=True, when="2026-08-29T00:00:00+00:00",
                               source="drive", skipped=True)

    body = client.get("/monitor/estate", headers={"X-Monitor-Key": _MONITOR_KEY}).json()
    assert body["sweep"]["last_skipped"] is True
    assert body["sweep"]["last_files"] is None


def test_monitor_estate_last_skipped_is_none_before_any_sweep(monitor_client):
    client, _ = monitor_client
    body = client.get("/monitor/estate", headers={"X-Monitor-Key": _MONITOR_KEY}).json()
    assert body["sweep"]["last_skipped"] is None
