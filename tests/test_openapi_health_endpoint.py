"""GET /openapi/health.json and GET /docs/health — the publicly-readable Swagger document for
ACP's health/readiness/heartbeat surface (api/routes/openapi_health.py).

These tests pin three things: the document is valid enough to be useful (well-formed OpenAPI,
covers the endpoints the module claims to cover), it stays reachable with no credential even in
PRODUCTION SHAPE (mirrors tests/test_monitor_estate_endpoint.py's prod_client), and it never
grows to include a route this module doesn't intend to document (which would be how a sensitive
endpoint's shape leaks into a document meant to be safe to publish).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

from routes.openapi_health import HEALTH_OPENAPI_SPEC  # noqa: E402

# Every path this document claims to describe must actually exist in the live route table —
# otherwise the "document" is describing an endpoint nobody can call.
EXPECTED_PATHS = {
    "/healthz", "/readyz", "/monitor/estate", "/schedule", "/ai/status", "/jobs",
    "/jobs/{job_id}", "/discovery/preflight", "/scans/active", "/scans/{sid}/status",
    "/scans/{sid}/live", "/scans/{sid}/remediation-status", "/scans/{sid}/source-status",
    "/control/estate", "/capability", "/alerts/webhook",
}


def test_the_document_is_well_formed_openapi():
    assert HEALTH_OPENAPI_SPEC["openapi"].startswith("3.")
    assert HEALTH_OPENAPI_SPEC["info"]["title"]
    assert set(HEALTH_OPENAPI_SPEC["paths"]) == EXPECTED_PATHS


def test_every_documented_path_resolves_to_a_real_registered_route():
    import core
    from app import app

    real_paths = {r.path for r in core.enumerate_api_routes(app)}
    for path in EXPECTED_PATHS:
        assert path in real_paths, f"{path} is documented but not a registered FastAPI route"


def test_every_schema_ref_resolves():
    schemas = HEALTH_OPENAPI_SPEC["components"]["schemas"]
    for path, methods in HEALTH_OPENAPI_SPEC["paths"].items():
        for method, op in methods.items():
            schema = op["responses"]["200"]["content"]["application/json"]["schema"]
            ref = schema.get("$ref")
            if ref:
                name = ref.rsplit("/", 1)[-1]
                assert name in schemas, f"{path} {method} references undefined schema {name!r}"


@pytest.fixture()
def prod_client(monkeypatch, isolated_store):
    """Production shape: the GIS gate live, no bypass — same posture as
    tests/test_monitor_estate_endpoint.py's prod_client."""
    import core
    from fastapi.testclient import TestClient

    from app import app

    monkeypatch.setattr(core, "store", isolated_store)
    monkeypatch.setattr(core, "ACCESS_CODE", "", raising=False)
    monkeypatch.setattr(core, "GOOGLE_CLIENT_ID", "test-client-id", raising=False)
    monkeypatch.setattr(core, "E2E_KEY", None, raising=False)
    return TestClient(app)


def test_the_json_document_is_reachable_with_no_credential(prod_client):
    # The gate is genuinely live — an ordinary route still needs auth.
    assert prod_client.get("/scans").status_code == 401

    res = prod_client.get("/openapi/health.json")
    assert res.status_code == 200, res.text
    assert res.json()["info"]["title"] == HEALTH_OPENAPI_SPEC["info"]["title"]


def test_the_swagger_ui_page_is_reachable_with_no_credential(prod_client):
    res = prod_client.get("/docs/health")
    assert res.status_code == 200, res.text
    assert "text/html" in res.headers["content-type"]
    assert "/openapi/health.json" in res.text


def test_is_public_agrees_with_the_live_prod_client_result():
    """The gate's own predicate must call these two paths public — the source of truth
    test_the_*_is_reachable_with_no_credential above exercises end to end."""
    import core

    assert core.is_public("/openapi/health.json") is True
    assert core.is_public("/docs/health") is True
