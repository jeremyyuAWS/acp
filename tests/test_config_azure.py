"""/config serves the Entra (SharePoint) client + tenant ids at runtime, like google_client_id.

The SPA reads these from /config rather than a build-time VITE_AZURE_* value so a deployment — or
each customer's tenant — is pointed at an Entra app with an env var and NO rebuild. This pins the
API contract the frontend's getSpAuth() depends on: the two keys are present, carry what core
holds, and are null (not missing) when SharePoint isn't configured, so the SPA hides the button.
"""
from __future__ import annotations

import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import core  # noqa: E402
import routes.system as system  # noqa: E402


def test_config_exposes_azure_ids_from_core(monkeypatch):
    monkeypatch.setattr(core, "AZURE_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(core, "AZURE_TENANT_ID", "test-tenant-id")
    cfg = system.config()
    assert cfg["azure_client_id"] == "test-client-id"
    assert cfg["azure_tenant_id"] == "test-tenant-id"


def test_config_azure_ids_null_when_unset(monkeypatch):
    """Absent, not missing — the SPA distinguishes 'not configured' (hide the button) from a
    key that vanished (a bug)."""
    monkeypatch.setattr(core, "AZURE_CLIENT_ID", None)
    monkeypatch.setattr(core, "AZURE_TENANT_ID", None)
    cfg = system.config()
    assert cfg["azure_client_id"] is None
    assert cfg["azure_tenant_id"] is None


def test_azure_ids_read_from_acp_env():
    """core reads ACP_AZURE_CLIENT_ID / ACP_AZURE_TENANT_ID (the deploy-time env names)."""
    import importlib
    import os
    os.environ["ACP_AZURE_CLIENT_ID"] = "env-cid"
    os.environ["ACP_AZURE_TENANT_ID"] = "env-tid"
    try:
        importlib.reload(core)
        assert core.AZURE_CLIENT_ID == "env-cid"
        assert core.AZURE_TENANT_ID == "env-tid"
    finally:
        del os.environ["ACP_AZURE_CLIENT_ID"]
        del os.environ["ACP_AZURE_TENANT_ID"]
        importlib.reload(core)
