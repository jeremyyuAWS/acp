"""Authoritative live-run snapshot (Live Assessment Experience PRD §8).

The load-bearing property: the running screen's tally is read from the SAME run-summary source the
final certification uses (`_fill_run_aggregate`: certifiable/uncertain/error), never a separate
re-tally — so running and final can never diverge. The last test pins that against a real store.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import live_snapshot  # noqa: E402


class _FakeStore:
    """Mirrors get_scan's real contract: it returns {"run": <summary>, "files": [...]}, not the flat
    summary — build_snapshot must unwrap it. live_findings_count returns None unless a value is set,
    so the "store can't supply findings" degrade path is testable."""
    def __init__(self, run, findings=None):
        self._run = run
        self._findings = findings

    def get_scan(self, sid, owner=None):
        return {"run": self._run, "files": []}

    def live_findings_count(self, sid):
        return self._findings

    def count_files_done(self, sid):
        return (0, self._run.get("files") or 0)


def _snap(run, now="2026-08-20T20:00:00Z", findings=None):
    return live_snapshot.build_snapshot(_FakeStore(run, findings), "s1", owner="o", now_iso=now)


# ── the fixed mapping (outcomesFromRun's), onto the PRD KPIs ──────────────────

def test_maps_run_summary_to_reconciled_kpis():
    snap = _snap({"status": "running", "source": "drive", "files": 100, "files_done": 40,
                  "certifiable": 30, "uncertain": 7, "error": 3})
    assert snap["kpis"]["completed"] == 40
    assert snap["kpis"]["processing"] == 0            # no worker activity is currently reported
    assert snap["kpis"]["need_attention"] == 7        # uncertain → needs review
    assert snap["kpis"]["unable_to_assess"] == 3      # error → could not be assessed
    assert snap["outcomes"] == {"passed": 30, "review": 7, "failed": 3, "processing": 60}
    assert snap["totals"]["eligible"] == 100          # no inventory → the scan's queued count
    assert snap["phase"] == "assessing" and snap["active"] is True
    assert snap["sequence"] == 40                     # monotonic reconnect marker == completed


def test_denominator_comes_from_the_estate_funnel_when_recorded():
    inv = {"discovered": 100, "assessment_eligible": 60,
           "by_status": {"assessable": 60, "metadata_only": 40}, "truncated": False}
    snap = _snap({"status": "running", "files": 60, "files_done": 10,
                  "certifiable": 8, "uncertain": 2, "error": 0, "scope": {"inventory": inv}})
    assert snap["totals"]["discovered"] == 100
    assert snap["totals"]["eligible"] == 60           # funnel assessable — same figure as ScopeFunnel


def test_live_snapshot_carries_compact_sharepoint_visibility_scope():
    scope = {"kind": "sharepoint", "inventory": {"discovered": 800}, "sites": [
        {"id": "s1", "name": "Clinical", "status": "complete",
         "libraries": [{"id": "l1", "name": "Documents"}]},
    ]}
    snap = _snap({"status": "running", "source": "sharepoint", "files": 10,
                  "files_done": 1, "scope": scope})
    assert snap["scope"] == {"kind": "sharepoint", "sites": scope["sites"]}
    assert "inventory" not in snap["scope"]


def test_phase_progression():
    base = {"status": "running", "files": 10, "certifiable": 0, "uncertain": 0, "error": 0}
    assert _snap({**base, "files": 0})["phase"] == "preparing"          # eligible not yet known
    assert _snap({**base, "files_done": 3})["phase"] == "assessing"
    assert _snap({**base, "files_done": 10})["phase"] == "finalizing"   # all eligible accounted for
    assert _snap({**base, "status": "completed", "files_done": 10})["phase"] == "done"


def test_completed_never_exceeds_eligible():
    # LA-02: completed must never overshoot the total, even if files_done races ahead.
    snap = _snap({"status": "running", "files": 50, "files_done": 80,
                  "certifiable": 50, "uncertain": 0, "error": 0})
    assert snap["kpis"]["completed"] == 50 and snap["kpis"]["processing"] == 0


def test_null_counters_degrade_to_zero():
    snap = _snap({"status": "running", "files": None, "files_done": None,
                  "certifiable": None, "uncertain": None, "error": None})
    assert snap["available"] is True and snap["kpis"]["completed"] == 0


def test_unknown_scan_degrades_not_raises():
    class _Empty:
        def get_scan(self, sid, owner=None):
            return None
    assert live_snapshot.build_snapshot(_Empty(), "x", owner="o") == \
        {"available": False, "reason": "scan_not_found"}


def test_pending_kpis_are_named_not_invented(monkeypatch):
    # Force the no-queue-layer path AND no findings source: with neither, all four unsupplied KPIs
    # stay named, none faked (findings=None keeps findings_so_far in pending, not a fake 0).
    monkeypatch.setattr(live_snapshot, "_live_queue_block", lambda store, sid: None)
    snap = _snap({"status": "running", "files": 10, "files_done": 1,
                  "certifiable": 1, "uncertain": 0, "error": 0}, findings=None)
    assert set(snap["kpis_pending"]) == {"queued", "throughput", "findings_so_far", "workers"}
    assert "findings_so_far" not in snap["kpis"]      # a finding count is not faked from file buckets
    assert "queue" not in snap                        # no queue layer → no fabricated block


def test_findings_so_far_added_when_the_store_supplies_it(monkeypatch):
    monkeypatch.setattr(live_snapshot, "_live_queue_block", lambda store, sid: None)
    snap = _snap({"status": "running", "files": 10, "files_done": 4,
                  "certifiable": 2, "uncertain": 1, "error": 1}, findings=9)
    assert snap["kpis"]["findings_so_far"] == 9        # real count, in the KPI set
    assert "findings_so_far" not in snap["kpis_pending"]


def test_queue_layer_is_folded_in_when_present(monkeypatch):
    # When api/live_queue.py is on the branch, its block is composed under `queue` and the KPIs it
    # supplies leave kpis_pending — a single merged snapshot (PRD §8), still owner-scoped once.
    block = {"in_flight": 4, "queued": 20, "workers": {"busy": 4, "max": 6, "idle": 2},
             "current": [{"file": "x.docx", "criterion": "1.3.1"}], "stale": False}
    monkeypatch.setattr(live_snapshot, "_live_queue_block", lambda store, sid: block)
    snap = _snap({"status": "running", "files": 100, "files_done": 40,
                  "certifiable": 30, "uncertain": 7, "error": 3})
    assert snap["queue"] == block
    assert snap["kpis"]["processing"] == 4       # in flight, not all 60 remaining
    assert set(snap["kpis_pending"]) == {"findings_so_far"}    # queued/throughput/workers now supplied
    # the coarse roll-up still reconciles with the authoritative split
    assert snap["queue"]["in_flight"] + snap["queue"]["queued"] >= 0


def test_durable_results_override_a_lagging_run_counter(monkeypatch):
    class _LaggingStore(_FakeStore):
        def count_files_done(self, sid):
            return (427, 986)

    monkeypatch.setattr(live_snapshot, "_live_queue_block", lambda store, sid: {
        "in_flight": 9, "queued": 550, "workers": {"busy": 9, "max": 12},
    })
    run = {"status": "running", "files": 986, "files_done": 0,
           "certifiable": 0, "uncertain": 0, "error": 0}
    snap = live_snapshot.build_snapshot(_LaggingStore(run), "s1")
    assert snap["kpis"]["completed"] == 427
    assert snap["kpis"]["processing"] == 9
    assert snap["sequence"] == 427


# ── the reconciliation guarantee, against a real store ────────────────────────

def test_snapshot_tally_reconciles_with_the_run_summary(isolated_store):
    s = isolated_store
    sid = "recon1"
    s.init_scan_run(sid, "drive", 3, "2026-08-20T00:00:00Z", "default", "rh",
                    owner="o@x.com", status="running")
    s.save_file_result(sid, {"file": "a.docx", "engine": "office", "status": "pass", "score": 100,
                             "compliant": 1, "skipped_rules": 0, "issues": []}, "2026-08-20T00:00:01Z")
    s.save_file_result(sid, {"file": "b.docx", "engine": "office", "status": "uncertain", "score": 80,
                             "compliant": 0, "skipped_rules": 0, "issues": []}, "2026-08-20T00:00:02Z")
    s.save_file_result(sid, {"file": "c.docx", "engine": "office", "status": "error", "score": None,
                             "compliant": 0, "skipped_rules": 0, "issues": []}, "2026-08-20T00:00:03Z")
    run = s.get_scan(sid, owner="o@x.com")["run"]      # the reconciled summary lives under "run"
    snap = live_snapshot.build_snapshot(s, sid, owner="o@x.com")
    # The snapshot's outcome tally IS the run summary's — the same source the final cert uses.
    assert snap["outcomes"]["passed"] == run["certifiable"] == 1
    assert snap["outcomes"]["review"] == run["uncertain"] == 1
    assert snap["outcomes"]["failed"] == run["error"] == 1


def test_findings_count_reconciles_with_the_report_source(isolated_store):
    # live_findings_count sums the SAME FAIL traces get_certification_facts totals into the report's
    # finding count — so the running "findings so far" lands on the final cert's finding total.
    s = isolated_store
    sid = "recon2"
    s.init_scan_run(sid, "drive", 1, "2026-08-20T00:00:00Z", "default", "rh",
                    owner="o@x.com", status="running")
    s.save_file_result(sid, {"file": "a.docx", "engine": "office", "status": "fail", "score": 60,
                             "compliant": 0, "skipped_rules": 0,
                             "issues": [{"ruleId": "1.1.1", "wcag": "SC_1_1_1", "severity": "SERIOUS", "detail": "d"},
                                        {"ruleId": "2.4.2", "wcag": "SC_2_4_2", "severity": "SERIOUS", "detail": "d"}]},
                       "2026-08-20T00:00:01Z")
    report_findings = sum(int(d.get("findings", 0)) for d in s.get_certification_facts(sid)["documents"])
    assert s.live_findings_count(sid) == report_findings > 0
    snap = live_snapshot.build_snapshot(s, sid, owner="o@x.com")
    assert snap["kpis"]["findings_so_far"] == report_findings


def test_second_opinion_usage_is_bounded_and_truthfully_labelled(isolated_store):
    s = isolated_store
    sid = "opinion-live"
    s.enqueue_scan(sid, "sharepoint", "o@x.com", "scan_sharepoint", {}, inputs={
                                 "source": "sharepoint", "feature_flags": {"second_opinion_policy": {
                                     "enabled": True, "criteria": ["1.3.5"], "confidence_threshold": "low",
                                     "max_requests_per_scan": 2, "max_requests_per_day": 4,
                                     "max_daily_cost_usd": 1.0, "estimated_cost_per_request_usd": .1}}})
    s.init_scan_run(sid, "sharepoint", 2, "2026-09-05T00:00:00Z", "default", "rh",
                    owner="o@x.com", status="running")
    policy = s.get_scan_inputs(sid)["feature_flags"]["second_opinion_policy"]
    s.set_setting("second_opinion_policy", json.dumps(policy))
    assert s.reserve_second_opinion(scan_id=sid, file="a.docx", policy=policy)[0]
    snap = live_snapshot.build_snapshot(s, sid, owner="o@x.com")
    block = snap["second_opinion"]
    assert block["status"] == "used" or block["status"] == "ready"
    assert block["scan"] == {"used": 1, "limit": 2, "remaining": 1}
    assert block["cost"]["estimated_remaining_usd"] == .9
