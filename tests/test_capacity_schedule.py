"""Desired capacity scheduling is safe, versioned, admin-gated, and honest about application."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))


def proposed(**overrides):
    body = {
        "enabled": True,
        "timezone": "America/Los_Angeles",
        "days": ["mon", "tue", "wed", "thu", "fri"],
        "start": "06:00", "end": "20:00", "version": 0,
        "business_hours": {"web": 2, "discovery": 2, "assess": 5, "remediate": 5, "gpu": 1},
        "off_hours": {"web": 1, "discovery": 1, "assess": 1, "remediate": 1, "gpu": 0},
        "maximums": {"web": 3, "discovery": 4, "assess": 10, "remediate": 10, "gpu": 1},
    }
    body.update(overrides)
    return body


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
    return TestClient(app)


def test_default_is_disabled_and_unapplied(client):
    answer = client.get("/control/capacity-schedule")
    assert answer.status_code == 200
    data = answer.json()
    assert data["enabled"] is False
    assert data["applied"] is False
    assert "not enabled" in data["application_status"].lower()
    assert data["validation"]["valid"] is True


def test_validate_prices_deployment_overlap(client):
    answer = client.post("/control/capacity-schedule/validate", json=proposed())
    assert answer.status_code == 200
    data = answer.json()
    assert data["valid"] is True
    assert data["projection"]["maximum_vcpu"] == 94
    assert data["projection"]["database_connections"] == 126
    assert any("cold-start" in warning for warning in data["warnings"])


def test_save_is_versioned_and_does_not_claim_azure_application(client):
    first = client.put("/control/capacity-schedule", json=proposed())
    assert first.status_code == 200
    assert first.json()["version"] == 1
    assert first.json()["applied"] is False
    stale = client.put("/control/capacity-schedule", json=proposed())
    assert stale.status_code == 409


def test_unsafe_off_hours_zero_is_rejected(client):
    body = proposed()
    body["off_hours"]["assess"] = 0
    answer = client.put("/control/capacity-schedule", json=body)
    assert answer.status_code == 422
    assert "at least one off-hours replica" in str(answer.json())


def test_invalid_timezone_is_rejected(client):
    answer = client.post("/control/capacity-schedule/validate", json=proposed(timezone="Pacific-ish"))
    assert answer.status_code == 200
    assert answer.json()["valid"] is False
    assert "IANA timezone" in " ".join(answer.json()["errors"])


def test_write_is_admin_only(monkeypatch, isolated_store):
    import core
    from fastapi.testclient import TestClient
    from app import app
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", "admin@example.com", raising=False)
    monkeypatch.setattr(core, "is_admin", lambda email: email == "admin@example.com", raising=False)
    assert TestClient(app).put("/control/capacity-schedule", json=proposed()).status_code == 403
