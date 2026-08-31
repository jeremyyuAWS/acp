"""Worker-free Discover (ACP_INLINE_DISCOVER) — the durable queue is skipped for DISCOVER only.

WHY THE MODE EXISTS. Discover is metadata-only by default (ADR 0020): it lists, classifies and
persists an inventory, and opens no file. Handing that to the durable queue buys little and costs
a hard dependency — a deployment whose worker tier has never come up cannot start a listing that
needs no worker at all — while every queue fault between "user clicked" and "listing began" lands
on the one stage that is merely reading metadata.

WHAT THESE PIN, in order of what would hurt most if it broke:

  1. The mode is DISCOVER-ONLY. Assess and Remediate still fan out to workers. The gate on defer
     mode is the load-bearing part: with ACP_DEFER_ANALYSIS_TO_ASSESS=0 a "discover" also
     downloads and analyses every file, and running THAT in the API process is exactly the long,
     restart-losable work the queue exists for.
  2. The response contract survives. A caller passing queue=true gets a scan_id back on the
     durable path and the SPA's queued flow reads it (api.js startScanQueued); the inline path
     lands in a different branch and must still name the scan it started.
  3. Nothing is enqueued. Asserted by making enqueue_scan fail the test if it is called — the
     mode is worthless if it quietly queues anyway.
"""
from __future__ import annotations
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "api"))

OWNER = "owner@example.com"


@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
    """Same shape as test_scan_single_flight.py's fixture."""
    import core
    from fastapi.testclient import TestClient
    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", OWNER, raising=False)
    monkeypatch.setattr(core, "verify_gis_token", lambda tok: tok or None)
    monkeypatch.setattr(core, "email_allowed", lambda e: True)

    client = TestClient(app)

    def as_user(email=OWNER):
        client.headers.update({"Authorization": f"Bearer {email}"})
        return client

    return as_user


@pytest.fixture()
def quiet_discover(monkeypatch):
    """Stand in for the real listing so these tests assert ROUTING, not scanning.

    `_scan_discover` is imported inside the request/thread body (`from handlers import
    _scan_discover`), so patching the attribute on the module is what the call site actually
    resolves. Returns the list of payloads it was handed, for the tests that care that the chosen
    scope travelled with the call.
    """
    import handlers
    seen: list[dict] = []

    def _fake(payload, job):
        seen.append(payload)

    monkeypatch.setattr(handlers, "_scan_discover", _fake)
    return seen


@pytest.fixture()
def no_enqueue(monkeypatch, isolated_store):
    """Make the durable path impossible to take silently: enqueue_scan fails the test."""
    def _boom(*a, **kw):
        raise AssertionError("enqueue_scan was called — the scan was queued, not run inline")

    monkeypatch.setattr(isolated_store, "enqueue_scan", _boom)


# ── the mode itself ──────────────────────────────────────────────────────────────────────────

def test_queued_request_runs_inline_and_never_enqueues(gated_client, monkeypatch,
                                                       quiet_discover, no_enqueue):
    monkeypatch.setenv("ACP_INLINE_DISCOVER", "1")
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    r = gated_client().post("/scans?source=local&queue=true&fanout=true")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["queued"] is False
    assert body["inline"] is True
    # The contract the SPA's queued flow depends on — a scan_id it can poll and stream.
    assert body["scan_id"]
    assert body["job_id"]


def test_the_same_request_is_queued_with_the_flag_off(gated_client, monkeypatch, quiet_discover):
    """The bite check for the test above: identical request, flag off, durable path taken.

    Without this pair the inline test would also pass if start_scan had simply stopped queueing.
    """
    monkeypatch.delenv("ACP_INLINE_DISCOVER", raising=False)
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    body = gated_client().post("/scans?source=local&queue=true&fanout=true").json()
    assert body["queued"] is True
    assert body.get("inline") is None
    assert body["job_id"]


def test_the_flag_does_not_widen_to_full_analysis(gated_client, monkeypatch, quiet_discover):
    """THE guard on this mode. With defer off, "discover" means download-and-analyse everything.

    Running that in the API process is precisely the long, blocking, restart-losable work the
    durable queue exists for, so the flag must stay out of it. If this ever regresses, the symptom
    is not a test failure — it is a production API replica quietly doing an estate's worth of
    document parsing on a request thread and losing all of it on the next deploy.
    """
    monkeypatch.setenv("ACP_INLINE_DISCOVER", "1")
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "0")

    body = gated_client().post("/scans?source=local&queue=true&fanout=true").json()
    assert body["queued"] is True, "full-analysis scans must still go to the worker tier"
    assert body.get("inline") is None


def test_an_unqueued_request_is_untouched_by_the_flag(gated_client, monkeypatch, quiet_discover,
                                                      no_enqueue):
    """queue=false already ran in-process. The flag must not change its response shape.

    That path is the SPA's `startScan` (api.js), which reads `job_id` and nothing else; adding
    fields would be harmless but changing the shape it returns would not be.
    """
    monkeypatch.setenv("ACP_INLINE_DISCOVER", "1")
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    body = gated_client().post("/scans?source=local").json()
    assert set(body) == {"job_id"}


# ── the scope has to travel with an inline scan, exactly as it does with a queued one ────────

def test_the_selected_scope_travels_with_an_inline_discover(gated_client, monkeypatch,
                                                            quiet_discover, no_enqueue):
    """A payload carrying only `folder` drops a chosen multi-folder scope silently — the card
    says "Scans: HR" and the scan covers the whole source. Widening is the one direction nobody
    re-checks, which is why it is asserted on this path too and not only on the durable one."""
    monkeypatch.setenv("ACP_INLINE_DISCOVER", "1")
    monkeypatch.setenv("ACP_DEFER_ANALYSIS_TO_ASSESS", "1")

    r = gated_client().post(
        "/scans?source=local&queue=true&fanout=true"
        "&folders=fldA&folders=fldB&exclude_folders=fldC")
    assert r.status_code == 200, r.text

    # The stub records what _scan_discover was actually handed. It runs on a daemon thread, so
    # give it a moment rather than asserting into a race.
    for _ in range(100):
        if quiet_discover:
            break
        __import__("time").sleep(0.02)

    assert quiet_discover, "_scan_discover was never called"
    payload = quiet_discover[0]
    assert payload["folders"] == ["fldA", "fldB"]
    assert payload["exclude_folders"] == ["fldC"]
    assert payload["scan_id"] == r.json()["scan_id"], (
        "the response must name the scan that actually ran")
