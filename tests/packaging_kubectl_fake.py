"""A fake `kubectl` on PATH, so doctor's checks can be tested against many cluster shapes.

WHY A FAKE AND NOT A REAL CLUSTER. `kind` needs a Docker daemon, which CI's runner does not give
the backend job, and one kind cluster could only ever be ONE shape. The interesting cases are the
absences — no KEDA, Flannel instead of Calico, an unreadable API list, a cluster too small — and
each is a different cluster. A fixture per shape covers them all; a real cluster covers one.

WHAT THIS DOES NOT PROVE, stated plainly because it is the limitation that matters: these fixtures
are what kubectl's output is DOCUMENTED to look like, not a recording of a specific cluster. They
test acpctl's logic and its parsing, not that a real kubectl agrees with the fixtures. The
mitigation is to keep the parsed surface tiny — seven commands, each read for a handful of fields,
all of them long-stable parts of kubectl's JSON — and `parse_version` in particular is fed the
real-world variants (GKE's "29+", EKS's patched builds) rather than only the clean case.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

# A cluster with everything ACP's standard profile needs. Individual tests take this and remove
# exactly one thing, which is the same shape as the packaging validate tests: break one thing,
# assert the one finding.
HEALTHY = {
    "server_version": {"major": "1", "minor": "29", "gitVersion": "v1.29.4"},
    "api_resources": [
        "pods", "nodes", "namespaces", "deployments.apps", "daemonsets.apps",
        "ingressclasses.networking.k8s.io", "networkpolicies.networking.k8s.io",
        "poddisruptionbudgets.policy", "horizontalpodautoscalers.autoscaling",
        "scaledobjects.keda.sh", "triggerauthentications.keda.sh",
        "externalsecrets.external-secrets.io", "secretstores.external-secrets.io",
        "nodes.metrics.k8s.io", "pods.metrics.k8s.io",
        "pods.custom.metrics.k8s.io",
        "storageclasses.storage.k8s.io",
    ],
    # 3 x 8 CPU / 32Gi. The standard profile's floor is 15 CPU / 30Gi, so this fits with room.
    "nodes": [{"cpu": "8", "memory": "32Gi"} for _ in range(3)],
    "kube_system_daemonsets": ["kube-proxy", "calico-node"],
    "ingress_classes": ["nginx"],
    "storage_classes": ["managed-csi"],
    "namespace_exists": True,
    "secret_stores": ["acp-production-acp-store"],
    # Commands the fake should fail, as {label: stderr}. Used for the "could not read" paths.
    "deny": {},
    # ── what `acpctl status` reads: a running installation ────────────────────
    #
    # Shaped to match the standard-production example: an api tier autoscaled 2-4, two worker
    # tiers autoscaled by KEDA, and ASSESS PINNED WARM at 5 (the owner's 2026-09-05 parity
    # decision — packaging/docs/azure-parity.md). `replicas: null` means the Deployment has NO
    # spec.replicas, which is what the chart renders for an autoscaled tier; a NUMBER means the
    # chart pinned it. That distinction is the whole of what status judges replica drift on, so
    # the healthy fixture has to carry one of each — a fixture where every tier autoscales cannot
    # tell a correct fixed-tier check from one that never runs.
    "release": "2026.9",
    "profile": "standard",
    "platform": "azure",
    "deployments": [
        {"name": "acp-api", "component": "api", "role": None, "replicas": None, "ready": 2},
        {"name": "acp-worker-discover", "component": "worker", "role": "discovery",
         "replicas": None, "ready": 1},
        {"name": "acp-worker-assess", "component": "worker", "role": "assess",
         "replicas": 5, "ready": 5},
        # 5, not 3: the standard-production document raised this tier's FLOOR to 5 on 2026-09-05
        # to match the five replicas production keeps warm. A "healthy, matching" fixture running
        # 3 would sit below the floor, and `acpctl status` correctly called it drift — which is
        # the check doing its job, not a fixture that needed loosening.
        {"name": "acp-worker-remediate", "component": "worker", "role": "remediate",
         "replicas": None, "ready": 5},
    ],
    # Each entry: {name, phase, containers: [{ready, restarts, waiting_reason, message}]}
    "pods": [],
    "jobs": [],
    # No ScaledObject for assess: it is pinned, and status reports a scaler on a tier the
    # document does not autoscale as its own kind of drift.
    "scaled_objects": ["acp-worker-discover", "acp-worker-remediate"],
}


def shape(**overrides) -> dict:
    """HEALTHY with specific keys replaced. `shape(api_resources=[...])` reads better at the call
    site than a deepcopy-and-mutate, and keeps each test's deviation on one line."""
    out = json.loads(json.dumps(HEALTHY))
    out.update(overrides)
    return out


def without_api(*prefixes: str) -> dict:
    """A cluster serving everything except the named API groups."""
    kept = [r for r in HEALTHY["api_resources"]
            if not any(r.startswith(p) for p in prefixes)]
    return shape(api_resources=kept)


_SCRIPT = '''#!/usr/bin/env python3
"""Fake kubectl. Answers from a fixture; refuses anything acpctl should never run."""
import json, os, sys

fixture = json.load(open(os.environ["ACP_FAKE_KUBECTL_FIXTURE"]))
args = [a for a in sys.argv[1:]]

# Record every invocation, so a test can assert WHAT was run — including that nothing mutating
# was attempted. A read-only promise nobody checks is a comment.
log = os.environ.get("ACP_FAKE_KUBECTL_LOG")
if log:
    with open(log, "a") as fh:
        fh.write(" ".join(args) + "\\n")

# Strip global flags acpctl may pass.
while args and args[0] == "--context":
    args = args[2:]

verb = args[0] if args else ""

def out(payload):
    print(json.dumps(payload))
    sys.exit(0)

def fail(message):
    print(message, file=sys.stderr)
    sys.exit(1)

deny = fixture.get("deny") or {}

if verb == "version":
    if "version" in deny:
        fail(deny["version"])
    server = fixture.get("server_version")
    payload = {"clientVersion": {"major": "1", "minor": "29", "gitVersion": "v1.29.4"}}
    if server is not None:
        payload["serverVersion"] = server
    out(payload)

if verb == "api-resources":
    if "api-resources" in deny:
        fail(deny["api-resources"])
    print("\\n".join(fixture.get("api_resources") or []))
    sys.exit(0)

if verb == "get":
    what = args[1] if len(args) > 1 else ""
    if what in deny:
        fail(deny[what])
    if what == "nodes":
        out({"items": [
            {"metadata": {"name": f"node-{i}"},
             "status": {"allocatable": {"cpu": n["cpu"], "memory": n["memory"]}}}
            for i, n in enumerate(fixture.get("nodes") or [])]})
    if what == "daemonsets":
        names = fixture.get("kube_system_daemonsets")
        if names is None:
            fail("daemonsets is forbidden")
        out({"items": [{"metadata": {"name": n}} for n in names]})
    if what == "ingressclasses":
        out({"items": [{"metadata": {"name": n}}
                       for n in (fixture.get("ingress_classes") or [])]})
    if what == "storageclasses":
        out({"items": [{"metadata": {"name": n}}
                       for n in (fixture.get("storage_classes") or [])]})
    if what == "secretstores":
        out({"items": [{"metadata": {"name": n}}
                       for n in (fixture.get("secret_stores") or [])]})
    if what == "deployments":
        items = []
        for d in fixture.get("deployments") or []:
            spec = {"template": {"spec": {"containers": [
                {"name": "c", "image": f"reg.example.org/acp:{fixture.get('release', '0')}"}]}}}
            # ABSENT, not zero, when an autoscaler owns the count — the chart omits the field.
            if d.get("replicas") is not None:
                spec["replicas"] = d["replicas"]
            items.append({
                "metadata": {"name": d["name"], "labels": {
                    "app.kubernetes.io/part-of": "acp",
                    "app.kubernetes.io/component": d["component"],
                    "app.kubernetes.io/version": d.get("version", fixture.get("release", "0")),
                    "acp.mova.io/profile": d.get("profile", fixture.get("profile", "standard")),
                    "acp.mova.io/platform": d.get("platform", fixture.get("platform", "azure")),
                    **({"acp.mova.io/worker-role": d["role"]} if d.get("role") else {}),
                }},
                "spec": spec,
                "status": {"readyReplicas": d.get("ready", 0),
                           "availableReplicas": d.get("ready", 0),
                           "updatedReplicas": d.get("ready", 0)},
            })
        out({"items": items})
    if what == "pods":
        items = []
        for pod in fixture.get("pods") or []:
            statuses = []
            for c in pod.get("containers") or []:
                state = {}
                if c.get("waiting_reason"):
                    state["waiting"] = {"reason": c["waiting_reason"],
                                        "message": c.get("message", "")}
                statuses.append({"name": "c", "ready": c.get("ready", True),
                                 "restartCount": c.get("restarts", 0), "state": state})
            items.append({
                "metadata": {"name": pod["name"], "labels": {"app.kubernetes.io/part-of": "acp"}},
                "status": {"phase": pod.get("phase", "Running"),
                           "containerStatuses": statuses,
                           "conditions": pod.get("conditions") or []},
            })
        out({"items": items})
    if what == "jobs":
        out({"items": [
            {"metadata": {"name": j["name"], "labels": {
                "app.kubernetes.io/part-of": "acp",
                "app.kubernetes.io/component": j.get("component", "migrations")}},
             "status": {k: j[k] for k in ("succeeded", "failed", "active") if k in j}}
            for j in (fixture.get("jobs") or [])]})
    if what == "scaledobjects":
        out({"items": [{"metadata": {"name": n}}
                       for n in (fixture.get("scaled_objects") or [])]})
    if what == "namespace":
        if fixture.get("namespace_exists"):
            out({"metadata": {"name": args[2] if len(args) > 2 else "?"}})
        fail("Error from server (NotFound): namespaces \\"x\\" not found")
    fail(f"fake kubectl: no fixture for `get {what}`")

# ANYTHING ELSE IS A MUTATION acpctl must never attempt. Failing loudly here means a future
# change that starts writing shows up as a test failure rather than as a changed cluster.
fail(f"fake kubectl: refusing non-read verb {verb!r} — acpctl must not mutate a cluster")
'''


def install(tmp_path: Path, fixture: dict) -> dict[str, str]:
    """Write a fake kubectl into `tmp_path` and return the env that activates it."""
    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    script = bindir / "kubectl"
    script.write_text(_SCRIPT, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    fixture_path = tmp_path / "fixture.json"
    fixture_path.write_text(json.dumps(fixture), encoding="utf-8")

    return {
        "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}",
        "ACP_FAKE_KUBECTL_FIXTURE": str(fixture_path),
        "ACP_FAKE_KUBECTL_LOG": str(tmp_path / "kubectl.log"),
    }
