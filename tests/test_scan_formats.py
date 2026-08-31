"""Discovery's format scope — one source of truth, and the two connector filters that read it.

WHAT THESE PIN. The scope narrowed to PDF/DOCX/XLSX/PPTX on 2026-08-31. The risk in that change
is not the narrowing itself, it is DRIFT: the set is consumed by a Drive MIME filter, a
SharePoint extension filter, and the estate inventory's `assessable` status, and before
api/scan_formats those were three independent literals. A file the connectors stop listing but
the inventory still calls assessable inflates the assessment-eligible denominator forever, and it
does so silently — the count just reads a little high.

So most of what is asserted here is AGREEMENT under a changed scope, not the default values.
Several tests deliberately move the scope and check that every consumer moves with it; a
consumer that kept its own copy of the list would pass on the defaults and fail here.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import estate_inventory  # noqa: E402
import scan_formats  # noqa: E402
import scanner  # noqa: E402

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
HTML = "text/html"
GDOC = "application/vnd.google-apps.document"
GSHEET = "application/vnd.google-apps.spreadsheet"
GSLIDES = "application/vnd.google-apps.presentation"


# ── the scope itself ────────────────────────────────────────────────────────────────────────
def test_default_scope_is_the_four_formats():
    assert scan_formats.formats() == frozenset({"pdf", "docx", "xlsx", "pptx"})


def test_env_var_widens_and_narrows_the_scope(monkeypatch):
    monkeypatch.setenv("ACP_SCAN_FORMATS", "pdf,html")
    assert scan_formats.formats() == frozenset({"pdf", "html"})

    # Whitespace, case and a leading dot are all tolerated — an operator writing ".PDF, .Docx"
    # means something obvious and should not get a silently different scope for it.
    monkeypatch.setenv("ACP_SCAN_FORMATS", " .PDF , .Docx ")
    assert scan_formats.formats() == frozenset({"pdf", "docx"})


def test_a_malformed_scope_falls_back_rather_than_discovering_nothing(monkeypatch):
    """An empty scope would produce empty scans that look exactly like an empty estate.

    That is the failure nobody investigates — "the scan found 0 files" reads as a fact about the
    customer's Drive, not about a typo in an env var — so a value that leaves nothing valid must
    fall back to the default rather than being honoured.
    """
    for bad in ("", "   ", "doc,ppt,xls", "everything", ",,,"):
        monkeypatch.setenv("ACP_SCAN_FORMATS", bad)
        assert scan_formats.formats() == frozenset(scan_formats.DEFAULT_FORMATS), bad

    # A partially-valid value keeps the valid part and drops the rest, rather than falling back
    # wholesale — "pdf,docx,mp4" plainly asks for pdf and docx.
    monkeypatch.setenv("ACP_SCAN_FORMATS", "pdf,docx,mp4")
    assert scan_formats.formats() == frozenset({"pdf", "docx"})


def test_scope_is_read_per_call_not_latched_at_import(monkeypatch):
    """The import-time-latch bug api/worker_main.py's header records, guarded against here.

    If any consumer computed its set at import, this test would pass on the first assertion and
    fail on the second — and in production the symptom would be a deployment silently ignoring
    its own configuration while reporting itself healthy.
    """
    before = scan_formats.formats()
    monkeypatch.setenv("ACP_SCAN_FORMATS", "html")
    assert scan_formats.formats() == frozenset({"html"})
    monkeypatch.delenv("ACP_SCAN_FORMATS")
    assert scan_formats.formats() == before


# ── Google-native types ride on their export format ─────────────────────────────────────────
def test_google_native_types_are_in_scope_via_their_export_target():
    """Reading "four file types" as "four MIME types" would drop native Google documents.

    A Google Doc exports to .docx and is assessed as one (scanner.EXPORT_MAP), so it is in scope
    exactly when docx is. On a Drive estate these are routinely the majority of the real content,
    which makes this the most expensive way to get the scope decision wrong.
    """
    mimes = scanner._scannable_mime()
    for native in (GDOC, GSHEET, GSLIDES):
        assert native in mimes, native


def test_google_native_leaves_scope_with_its_export_format(monkeypatch):
    monkeypatch.setenv("ACP_SCAN_FORMATS", "pdf")
    mimes = scanner._scannable_mime()
    assert PDF in mimes
    for native in (GDOC, GSHEET, GSLIDES):
        assert native not in mimes, native

    # Slides only: the presentation native comes back, the other two stay out.
    monkeypatch.setenv("ACP_SCAN_FORMATS", "pptx")
    mimes = scanner._scannable_mime()
    assert GSLIDES in mimes
    assert GDOC not in mimes and GSHEET not in mimes


# ── the Drive filter ────────────────────────────────────────────────────────────────────────
def test_drive_scannable_mimes_follow_the_scope(monkeypatch):
    assert scanner._is_scannable_mime({"mimeType": PDF})
    assert scanner._is_scannable_mime({"mimeType": DOCX})
    assert scanner._is_scannable_mime({"mimeType": XLSX})
    assert scanner._is_scannable_mime({"mimeType": PPTX})
    assert not scanner._is_scannable_mime({"mimeType": HTML})
    assert not scanner._is_scannable_mime({"mimeType": "text/plain"})

    monkeypatch.setenv("ACP_SCAN_FORMATS", "pdf,docx,xlsx,pptx,html")
    assert scanner._is_scannable_mime({"mimeType": HTML})


def test_drive_mime_query_is_stable_and_scoped(monkeypatch):
    """`/sources` builds a Drive query from this, so it must be deterministic.

    Set iteration order is not, and an unstable query string differs run to run — which defeats
    both response caching and any attempt to compare two listings in a log.
    """
    monkeypatch.setenv("ACP_SCAN_FORMATS", "pdf,docx")
    q = scanner._drive_mime_q()
    assert q == scanner._drive_mime_q()
    assert f"mimeType='{PDF}'" in q and f"mimeType='{DOCX}'" in q
    assert HTML not in q
    assert q.count(" or ") == len(scanner._scannable_mime()) - 1


# ── the SharePoint filter ───────────────────────────────────────────────────────────────────
def test_sharepoint_extensions_follow_the_scope(monkeypatch):
    assert scanner._sp_scannable_exts() == frozenset({".pdf", ".docx", ".xlsx", ".pptx"})

    # html is the one format with two extensions; both come and go together.
    monkeypatch.setenv("ACP_SCAN_FORMATS", "html")
    assert scanner._sp_scannable_exts() == frozenset({".html", ".htm"})


def test_sharepoint_walk_drops_an_out_of_scope_file():
    """The connector-side filter, exercised through the classifier the walk actually calls.

    Not a check on the extension set in isolation: `_sp_classify_item` is where the intake
    boundary is enforced, and it is what has to stop fetching HTML — the set agreeing while the
    call site used a stale copy is precisely the drift these tests exist for.
    """
    exts = scanner._sp_scannable_exts()

    def _item(name):
        return {"id": "i-" + name, "name": name, "file": {"mimeType": "application/octet-stream"},
                "parentReference": {"path": "/drive/root:/Policies"}}

    kept = scanner._sp_classify_item(_item("report.pdf"), drive_id="d1",
                                     skip_folders=set(), exts=exts)
    assert kept is not None and kept["scannable"] is not None

    dropped = scanner._sp_classify_item(_item("page.html"), drive_id="d1",
                                        skip_folders=set(), exts=exts)
    # Still inventoried — discovery counts the whole estate — but never handed to the scan.
    assert dropped is not None
    assert dropped["scannable"] is None
    assert dropped["inventory_row"] is not None


# ── the three consumers agree ───────────────────────────────────────────────────────────────
def test_every_consumer_moves_together_when_the_scope_changes(monkeypatch):
    """The whole point of the module, asserted directly across all three consumers at once."""
    monkeypatch.setenv("ACP_SCAN_FORMATS", "pdf")

    # 1. Drive listing filter
    assert scanner._is_scannable_mime({"mimeType": PDF})
    assert not scanner._is_scannable_mime({"mimeType": DOCX})
    # 2. SharePoint walk filter
    assert scanner._sp_scannable_exts() == frozenset({".pdf"})
    # 3. Capability status the coverage funnel counts
    assert estate_inventory.classify(
        {"id": "1", "name": "a.pdf", "mimeType": PDF})["status"] == estate_inventory.ASSESSABLE
    assert estate_inventory.classify(
        {"id": "2", "name": "b.docx", "mimeType": DOCX})["status"] == estate_inventory.UNSUPPORTED
