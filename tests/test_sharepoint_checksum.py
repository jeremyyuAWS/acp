"""SharePoint checksum support (PRD Phase 3 follow-up to #961).

Every checksum-gated reuse path in the pipeline reads `item.get("checksum")` off whatever
scanner._list() returned for a file — ADR 0011 cross-scan analysis reuse
(store.find_prior_analysis), within-scan dedup (store.find_by_checksum), the ADR 0020
source-bytes cache (scanner.read_cached_source/cache_source_bytes), and the ADR 0003 document
identity layer (documents.resolve_doc_id). store.py's own docstrings named SharePoint as "a
checksum-less source" because _sp_list's `rec` never set the key — every one of those paths was
silently a no-op for SharePoint, even though Microsoft Graph's `file` facet (already selected by
_SP_ITEM_SELECT) carries `hashes.quickXorHash`, OneDrive/SharePoint's own content hash, right
alongside the mimeType this code already read. This closes that gap: no plumbing changes, no new
Graph field selection (a facet comes back whole once selected — there's no narrower
`file.hashes` sub-select), just reading a value that was already in every response.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import scanner  # noqa: E402

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PNG = "image/png"


def _item(fid, name, mime, *, quickxor=None, path="/drive/root:"):
    fmeta = {"mimeType": mime}
    if quickxor is not None:
        fmeta["hashes"] = {"quickXorHash": quickxor}
    return {"id": fid, "name": name, "file": fmeta, "parentReference": {"path": path}}


# ── the scannable item (rec) ─────────────────────────────────────────────────────────────────

def test_a_scannable_items_quickxorhash_becomes_its_checksum(monkeypatch):
    page = {"value": [_item("1", "brief.docx", DOCX, quickxor="ABC123==")]}
    monkeypatch.setattr(scanner, "_sp_get", lambda token, url: page)
    [result] = scanner._sp_list("tok", max_files=10, site=None)
    assert result["checksum"] == "ABC123=="


def test_a_file_with_no_computed_hash_yet_has_a_none_checksum_not_a_crash(monkeypatch):
    # Graph has not finished computing quickXorHash for a very freshly-written file — same gap
    # Drive's own md5Checksum has (see _normalize's comment). Must not KeyError.
    page = {"value": [_item("1", "brief.docx", DOCX)]}   # no "hashes" key at all
    monkeypatch.setattr(scanner, "_sp_get", lambda token, url: page)
    [result] = scanner._sp_list("tok", max_files=10, site=None)
    assert result["checksum"] is None


def test_two_files_with_the_same_hash_are_still_two_distinct_results(monkeypatch):
    # Checksum dedup happens downstream (store.find_by_checksum, scoped to one scan_id) — _sp_list
    # itself must not collapse or otherwise special-case a repeated hash.
    page = {"value": [_item("1", "a.docx", DOCX, quickxor="SAME"),
                      _item("2", "b.docx", DOCX, quickxor="SAME")]}
    monkeypatch.setattr(scanner, "_sp_get", lambda token, url: page)
    result = scanner._sp_list("tok", max_files=10, site=None)
    assert sorted(r["name"] for r in result) == ["a.docx", "b.docx"]
    assert [r["checksum"] for r in result] == ["SAME", "SAME"]


def test_checksum_survives_the_multi_library_site_path_too(monkeypatch):
    monkeypatch.setattr(scanner, "_sp_drives", lambda token, site: [{"id": "libA"}])
    monkeypatch.setattr(scanner, "_sp_get",
                        lambda token, url: {"value": [_item("1", "a.docx", DOCX, quickxor="X")]})
    [result] = scanner._sp_list("tok", max_files=10, site="contoso.sharepoint.com,g1,g2")
    assert result["checksum"] == "X"


# ── the non-scannable item (_sp_inventory_row) ──────────────────────────────────────────────

def test_a_non_scannable_items_quickxorhash_also_reaches_its_inventory_row(monkeypatch):
    page = {"value": [_item("1", "photo.png", PNG, quickxor="PNGHASH")]}
    monkeypatch.setattr(scanner, "_sp_get", lambda token, url: page)
    inv: list = []
    scanner._sp_list("tok", max_files=10, site=None, inventory_out=inv)
    [row] = inv
    assert row["checksum"] == "PNGHASH"


def test_sp_inventory_row_direct_with_no_hashes_key_is_none(monkeypatch):
    row = scanner._sp_inventory_row({"id": "1", "name": "photo.png", "file": {"mimeType": PNG}})
    assert row["checksum"] is None
