"""Per-stage timing (ADR 0037 Step 0). Pure accumulation + aggregation; the load-bearing property is
that it MEASURES without ever being able to fail the scan — malformed input is skipped, not raised,
and a stage is still timed when its block throws."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import stage_timing as st  # noqa: E402


def test_stage_records_duration_and_count(monkeypatch):
    clock = iter([100.0, 100.5, 200.0, 202.0])            # (enter, finally) per stage
    monkeypatch.setattr(st.time, "monotonic", lambda: next(clock))
    t = st.ScanTimings()
    with t.stage("download"):
        pass
    with t.stage("analyse"):
        pass
    d = t.as_dict()
    assert d["totals_s"] == {"download": 0.5, "analyse": 2.0}
    assert d["counts"] == {"download": 1, "analyse": 1}


def test_repeated_stages_accumulate(monkeypatch):
    clock = iter([0.0, 1.0, 10.0, 12.5])
    monkeypatch.setattr(st.time, "monotonic", lambda: next(clock))
    t = st.ScanTimings()
    with t.stage("download"):
        pass
    with t.stage("download"):
        pass
    assert t.as_dict() == {"totals_s": {"download": 3.5}, "counts": {"download": 2}}


def test_a_stage_is_timed_even_when_its_block_raises(monkeypatch):
    clock = iter([10.0, 13.0])
    monkeypatch.setattr(st.time, "monotonic", lambda: next(clock))
    t = st.ScanTimings()
    with pytest.raises(ValueError):
        with t.stage("analyse"):
            raise ValueError("boom")
    assert t.as_dict() == {"totals_s": {"analyse": 3.0}, "counts": {"analyse": 1}}


def test_add_records_a_raw_duration_and_drops_bad_values():
    t = st.ScanTimings()
    t.add("download", 1.5)
    t.add("download", 0.5)
    t.add("analyse", "nope")          # non-numeric → dropped, not raised
    t.add("analyse", -3)              # negative → dropped
    assert t.as_dict() == {"totals_s": {"download": 2.0}, "counts": {"download": 2}}


def test_merge_sums_totals_and_counts_and_skips_junk():
    a = {"totals_s": {"download": 1.0, "analyse": 2.0}, "counts": {"download": 1, "analyse": 1}}
    b = {"totals_s": {"download": 0.5}, "counts": {"download": 1}}
    m = st.merge_rollups([a, b, None, "junk", {"totals_s": {"analyse": "bad"}}])
    assert m["totals_s"] == {"download": 1.5, "analyse": 2.0}   # 'bad' skipped, not raised
    assert m["counts"] == {"download": 2, "analyse": 1}
    assert st.merge_rollups([]) == {"totals_s": {}, "counts": {}}


def test_bottleneck_is_the_biggest_stage_or_none_when_unmeasured():
    assert st.bottleneck({"totals_s": {"download": 1.0, "analyse": 5.0}}) == "analyse"
    assert st.bottleneck({"totals_s": {}}) is None
    assert st.bottleneck(None) is None
    assert st.bottleneck({"totals_s": {"download": 0}}) is None    # zero is not a bottleneck


def test_summarize_reports_average_and_bottleneck():
    r = {"totals_s": {"download": 4.0, "analyse": 10.0}, "counts": {"download": 8, "analyse": 5}}
    s = st.summarize(r)
    assert s["avg_s"] == {"download": 0.5, "analyse": 2.0}         # slow ≠ merely frequent
    assert s["bottleneck"] == "analyse"
    assert st.summarize(None)["bottleneck"] is None
