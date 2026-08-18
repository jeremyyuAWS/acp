"""Per-file estate inventory: paginated list + CSV export (Discovery gap G2).

The estate is persisted per file in scan_inventory, but no client could LIST or EXPORT it — the
dashboard only ever saw a capped 200/status sample. These pin the two endpoints that expose the
durable rows: owner-scoped, DB-paginated, capability-enriched, and a full CSV export.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

ROOT = Path(__file__).resolve().parent.parent
DOC = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# ── store: DB-level pagination ────────────────────────────────────────────────────────────────
def test_list_inventory_page_pages_from_the_db_by_file(isolated_store):
    s = isolated_store
    s.add_inventory("scan1", [{"file": f"f{i:03d}.docx", "mime": DOC, "owner": "a@b.c", "size_kb": i}
                              for i in range(10)])
    assert s.count_inventory("scan1") == 10
    first = s.list_inventory_page("scan1", limit=4, offset=0)
    assert [r["file"] for r in first] == ["f000.docx", "f001.docx", "f002.docx", "f003.docx"]  # ORDER BY file
    last = s.list_inventory_page("scan1", limit=4, offset=8)
    assert [r["file"] for r in last] == ["f008.docx", "f009.docx"]     # partial final page, no error
    assert first[0]["owner"] == "a@b.c" and first[0]["size_kb"] == 0    # source metadata round-trips


# ── endpoint wiring (source-level, matching the repo's route-test style) ───────────────────────
def test_inventory_endpoints_owner_scoped_paginated_and_capability_enriched():
    src = (ROOT / "api" / "routes" / "scans.py").read_text()
    assert '@router.get("/scans/{sid}/inventory")' in src
    assert '@router.get("/scans/{sid}/inventory.csv")' in src

    listbody = re.search(r"def scan_inventory_list\(.*?(?=\n@router)", src, re.S).group(0)
    assert "get_scan(sid, owner=_owner(request))" in listbody and "404" in listbody   # owner-scoped
    assert "limit: int = Query(200, ge=1, le=1000)" in listbody                       # paginated, bounded
    assert "list_inventory_page(sid, limit=limit, offset=offset)" in listbody         # DB paging, not fetch-all
    assert '"total": core.store.count_inventory(sid)' in listbody                     # real total
    assert "_inv_capability(r)" in listbody                                           # capability-enriched

    csvbody = re.search(r"def scan_inventory_csv\(.*?(?=\n@router)", src, re.S).group(0)
    assert 'media_type="text/csv"' in csvbody and "attachment; filename=" in csvbody  # a download
    assert "list_inventory(sid)" in csvbody                                           # ALL rows, not a page
    assert '"format", "status"' in csvbody                                            # capability columns exported


def test_inv_capability_derives_format_status_from_the_stored_mime():
    body = re.search(r"def _inv_capability\(.*?(?=\ndef |\n@router)",
                     (ROOT / "api" / "routes" / "scans.py").read_text(), re.S).group(0)
    assert "estate_inventory" in body and "classify" in body
    assert 'row.get("mime")' in body   # classification comes from the persisted mime, same as the estate summary
