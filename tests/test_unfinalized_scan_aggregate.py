"""A scan that never reached finalize_scan_run must not report NULL counters.

Observed live on 2026-07-29 (v2026.7.29.2): the Overview showed 258 documents, a BLANK
certifiable tile, "258 need remediation", "0% audit-ready", a status donut reading
"issues 258" — and, beside it, "No open findings." There were no findings. Not one of those
numbers came from one.

`init_scan_run` creates the scan_runs row with certifiable/uncertain/error/avg_score unset;
only `finalize_scan_run` fills them. Two paths close a scan WITHOUT finalizing — `cancel_scan`
('cancelled') and the lost-worker sweeper ('interrupted') — and both stamp completed_at, so the
scan passes list_scans' `completed_at IS NOT NULL` filter and loads into the dashboard with
those counters still NULL.

NULL is not zero, but it reaches JavaScript as `null` and every consumer coerces it silently:
`certifiable / files` is 0, `files - certifiable - uncertain - error` is `files`, and
`{run.certifiable}` renders nothing at all. So the API must not emit NULL here.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

COUNTERS = ("certifiable", "uncertain", "error")


def _discovered_estate(store, sid="s-258", owner="auditor@example.com", n=258):
    """A Discover-phase scan (ADR 0020): inventory listed, no file opened."""
    store.init_scan_run(sid, "drive", n, "2026-07-29T09:00:00Z", "default", "rh1",
                        owner=owner, status="running")
    store.add_inventory(sid, [
        {"file": f"dept-doc-{i:03d}.pdf", "doc_class": "pdf", "size_kb": 120 + i}
        for i in range(n)
    ])
    return sid, owner


def test_cancelled_scan_reports_numbers_not_nulls(isolated_store):
    store = isolated_store
    sid, owner = _discovered_estate(store)
    assert store.cancel_scan(sid, owner=owner) is True

    run = store.get_scan(sid, owner=owner)["run"]

    assert run["files"] == 258
    for k in COUNTERS:
        assert run[k] is not None, f"{k} came back NULL — the dashboard renders that as 0/blank"
        assert run[k] == 0
    # Nothing was scored, so there is genuinely no average. That one stays absent rather than
    # becoming a fabricated 0 — the UI already renders '—' for it.
    assert run["avg_score"] is None


def test_interrupted_scan_reports_numbers_not_nulls(isolated_store):
    """The lost-worker path (a deploy mid-scan) closes the run the same way cancel does."""
    store = isolated_store
    sid, owner = _discovered_estate(store, sid="s-interrupted")
    with store._db.cursor() as cur:
        store._db.execute(cur,
                          "UPDATE scan_runs SET status='interrupted', completed_at=%s WHERE id=%s",
                          ("2026-07-29T09:30:00Z", sid))

    run = store.get_scan(sid, owner=owner)["run"]
    assert all(run[k] is not None for k in COUNTERS)


def test_derived_counters_match_what_actually_ran(isolated_store):
    """A scan cancelled PARTWAY reports the real counts of the files it did analyse."""
    store = isolated_store
    sid, owner = _discovered_estate(store, sid="s-partial", n=10)
    for i, (status, score, compliant) in enumerate([
        ("analysed", 100, 1),
        ("analysed", 100, 1),
        ("analysed", 55, 0),
        ("uncertain", 84, 0),
        ("error", None, 0),
    ]):
        store.save_file_result(sid, {
            "file": f"dept-doc-{i:03d}.pdf", "engine": "pdf", "status": status,
            "score": score, "compliant": compliant, "skipped_rules": 0, "issues": [],
        }, "2026-07-29T09:15:00Z")
    store.cancel_scan(sid, owner=owner)

    run = store.get_scan(sid, owner=owner)["run"]
    assert run["certifiable"] == 2
    assert run["uncertain"] == 1
    assert run["error"] == 1
    assert run["avg_score"] == 85  # mean of 100, 100, 55, 84 — the error row has no score


def test_the_frontends_arithmetic_no_longer_produces_the_whole_estate(isolated_store):
    """The exact expressions the dashboard evaluates, on the exact payload it receives.

    `issues` is the status donut's amber bucket and `audit_ready` is the tile. Pre-fix, with
    NULL counters, these came out as 258 and 0 for a scan with zero findings.
    """
    store = isolated_store
    sid, owner = _discovered_estate(store)
    store.cancel_scan(sid, owner=owner)
    res = store.get_scan(sid, owner=owner)
    run, files = res["run"], res["files"]

    issues = run["files"] - run["certifiable"] - run["uncertain"] - run["error"]
    assert issues == 258, "every document is unanalysed, so it is not certifiable/uncertain/error"
    # ...which is exactly why subtraction is the wrong way to find open findings. The documents
    # themselves carry none, and that is the number the severity panel reports.
    assert sum(len(f["issues"]) for f in files) == 0

    assert run["certifiable"] / run["files"] == 0.0
    # The rate is computable but meaningless here: 0 of 258 documents were opened. The UI shows
    # '—' rather than "0% audit-ready" (see frontend/src/overviewAgreement.test.js).
    assert all(f["status"] == "discovered" for f in files)


def test_scan_picker_rows_are_filled_too(isolated_store):
    """list_scans feeds the picker, which renders "certifiable / files" per row."""
    store = isolated_store
    sid, owner = _discovered_estate(store, sid="s-picker")
    store.cancel_scan(sid, owner=owner)

    rows = store.list_scans(owner=owner)
    assert len(rows) == 1
    assert all(rows[0][k] is not None for k in COUNTERS)


def test_the_broken_screen_is_reachable_through_the_real_routes(monkeypatch, isolated_store):
    """Prove the state the Overview was rendering is one the app can actually get into.

    The Overview is gated on `assessed` (App.jsx: `!!run?.assessed_at`), so a scan with NULL
    counters only reaches that screen if something stamps assessed_at without finalizing.
    POST /scans/{sid}/assess does exactly that: its deferred branch requires
    `status == 'discovered'`, and a cancelled scan is 'cancelled', so it falls through to the
    immediate branch and calls mark_assessed. The dashboard then loads a scan that was never
    finalized — inventory rows, no findings, and (pre-fix) NULL counters.
    """
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    from fastapi.testclient import TestClient
    from app import app

    store = isolated_store
    sid, _ = _discovered_estate(store, sid="s-route", owner="demo")
    store.cancel_scan(sid, owner="demo")

    c = TestClient(app)
    assert c.post(f"/scans/{sid}/assess").status_code == 200

    res = c.get(f"/scans/{sid}")
    assert res.status_code == 200
    run = res.json()["run"]

    assert run["assessed_at"] is not None, "the Overview would not render without this"
    assert run["status"] == "cancelled", "…and it was never finalized"
    for k in COUNTERS:
        assert run[k] is not None, f"{k} reached the dashboard as NULL"


def test_a_finalized_scan_keeps_its_stored_counters(isolated_store):
    """The derivation is a fallback for absent values, not a second source of truth."""
    store = isolated_store
    sid, owner = _discovered_estate(store, sid="s-final", n=3)
    for i, compliant in enumerate([1, 0, 1]):
        store.save_file_result(sid, {
            "file": f"dept-doc-{i:03d}.pdf", "engine": "pdf", "status": "analysed",
            "score": 90, "compliant": compliant, "skipped_rules": 0, "issues": [],
        }, "2026-07-29T09:15:00Z")
    store.finalize_scan_run(sid, "2026-07-29T09:20:00Z")

    run = store.get_scan(sid, owner=owner)["run"]
    assert run["certifiable"] == 2
    assert run["files"] == 3
