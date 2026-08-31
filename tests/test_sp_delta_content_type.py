"""SharePoint Content Type survives a delta-sync reconstruction (docs/TODO.md P1e).

THE BUG. `scan_inventory.content_type` is a real column and `store.add_inventory` populates it —
but `store.latest_scan_inventory_items`, the query that reads a prior scan's inventory back as a
reconstruction baseline, did not list it. So every delta sync rebuilt the estate from rows with
the field absent, and each carried-forward file was re-inventoried as having no Content Type. A
library scanned incrementally lost the metadata on every file that had not changed — which, in a
feature whose entire point is that most files have not changed, is nearly all of them.

WHY IT SURVIVED. `scanner._sp_file_from_inventory_row`'s docstring stated the conclusion as
settled fact: "`content_type` … can NEVER be reconstructed: it is never persisted to
scan_inventory". The premise was false. The symptom (the value is absent from the baseline) was
read as its cause (the value was never stored), and the note then made the loss look designed,
so nobody re-checked. The cost argument in that note was correct and still is — recovering it
live is a per-item Graph call and delta sync exists to avoid exactly that — but nothing needed
recovering.

WHAT MUST HOLD, and the reason each is here rather than one end-to-end assertion: the three
pieces failed independently, and a test that only checked the final estate would not say which.

  1. The column comes back from the store query at all.
  2. The reconstructed raw item carries it, under a key marked as ACP's own rather than
     disguised as a Graph field.
  3. A CHANGED file legitimately has none. apply_sp_delta replaces a changed id wholly with its
     fresh raw item, and that item has not been enriched — so this is correct behaviour, not a
     leak in the fix, and pinning it stops someone "fixing" it by merging field-by-field.
  4. A live listing classifies byte-identically to before. `_sp_classify_item` is shared VERBATIM
     between the live and reconstructed paths and its docstring depends on that.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import scanner  # noqa: E402

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
DRIVE = "b!drive-a"


def _inv_row(fid, name, content_type=None):
    """A scan_inventory row shaped as store.latest_scan_inventory_items returns it."""
    return {"file": name, "drive_file_id": fid, "mime": DOCX, "size_kb": 12,
            "checksum": "qxh", "created_at": "2026-08-01T00:00:00Z",
            "source_modified": "2026-08-02T00:00:00Z", "owner": "alice",
            "parent_folder": "/drive/root:", "drive_id": DRIVE,
            "drive_account_id": None, "content_type": content_type}


def _live_item(fid, name):
    return {"id": fid, "name": name, "file": {"mimeType": DOCX, "hashes": {}},
            "parentReference": {"path": "/drive/root:", "driveId": DRIVE},
            "lastModifiedDateTime": "2026-08-30T00:00:00Z"}


# ── 2. the reconstructed raw item carries it ─────────────────────────────────────

def test_a_stored_content_type_rides_the_reconstructed_item():
    raw = scanner._sp_file_from_inventory_row(_inv_row("F1", "policy.docx", "Contract"))
    assert raw["_acp_content_type"] == "Contract"


def test_a_row_without_one_gets_no_key_at_all():
    """Not `None` — absent. A contentless row's reconstructed shape stays exactly what it was
    before this change, so nothing downstream can start distinguishing the two by accident."""
    raw = scanner._sp_file_from_inventory_row(_inv_row("F1", "policy.docx"))
    assert "_acp_content_type" not in raw


def test_the_carrier_key_is_marked_as_acps_own():
    """The dict is otherwise a faithful raw driveItem. A Graph-shaped name (`contentType`) would
    leave a reader unable to tell which fields Graph sent and which ACP invented."""
    raw = scanner._sp_file_from_inventory_row(_inv_row("F1", "policy.docx", "Contract"))
    ours = [k for k in raw if k.startswith("_acp_")]
    assert ours == ["_acp_content_type"]
    assert "contentType" not in raw


# ── the value reaches the scannable record, and the estate ───────────────────────

def _reconstruct(prior, changed=(), removed=()):
    return scanner.sp_reconstructed_listing(list(prior), list(changed), set(removed))


def test_an_unchanged_file_keeps_its_content_type_through_a_full_reconstruction():
    prior = [scanner._sp_file_from_inventory_row(_inv_row("F1", "policy.docx", "Contract"))]
    files = _reconstruct(prior)
    assert [f["name"] for f in files] == ["policy.docx"]
    assert files[0]["content_type"] == "Contract", (
        "an unchanged file lost its Content Type — this is the P1e regression")


def test_a_changed_file_correctly_has_none():
    """apply_sp_delta replaces a changed id WHOLLY with the fresh raw item, which has not been
    enriched. Correct, and pinned so it is not "fixed" by merging field-by-field: the delta's
    metadata is the authority for a file it reports as changed."""
    prior = [scanner._sp_file_from_inventory_row(_inv_row("F1", "policy.docx", "Contract"))]
    files = _reconstruct(prior, changed=[_live_item("F1", "policy.docx")])
    assert len(files) == 1
    assert files[0].get("content_type") is None


def test_a_mixed_estate_carries_only_the_unchanged_ones():
    prior = [scanner._sp_file_from_inventory_row(_inv_row("F1", "a.docx", "Contract")),
             scanner._sp_file_from_inventory_row(_inv_row("F2", "b.docx", "Policy")),
             scanner._sp_file_from_inventory_row(_inv_row("F3", "c.docx"))]
    files = _reconstruct(prior, changed=[_live_item("F2", "b.docx")])
    got = {f["name"]: f.get("content_type") for f in files}
    assert got == {"a.docx": "Contract", "b.docx": None, "c.docx": None}


# ── 4. a live listing is unchanged ───────────────────────────────────────────────

def test_a_live_item_classifies_exactly_as_before():
    """`_sp_classify_item` is shared verbatim by the live paging loop and the reconstruction
    replay. A live Graph item never carries the private key, so the live path must be untouched
    — no content_type invented, and none of the other fields disturbed."""
    classified = scanner._sp_classify_item(
        _live_item("F9", "fresh.docx"), drive_id=DRIVE,
        skip_folders=scanner._sp_skip_folders(False), exts=scanner._sp_scannable_exts())
    assert classified["scannable"] is not None
    assert "content_type" not in classified["scannable"]
    assert classified["scannable"]["id"] == "F9"
    assert classified["scannable"]["driveId"] == DRIVE


# ── 1. the store query actually reads the column ─────────────────────────────────

def test_the_baseline_query_selects_content_type():
    """The one-name omission that caused all of it. Asserted against the source because the
    query's shape IS the defect — a store-level round trip would pass on any column list that
    happens to include it for another reason."""
    import inspect
    import store
    src = inspect.getsource(store.Store.latest_scan_inventory_items)
    select = src[src.index("SELECT file,"):]
    assert "content_type" in select[:select.index("FROM scan_inventory")], (
        "latest_scan_inventory_items does not read content_type back, so every delta-sync "
        "reconstruction starts from a baseline that has already lost it")
