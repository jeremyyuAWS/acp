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
# Raw Drive file resources, NOT _normalize()d — a caller reconstructing a full estate
# (apply_drive_delta) needs the unfiltered shape so a non-scannable changed file still counts
# in the estate inventory, exactly as a fresh listing would count it.

def test_a_single_page_of_changed_files_is_raw_not_normalized():
    resp = {"changes": [{"fileId": "F1", "removed": False, "file": _file("F1", "deck.pptx")}],
           "newStartPageToken": "tok-2"}
    svc = _FakeSvc(_Changes({"tok-1": resp}))
    changed, removed_ids, new_token = scanner.drive_changes_since(svc, "tok-1")
    assert changed == [_file("F1", "deck.pptx")]           # raw dict, untouched
    assert removed_ids == set()
    assert new_token == "tok-2"


def test_no_changes_returns_an_empty_list_and_the_new_token():
    resp = {"changes": [], "newStartPageToken": "tok-2"}
    svc = _FakeSvc(_Changes({"tok-1": resp}))
    changed, removed_ids, new_token = scanner.drive_changes_since(svc, "tok-1")
    assert changed == [] and removed_ids == set() and new_token == "tok-2"


def test_os_metadata_is_dropped_even_though_it_is_raw(monkeypatch):
    resp = {"changes": [{"fileId": "F1", "removed": False, "file": _file("F1", ".DS_Store")}],
           "newStartPageToken": "tok-2"}
    svc = _FakeSvc(_Changes({"tok-1": resp}))
    changed, removed_ids, _ = scanner.drive_changes_since(svc, "tok-1")
    assert changed == []


# ── drive_changes_since: removed / trashed ───────────────────────────────────────

def test_a_removed_change_yields_its_id_not_normalized():
    resp = {"changes": [{"fileId": "GONE", "removed": True}],   # no `file` at all — real shape
           "newStartPageToken": "tok-2"}
    svc = _FakeSvc(_Changes({"tok-1": resp}))
    changed, removed_ids, new_token = scanner.drive_changes_since(svc, "tok-1")
    assert changed == [] and removed_ids == {"GONE"}


def test_a_trashed_file_counts_as_removed_even_though_removed_is_false():
    """Drive's `removed` flag means permanently gone/inaccessible; a file moved to trash still
    has `removed: false` but `file.trashed: true` — both mean 'no longer in the estate'."""
    resp = {"changes": [{"fileId": "F1", "removed": False,
                        "file": {**_file("F1", "old.pptx"), "trashed": True}}],
           "newStartPageToken": "tok-2"}
    svc = _FakeSvc(_Changes({"tok-1": resp}))
    changed, removed_ids, new_token = scanner.drive_changes_since(svc, "tok-1")
    assert changed == [] and removed_ids == {"F1"}


def test_mixed_changed_and_removed_in_one_page():
    resp = {"changes": [
                {"fileId": "F1", "removed": False, "file": _file("F1", "keep.pptx")},
                {"fileId": "F2", "removed": True},
            ],
           "newStartPageToken": "tok-2"}
    svc = _FakeSvc(_Changes({"tok-1": resp}))
    changed, removed_ids, new_token = scanner.drive_changes_since(svc, "tok-1")
    assert [f["name"] for f in changed] == ["keep.pptx"]
    assert removed_ids == {"F2"}


# ── drive_changes_since: paging ───────────────────────────────────────────────────

def test_pages_through_nextPageToken_until_newStartPageToken():
    page1 = {"changes": [{"fileId": "F1", "removed": False, "file": _file("F1", "a.pptx")}],
            "nextPageToken": "tok-2"}
    page2 = {"changes": [{"fileId": "F2", "removed": False, "file": _file("F2", "b.pptx")}],
            "newStartPageToken": "tok-3"}
    changes = _Changes({"tok-1": page1, "tok-2": page2})
    svc = _FakeSvc(changes)
    changed, removed_ids, new_token = scanner.drive_changes_since(svc, "tok-1")
    assert sorted(f["name"] for f in changed) == ["a.pptx", "b.pptx"]
    assert new_token == "tok-3"
    assert changes.list_calls == ["tok-1", "tok-2"]   # both pages actually requested


# ── drive_changes_since: propagates real failures ────────────────────────────────

def test_an_expired_token_raises_rather_than_silently_returning_nothing():
    """An expired/invalid page token is a 404 from the real SDK — this must propagate, not be
    swallowed, so the caller (core._drive_sync_plan) can fall back to a full scan rather than
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


# ── apply_drive_delta: pure merge, no I/O ─────────────────────────────────────────

def test_an_unmentioned_file_carries_forward_untouched():
    prior = [_file("F1", "untouched.pptx")]
    out = scanner.apply_drive_delta(prior, [], set())
    assert out == prior


def test_a_changed_file_replaces_its_prior_entry_wholly():
    prior = [_file("F1", "old-name.pptx", checksum="old")]
    changed = [_file("F1", "new-name.pptx", checksum="new")]
    out = scanner.apply_drive_delta(prior, changed, set())
    assert out == [changed[0]]           # the fresh dict wins entirely, not a field merge


def test_a_removed_id_drops_its_prior_entry():
    prior = [_file("F1", "gone.pptx"), _file("F2", "stays.pptx")]
    out = scanner.apply_drive_delta(prior, [], {"F1"})
    assert [f["id"] for f in out] == ["F2"]


def test_a_changed_id_with_no_prior_entry_is_a_new_file():
    out = scanner.apply_drive_delta([], [_file("F9", "brand-new.pptx")], set())
    assert [f["id"] for f in out] == ["F9"]


def test_removed_wins_over_changed_for_the_same_id():
    """Shouldn't happen in one real delta (a file can't be both edited and removed in the same
    window), but if it did, 'gone' must win — a stale 'changed' entry must never resurrect it."""
    prior = [_file("F1", "old.pptx")]
    changed = [_file("F1", "edited-then-deleted.pptx")]
    out = scanner.apply_drive_delta(prior, changed, {"F1"})
    assert out == []


def test_a_full_reconstruction_scenario():
    prior = [_file("F1", "unchanged.pptx"), _file("F2", "will-change.pptx", checksum="old"),
            _file("F3", "will-be-removed.pptx")]
    changed = [_file("F2", "will-change.pptx", checksum="new"), _file("F4", "new-file.pptx")]
    out = scanner.apply_drive_delta(prior, changed, {"F3"})
    by_id = {f["id"]: f for f in out}
    assert set(by_id) == {"F1", "F2", "F4"}
    assert by_id["F2"]["md5Checksum"] == "new"


# ── _drive_file_from_inventory_row: the inverse of _drive_inventory_row ──────────

def test_inventory_row_round_trips_into_a_raw_drive_file_shape():
    row = {"file": "report.pptx", "drive_file_id": "F1", "mime": PPTX, "size_kb": 512,
          "checksum": "abc123", "created_at": "2026-01-01T00:00:00Z",
          "source_modified": "2026-02-01T00:00:00Z", "owner": "a@b.c",
          "parent_folder": "folder-1"}
    f = scanner._drive_file_from_inventory_row(row)
    assert f["id"] == "F1" and f["name"] == "report.pptx" and f["mimeType"] == PPTX
    assert f["md5Checksum"] == "abc123"
    assert f["createdTime"] == "2026-01-01T00:00:00Z"
    assert f["modifiedTime"] == "2026-02-01T00:00:00Z"
    assert f["size"] == 512 * 1024
    assert f["owners"] == [{"displayName": "a@b.c"}]
    assert f["parents"] == ["folder-1"]


def test_inventory_row_with_no_owner_or_folder_or_size_degrades_gracefully():
    row = {"file": "x.pptx", "drive_file_id": "F1", "mime": PPTX, "size_kb": None,
          "checksum": None, "created_at": None, "source_modified": None, "owner": None,
          "parent_folder": None}
    f = scanner._drive_file_from_inventory_row(row)
    assert f["size"] is None and f["owners"] == [] and f["parents"] == []


# ── drive_reconstructed_listing: parity with a fresh _search_drive listing ──────

def test_reconstructed_listing_matches_search_drives_scope_out_shape():
    prior_row = {"file": "unchanged.pptx", "drive_file_id": "F1", "mime": PPTX, "size_kb": 10,
                "checksum": "abc", "created_at": None, "source_modified": None,
                "owner": None, "parent_folder": None}
    prior_files = [scanner._drive_file_from_inventory_row(prior_row)]
    changed = [_file("F2", "new.pptx")]
    scope_out: dict = {}
    inventory_out: list = []
    result = scanner.drive_reconstructed_listing(prior_files, changed, set(),
                                                 scope_out=scope_out, inventory_out=inventory_out)
    assert sorted(i["name"] for i in result) == ["new.pptx", "unchanged.pptx"]
    # Same keys a live _search_drive call would populate, plus the one extra marker.
    for key in ("kind", "raw", "scannable", "skipped_acp", "kept", "truncated", "inventory"):
        assert key in scope_out, f"missing {key} — reconstructed scope_out must match a live listing"
    assert scope_out["kind"] == "drive"
    assert scope_out["kept"] == 2
    assert scope_out["truncated"] is False
    assert scope_out["reconstructed"] is True
    assert "cap" not in scope_out, "a reconstruction has no raw-listing ceiling to report"


def test_reconstructed_listing_honors_max_files():
    prior_files = [scanner._drive_file_from_inventory_row(
        {"file": f"f{i}.pptx", "drive_file_id": f"F{i}", "mime": PPTX, "size_kb": 1,
         "checksum": None, "created_at": None, "source_modified": None, "owner": None,
         "parent_folder": None}) for i in range(5)]
    result = scanner.drive_reconstructed_listing(prior_files, [], set(), max_files=3)
    assert len(result) == 3


# ── _list()'s drive_delta seam: the full wiring, no real Drive access ────────────

def test_list_uses_the_reconstruction_when_drive_delta_is_given():
    """svc=None proves it: a reconstruction never touches Drive at all."""
    prior_row = {"file": "unchanged.pptx", "drive_file_id": "F1", "mime": PPTX, "size_kb": 1,
                "checksum": "abc", "created_at": None, "source_modified": None,
                "owner": None, "parent_folder": None}
    delta = {"prior_files": [scanner._drive_file_from_inventory_row(prior_row)],
            "changed": [_file("F2", "new.pptx")], "removed_ids": set()}
    scope: dict = {}
    items = scanner._list("drive", svc=None, folder=None, scope_out=scope, drive_delta=delta)
    assert sorted(i["name"] for i in items) == ["new.pptx", "unchanged.pptx"]
    assert scope["reconstructed"] is True


def test_list_falls_back_to_a_live_walk_when_drive_delta_is_none():
    """The existing behavior, unchanged: no drive_delta means _search_drive runs as always."""
    class _FakeFiles:
        def list(self, **kw):
            return _Req({"files": []})

    class _FakeDriveSvc:
        def files(self):
            return _FakeFiles()

    scope: dict = {}
    items = scanner._list("drive", svc=_FakeDriveSvc(), folder=None, scope_out=scope,
                          drive_delta=None)
    assert items == []
    assert "reconstructed" not in scope


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


# ── store.latest_scan_inventory_items ─────────────────────────────────────────────

def _seed_completed_scan(store, scan_id, owner, source, completed_at, inventory_rows):
    with store._db.cursor() as cur:
        store._db.execute(cur,
            "INSERT INTO scan_runs (id, owner_email, source, completed_at) VALUES (%s,%s,%s,%s)",
            (scan_id, owner, source, completed_at))
        for r in inventory_rows:
            store._db.execute(cur,
                "INSERT INTO scan_inventory (scan_id, file, drive_file_id, mime, size_kb, "
                "checksum, created_at, source_modified, owner, parent_folder) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (scan_id, r["file"], r.get("drive_file_id"), r.get("mime"), r.get("size_kb"),
                 r.get("checksum"), r.get("created_at"), r.get("source_modified"),
                 r.get("owner"), r.get("parent_folder")))


def test_no_prior_completed_scan_returns_none(isolated_store):
    assert isolated_store.latest_scan_inventory_items("a@b.c", "drive") is None


def test_returns_the_most_recent_completed_scans_inventory(isolated_store):
    _seed_completed_scan(isolated_store, "s1", "a@b.c", "drive", "2026-01-01T00:00:00Z",
                         [{"file": "old.pptx", "drive_file_id": "F1"}])
    _seed_completed_scan(isolated_store, "s2", "a@b.c", "drive", "2026-02-01T00:00:00Z",
                         [{"file": "new.pptx", "drive_file_id": "F2"}])
    items = isolated_store.latest_scan_inventory_items("a@b.c", "drive")
    assert [i["file"] for i in items] == ["new.pptx"]


def test_an_incomplete_scan_is_never_the_source(isolated_store):
    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur,
            "INSERT INTO scan_runs (id, owner_email, source, completed_at) VALUES (%s,%s,%s,NULL)",
            ("running-scan", "a@b.c", "drive"))
    assert isolated_store.latest_scan_inventory_items("a@b.c", "drive") is None


def test_rows_with_no_drive_file_id_are_dropped(isolated_store):
    _seed_completed_scan(isolated_store, "s1", "a@b.c", "drive", "2026-01-01T00:00:00Z",
                         [{"file": "local.pdf", "drive_file_id": None},
                          {"file": "drive.pdf", "drive_file_id": "F1"}])
    items = isolated_store.latest_scan_inventory_items("a@b.c", "drive")
    assert [i["file"] for i in items] == ["drive.pdf"]


def test_scoped_by_owner_and_source(isolated_store):
    _seed_completed_scan(isolated_store, "s1", "alice@x.io", "drive", "2026-01-01T00:00:00Z",
                         [{"file": "alices.pptx", "drive_file_id": "F1"}])
    assert isolated_store.latest_scan_inventory_items("bob@x.io", "drive") is None
    assert isolated_store.latest_scan_inventory_items("alice@x.io", "sharepoint") is None
    items = isolated_store.latest_scan_inventory_items("alice@x.io", "drive")
    assert [i["file"] for i in items] == ["alices.pptx"]


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
