"""What the Azure Container Apps deployment ACTUALLY configures — read from the scripts.

PHASE 3 ASKS FOR PARITY, AND PARITY NEEDS A BASELINE. PRD §21 phase 3 is "rebuild the current
Azure deployment using the common contract; prove feature and performance parity". That second
half is unprovable until somebody writes down what the current deployment does, and writing it
down by hand produces a document that is true on the day it is written and quietly wrong
afterwards — `deploy/public/` is edited by other work (PR #1366 was changing its drain windows
while this was being built).

So this PARSES the scripts. `deploy/public/rightsize-production.sh` is the reviewed capacity
baseline and states each app's CPU, memory and replica range in one place; `deploy/public/deploy.sh`
creates the apps and carries the ingress posture and the scale rules. Deriving from them means the
baseline cannot drift from the deployment: change the script and the generated document changes,
or `--check` fails.

WHAT THIS IS NOT. It does not read a live Azure subscription — there are no credentials here and
production must not be touched to answer a documentation question. It reports what the scripts
would configure, which is the reviewed intent. Where the running estate has been changed by hand
outside these scripts, this cannot see it, and the generated document says so.

WHY A PARSER AND NOT A TRANSCRIPTION. A transcription is a second copy of the numbers, and the
whole lesson of this repo's generated documents is that a second copy is a copy that goes stale
while reading as current. The regex surface is deliberately tiny — one function call shape in
rightsize-production.sh and a handful of `az containerapp create` flags — and
tests/test_azure_parity.py asserts the parse found the apps it expects, so a script rewrite that
breaks the parse fails loudly rather than yielding an empty baseline that reads as "no
divergences".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEPLOY = ROOT / "deploy" / "public"
RIGHTSIZE = DEPLOY / "rightsize-production.sh"
DEPLOY_SH = DEPLOY / "deploy.sh"
REDEPLOY_SH = DEPLOY / "redeploy.sh"

# Which container app plays which role in the contract's vocabulary. The names are the deployment's
# and the tiers are the document's; this table is the join, and it is the one hand-maintained fact
# here — which is why tests/test_azure_parity.py checks every app the scripts create is either
# mapped or explicitly out of scope.
APP_TO_TIER: dict[str, str] = {
    "acp-app": "api",
    "acp-discovery": "discover",
    "acp-assess": "assess",
    "acp-remediate": "remediate",
}

# Apps the contract does not model, with the reason. Named rather than filtered silently: an
# unmapped app that nobody decided about is exactly the gap a parity report exists to surface.
OUT_OF_SCOPE: dict[str, str] = {
    "acp-ollama": "the local model runtime; ai.ollama in the document, not a workload tier",
    "acp-ollama-gpu": "the GPU model runtime production actually uses",
    "acp-grafana": "observability.grafana in the document, not a workload tier",
    "acp-worker": "the retired generic mixed-role worker (redeploy.sh excludes it deliberately)",
}


@dataclass
class AzureApp:
    """One container app as the scripts configure it."""

    name: str
    cpu: float | None = None
    memory: str | None = None
    min_replicas: int | None = None
    max_replicas: int | None = None
    # ACP_DB_MAX_CONN, where the reviewed baseline pins one. Added by #1370 to keep the fleet
    # under Postgres's measured 150-connection ceiling; carried here because a replica ceiling
    # means something different once each replica's pool is capped.
    db_pool: int | None = None
    ingress: str | None = None            # "external" | "internal" | None (no ingress)
    scale_rules: list[str] = field(default_factory=list)
    source: str = ""

    @property
    def tier(self) -> str | None:
        return APP_TO_TIER.get(self.name)

    @property
    def autoscaled(self) -> bool:
        """Does this app scale at all?

        A range whose min equals its max does not, whatever scale rules are attached — and that
        distinction is the whole finding for the assess and remediate tiers, which production pins
        warm at 5-5 while the contract's example describes them as autoscaling 3-10.
        """
        if self.min_replicas is None or self.max_replicas is None:
            return False
        return self.max_replicas > self.min_replicas


# `update_app acp-app 1.0 2Gi 1 3` and `update_app acp-assess 2.0 4Gi 5 5 2` — the reviewed
# baseline's call shape, with the optional sixth argument (ACP_DB_MAX_CONN) that PR #1370 added.
#
# THE OPTIONAL ARGUMENT IS WHY THIS TOLERATES A TRAILING FIELD RATHER THAN ANCHORING AT `$`. The
# first version anchored, so when #1370 landed a connection-pool size on three of the five calls,
# the parse silently found only `acp-app` and `acp-ollama` — an empty-ish baseline that would
# have rendered as a shorter table with fewer differences. That is the quiet failure this
# module's tests are built around, and it happened for real within an hour of the parser being
# written: tests/test_azure_parity.py::test_the_baseline_found_every_workload_tier caught it.
_RIGHTSIZE_CALL = re.compile(
    r"^update_app\s+(?P<name>\S+)\s+(?P<cpu>[\d.]+)\s+(?P<memory>\S+)\s+"
    r"(?P<min>\d+)\s+(?P<max>\d+)(?:\s+(?P<pool>\d+))?\s*(?:#.*)?$", re.MULTILINE)

# A scale rule applied by a dedicated function rather than by `update_app` — #1370's
# `apply_remediation_autoscale`. Matched on the `--name <app>` inside the function body so a
# second such function for another tier is picked up without another pattern.
_NAMED_SCALE_RULE = re.compile(
    r"--name\s+(?P<app>acp-[\w-]+)\s+--scale-rule-name\s+(?P<rule>\S+)")

_CREATE = re.compile(r"az containerapp create .*?-n \"?\$(?P<var>[A-Z_]+)\"?(?P<body>.*?)-o none",
                     re.DOTALL)
_CPU = re.compile(r"--cpu\s+([\d.]+)")
_MEMORY = re.compile(r"--memory\s+(\S+)")
_MIN = re.compile(r"--min-replicas\s+(\d+)")
_MAX = re.compile(r"--max-replicas\s+(\d+)")
_INGRESS = re.compile(r"--ingress\s+(\w+)")
_SCALE_RULE = re.compile(r"--scale-rule-name\s+(\S+)")


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def parse_rightsize(text: str | None = None) -> dict[str, AzureApp]:
    """The reviewed capacity baseline: CPU, memory and replica range per app.

    THIS FILE IS THE AUTHORITY ON SIZING, not deploy.sh. deploy.sh's `create` flags are the values
    an app is born with; rightsize-production.sh is what an operator applied afterwards and is
    described in the script itself as "the reviewed production capacity baseline". Reading the
    creation flags as the production shape would report the API tier as max-replicas 1, which it
    has not been since that script was run.
    """
    body = text if text is not None else _text(RIGHTSIZE)
    apps: dict[str, AzureApp] = {}
    for match in _RIGHTSIZE_CALL.finditer(body):
        apps[match["name"]] = AzureApp(
            name=match["name"], cpu=float(match["cpu"]), memory=match["memory"],
            min_replicas=int(match["min"]), max_replicas=int(match["max"]),
            db_pool=int(match["pool"]) if match["pool"] else None,
            source="rightsize-production.sh")
    for rule in _NAMED_SCALE_RULE.finditer(body):
        app = apps.get(rule["app"])
        if app and rule["rule"] not in app.scale_rules:
            app.scale_rules.append(rule["rule"])
    return apps


def parse_deploy(text: str | None = None) -> dict[str, AzureApp]:
    """Ingress posture and scale rules, which only deploy.sh carries.

    Keyed by the shell VARIABLE the create call names ($APP, $WORKER_APP, $GF_APP) resolved
    through its default, because the script parameterises every name. A create whose variable
    cannot be resolved is skipped rather than guessed at — an app attributed to the wrong name
    would put its ingress posture on somebody else's tier.
    """
    body = text if text is not None else _text(DEPLOY_SH)
    # Two assignment shapes, because the script uses both: `APP="${ACP_APP:-acp-app}"` for the
    # overridable names and `GF_APP="acp-grafana"` for the fixed one. Matching only the first
    # silently dropped Grafana from the baseline — an app the deployment creates and the report
    # never mentioned, which is the exact shape of omission a parity report must not have.
    defaults = dict(re.findall(r'^(\w+)="\$\{[A-Z_]+:-([\w-]+)\}"', body, re.MULTILINE))
    defaults.update(dict(re.findall(r'^(\w+)="([\w-]+)"\s*$', body, re.MULTILINE)))
    apps: dict[str, AzureApp] = {}
    for match in _CREATE.finditer(body):
        name = defaults.get(match["var"])
        if not name:
            continue
        chunk = match["body"]
        ingress = _INGRESS.search(chunk)
        app = AzureApp(name=name, source="deploy.sh",
                       ingress=ingress.group(1) if ingress else None)
        for pattern, attr, cast in ((_CPU, "cpu", float), (_MEMORY, "memory", str),
                                    (_MIN, "min_replicas", int), (_MAX, "max_replicas", int)):
            found = pattern.search(chunk)
            if found:
                setattr(app, attr, cast(found.group(1)))
        apps[name] = app

    # Scale rules are attached by a separate `az containerapp update` (see deploy.sh's comment
    # about the worker tier having been created with a max-replicas and no rule), so they are
    # collected across the whole file rather than from the create block.
    for match in re.finditer(r'-n "\$(\w+)"(?P<body>(?:(?!az containerapp).)*?)--scale-rule-name\s+(\S+)',
                             body, re.DOTALL):
        name = defaults.get(match.group(1))
        if name and name in apps:
            apps[name].scale_rules.append(match.group(3))
    return apps


# `secretref:database-url` — how a container app names a secret from its own store. The names are
# what the deployment actually keeps a credential FOR, which is a different and more useful set
# than the names the contract requires: production reaches Blob Storage through a managed identity
# and so has no storage secret at all, and that absence is only visible if the present ones are
# read rather than assumed.
_SECRETREF = re.compile(r"secretref:(?P<name>[a-z0-9][a-z0-9-]*)")


def secret_names(text: str | None = None) -> set[str]:
    """Every secret the create script wires into a container app, by name."""
    body = DEPLOY_SH.read_text(encoding="utf-8") if text is None else text
    return {m["name"] for m in _SECRETREF.finditer(body)}


def baseline() -> dict[str, AzureApp]:
    """One record per app: sizing from the reviewed baseline, posture from the create script."""
    apps = parse_rightsize()
    for name, created in parse_deploy().items():
        if name in apps:
            apps[name].ingress = created.ingress
            apps[name].scale_rules = created.scale_rules
            apps[name].source = "rightsize-production.sh + deploy.sh"
        else:
            apps[name] = created
    return dict(sorted(apps.items()))
