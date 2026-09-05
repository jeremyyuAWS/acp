"""Reading a live cluster — the only part of acpctl that leaves the machine.

WHY kubectl AND NOT A KUBERNETES CLIENT LIBRARY. acpctl ships in the air-gapped bundle (PRD §17)
and deliberately has almost no dependencies: PyYAML for documents, and otherwise the standard
library. `kubernetes` would pull in urllib3, requests, google-auth and a certificate story, and it
would need its own answer to every auth plugin (`exec` credentials, cloud IAM) that kubectl
already solves. An operator installing ACP with Helm has kubectl. Shelling out to the tool they
already trust for cluster access is smaller, and it inherits their kubeconfig, context and
credentials exactly.

READ-ONLY IS ENFORCED HERE, NOT PROMISED IN A DOCSTRING. Phase 0 kept acpctl honest by patching
`open` in a test — a guard that can see file writes and cannot see a subprocess. Introducing a
cluster connection would have walked straight past it, so the verb allow-list below is the
replacement: every kubectl invocation goes through `run()`, and `run()` refuses anything that is
not a read. PRD §22 forbids exposing infrastructure mutation before RBAC and audit logging exist,
and "doctor accidentally grew a --fix flag" is exactly how that rule gets broken by degrees.

WHAT THIS MODULE DOES NOT DO: interpret. It gathers facts and hands them to doctor.py, which
decides what they mean. The split is what lets the decisions be tested without a cluster, and it
keeps the surface that depends on kubectl's exact output as small as it can be — seven commands,
each parsed for a handful of fields.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

# kubectl verbs acpctl may use. Reads only — and the list is short so that adding to it is a
# visible act rather than a habit.
#
# `version` and `api-resources` are here because they are how the cluster describes itself;
# `get` is the only one that touches objects. Everything that changes a cluster — apply, create,
# delete, patch, edit, scale, annotate, label, rollout, exec, cp, drain, cordon — is absent, and
# absent is enforced rather than assumed (see run()).
READ_VERBS = frozenset({"version", "api-resources", "get"})

# A cluster that does not answer in this long is not a cluster acpctl should keep waiting on: the
# operator is at a terminal expecting a report, and a hung doctor is worse than a stated timeout.
TIMEOUT_SECONDS = 30


class ClusterUnavailable(RuntimeError):
    """kubectl is missing, or the cluster did not answer.

    Distinct from "the check failed": a check that could not RUN has not established anything,
    and reporting it as a pass is the failure mode this whole command exists to prevent.
    """


class ForbiddenVerb(RuntimeError):
    """A caller tried to run something that is not a read. Never raised in normal operation; it
    is a programming error, caught loudly so a future edit cannot quietly make acpctl a tool that
    changes clusters."""


@dataclass
class ClusterFacts:
    """Everything doctor.py is allowed to reason about.

    Every field has a "not known" representation distinct from "known to be empty", because the
    two lead to opposite conclusions: no KEDA API means the scalers will not work, while an
    unreadable API list means we cannot say whether they will.
    """

    reachable: bool = False
    unreachable_reason: str = ""
    server_version: tuple[int, int] | None = None
    version_text: str = ""
    api_resources: frozenset[str] | None = None
    nodes: list[dict] | None = None
    kube_system_daemonsets: list[str] | None = None
    ingress_classes: list[str] | None = None
    namespace_exists: bool | None = None
    secret_stores: list[str] | None = None
    storage_classes: list[str] | None = None
    # Commands that failed for a reason other than the cluster being unreachable — a permission
    # error on one resource, say. Kept so doctor can report "not checked, and here is why"
    # instead of silently omitting a check.
    read_failures: dict[str, str] = field(default_factory=dict)


def kubectl_available() -> bool:
    return shutil.which("kubectl") is not None


def run(args: list[str], *, context: str | None = None, timeout: int = TIMEOUT_SECONDS
        ) -> subprocess.CompletedProcess:
    """Invoke kubectl for a READ. Raises ForbiddenVerb for anything else.

    The check is on the first non-flag argument, which is where kubectl's verb goes. A caller
    passing `["--context", "x", "delete", ...]` is caught too, which is why the scan skips flags
    rather than looking only at args[0].
    """
    verb = next((a for a in args if not a.startswith("-")), None)
    if verb not in READ_VERBS:
        raise ForbiddenVerb(
            f"acpctl may only run kubectl reads ({', '.join(sorted(READ_VERBS))}); "
            f"refused {verb!r}. acpctl provisions nothing — see PRD S22 and ADR 0048.")
    if not kubectl_available():
        raise ClusterUnavailable("kubectl is not on PATH")
    cmd = ["kubectl"]
    if context:
        cmd += ["--context", context]
    cmd += args
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ClusterUnavailable(f"kubectl timed out after {timeout}s: {' '.join(args)}") from exc
    except OSError as exc:
        raise ClusterUnavailable(f"could not run kubectl: {exc}") from exc


def _json(args: list[str], *, context: str | None, facts: ClusterFacts, label: str) -> Any | None:
    """A read whose failure is RECORDED rather than raised.

    One unreadable resource must not abort the report — an operator with permission to read nodes
    but not SecretStores should still learn everything else about their cluster, and be told
    which check did not run. That is the difference between a partial report and a wrong one.
    """
    proc = run(args, context=context)
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "").strip().splitlines()
        facts.read_failures[label] = message[0] if message else f"kubectl exit {proc.returncode}"
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        facts.read_failures[label] = f"unparseable JSON from kubectl: {exc}"
        return None


def _parse_version(payload: dict) -> tuple[tuple[int, int] | None, str]:
    """major/minor out of `kubectl version -o json`.

    Minor arrives as "29", "29+" or "29.1" depending on the distribution — GKE and EKS both
    append a "+" to signal a patched build. Stripping to the leading digits is what makes this
    work on a managed cluster rather than only on kind.
    """
    server = (payload or {}).get("serverVersion") or {}
    raw_major, raw_minor = str(server.get("major", "")), str(server.get("minor", ""))
    digits_major = "".join(c for c in raw_major if c.isdigit())
    digits_minor = "".join(c for c in raw_minor.split(".")[0] if c.isdigit())
    text = server.get("gitVersion") or f"{raw_major}.{raw_minor}"
    if not digits_major or not digits_minor:
        return None, text
    return (int(digits_major), int(digits_minor)), text


def gather(*, namespace: str, context: str | None = None) -> ClusterFacts:
    """Everything doctor needs, in as few calls as the questions allow."""
    facts = ClusterFacts()

    if not kubectl_available():
        facts.unreachable_reason = (
            "kubectl is not on PATH. acpctl reads a cluster through kubectl so that it inherits "
            "your kubeconfig, context and credentials; install it, or run `acpctl validate` and "
            "`acpctl plan` instead, which need no cluster.")
        return facts

    version_proc = run(["version", "-o", "json"], context=context)
    if version_proc.returncode != 0:
        facts.unreachable_reason = (version_proc.stderr or version_proc.stdout).strip() \
            or "kubectl could not reach the cluster"
        return facts
    try:
        payload = json.loads(version_proc.stdout)
    except json.JSONDecodeError as exc:
        facts.unreachable_reason = f"kubectl version returned unparseable JSON: {exc}"
        return facts
    if "serverVersion" not in payload:
        # kubectl answers with clientVersion alone when it cannot reach the API server. Treating
        # that as reachable would let every check below run against nothing and report an empty
        # cluster as a healthy one.
        facts.unreachable_reason = (
            "kubectl reported no server version, which means it could not reach the API server. "
            "Check your context and credentials.")
        return facts

    facts.reachable = True
    facts.server_version, facts.version_text = _parse_version(payload)

    resources = run(["api-resources", "-o", "name"], context=context)
    if resources.returncode == 0:
        facts.api_resources = frozenset(
            line.strip() for line in resources.stdout.splitlines() if line.strip())
    else:
        facts.read_failures["api-resources"] = (resources.stderr or "").strip() or "failed"

    nodes = _json(["get", "nodes", "-o", "json"], context=context, facts=facts, label="nodes")
    if nodes is not None:
        facts.nodes = nodes.get("items", [])

    daemonsets = _json(["get", "daemonsets", "-n", "kube-system", "-o", "json"],
                       context=context, facts=facts, label="kube-system daemonsets")
    if daemonsets is not None:
        facts.kube_system_daemonsets = [d["metadata"]["name"] for d in daemonsets.get("items", [])]

    classes = _json(["get", "ingressclasses", "-o", "json"],
                    context=context, facts=facts, label="ingressclasses")
    if classes is not None:
        facts.ingress_classes = [c["metadata"]["name"] for c in classes.get("items", [])]

    storage = _json(["get", "storageclasses", "-o", "json"],
                    context=context, facts=facts, label="storageclasses")
    if storage is not None:
        facts.storage_classes = [c["metadata"]["name"] for c in storage.get("items", [])]

    ns = run(["get", "namespace", namespace, "-o", "json"], context=context)
    facts.namespace_exists = ns.returncode == 0

    # Only ask about SecretStores when the CRD is there. Asking otherwise produces a confusing
    # "the server doesn't have a resource type" that reads as a permissions problem.
    if facts.api_resources and any(r.startswith("secretstores.") for r in facts.api_resources):
        stores = _json(["get", "secretstores", "-n", namespace, "-o", "json"],
                       context=context, facts=facts, label="secretstores")
        if stores is not None:
            facts.secret_stores = [s["metadata"]["name"] for s in stores.get("items", [])]

    return facts
