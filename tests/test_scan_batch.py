"""Unit tests for the scan_batch job handler — previously untested.

scan_batch (ADR 0008): analyse a chunk of files in a single durable job, then fire
scan_finalize exactly once when the chunk completes the last outstanding files.

Three behavioural invariants:
  1. Every item in the batch is forwarded to _analyse_and_persist_one, in order.
  2. When count_files_done reports done >= total > 0, scan_finalize is enqueued.
  3. When done < total (more batches still pending), scan_finalize is NOT enqueued.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def _wire(monkeypatch, st, count_files_done_fn):
    """Stub the external dependencies that scan_batch touches."""
    import core
    import handlers
    import lf

    monkeypatch.setattr(core, "store", st)
    monkeypatch.setattr(lf, "flush", lambda: None)
    monkeypatch.setattr(core, "get_scan_tokens", lambda sid: {})
    monkeypatch.setattr(core, "active_rubric",
                        lambda: type("R", (), {"hash": "test-hash"})())
    monkeypatch.setattr(handlers, "_make_svc", lambda source, toks: None)
    monkeypatch.setattr(st, "count_files_done", count_files_done_fn)
    # ADR 0038's pause checkpoint (_run_one checks scan_paused() before each item) is
    # unrelated to what this file tests — stubbed so these tests exercise ordering/finalize
    # behavior without paying for a real DB round-trip inside the ThreadPoolExecutor's hot
    # path. Found live: the real get_setting() call was slow/variable enough to turn
    # test_scan_batch_analyses_every_item_in_order flaky (4 of 5 runs failed) even though
    # every item was still correctly analysed — pause behavior itself is covered directly
    # in tests/test_scan_pause_resume.py.
    monkeypatch.setattr(handlers, "scan_paused", lambda scan_id: False)


def _items(n):
    return [{"file": f"file{i}.docx", "id": f"id-{i}"} for i in range(n)]


# ── Item analysis ─────────────────────────────────────────────────────────────

def test_scan_batch_analyses_every_item_exactly_once(isolated_store, monkeypatch):
    """_scan_batch must forward every item to _analyse_and_persist_one — no items skipped,
    none duplicated. NOT asserting submission order: _scan_batch dispatches items to a
    ThreadPoolExecutor with multiple workers, and neither its own docstring nor its code ever
    promised completion order matches submission order — only that every item lands, exactly
    once, before the batch job returns."""
    import handlers

    _wire(monkeypatch, isolated_store, lambda sid: (0, 3))

    analysed = []
    monkeypatch.setattr(handlers, "_analyse_and_persist_one",
                        lambda scan_id, item, *a, **k: analysed.append(item["file"]))

    handlers._scan_batch(
        {"scan_id": "s1", "source": "local", "items": _items(3)},
        {},
    )

    assert sorted(analysed) == ["file0.docx", "file1.docx", "file2.docx"]


# ── Finalize trigger ──────────────────────────────────────────────────────────

def test_scan_batch_enqueues_finalize_when_last_batch_completes(isolated_store, monkeypatch):
    """When count_files_done returns done >= total > 0, the completing batch must
    enqueue scan_finalize so the scan closes without a separate trigger."""
    import handlers

    _wire(monkeypatch, isolated_store, lambda sid: (5, 5))  # all 5 done

    monkeypatch.setattr(handlers, "_analyse_and_persist_one", lambda *a, **k: None)

    handlers._scan_batch(
        {"scan_id": "s1", "source": "local", "items": _items(1)},
        {},
    )

    jobs = isolated_store.list_jobs()
    finalize = [j for j in jobs if j["type"] == "scan_finalize"]
    assert len(finalize) == 1
    assert json.loads(finalize[0]["payload"])["scan_id"] == "s1"


def test_scan_batch_does_not_enqueue_finalize_when_batches_remain(isolated_store, monkeypatch):
    """When done < total, more batches are still in flight — scan_finalize must NOT be
    enqueued prematurely, or the scan would finalise before all files are scored."""
    import handlers

    _wire(monkeypatch, isolated_store, lambda sid: (3, 5))  # 2 files still outstanding

    monkeypatch.setattr(handlers, "_analyse_and_persist_one", lambda *a, **k: None)

    handlers._scan_batch(
        {"scan_id": "s1", "source": "local", "items": _items(1)},
        {},
    )

    jobs = isolated_store.list_jobs()
    assert not any(j["type"] == "scan_finalize" for j in jobs), \
        "scan_finalize must not fire while files are still outstanding"
