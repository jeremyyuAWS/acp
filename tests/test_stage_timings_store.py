"""Store persistence for per-stage timings (ADR 0037 Step 0). The side-channel table + record/rollup:
idempotent per file (a retried job re-writes, never doubles), and an empty scan reports zeros rather
than a fabricated bottleneck. Runs against the real store (isolated_store)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))


def test_record_and_per_scan_rollup(isolated_store):
    s = isolated_store
    s.record_file_timing("scan1", "a.docx",
                         {"totals_s": {"download": 1.0, "analyse": 3.0}, "counts": {"download": 1, "analyse": 1}})
    s.record_file_timing("scan1", "b.pdf",
                         {"totals_s": {"download": 0.5, "analyse": 9.0}, "counts": {"download": 1, "analyse": 1}})
    out = s.scan_timings("scan1")
    assert out["totals_s"] == {"download": 1.5, "analyse": 12.0}
    assert out["counts"] == {"download": 2, "analyse": 2}
    assert out["avg_s"]["analyse"] == 6.0          # slow, not merely frequent
    assert out["bottleneck"] == "analyse"
    assert out["files_timed"] == 2


def test_record_is_idempotent_on_retry(isolated_store):
    s = isolated_store
    s.record_file_timing("scan2", "a.docx", {"totals_s": {"download": 1.0}, "counts": {"download": 1}})
    s.record_file_timing("scan2", "a.docx", {"totals_s": {"download": 2.0}, "counts": {"download": 1}})  # re-run
    out = s.scan_timings("scan2")
    assert out["totals_s"] == {"download": 2.0}     # upsert replaced the row, never doubled it
    assert out["files_timed"] == 1


def test_an_unrecorded_scan_reports_zeros_not_a_fake_bottleneck(isolated_store):
    out = isolated_store.scan_timings("never-scanned")
    assert out["bottleneck"] is None
    assert out["files_timed"] == 0
    assert out["totals_s"] == {}


def test_a_corrupt_timing_row_does_not_sink_the_rollup(isolated_store):
    s = isolated_store
    s.record_file_timing("scan3", "good.docx", {"totals_s": {"analyse": 4.0}, "counts": {"analyse": 1}})
    # Write a deliberately broken JSON blob straight to the table.
    with s._db.cursor() as cur:
        s._db.execute(cur, "INSERT INTO file_stage_timings(scan_id,file,timings) VALUES(%s,%s,%s)",
                      ("scan3", "broken.pdf", "{not json"))
    out = s.scan_timings("scan3")
    assert out["totals_s"] == {"analyse": 4.0}      # the good row survives; the corrupt one is skipped
    assert out["files_timed"] == 1
