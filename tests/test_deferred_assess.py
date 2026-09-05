"""Deferred analysis: Discover lists, Assess opens the file (ADR 0020 stage 3/4).

The behavioural contract, both directions of the kill-switch:
  - deferral ON  → scan_discover writes a metadata-only inventory + status 'discovered' and
    enqueues NO analysis; the download+WCAG work runs only when Assess (scan_assess) fires.
  - deferral OFF → scan_discover fans out the analysis immediately (today's behaviour).
The finalize counter (count_files_done over file_records) is untouched: file_records fill only
during Assess, so nothing about finalization changes.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import classify  # noqa: E402

_PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _items():
    return [{"name": "deck.pptx", "id": "d1", "mime": _PPTX_MIME},
            {"name": "sheet.xlsx", "id": "d2", "mime": _XLSX_MIME}]


# ── metadata-only classification (no bytes) ─────────────────────────────────────

def test_classify_from_metadata_by_ext_and_mime():
    assert classify.classify_from_metadata("a.pptx")["doc_class"] == "slide-deck"
    assert classify.classify_from_metadata("a.xlsx")["doc_class"] == "spreadsheet"
    assert classify.classify_from_metadata("a.pdf")["doc_class"] == "pdf-document"
    assert classify.classify_from_metadata("a.docx")["doc_class"] == "text-document"
    assert classify.classify_from_metadata("a.html")["doc_class"] == "web-page"
    # mime wins when the name has no useful extension
    assert classify.classify_from_metadata("Untitled", _PPTX_MIME)["doc_class"] == "slide-deck"
    # image extensions and MIME types
    assert classify.classify_from_metadata("photo.png")["doc_class"] == "image"
    assert classify.classify_from_metadata("photo.jpg")["doc_class"] == "image"
    assert classify.classify_from_metadata("logo.svg")["doc_class"] == "image"
    assert classify.classify_from_metadata("Untitled", "image/png")["doc_class"] == "image"
    assert classify.classify_from_metadata("Untitled", "image/jpeg")["doc_class"] == "image"
    assert classify.classify_from_metadata("Untitled", "image/webp")["doc_class"] == "image"
    img = classify.classify_from_metadata("photo.png")
    assert img["has_images"] is True
    # audio/video extensions and MIME types
    assert classify.classify_from_metadata("clip.mp4")["doc_class"] == "audio-video"
    assert classify.classify_from_metadata("song.mp3")["doc_class"] == "audio-video"
    assert classify.classify_from_metadata("Untitled", "video/mp4")["doc_class"] == "audio-video"
    assert classify.classify_from_metadata("Untitled", "audio/mpeg")["doc_class"] == "audio-video"
    # counts are deferred to Assess (need the bytes) — null here, never fabricated
    m = classify.classify_from_metadata("a.pptx")
    assert m["pages"] is None and m["images"] is None and m["is_scanned"] is False


# ── discover: deferred vs immediate ─────────────────────────────────────────────

def test_discover_deferred_writes_inventory_and_no_analysis(isolated_store, monkeypatch):
    import core
    import handlers
    import scanner
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: _items())
    handlers._scan_discover({"scan_id": "s1", "source": "local", "user": None}, {"scan_id": "s1"})

    inv = isolated_store.list_inventory("s1")
    assert {r["file"] for r in inv} == {"deck.pptx", "sheet.xlsx"}
    assert {r["doc_class"] for r in inv} == {"slide-deck", "spreadsheet"}
    run = isolated_store.get_scan("s1")["run"]
    assert run["status"] == "discovered"
    jobs = isolated_store.list_jobs()
    assert not any(j["type"] in ("scan_file", "scan_batch") for j in jobs)   # NOTHING opened
    # get_scan surfaces the inventory as 'discovered' rows so Discover shows the estate
    files = isolated_store.get_scan("s1")["files"]
    assert len(files) == 2 and all(f["status"] == "discovered" and f["score"] is None for f in files)


def test_discover_immediate_enqueues_analysis(isolated_store, monkeypatch):
    import core
    import handlers
    import scanner
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "0")
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: _items())
    handlers._scan_discover({"scan_id": "s2", "source": "local", "user": None}, {"scan_id": "s2"})

    run = isolated_store.get_scan("s2")["run"]
    assert run["status"] == "running"
    assert isolated_store.count_inventory("s2") == 0                          # no inventory table use
    jobs = isolated_store.list_jobs()
    assert sum(1 for j in jobs if j["type"] == "scan_file") == 2              # analysis fanned out now


def test_assess_kicks_off_fanout_from_inventory(isolated_store, monkeypatch):
    import core
    import handlers
    import scanner
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: _items())
    handlers._scan_discover({"scan_id": "s3", "source": "local", "user": None}, {"scan_id": "s3"})
    # now Assess: the fan-out is rebuilt from the inventory
    handlers._scan_assess({"scan_id": "s3", "user": None}, {"scan_id": "s3"})
    run = isolated_store.get_scan("s3")["run"]
    assert run["status"] == "running"                                        # flipped back for analysis
    jobs = isolated_store.list_jobs()
    assert sum(1 for j in jobs if j["type"] == "scan_file") == 2             # both files now enqueued


def test_repeated_assess_click_reuses_the_exact_discovery_snapshot(isolated_store, monkeypatch):
    import core
    import handlers
    import scanner
    from fastapi.testclient import TestClient
    from app import app
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: _items())
    handlers._scan_discover(
        {"scan_id": "s-assess-idem", "source": "local", "user": "demo"},
        {"scan_id": "s-assess-idem"})

    client = TestClient(app)
    first = client.post("/scans/s-assess-idem/assess?level=AA").json()
    second = client.post("/scans/s-assess-idem/assess?level=AA").json()

    assert first["job_id"] == second["job_id"]
    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["reused"] is False and second["reused"] is True
    payload = isolated_store.get_job(first["job_id"])["payload"]
    assert payload["snapshot_id"] == first["snapshot_id"]

    with isolated_store._db.cursor() as cur:
        isolated_store._db.execute(cur, "UPDATE jobs SET status='done' WHERE id=%s",
                                   (first["job_id"],))
    isolated_store.mark_assessed("s-assess-idem", "2026-09-05T00:00:00Z")
    isolated_store.set_scan_status("s-assess-idem", "completed")
    completed_retry = client.post("/scans/s-assess-idem/assess?level=AA").json()
    assert completed_retry["reused"] is True
    assert completed_retry["job_id"] == first["job_id"]


# ── metadata-only discovery is the DEFAULT, including the monolithic 'scan' job ──────────────────

def test_default_is_metadata_only(monkeypatch):
    """With NO override set, discovery defers by default — the whole point of ADR 0020's flip."""
    import handlers
    monkeypatch.delenv("ACP_DEFER_ANALYSIS_TO_ASSESS", raising=False)
    assert handlers._defer_analysis_to_assess() is True
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "0")                  # legacy override still works
    assert handlers._defer_analysis_to_assess() is False


def test_monolithic_scan_job_defers_to_metadata_only_by_default(isolated_store, monkeypatch):
    """The non-fanout durable 'scan' job now LISTS metadata and STOPS by default (ADR 0020),
    delegating to _scan_discover — run_scan (which would download+analyse) is never called, no
    file is opened, and the in-memory tokens survive for the later Assess."""
    import core
    import handlers
    import scanner
    import worker
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.delenv("ACP_DEFER_ANALYSIS_TO_ASSESS", raising=False)         # exercise the DEFAULT
    monkeypatch.setattr(scanner, "_list", lambda *a, **k: _items())

    def _boom(*a, **k):                                                       # must NOT be reached
        raise AssertionError("run_scan was called — the default should defer, not download")
    monkeypatch.setattr(handlers, "run_scan", _boom)

    sid = "s-mono-default"
    core.register_scan_tokens(sid, drive="tok")
    jid = isolated_store.enqueue_job("scan", {"source": "local", "scan_id": sid, "ai": True},
                                     scan_id=sid)
    assert worker.JobWorker(isolated_store, worker_id="w-mono").run_once() is True
    assert isolated_store.get_job(jid)["status"] == "done"
    assert isolated_store.get_scan(sid)["run"]["status"] == "discovered"     # stopped at discovery
    assert isolated_store.count_inventory(sid) == 2                          # estate listed from metadata
    jobs = isolated_store.list_jobs()
    assert not any(j["type"] in ("scan_file", "scan_batch") for j in jobs)   # NOTHING opened
    assert core.get_scan_tokens(sid) == {"drive": "tok"}                     # kept for the later Assess
