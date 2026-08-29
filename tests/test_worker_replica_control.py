"""Replica-control endpoints in api/routes/control.py.

Source-level: the semantics we care about are structural — the endpoint must be
present, must fail-gracefully when Azure is unconfigured, and must not accept
min_replicas outside the 1–5 guard. These are visible in the source and
untestable in a live round-trip without an Azure subscription.

GET is deliberately open to any authenticated user — it's visibility into shared
worker capacity, not a control action. PATCH (changing real Azure spend) is
admin-only, same gate as PUT /workers. Both are live-testable without any Azure
mocking: _require_admin runs before the AZURE_SUBSCRIPTION_ID check in PATCH, and
GET has no gate to clear at all, so neither the 403 path nor the (unconfigured,
in tests) 200 path ever reaches _az_client().
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

SRC = (ACP / "api" / "routes" / "control.py").read_text()


def test_get_replicas_route_exists():
    assert '@router.get("/control/workers/replicas")' in SRC


def test_patch_replicas_route_exists():
    assert '@router.patch("/control/workers/replicas")' in SRC


def test_get_replicas_returns_configured_false_when_unconfigured():
    """When AZURE_SUBSCRIPTION_ID is absent the endpoint must return configured: False
    rather than 502, so the frontend can hide the control instead of showing a broken state."""
    assert 'return {"configured": False' in SRC or "return {\"configured\": False" in SRC


def test_patch_replicas_raises_503_when_unconfigured():
    """PATCH must 503 when the env var is missing — not silently succeed or 500."""
    assert "503" in SRC
    assert "AZURE_SUBSCRIPTION_ID not set" in SRC


def test_replica_body_bounds():
    """min_replicas must be clamped to 1–5 in the Pydantic model so invalid values are
    rejected before any Azure API call."""
    assert "ge=1" in SRC
    assert "le=5" in SRC


def test_patch_does_not_touch_max_replicas():
    """PATCH adjusts minReplicas only; maxReplicas is left at its current value so the
    Azure autoscaler ceiling is not clobbered."""
    # The patch body model must have no max_replicas field.
    replica_body_section = re.search(
        r"class ReplicaBody.*?(?=\n@router|\nclass )", SRC, re.DOTALL
    )
    assert replica_body_section, "ReplicaBody model not found"
    assert "max_replicas" not in replica_body_section.group(), \
        "ReplicaBody should not expose max_replicas — callers set min only"


def test_az_client_uses_default_azure_credential():
    """Managed-identity auth only — no stored secret, no PAT."""
    assert "DefaultAzureCredential" in SRC


def test_lazy_azure_import():
    """The Azure SDK must be imported inside the helper, not at module level, so the
    service starts even when azure-mgmt-appcontainers is absent in non-Azure envs."""
    # Confirm no top-level 'from azure.mgmt' or 'import azure.mgmt'
    top_level_imports = re.findall(r"^(?:from|import) azure\.mgmt", SRC, re.MULTILINE)
    assert not top_level_imports, \
        f"azure.mgmt must be imported lazily inside _az_client(), not at module level: {top_level_imports}"


def test_only_patch_calls_require_admin():
    """Source-level pin: PATCH must gate on _require_admin — it changes real Azure spend, the
    same class of action PUT /workers (routes/system.py) already gates, and was found ungated
    on 2026-08-29. GET must NOT gate on it — replica visibility is meant to be open to any
    signed-in user, not locked to admins, same as the rest of WorkerAvailability.jsx's data."""
    get_section = re.search(r'@router\.get\("/control/workers/replicas"\)\ndef get_replicas.*?'
                             r'(?=\n@router|\Z)', SRC, re.DOTALL)
    patch_section = re.search(r'@router\.patch\("/control/workers/replicas"\)\ndef set_replicas.*?'
                               r'(?=\n@router|\Z)', SRC, re.DOTALL)
    assert get_section and "_require_admin" not in get_section.group()
    assert patch_section and "_require_admin(request)" in patch_section.group()


# ── live admin-gate enforcement ─────────────────────────────────────────────────
# Fully testable without an Azure subscription: _require_admin (PATCH only) runs
# BEFORE the AZURE_SUBSCRIPTION_ID check, so neither the 403 path nor the
# (unconfigured) 200 path ever reaches _az_client().

@pytest.fixture()
def gated_client(monkeypatch, isolated_store):
    """OWNER_EMAIL set, no recognised admin identity on the request → PATCH 403s."""
    import core
    from fastapi.testclient import TestClient
    from app import app
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", "admin@example.com", raising=False)
    monkeypatch.setattr(core, "is_admin", lambda e: e == "admin@example.com", raising=False)
    return TestClient(app)


def test_get_replicas_succeeds_for_a_non_admin_caller(gated_client):
    """Visibility is for everyone — a non-admin, ordinary signed-in caller must NOT 403."""
    r = gated_client.get("/control/workers/replicas")
    assert r.status_code == 200
    assert r.json()["configured"] is False   # no Azure subscription in tests


def test_patch_replicas_403s_for_a_non_admin_caller(gated_client):
    r = gated_client.patch("/control/workers/replicas", json={"min_replicas": 2})
    assert r.status_code == 403


def test_patch_replicas_reaches_the_unconfigured_503_for_an_admin_caller(monkeypatch, isolated_store):
    """An admin caller clears the gate and reaches the ordinary unconfigured response — the
    gate must not itself break the documented 503 fallback."""
    import core
    from fastapi.testclient import TestClient
    from app import app
    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    monkeypatch.setattr(core, "OWNER_EMAIL", "", raising=False)  # open mode — every caller passes
    r = TestClient(app).patch("/control/workers/replicas", json={"min_replicas": 2})
    assert r.status_code == 503
