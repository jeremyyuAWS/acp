"""Azure Container Apps against the contract — every difference, classified.

PRD §21 phase 3: "rebuild the current Azure deployment using the common contract; prove feature
and performance parity". You cannot prove parity against an undescribed baseline, and you cannot
rebuild toward a target without knowing which of today's differences are deliberate. This is that
comparison, derived on both sides: the deployment from `azure_baseline` (which parses the scripts)
and the contract from `packaging/examples/standard-production.acp-deployment.yaml` (which the
validator already checks).

FOUR CLASSIFICATIONS, and the middle two are the point:

  match          the contract describes what Azure runs
  acknowledged   they differ, somebody decided that, and the reason is recorded below
  divergence     they differ and nobody wrote down why — the finding a parity report exists for
  not-modelled   Azure runs something the contract has no vocabulary for

An ACKNOWLEDGED entry is not a way to silence a difference: `test_azure_parity.py` requires each
one to correspond to a difference that is still real, so an acknowledgement outliving the thing it
excuses fails rather than sitting there looking considered. That is the same guard the unmounted-
component list in CLAUDE.md carries, for the same reason.

WHAT THIS DOES NOT CLAIM. It compares the SCRIPTS to the CONTRACT. It does not read the live
subscription, so configuration applied by hand outside `deploy/public/` is invisible to it — and
at least one such thing is known to exist (see UNVERIFIABLE). Reporting a clean comparison as
"production matches the contract" would be the overstatement this whole exercise is meant to
avoid.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .azure_baseline import APP_TO_TIER, OUT_OF_SCOPE, AzureApp, baseline

MATCH, ACKNOWLEDGED, DIVERGENCE, NOT_MODELLED = (
    "match", "acknowledged", "divergence", "not-modelled")

# The document the comparison is against. The standard profile, because that is what production
# is: split tiers, managed data services, independent worker scaling.
EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "standard-production.acp-deployment.yaml"

# Differences somebody decided on, keyed (tier, field). The text is the reason, and it is the whole
# value of the entry — "acknowledged" with no reason is indistinguishable from unnoticed.
ACKNOWLEDGED_DIFFERENCES: dict[tuple[str, str], str] = {
    ("api", "replicas.min"): (
        "The example raises the API floor from 1 to 2 because the standard profile requires two "
        "API replicas (PRD S8), and the example's own header says so. Azure runs 1 — so today's "
        "production would FAIL its own profile's floor, which is a finding about the deployment "
        "rather than about the contract."),
}

# Configuration this repo cannot see, and why. Named so that a clean report is not read as a
# complete one.
UNVERIFIABLE: dict[str, str] = {
    "acp-discovery scale rule": (
        "rightsize-production.sh says 'Discovery can use its existing CPU scale rule', but no "
        "scale rule for acp-discovery exists anywhere in this repository — it was applied outside "
        "these scripts. Its trigger, threshold and even its existence cannot be checked from here."),
    "ACP_WORKER_ROLE on assess and remediate": (
        "redeploy.sh states that only acp-discovery's role is set in this repo; the other two get "
        "ACP_WORKER_ROLE from container-app environment variables set outside it. Which lane each "
        "worker actually serves is therefore a convention this repository cannot verify."),
    "live estate drift": (
        "Everything here is what the SCRIPTS configure. An app resized or rescaled by hand in the "
        "portal is invisible to this comparison."),
}


@dataclass
class Difference:
    tier: str
    field: str
    azure: Any
    contract: Any
    classification: str
    note: str = ""

    def render(self) -> str:
        return (f"{self.tier}.{self.field}: azure={self.azure!r} contract={self.contract!r} "
                f"[{self.classification}]")


def _example() -> dict:
    from .spec import load_document
    return load_document(EXAMPLE)


def _contract_tiers(doc: dict) -> dict[str, dict]:
    from . import presets
    tiers = {"api": doc["api"]}
    tiers.update(doc["workers"])
    out = {}
    for name, tier in tiers.items():
        row = presets.PRESETS[tier["resources"]["preset"]]
        out[name] = {
            "cpu": float(row["cpu"]),
            "memory": row["memory"],
            "replicas.min": tier["replicas"]["min"],
            "replicas.max": tier["replicas"]["max"],
            "autoscaled": bool(tier.get("autoscale")),
        }
    return out


def _azure_fields(app: AzureApp) -> dict[str, Any]:
    return {
        "cpu": app.cpu,
        # 4.0Gi and 4Gi are the same quantity written two ways, and the scripts use both — but
        # DEFENSIVELY, and it is worth being exact about that. Today the decimal form appears only
        # on apps outside the tier model (`acp-worker` at 4.0Gi, `acp-grafana` at 1.0Gi) and on
        # deploy.sh's create flags; every app the comparison actually reaches is written the short
        # way in rightsize-production.sh, so removing this normalisation changes no current
        # result. A bite check established that rather than the comment claiming otherwise.
        #
        # It stays because the two files disagree about the format TODAY, so one edit to the
        # reviewed baseline in deploy.sh's style would start a false difference — and
        # test_a_decimal_memory_quantity_is_not_reported_as_a_difference drives this path so the
        # normalisation is exercised rather than merely present.
        "memory": _normalise_memory(app.memory),
        "replicas.min": app.min_replicas,
        "replicas.max": app.max_replicas,
        "autoscaled": app.autoscaled,
    }


def _normalise_memory(text: str | None) -> str | None:
    if not text:
        return None
    for suffix in ("Gi", "G"):
        if text.endswith(suffix):
            number = float(text[: -len(suffix)])
            whole = int(number)
            return f"{whole}Gi" if number == whole else f"{number}Gi"
    return text


def compare() -> dict[str, Any]:
    """Every tier, every field, classified."""
    azure = baseline()
    contract = _contract_tiers(_example())
    by_tier = {app.tier: app for app in azure.values() if app.tier}

    differences: list[Difference] = []
    for tier, expected in sorted(contract.items()):
        app = by_tier.get(tier)
        if app is None:
            differences.append(Difference(
                tier, "(whole tier)", None, "described", DIVERGENCE,
                "the contract describes this tier and no Azure app serves it"))
            continue
        actual = _azure_fields(app)
        for field, want in expected.items():
            got = actual.get(field)
            if got == want:
                continue
            note = ACKNOWLEDGED_DIFFERENCES.get((tier, field), "")
            differences.append(Difference(
                tier, field, got, want,
                ACKNOWLEDGED if note else DIVERGENCE, note))

    not_modelled = [
        Difference(name, "(whole app)", "deployed", None, NOT_MODELLED,
                   OUT_OF_SCOPE.get(name, "no reason recorded — decide about this app"))
        for name in sorted(azure) if not azure[name].tier
    ]

    real = [d for d in differences if d.classification == DIVERGENCE]
    return {
        "apps": azure,
        "contract": contract,
        "differences": differences,
        "not_modelled": not_modelled,
        "unverifiable": dict(UNVERIFIABLE),
        "divergences": len(real),
        "acknowledged": len([d for d in differences if d.classification == ACKNOWLEDGED]),
        "parity": not real,
    }
