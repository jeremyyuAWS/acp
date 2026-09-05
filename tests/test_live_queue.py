"""The live worker/queue/lane block for the Assess running screen. The composition is pure, so it is
exercised here with plain dicts — no pipeline, no store, no clock — which is the whole point of keeping
it out of the scan hot path."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

import live_queue as lq  # noqa: E402


NOW = 1_000_000.0


def _act(**kw):
    kw.setdefault("at", NOW)
    return kw


def test_mid_assessment_reports_in_flight_queued_and_current():
    run = {"files": 250, "files_done": 145, "phase": "assessing"}
    act = _act(in_flight=6, file="discharge.pdf", sc="1.4.3", sc_name="Contrast (Minimum)",
               action="assessing", text="Assessing discharge.pdf for 1.4.3  (+5 more in progress)")
    s = lq.compose(run, act, pool_max=8, now=NOW)
    assert s["total"] == 250 and s["done"] == 145
    assert s["in_flight"] == 6
    assert s["queued"] == 250 - 145 - 6                 # discovered, not done, not in a worker
    assert s["processing"] is True and s["stale"] is False
    assert s["workers"] == {"busy": 6, "max": 8, "idle": 2}
    assert s["current"]["file"] == "discharge.pdf" and s["current"]["criterion"] == "1.4.3"


def test_stale_activity_is_not_counted_as_live():
    """A worker that stopped reporting minutes ago must not leave a document reading as 'being assessed'.
    Stale activity → 0 in flight, no current lane, stale=True."""
    run = {"files": 100, "files_done": 40}
    act = _act(in_flight=4, file="x.docx", text="Assessing x.docx", at=NOW - (lq.STALE_AFTER + 30))
    s = lq.compose(run, act, pool_max=8, now=NOW)
    assert s["in_flight"] == 0 and s["current"] is None
    assert s["processing"] is False and s["stale"] is True
    assert s["queued"] == 100 - 40                      # nothing in a worker → all remaining are queued


def test_no_activity_yet_is_a_safe_zero_not_an_error():
    s = lq.compose({"files": 30, "files_done": 0}, None, now=NOW)
    assert s["in_flight"] == 0 and s["queued"] == 30 and s["current"] is None
    assert s["processing"] is False and s["stale"] is False       # no activity at all ≠ stale


def test_finished_scan_has_nothing_queued_or_in_flight():
    s = lq.compose({"files": 50, "files_done": 50}, None, now=NOW)
    assert s["done"] == 50 and s["queued"] == 0 and s["in_flight"] == 0


def test_counts_never_go_negative_when_activity_lags_the_run_summary():
    # files_done already 48 of 50, but a lagging activity still claims 6 in flight — queued must clamp
    # to 0, and done is clamped to total, rather than producing a negative "queued".
    run = {"files": 50, "files_done": 60}               # files_done > files (a lag/dup) → clamp done
    act = _act(in_flight=6)
    s = lq.compose(run, act, pool_max=8, now=NOW)
    assert s["done"] == 50 and s["queued"] == 0


def test_pool_max_absent_reports_busy_only():
    s = lq.compose({"files": 10, "files_done": 2}, _act(in_flight=3), now=NOW)
    assert s["workers"] == {"busy": 3}                  # no max known → don't invent one


def test_workers_busy_is_in_flight_by_construction_not_an_independent_signal():
    """`workers.busy` is DERIVED from in_flight, so the two can never disagree.

    Worth pinning because a consumer read it as a second, independent measurement and computed
    "assigned next" as `in_flight - workers.busy` — a figure that is structurally always 0, so the
    category could never appear on screen. There is no scan-scoped "claimed but not yet started"
    count in this block; anything that needs one has to add it here first rather than subtract two
    numbers that are the same number.
    """
    for n in (0, 1, 6, 40):
        s = lq.compose({"files": 100, "files_done": 0}, _act(in_flight=n), pool_max=8, now=NOW)
        assert s["workers"]["busy"] == s["in_flight"] == n
        assert s["in_flight"] - s["workers"]["busy"] == 0     # the always-zero subtraction


def test_for_scan_degrades_safely_when_activity_store_is_unavailable():
    """The fetch wrapper must never raise into a running screen. With a store that returns a run but no
    reachable activity/core (the .robenv case), it still returns the safe block from the run alone."""
    class _Store:
        def get_scan(self, sid):
            return {"files": 12, "files_done": 5, "phase": "assessing"}
    s = lq.for_scan(_Store(), "scan1", now=NOW)
    assert s["total"] == 12 and s["done"] == 5
    assert s["in_flight"] == 0 and s["queued"] == 7     # activity unavailable → 0 in flight, rest queued


def test_split_api_uses_live_assess_role_capacity_without_claiming_an_aggregate(monkeypatch):
    """ACP_WORKERS=0 on the API must not hide the dedicated Assess service's heartbeat."""
    class _Store:
        def get_scan(self, sid):
            return {"files": 235, "files_done": 54, "phase": "assessing"}

        def worker_roles_status(self):
            return {"assess": {"alive": True, "pool_size": 2}}

    import core
    monkeypatch.setattr(core, "WORKERS", 0)
    monkeypatch.setattr(lq, "_activity", None, raising=False)
    snapshot = lq.for_scan(_Store(), "scan1", now=NOW)
    assert snapshot["workers"] == {
        "busy": 0, "max": 2, "idle": 2, "capacity_scope": "per_replica",
    }


def test_stale_assess_heartbeat_is_not_presented_as_current_capacity(monkeypatch):
    class _Store:
        def get_scan(self, sid):
            return {"files": 10, "files_done": 2}

        def worker_roles_status(self):
            return {"assess": {"alive": False, "pool_size": 2}}

    import core
    monkeypatch.setattr(core, "WORKERS", 0)
    assert lq.for_scan(_Store(), "scan1", now=NOW)["workers"] == {"busy": 0}
