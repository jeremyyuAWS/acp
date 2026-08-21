"""Multi-tenant SharePoint (connecting a SECOND Entra tenant's SharePoint/OneDrive as a scan
source) — core._load_microsoft_tenants() and its exposure through /config.

A single-tenant Entra app registration (docs/sharepoint-app-registration.md) reaches exactly one
organization's SharePoint/OneDrive. AZURE_CLIENT_ID/AZURE_TENANT_ID alone made this deployment
structurally unable to reach a second, separate production tenant's estate no matter what a user
did in the UI. ACP_AZURE_CLIENT_ID_2/ACP_AZURE_TENANT_ID_2 (and _3, ...) add more, each requiring
its OWN app registration and admin consent in ITS OWN tenant — nothing here substitutes for that;
this only pins the config-loading contract the frontend's getMicrosoftTenants()/getSpAuth(key)
depend on.

Deliberately NOT the identity provider that gates sign-in to ACP itself — AZURE_CLIENT_ID/
AZURE_TENANT_ID stay singular and untouched; SignIn.jsx's "Sign in with Microsoft" is unaffected.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

ACP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ACP / "api"))

import core  # noqa: E402
import routes.system as system  # noqa: E402


def test_a_single_configured_tenant_yields_one_primary_entry(monkeypatch):
    monkeypatch.setattr(core, "AZURE_CLIENT_ID", "c1")
    monkeypatch.setattr(core, "AZURE_TENANT_ID", "t1")
    tenants = core._load_microsoft_tenants()
    assert tenants == [{"key": "primary", "label": "Primary", "client_id": "c1", "tenant_id": "t1"}]


def test_no_configured_tenant_yields_an_empty_list(monkeypatch):
    monkeypatch.setattr(core, "AZURE_CLIENT_ID", None)
    monkeypatch.setattr(core, "AZURE_TENANT_ID", None)
    assert core._load_microsoft_tenants() == []


def test_a_partial_pair_primary_client_id_with_no_tenant_id_is_not_reported(monkeypatch):
    """A half-set primary pair is not a usable tenant — matches the existing azure_client_id/
    azure_tenant_id contract, where the SPA hides the button unless BOTH are present."""
    monkeypatch.setattr(core, "AZURE_CLIENT_ID", "c1")
    monkeypatch.setattr(core, "AZURE_TENANT_ID", None)
    assert core._load_microsoft_tenants() == []


def test_a_custom_primary_label_is_honoured(monkeypatch):
    monkeypatch.setattr(core, "AZURE_CLIENT_ID", "c1")
    monkeypatch.setattr(core, "AZURE_TENANT_ID", "t1")
    monkeypatch.setenv("ACP_AZURE_TENANT_LABEL", "Acme Corp")
    tenants = core._load_microsoft_tenants()
    assert tenants[0]["label"] == "Acme Corp"


def test_a_second_tenant_env_pair_is_picked_up(monkeypatch):
    monkeypatch.setattr(core, "AZURE_CLIENT_ID", "c1")
    monkeypatch.setattr(core, "AZURE_TENANT_ID", "t1")
    monkeypatch.setenv("ACP_AZURE_CLIENT_ID_2", "c2")
    monkeypatch.setenv("ACP_AZURE_TENANT_ID_2", "t2")
    monkeypatch.setenv("ACP_AZURE_TENANT_2_LABEL", "Contoso")
    tenants = core._load_microsoft_tenants()
    assert tenants == [
        {"key": "primary", "label": "Primary", "client_id": "c1", "tenant_id": "t1"},
        {"key": "tenant2", "label": "Contoso", "client_id": "c2", "tenant_id": "t2"},
    ]


def test_a_second_tenant_with_no_label_gets_a_default_name(monkeypatch):
    monkeypatch.setattr(core, "AZURE_CLIENT_ID", "c1")
    monkeypatch.setattr(core, "AZURE_TENANT_ID", "t1")
    monkeypatch.setenv("ACP_AZURE_CLIENT_ID_2", "c2")
    monkeypatch.setenv("ACP_AZURE_TENANT_ID_2", "t2")
    tenants = core._load_microsoft_tenants()
    assert tenants[1]["label"] == "Tenant 2"


def test_a_second_tenant_can_exist_without_a_primary(monkeypatch):
    """An operator who only wants the second registration (e.g. mid-migration off the first)
    should not be forced to keep a primary pair just to make numbering work."""
    monkeypatch.setattr(core, "AZURE_CLIENT_ID", None)
    monkeypatch.setattr(core, "AZURE_TENANT_ID", None)
    monkeypatch.setenv("ACP_AZURE_CLIENT_ID_2", "c2")
    monkeypatch.setenv("ACP_AZURE_TENANT_ID_2", "t2")
    tenants = core._load_microsoft_tenants()
    assert tenants == [{"key": "tenant2", "label": "Tenant 2", "client_id": "c2", "tenant_id": "t2"}]


def test_a_gap_in_numbering_stops_the_scan_rather_than_skipping_silently(monkeypatch):
    """2 and 4 set, 3 unset: a silently-skipped slot (finding 4 anyway) is worse than an
    obviously-missing one — an operator who mistyped _3 should see tenant 4 simply absent, not
    present under the wrong number."""
    monkeypatch.setattr(core, "AZURE_CLIENT_ID", "c1")
    monkeypatch.setattr(core, "AZURE_TENANT_ID", "t1")
    monkeypatch.setenv("ACP_AZURE_CLIENT_ID_2", "c2")
    monkeypatch.setenv("ACP_AZURE_TENANT_ID_2", "t2")
    monkeypatch.setenv("ACP_AZURE_CLIENT_ID_4", "c4")
    monkeypatch.setenv("ACP_AZURE_TENANT_ID_4", "t4")
    tenants = core._load_microsoft_tenants()
    assert [t["key"] for t in tenants] == ["primary", "tenant2"]


def test_multiple_tenants_are_read_from_real_env_vars_end_to_end():
    """The deploy-time env names, reloading the module exactly as test_config_azure.py's
    single-pair test does — pins that _load_microsoft_tenants runs at import time, not lazily."""
    os.environ["ACP_AZURE_CLIENT_ID"] = "env-c1"
    os.environ["ACP_AZURE_TENANT_ID"] = "env-t1"
    os.environ["ACP_AZURE_CLIENT_ID_2"] = "env-c2"
    os.environ["ACP_AZURE_TENANT_ID_2"] = "env-t2"
    try:
        importlib.reload(core)
        assert [t["key"] for t in core.MICROSOFT_TENANTS] == ["primary", "tenant2"]
    finally:
        for k in ("ACP_AZURE_CLIENT_ID", "ACP_AZURE_TENANT_ID",
                 "ACP_AZURE_CLIENT_ID_2", "ACP_AZURE_TENANT_ID_2"):
            os.environ.pop(k, None)
        importlib.reload(core)


# ── /config exposure ──────────────────────────────────────────────────────────────────────────

def test_config_exposes_microsoft_tenants(monkeypatch):
    fake = [{"key": "primary", "label": "Primary", "client_id": "c1", "tenant_id": "t1"},
            {"key": "tenant2", "label": "Contoso", "client_id": "c2", "tenant_id": "t2"}]
    monkeypatch.setattr(core, "MICROSOFT_TENANTS", fake)
    cfg = system.config()
    assert cfg["microsoft_tenants"] == fake


def test_config_microsoft_tenants_is_empty_list_not_missing_when_unconfigured(monkeypatch):
    monkeypatch.setattr(core, "MICROSOFT_TENANTS", [])
    cfg = system.config()
    assert cfg["microsoft_tenants"] == []


def test_config_still_exposes_the_singular_azure_fields_unchanged(monkeypatch):
    """The identity-provider fields that gate sign-in to ACP itself must not be affected by
    multi-tenant SharePoint support — a second data-source tenant is not a second way to sign in."""
    monkeypatch.setattr(core, "AZURE_CLIENT_ID", "c1")
    monkeypatch.setattr(core, "AZURE_TENANT_ID", "t1")
    monkeypatch.setattr(core, "MICROSOFT_TENANTS",
                        [{"key": "primary", "label": "Primary", "client_id": "c1", "tenant_id": "t1"},
                         {"key": "tenant2", "label": "Contoso", "client_id": "c2", "tenant_id": "t2"}])
    cfg = system.config()
    assert cfg["azure_client_id"] == "c1" and cfg["azure_tenant_id"] == "t1"
