"""GET /jobs reports the worker tier's heartbeat AGE, not just alive/dead (2026-08-29).

Discover's processing panel already distinguishes connection freshness (its own SSE stream)
from progress freshness (inventory last changing) — this is the third of the "Live Discovery
Operations Card" PRD's three timestamps (§15): whether the ASSIGNED WORKER is still alive,
as opposed to whether the browser is still hearing from the server. Nothing exposed this
before; worker_tier_status() already computed it (store.py) for a different caller.

worker_tier_alive stays a bare bool at the same key — additive, not a breaking response change.

Also covers `worker_tier_pool_size` (stakeholder UX review — "ACP-ready worker slots: N"):
the worker container's own `core.WORKERS`, carried through the heartbeat's JSON envelope and
surfaced here as a fourth field, None when the beat is old-format or never carried it.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


def _stamp(delta_s: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=delta_s)).isoformat()


def _envelope(delta_s: float, pool_size: int | None = 12) -> str:
    body = {"at": _stamp(delta_s)}
    if pool_size is not None:
        body["pool_size"] = pool_size
    return json.dumps(body)


@pytest.fixture()
def client(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient
    from app import app
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", "", raising=False)
    return TestClient(app), isolated_store


def test_reports_none_when_no_worker_has_ever_beaten(client):
    c, st = client
    body = c.get("/jobs").json()
    assert body["worker_tier_alive"] is False
    assert body["worker_heartbeat_at"] is None
    assert body["worker_heartbeat_age_s"] is None
    assert body["worker_tier_pool_size"] is None


def test_reports_the_beat_and_its_age_when_alive(client):
    c, st = client
    st.set_setting("worker_tier_heartbeat", _stamp(5))
    body = c.get("/jobs").json()
    assert body["worker_tier_alive"] is True
    assert body["worker_heartbeat_at"] is not None
    assert 4 <= body["worker_heartbeat_age_s"] <= 6
    # Bare-ISO (old-format) beat: pool_size is unknown, not fabricated.
    assert body["worker_tier_pool_size"] is None


def test_still_reports_age_when_stale_not_alive(client):
    """A dead worker's beat is worth showing — 'last seen 12 minutes ago' is a real fact,
    not just a boolean 'no'."""
    c, st = client
    st.set_setting("worker_tier_heartbeat", _stamp(600))
    body = c.get("/jobs").json()
    assert body["worker_tier_alive"] is False
    assert body["worker_heartbeat_age_s"] == pytest.approx(600, abs=2)


def test_a_corrupt_beat_does_not_crash_the_route(client):
    c, st = client
    st.set_setting("worker_tier_heartbeat", "not-a-timestamp")
    body = c.get("/jobs").json()
    assert body["worker_tier_alive"] is False
    assert body["worker_heartbeat_age_s"] is None
    assert "unparseable" in body["worker_heartbeat_at"]
    assert body["worker_tier_pool_size"] is None


def test_reports_pool_size_from_a_json_envelope_heartbeat(client):
    """The new format: a worker container that has redeployed onto the JSON envelope reports
    its real `core.WORKERS` as `worker_tier_pool_size` — the stakeholder-requested "ACP-ready
    worker slots: N" figure, sourced honestly instead of the API tier's own (0-in-split-
    topology) pool."""
    c, st = client
    st.set_setting("worker_tier_heartbeat", _envelope(5, pool_size=12))
    body = c.get("/jobs").json()
    assert body["worker_tier_alive"] is True
    assert body["worker_tier_pool_size"] == 12
    assert 4 <= body["worker_heartbeat_age_s"] <= 6


def test_json_envelope_missing_pool_size_reports_none_not_a_crash(client):
    c, st = client
    st.set_setting("worker_tier_heartbeat", _envelope(5, pool_size=None))
    body = c.get("/jobs").json()
    assert body["worker_tier_alive"] is True
    assert body["worker_tier_pool_size"] is None
