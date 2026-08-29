"""PRD Phase 3 (item 10) — reconstruct a SharePoint/OneDrive listing from a prior scan +
scanner.sp_delta_since's Graph delta, mirroring Drive's apply_drive_delta/
drive_reconstructed_listing (#951). Hermetic: no real Graph access anywhere in this file.

_sp_list has no _normalize()-equivalent shared tail of its own, so this reconstruction replays
_sp_classify_item — the SAME per-item classification _sp_list's live loop uses (extracted from
it, byte-identical) — over a merged prior+changed set, rather than sharing a finishing function
the way _finish_drive_listing lets the Drive path.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))
import scanner  # noqa: E402

PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
DRIVE = "drv-1"


def _item(item_id, name, *, mime=PPTX, checksum=None, drive_id=DRIVE, size=1024,
         parent="/drives/drv-1/root:"):
    fmeta = {"mimeType": mime}
    if checksum:
        fmeta["hashes"] = {"quickXorHash": checksum}
    return {"id": item_id, "name": name, "file": fmeta, "size": size,
           "createdDateTime": "2026-01-01T00:00:00Z",
           "lastModifiedDateTime": "2026-02-01T00:00:00Z",
           "createdBy": {"user": {"displayName": "Dana Owner"}},
           "parentReference": {"path": parent, "driveId": drive_id}}


def _row(item_id, name, *, checksum="x", drive_id=DRIVE):
    return {"file": name, "drive_file_id": item_id, "mime": PPTX, "size_kb": 1,
           "checksum": checksum, "created_at": "2026-01-01T00:00:00Z",
           "source_modified": "2026-02-01T00:00:00Z", "owner": "Dana Owner",
           "parent_folder": "/drives/drv-1/root:", "drive_id": drive_id}


# ── apply_sp_delta ────────────────────────────────────────────────────────────────────────────

def test_an_unmentioned_file_carries_forward_untouched():
    prior = [_item("F1", "untouched.pptx")]
    out = scanner.apply_sp_delta(prior, [], set())
    assert out == prior


def test_a_changed_file_replaces_its_prior_entry_wholly():
    prior = [_item("F1", "old-name.pptx", checksum="old")]
    changed = [_item("F1", "new-name.pptx", checksum="new")]
    out = scanner.apply_sp_delta(prior, changed, set())
    assert out == [changed[0]]


def test_a_removed_id_drops_its_prior_entry():
    prior = [_item("F1", "gone.pptx"), _item("F2", "stays.pptx")]
    out = scanner.apply_sp_delta(prior, [], {(DRIVE, "F1")})
    assert [f["id"] for f in out] == ["F2"]


def test_a_changed_id_with_no_prior_entry_is_a_new_file():
    out = scanner.apply_sp_delta([], [_item("F9", "brand-new.pptx")], set())
    assert [f["id"] for f in out] == ["F9"]


def test_removed_wins_over_changed_for_the_same_id():
    prior = [_item("F1", "old.pptx")]
    changed = [_item("F1", "edited-then-deleted.pptx")]
    out = scanner.apply_sp_delta(prior, changed, {(DRIVE, "F1")})
    assert out == []


def test_removed_ids_are_scoped_by_drive_not_bare_id():
    """A Graph item id is unique only within its drive — a removal in a DIFFERENT drive must
    never drop an item with the same bare id in this one."""
    prior = [_item("F1", "same-id-different-drive.pptx", drive_id=DRIVE)]
    out = scanner.apply_sp_delta(prior, [], {("some-other-drive", "F1")})
    assert [f["id"] for f in out] == ["F1"]


def test_a_full_reconstruction_scenario():
    prior = [_item("F1", "unchanged.pptx"), _item("F2", "will-change.pptx", checksum="old"),
            _item("F3", "will-be-removed.pptx")]
    changed = [_item("F2", "will-change.pptx", checksum="new"), _item("F4", "new-file.pptx")]
    out = scanner.apply_sp_delta(prior, changed, {(DRIVE, "F3")})
    by_id = {f["id"]: f for f in out}
    assert set(by_id) == {"F1", "F2", "F4"}
    assert by_id["F2"]["file"]["hashes"]["quickXorHash"] == "new"


# ── _sp_file_from_inventory_row: the inverse of the scannable rec / _sp_inventory_row ──────────

def test_inventory_row_round_trips_into_a_raw_graph_item_shape():
    row = _row("F1", "report.pptx", checksum="abc123")
    f = scanner._sp_file_from_inventory_row(row)
    assert f["id"] == "F1" and f["name"] == "report.pptx"
    assert f["file"]["mimeType"] == PPTX
    assert f["file"]["hashes"]["quickXorHash"] == "abc123"
    assert f["createdDateTime"] == "2026-01-01T00:00:00Z"
    assert f["lastModifiedDateTime"] == "2026-02-01T00:00:00Z"
    assert f["size"] == 1 * 1024
    assert f["createdBy"]["user"]["displayName"] == "Dana Owner"
    assert f["parentReference"] == {"path": "/drives/drv-1/root:", "driveId": DRIVE}


def test_inventory_row_with_no_owner_or_folder_or_size_or_checksum_degrades_gracefully():
    row = {"file": "x.pptx", "drive_file_id": "F1", "mime": PPTX, "size_kb": None,
          "checksum": None, "created_at": None, "source_modified": None, "owner": None,
          "parent_folder": None, "drive_id": None}
    f = scanner._sp_file_from_inventory_row(row)
    assert f["size"] is None
    assert f["createdBy"] == {}
    assert f["file"]["hashes"] == {}
    assert f["parentReference"] == {"path": None, "driveId": None}


# ── sp_reconstructed_listing: parity with a fresh _sp_list listing ────────────────────────────

def test_reconstructed_listing_matches_a_fresh_listings_scope_out_shape():
    prior_files = [scanner._sp_file_from_inventory_row(_row("F1", "unchanged.pptx"))]
    changed = [_item("F2", "new.pptx")]
    scope_out: dict = {}
    inventory_out: list = []
    result = scanner.sp_reconstructed_listing(prior_files, changed, set(),
                                              scope_out=scope_out, inventory_out=inventory_out)
    assert sorted(i["name"] for i in result) == ["new.pptx", "unchanged.pptx"]
    # _sp_list's own scope_out contract is just {"inventory": ...} — _list()'s SharePoint tail
    # adds kind/site/kept/truncated afterwards for BOTH a live and a reconstructed listing.
    assert "inventory" in scope_out
    assert scope_out["reconstructed"] is True
    assert scope_out["inventory"]["truncated"] is False


def test_reconstructed_listing_honors_max_files():
    prior_files = [scanner._sp_file_from_inventory_row(_row(f"F{i}", f"f{i}.pptx"))
                  for i in range(5)]
    result = scanner.sp_reconstructed_listing(prior_files, [], set(), max_files=3)
    assert len(result) == 3


def test_reconstructed_listing_flags_truncation_when_the_merged_set_exceeds_max_files():
    prior_files = [scanner._sp_file_from_inventory_row(_row(f"F{i}", f"f{i}.pptx"))
                  for i in range(5)]
    scope_out: dict = {}
    scanner.sp_reconstructed_listing(prior_files, [], set(), max_files=3, scope_out=scope_out)
    assert scope_out["inventory"]["truncated"] is True


def test_reconstructed_listing_still_excludes_acps_own_mirror_folder(monkeypatch):
    import core
    monkeypatch.setattr(core.store, "get_drive_mirror_folder", lambda: "Remediated", raising=False)
    mirrored = _item("F1", "fixed.pptx", parent="/drives/drv-1/root:/Remediated")
    kept = _item("F2", "real.pptx")
    result = scanner.sp_reconstructed_listing([], [mirrored, kept], set(),
                                              exclude_remediated=True)
    assert [f["name"] for f in result] == ["real.pptx"]


def test_reconstructed_listing_still_inventories_non_scannable_items():
    photo = _item("F1", "photo.png", mime="image/png")
    inventory_out: list = []
    result = scanner.sp_reconstructed_listing([], [photo], set(), inventory_out=inventory_out)
    assert result == []
    assert len(inventory_out) == 1 and inventory_out[0]["file"] == "photo.png"


def test_reconstructed_listing_carries_the_checksum_through(monkeypatch):
    """The whole point of #963 (checksum support) reaching reconstruction too: a changed item's
    quickXorHash must survive into the scannable record ADR 0011 reuse reads."""
    changed = [_item("F1", "fixed.pptx", checksum="NEWHASH")]
    [rec] = scanner.sp_reconstructed_listing([], changed, set())
    assert rec["checksum"] == "NEWHASH"


# ── _list()'s sp_delta seam: the full wiring, no real Graph access ────────────────────────────

def test_list_uses_the_reconstruction_when_sp_delta_is_given():
    """token=None proves it: a reconstruction never touches Graph at all."""
    prior_files = [scanner._sp_file_from_inventory_row(_row("F1", "unchanged.pptx"))]
    delta = {"prior_files": prior_files, "changed": [_item("F2", "new.pptx")],
            "removed_ids": set()}
    scope: dict = {}
    items = scanner._list("sharepoint", svc=None, folder=f"{DRIVE}/root", sp_token=None,
                          scope_out=scope, sp_delta=delta)
    assert sorted(i["name"] for i in items) == ["new.pptx", "unchanged.pptx"]
    assert scope["reconstructed"] is True


def test_list_falls_back_to_a_live_walk_when_sp_delta_is_none(monkeypatch):
    """The existing behavior, unchanged: no sp_delta means _sp_list runs as always."""
    calls = []
    monkeypatch.setattr(scanner, "_sp_list", lambda *a, **kw: (calls.append(kw), [])[1])
    scanner._list("sharepoint", svc=None, folder=f"{DRIVE}/root", sp_token="tok", sp_delta=None)
    assert len(calls) == 1
