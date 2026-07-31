"""A scan's summary must count the documents the same scan's file list hands out.

Observed live on 2026-07-30 against acp-app:598abe9 (v2026.7.30.3), scan 12f28938cd2f — a
whole-Drive scan that listed 8 raw files and kept 4. One of the 4 was a remediated .docx ACP had
written back to Drive under the source document's own name, so `get_scan` correctly dropped it
from `files` (shadowed_acp_outputs). `scan_runs` still counted it. The Overview then said, on one
screen:

    documents 4 · certifiable 3 · audit-ready 75%
    [status donut] 3 documents — 2 certifiable, 1 issues
    Scope: 3 of 4 documents have been analysed — the rest were discovered but not yet assessed.
           Findings, certifiable and audit-ready describe the analysed documents only.

and the Discover tab, reading the same file list, said 3 documents.

Both halves of every pair came from the same scan. The tile counted an artifact ACP made; the
donut counted the estate. The scope line then explained the gap with a reason that was false —
the hidden file was analysed, and scored 92 — and promised that certifiable described the
analysed documents only, which the 3 in the tile did not.

The artifact was compliant and scored 92, as remediated output tends to be, so documents,
certifiable, audit-ready and avg_score were all wrong in the flattering direction.

The row shape below is production's, exactly: a source .docx that failed at 68, the ACP copy of
it stamped and passing at 92, plus two unrelated passing PDFs.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "jeremyyu.movate@gmail.com"
SOURCE = "HIM_ROI_Instructions_06.02.2025 (1).docx"
ACP_COPY = "HIM_ROI_Instructions_06.02.2025.docx"     # ACP's own output, same logical name


def _prod_shaped_scan(store, sid="s-shadow"):
    """Scan 12f28938cd2f's four file_records, reproduced from their real column values."""
    store.init_scan_run(sid, "drive", 4, "2026-07-30T14:21:02Z", "default", "rh1",
                        owner=OWNER, status="running")
    rows = [
        ("authorization-to-disclose-phi-english-2026-04.pdf", "python/pdf", "analysed", 92, 1, None),
        (SOURCE, ".net/office", "analysed", 68, 0, None),
        (ACP_COPY, ".net/office", "analysed", 92, 1, "2026-07-30"),
        ("HIM_ROI_Instructions_06.02.2025.pdf", "python/pdf", "analysed", 92, 1, None),
    ]
    for name, engine, status, score, compliant, stamped in rows:
        store.save_file_result(sid, {
            "file": name, "engine": engine, "status": status, "score": score,
            "compliant": compliant, "skipped_rules": 0, "acp_stamped": stamped, "issues": [],
        }, "2026-07-30T14:30:43Z")
    store.finalize_scan_run(sid, "2026-07-30T14:30:43Z")
    return sid


def test_the_hidden_artifact_is_hidden_from_the_counters_too(isolated_store):
    store = isolated_store
    sid = _prod_shaped_scan(store)
    g = store.get_scan(sid, owner=OWNER)
    run, files = g["run"], g["files"]

    # The file list already got this right; it is the summary that did not.
    assert [f["file"] for f in files] == sorted(
        ["authorization-to-disclose-phi-english-2026-04.pdf", SOURCE,
         "HIM_ROI_Instructions_06.02.2025.pdf"])

    # The four tiles, in the order the Overview renders them.
    assert run["files"] == len(files) == 3            # was 4 — counted ACP's own copy
    assert run["certifiable"] == 2                    # was 3 — the copy passes at 92
    assert round(run["certifiable"] / run["files"] * 100) == 67   # audit-ready; was 75%
    assert run["avg_score"] == 84                     # was 86 — (92+68+92)/3, not /4


def test_the_scope_line_stops_firing_because_there_is_no_gap_left(isolated_store):
    """`analysed < n` is what puts the (false) "the rest were discovered but not yet assessed"
    banner on screen. With the counters reconciled, every document in the list is accounted for
    by the total and the banner does not render at all."""
    store = isolated_store
    sid = _prod_shaped_scan(store)
    g = store.get_scan(sid, owner=OWNER)
    analysed = [f for f in g["files"] if f.get("score") is not None]
    assert len(analysed) == g["run"]["files"]


def test_the_scan_picker_row_agrees_with_the_tile(isolated_store):
    """Overview renders scan history as "certifiable / files" straight off list_scans, on the
    same screen as the tiles. It funnels through the same _fill_run_aggregate, so it must not
    need its own copy of the rule."""
    store = isolated_store
    sid = _prod_shaped_scan(store)
    row = next(r for r in store.list_scans(owner=OWNER) if r["id"] == sid)
    assert (row["certifiable"], row["files"]) == (2, 3)
    assert row["avg_score"] == 84


def test_an_ordinary_scan_is_left_exactly_as_it_was(isolated_store):
    """Nothing shadowed — the overwhelmingly common case — must be untouched, counters and all.
    This is the guard that keeps the reconciliation from becoming a second opinion about every
    scan in the product."""
    store = isolated_store
    sid = "s-clean"
    store.init_scan_run(sid, "drive", 2, "2026-07-30T14:00:00Z", "default", "rh1",
                        owner=OWNER, status="running")
    for name, score, compliant in [("a.pdf", 90, 1), ("b.docx", 40, 0)]:
        store.save_file_result(sid, {
            "file": name, "engine": "python/pdf", "status": "analysed", "score": score,
            "compliant": compliant, "skipped_rules": 0, "issues": [],
        }, "2026-07-30T14:05:00Z")
    stored = store.finalize_scan_run(sid, "2026-07-30T14:05:00Z")

    run = store.get_scan(sid, owner=OWNER)["run"]
    assert (run["files"], run["certifiable"], run["avg_score"]) == (2, 1, 65)
    assert (stored["files"], stored["certifiable"], stored["avg_score"]) == (2, 1, 65)


def test_a_published_certified_document_still_counts_as_a_document(isolated_store):
    """A stamped file with no unstamped twin IS the document now (shadowed_acp_outputs says so).
    It must keep its place in both the list and the count — dropping it here would be the
    mirror-image error, an estate that shrinks every time a fix is published."""
    store = isolated_store
    sid = "s-published"
    store.init_scan_run(sid, "drive", 1, "2026-07-30T14:00:00Z", "default", "rh1",
                        owner=OWNER, status="running")
    store.save_file_result(sid, {
        "file": "policy.pdf", "engine": "python/pdf", "status": "analysed", "score": 96,
        "compliant": 1, "skipped_rules": 0, "acp_stamped": "2026-07-30", "issues": [],
    }, "2026-07-30T14:05:00Z")
    store.finalize_scan_run(sid, "2026-07-30T14:05:00Z")

    g = store.get_scan(sid, owner=OWNER)
    assert [f["file"] for f in g["files"]] == ["policy.pdf"]
    assert (g["run"]["files"], g["run"]["certifiable"]) == (1, 1)


def test_a_discover_only_scan_keeps_its_inventory_total(isolated_store):
    """ADR 0020: inventory listed, no file_records yet. There are no rows to reconcile against,
    and reading zero rows as "zero documents" would blank the estate."""
    store = isolated_store
    sid = "s-discovered"
    store.init_scan_run(sid, "drive", 8, "2026-07-30T14:00:00Z", "default", "rh1",
                        owner=OWNER, status="discovered")
    store.add_inventory(sid, [{"file": f"doc-{i}.pdf", "doc_class": "pdf", "size_kb": 10}
                              for i in range(8)])
    with store._db.cursor() as cur:
        store._db.execute(cur, "UPDATE scan_runs SET completed_at=%s WHERE id=%s",
                          ("2026-07-30T14:01:00Z", sid))

    run = store.get_scan(sid, owner=OWNER)["run"]
    assert run["files"] == 8
    assert run["avg_score"] is None      # nobody measured anything; not a 0
