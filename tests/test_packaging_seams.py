"""Where the chart's wiring and the application's reads do not meet.

WHY THIS FILE EXISTS. Six defects found on 2026-09-08 were the same defect: the chart deployed a
workload that read an environment variable the chart never set, or set one the application never
read. Each was silent, each was green under a rendered-manifest test, and each was found by hand.

  worker `command`          worker pods ran the API server
  readiness probe path      the gate could not return non-200
  pre-install hook ordering no `helm install` had ever succeeded
  default-deny egress       no DNS, and no route to Postgres
  ACP_BLOB_ACCOUNT          every remediated document was produced and dropped
  ai.ollama.gpu             a GPU was requested nowhere
  the access gate           a public ingress authenticated nobody

Finding the seventh by hand is not a plan. So this file pins BOTH DIRECTIONS of the seam and makes
every remaining gap a named entry with a reason — the shape `unmountedComponents.test.jsx` uses for
the same problem in the frontend. A new gap fails a test in seconds; closing one fails until its
entry is deleted, so the list cannot rot into a description of a state that no longer exists.

WHAT THIS CANNOT DO, said plainly. Direction 1 is derived from the render and is exhaustive.
Direction 2 is a CURATED list — resolving what `deploy.sh` sets means resolving shell variables
through their defaults, and a parser for that would be a second implementation of bash that goes
wrong quietly. Every entry in it is verified against the three facts that make it a gap, so the
list cannot contain a false claim; it just cannot promise to be complete. That limitation is why
direction 1 is written the other way round.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from packaging_helpers import PACKAGING, ROOT, load_example

CHART = PACKAGING / "chart" / "acp"
API = ROOT / "api"
DEPLOY_SCRIPTS = sorted((ROOT / "deploy" / "public").glob("*.sh"))
HELM = shutil.which("helm")

needs_helm = pytest.mark.skipif(HELM is None, reason="helm is not installed")


def _api_source() -> str:
    return "\n".join(p.read_text(encoding="utf-8", errors="replace")
                     for p in sorted(API.rglob("*.py")))


def _deploy_source() -> str:
    return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in DEPLOY_SCRIPTS)


def rendered_env_names() -> set[str]:
    """Every environment variable name the chart can put on a container.

    Rendered rather than grepped from the templates, because half of them do not appear in the
    templates at all: `acp.commonEnv` projects each `secrets.refs` key as an uppercase env var, so
    the name exists only after a document has been through `acpctl values`.
    """
    from acpctl.values import render_values_yaml
    names: set[str] = set()
    for example in ("standard-production", "high-availability"):
        proc = subprocess.run([HELM, "template", "acp", str(CHART), "-f", "-"],
                              input=render_values_yaml(load_example(example)),
                              capture_output=True, text=True, timeout=120)
        assert proc.returncode == 0, proc.stderr
        for doc in yaml.safe_load_all(proc.stdout):
            if not doc or doc["kind"] not in ("Deployment", "Job"):
                continue
            for container in doc["spec"]["template"]["spec"]["containers"]:
                names.update(e["name"] for e in container.get("env", []))
    return names


# ── direction 1: the chart sets it, nothing in api/ reads it ──────────────────
#
# DERIVED, NOT LISTED — the set is computed from the render and compared with this table, so a
# variable added to the chart that nothing reads fails here rather than sitting in a Deployment
# looking like configuration.
UNREAD_BY_THE_APPLICATION = {
    # Provenance. Deliberately on the workload so an operator can read what is deployed off the
    # running object; ADR 0048 asserts elsewhere that nothing branches on ACP_PLATFORM, because the
    # moment application code did, "one package, four clouds" would stop being true.
    "ACP_RELEASE": "provenance: which release this workload is",
    "ACP_DEPLOY_PROFILE": "provenance: which profile installed this",
    "ACP_PLATFORM": "provenance: which adapter installed this, and nothing may branch on it",
    "ACP_AI_LOCAL_ONLY": "an auditable statement of the regulated profile's promise, readable off "
                         "the Deployment; the AI lane is chosen by ai.mode, not by this",
    # Other containers' variables. Read by the image, not by api/.
    "OLLAMA_HOST": "the ollama server's own bind address",
    "GF_SERVER_ROOT_URL": "Grafana's own absolute-link base",
    "OTEL_SERVICE_NAME": "read by the OpenTelemetry SDK, not by api/",
    # THE READ-ONLY ROOT'S CACHE REDIRECTIONS. Read by libraries and by CPython rather than by
    # api/, which is precisely why they belong here: grep the application for them and you find
    # nothing, and every one of them fails QUIETLY if it is wrong. `securityContext.
    # readOnlyRootFilesystem` is true, so each names a path on the scratch volume.
    "HOME": "UID 10001 has no passwd entry — no Dockerfile sets USER, useradd or HOME — so "
            "expanduser('~') resolved somewhere unverified; api/scanner.py reads ~/.dotnet when "
            "it invokes the Office analyser",
    "XDG_CACHE_HOME": "fontconfig, under WeasyPrint/Pango in the report renderer; an unwritable "
                      "cache is a warning and a slow render rather than an error",
    "DOTNET_CLI_HOME": "the .NET CLI's own first-run state, for the Office analyser",
    "PYTHONDONTWRITEBYTECODE": "read by CPython: /app is read-only now, so without it every "
                               "module attempts a __pycache__ write on first import, fails, and "
                               "continues silently",
    # DEAD WIRING, and the only entries here that are defects rather than decisions. Each is a
    # `secrets.refs` key the contract REQUIRES, projected to a name no application code reads.
    # Renaming them changes which documents are valid, so it needs an owner decision (PRD S2.8)
    # rather than a quiet fix — recorded here so the cost is visible while it waits.
    "GOOGLE_OAUTH_CLIENT_SECRET": "DEAD: required for the google-drive source; api/ reads "
                                  "ACP_GOOGLE_CLIENT_ID, which is a different value",
    "MICROSOFT_OAUTH_CLIENT_SECRET": "DEAD: required for the sharepoint source; api/ reads "
                                     "ACP_AZURE_CLIENT_ID and ACP_AZURE_TENANT_ID",
    "OBJECT_STORAGE": "DEAD: required whenever object storage is not embedded; the variable that "
                      "wires the store is ACP_BLOB_ACCOUNT, from data.objectStorage.account",
}


@needs_helm
def test_every_variable_the_chart_sets_is_one_the_application_reads():
    """Both directions, so the table cannot rot.

    An unexplained variable fails because it is not in the table. An entry for a variable the chart
    no longer sets fails because it is stale — which is what stops this from becoming a list of
    problems somebody already fixed.
    """
    source = _api_source()
    rendered = rendered_env_names()
    assert rendered, "nothing rendered; this test would prove nothing"
    unread = {name for name in rendered if name not in source}
    documented = set(UNREAD_BY_THE_APPLICATION)
    assert unread == documented, (
        f"undocumented and read by nothing: {sorted(unread - documented)}; "
        f"documented but no longer unread or no longer rendered: {sorted(documented - unread)}")


@needs_helm
def test_the_dead_wiring_is_named_as_dead():
    """The three entries marked DEAD are defects waiting on a decision, not design choices. Naming
    them apart from the provenance labels is what keeps 'the chart sets things nothing reads' from
    reading as normal."""
    dead = {k for k, why in UNREAD_BY_THE_APPLICATION.items() if why.startswith("DEAD:")}
    assert dead == {"GOOGLE_OAUTH_CLIENT_SECRET", "MICROSOFT_OAUTH_CLIENT_SECRET",
                    "OBJECT_STORAGE"}
    assert dead <= rendered_env_names()


# ── direction 2: api/ reads it, the Azure deployment sets it, the chart does not ──
#
# CURATED, and every entry is checked against the three facts below rather than trusted. The value
# is what the absence COSTS, because that is the judgement a reader needs and the thing a grep
# cannot supply.
NOT_WIRED_BY_THE_CHART = {
    "ACP_ALLOWED_EMAILS":
        "the sign-in allow-list is empty, which is fail-closed and therefore harmless until the "
        "access gate is armed — it becomes load-bearing the moment it is",
    "ACP_GOOGLE_ADC":
        "read by the image entrypoint rather than by Python (deploy/public/worker-entry.sh writes "
        "/tmp/adc.json and exports GOOGLE_APPLICATION_CREDENTIALS); the chart runs that entrypoint "
        "and supplies nothing, so Drive service-account access is silently unavailable",
    "ACP_VISION_PROVIDER":
        "vision selection falls to the local CPU floor with no GPU provider configurable",
    "RUNPOD_ENDPOINT_ID":
        "the serverless vision provider returns None, so GPU vision is quietly absent",
    "RUNPOD_API_KEY":
        "the credential half of the same provider; without both, selection falls through silently "
        "rather than reporting a provider that was configured and could not be reached",
    "HITL_WEBHOOK_URL":
        "no POST when a human-in-the-loop item queues; deploy.sh also defaults it empty, so this "
        "is the mildest entry here and is listed for completeness",
}


@needs_helm
@pytest.mark.parametrize("name", sorted(NOT_WIRED_BY_THE_CHART))
def test_each_recorded_gap_is_still_a_gap(name):
    """THREE FACTS PER ENTRY, so the list cannot contain a false claim: the application reads it,
    the Azure deployment sets it, and the chart does not. Closing a gap fails here until the entry
    is deleted — which is the only thing that stops a record of known problems from quietly
    becoming a record of solved ones."""
    assert name in _api_source(), f"{name} is no longer read by api/ — delete this entry"
    assert name in _deploy_source(), (
        f"{name} is no longer set by deploy/public/*.sh — delete this entry")
    assert name not in rendered_env_names(), (
        f"{name} is now rendered by the chart — delete this entry, the gap is closed")


def test_every_gap_says_what_its_absence_costs():
    """A list of names is a list nobody acts on. Each entry has to say what breaks, in the words a
    reader would need to decide whether it matters to them."""
    for name, why in NOT_WIRED_BY_THE_CHART.items():
        assert len(why) > 40, name
        assert not why.lower().startswith(("missing", "not set", "todo")), name
