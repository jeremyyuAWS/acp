"""The live-run event stream (Live Assessment Experience PRD §8): server-tailing SSE over the same
snapshot /scans/{sid}/live returns. Two load-bearing things: the change-detection signature emits
only on real change (not on the clock ticking), and the stream sends a frame then CLOSES on a
terminal run rather than looping forever.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import live_snapshot  # noqa: E402


# ── the change-detection signature ────────────────────────────────────────────

def test_signature_ignores_generated_at_but_reflects_content():
    base = {"available": True, "state": "running", "phase": "assessing",
            "kpis": {"completed": 1}, "sequence": 1, "generated_at": "t1"}
    only_time_changed = {**base, "generated_at": "t2"}      # a new build, same state
    kpi_changed = {**base, "kpis": {"completed": 2}, "sequence": 2, "generated_at": "t3"}
    assert live_snapshot.snapshot_signature(base) == live_snapshot.snapshot_signature(only_time_changed)
    assert live_snapshot.snapshot_signature(base) != live_snapshot.snapshot_signature(kpi_changed)


def test_signature_is_total_on_junk():
    assert live_snapshot.snapshot_signature({}) == ""
    assert live_snapshot.snapshot_signature(None) == ""
    assert isinstance(live_snapshot.snapshot_signature({"x": object()}), str)   # unserialisable → no raise


# ── the SSE endpoint ──────────────────────────────────────────────────────────

@pytest.fixture
def client(monkeypatch, isolated_store):
    import core
    monkeypatch.setattr(core, "store", isolated_store)
    from fastapi.testclient import TestClient
    from app import app
    return TestClient(app)


def test_events_streams_a_frame_then_closes_on_a_terminal_run(client, isolated_store):
    # A completed run is terminal, so the stream emits one snapshot frame and CLOSES (never loops).
    # owner "demo" matches _owner()'s unauthenticated default, so the snapshot resolves the scan.
    isolated_store.init_scan_run("done1", "drive", 2, "2026-08-20T00:00:00Z", "default", "rh",
                                 owner="demo", status="completed")
    with client.stream("GET", "/scans/done1/events") as r:
        assert r.status_code == 200
        assert "text/event-stream" in r.headers["content-type"]
        body = "".join(r.iter_text())          # completes because the stream closes on terminal
    assert "data:" in body
    frame = body.split("data:", 1)[1].split("\n\n", 1)[0].strip()
    snap = json.loads(frame)
    assert snap["available"] is True and snap["active"] is False    # terminal snapshot, stream ended


def test_events_on_unknown_scan_emits_a_degrade_frame_and_closes(client):
    with client.stream("GET", "/scans/nope/events") as r:
        assert r.status_code == 200
        body = "".join(r.iter_text())
    frame = body.split("data:", 1)[1].split("\n\n", 1)[0].strip()
    assert json.loads(frame) == {"available": False, "reason": "scan_not_found"}
