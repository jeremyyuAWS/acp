"""The capacity-schedule endpoints over real HTTP, through the app's own middleware.

ADAPTED FROM #1538's tests/test_capacity_schedule.py, which two independent implementations of
this PRD both claimed. Its HTTP-level coverage is what the rest of this feature's tests lack —
they drive the handlers directly — so it is kept, pointed at the surviving implementation, and
its one substantive assertion is corrected rather than deleted.

THE ASSERTION THAT CHANGED, AND WHY. The original read:

    assert data["projection"]["database_connections"] == 126     # and valid is True

126 came from `worker_max * db_pool * 2 + reserve`, which omits the API tier. `acp-app` carries a
16-connection pool (store.db_max_conn with ACP_WORKERS=0, verified) and at these maximums
contributes 80 connections — 3 replicas x 16, plus 2 x 16 during a revision overlap. Counting it
takes the same table from 126 to 167 against a 150-connection server, which is what this
repository's own pre-existing model in tests/test_db_connection_budget.py has said since the
2026-08-30 pool-exhaustion incident.

So the same request that used to be priced at 126 and accepted is now priced at 167 and refused,
and the table it prices is the one the PRD itself proposes in §5.3. That is the finding, arriving
through the endpoint rather than through a document.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


def proposed(**overrides):
    """The PRD's §5.3 table, verbatim. Over budget — see the module docstring."""
    body = {
        "enabled": True,
        "timezone": "America/Los_Angeles",
        "days": ["mon", "tue", "wed", "thu", "fri"],
        "start": "06:00", "end": "20:00", "version": 0, "reason": "http test",
        "business_hours": {"web": 2, "discovery": 2, "assess": 5, "remediate": 5, "gpu": 1},
        "off_hours": {"web": 1, "discovery": 1, "assess": 1, "remediate": 1, "gpu": 0},
        "maximums": {"web": 3, "discovery": 4, "assess": 10, "remediate": 10, "gpu": 1},
    }
    body.update(overrides)
    return body


def affordable(**overrides):
    """The same shape with floors the fleet can actually carry, for the tests that need a save
    to succeed. web 1 / discovery 2 / assess 4 / remediate 4 lands at 147 of 150."""
    return proposed(business_hours={"web": 1, "discovery": 2, "assess": 4,
                                    "remediate": 4, "gpu": 1}, **overrides)


def _app_client(monkeypatch, isolated_store, owner=""):
    import core
    from fastapi.testclient import TestClient
    from app import app
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", owner, raising=False)
    if owner:
        monkeypatch.setattr(core, "is_admin", lambda email: email == owner, raising=False)
    return TestClient(app)


@pytest.fixture()
def client(monkeypatch, isolated_store):
    return _app_client(monkeypatch, isolated_store)


def test_default_is_disabled_and_unapplied(client):
    answer = client.get("/control/capacity-schedule")
    assert answer.status_code == 200
    data = answer.json()
    assert data["enabled"] is False
    assert data["applied"] is False
    # The PRD's own proposal is what a fresh deployment serves, and it does not fit the fleet —
    # so the honest default carries a blocking validation rather than a clean bill of health.
    assert data["validation"]["blocked"] is True


def test_validate_prices_the_deployment_overlap_including_the_api_tier(client):
    """The corrected arithmetic, end to end through the endpoint."""
    answer = client.post("/control/capacity-schedule/validate", json=proposed())
    assert answer.status_code == 200
    data = answer.json()
    assert data["blocked"] is True
    assert data["capacity"]["deploy_connections"] == 152
    assert data["capacity"]["server_max_connections"] == 150
    assert data["capacity"]["connection_headroom"] == -17
    assert any(f["code"] == "over_connection_budget" for f in data["findings"])


def test_the_prd_table_cannot_be_saved(client):
    """§7 says saving is BLOCKED, not warned, when the fleet cannot carry the shape."""
    answer = client.put("/control/capacity-schedule", json=proposed())
    assert answer.status_code == 422
    assert "over_connection_budget" in str(answer.json())
    # And nothing was written: the GET still reports the unsaved default.
    assert client.get("/control/capacity-schedule").json()["version"] == 0


def test_save_is_versioned_and_does_not_claim_azure_application(client):
    first = client.put("/control/capacity-schedule", json=affordable())
    assert first.status_code == 200, first.json()
    assert first.json()["version"] == 1
    # Saved is not applied. Persistence and application are separate steps with separate failure
    # modes, and §9's drift reporting is built on the state between them.
    assert first.json()["azure_applied"] is False
    stale = client.put("/control/capacity-schedule", json=affordable())
    assert stale.status_code == 409


def test_unsafe_off_hours_zero_is_rejected(client):
    body = affordable()
    body["off_hours"]["assess"] = 0
    answer = client.put("/control/capacity-schedule", json=body)
    assert answer.status_code == 422
    assert "no warm replica off-hours" in str(answer.json())


def test_invalid_timezone_is_rejected(client):
    answer = client.post("/control/capacity-schedule/validate",
                         json=proposed(timezone="Pacific-ish"))
    assert answer.status_code == 200
    assert answer.json()["blocked"] is True
    assert any(f["code"] == "unknown_timezone" for f in answer.json()["findings"])


def test_the_rendered_policy_is_readable_without_being_applied(client):
    answer = client.get("/control/capacity-schedule/policy")
    assert answer.status_code == 200
    assert answer.json()["transitions_create_no_revision"] is True


def test_write_is_admin_only(monkeypatch, isolated_store):
    admin_only = _app_client(monkeypatch, isolated_store, owner="admin@example.com")
    assert admin_only.put("/control/capacity-schedule", json=affordable()).status_code == 403
    assert admin_only.post("/control/capacity-schedule/override",
                           json={"mode": "off_hours", "duration": "1h",
                                 "reason": "r"}).status_code == 403
    # Reads stay open: §4 gives a view-only Settings user the right to inspect the schedule.
    assert admin_only.get("/control/capacity-schedule").status_code == 200
