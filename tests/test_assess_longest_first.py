"""Assess schedules predicted stragglers first so they do not become the final idle-worker tail."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def test_known_size_is_the_primary_pre_download_work_signal():
    import handlers

    assert handlers._estimated_assess_work({"file": "small.pdf", "size_kb": 20}) == 20
    assert handlers._estimated_assess_work({"file": "large.docx", "size_kb": "9000"}) == 9000


def test_unknown_cloud_files_use_stable_format_estimates():
    import handlers

    ordered = sorted(
        [{"file": "note.docx"}, {"file": "deck.pptx"}, {"file": "book.xlsx"},
         {"file": "scan.pdf"}, {"file": "page.html"}],
        key=handlers._estimated_assess_work,
        reverse=True,
    )
    assert [x["file"] for x in ordered] == [
        "scan.pdf", "deck.pptx", "book.xlsx", "note.docx", "page.html"
    ]


def test_enqueue_analysis_places_largest_files_first(isolated_store, monkeypatch):
    import handlers

    monkeypatch.setattr(handlers.core, "store", isolated_store)
    captured = []
    original = isolated_store.enqueue_job

    def capture(job_type, payload, **kwargs):
        if job_type == "scan_file":
            captured.append((payload["file"], payload.get("size_kb")))
        return original(job_type, payload, **kwargs)

    monkeypatch.setattr(isolated_store, "enqueue_job", capture)
    handlers._enqueue_analysis(
        "s1", "drive",
        [{"file": "small.docx", "size_kb": 10},
         {"file": "largest.xlsx", "size_kb": 9000},
         {"file": "middle.pdf", "size_kb": 1200}],
        ai=False, pii=False, user=None, incremental=True, exclude_remediated=False,
    )

    assert captured == [
        ("largest.xlsx", 9000), ("middle.pdf", 1200), ("small.docx", 10)
    ]
    jobs = [j for j in isolated_store.list_jobs() if j["type"] == "scan_file"]
    assert sorted(json.loads(j["payload"])["size_kb"] for j in jobs) == [10, 1200, 9000]


def test_equal_estimates_keep_inventory_order():
    import handlers

    items = [{"file": "z.docx", "size_kb": 100}, {"file": "a.docx", "size_kb": 100}]
    assert [x["file"] for x in sorted(items, key=handlers._estimated_assess_work, reverse=True)] == [
        "z.docx", "a.docx"
    ]
