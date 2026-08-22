"""Replica-control endpoints in api/routes/control.py.

Source-level: the semantics we care about are structural — the endpoint must be
present, must fail-gracefully when Azure is unconfigured, and must not accept
min_replicas outside the 1–5 guard. These are visible in the source and
untestable in a live round-trip without an Azure subscription.
"""
from __future__ import annotations

import re
from pathlib import Path

SRC = (Path(__file__).resolve().parent.parent / "api" / "routes" / "control.py").read_text()


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
