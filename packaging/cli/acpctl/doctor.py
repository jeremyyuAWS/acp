"""`acpctl doctor` — can this cluster actually run what the chart is about to install?

THE COMMAND EXISTS FOR TWO SILENT FAILURES. Most misconfigurations announce themselves: a missing
Secret leaves pods in CreateContainerConfigError, a bad image gives ImagePullBackOff. Two do not,
and both are things the chart renders:

  * A `ScaledObject` in a cluster with no KEDA is an object nothing reconciles. No error, no
    event, no status. The worker tiers sit at their floor replica count and the queue grows, and
    the only symptom is autoscaling that never happens — which looks like ACP being slow.
  * A `NetworkPolicy` under a CNI that does not implement them is accepted by the API server and
    enforces nothing. No error, no status field saying "unenforced". A regulated installation can
    render every policy, pass review, and run with completely open pod networking.

Everything else here is ordinary preflight. Those two are the reason there is a command.

THREE OUTCOMES, NOT TWO. `pass`, `fail`, and `unknown` — and `unknown` is the one that makes the
report honest. A check that could not run has established nothing, and folding it into "pass"
because nothing went wrong is how a report comes to mean the opposite of what it says. An operator
reading `unknown: could not list nodes (forbidden)` knows to go and look; one reading a green tick
does not.

WHAT IT CANNOT DO. It cannot prove NetworkPolicy enforcement — no API reports it. It infers from
the CNI and says so in the finding text rather than implying certainty. And it does not connect to
Postgres, Redis or object storage: those live behind the cluster's network from acpctl's point of
view, and reaching them would mean shipping credentials to a laptop. The connection-budget rule in
`spec.py` is the static half of that question; the runtime half belongs to `acpctl status`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import cluster as cluster_mod

PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"
BLOCKER, WARNING, INFO = "blocker", "warning", "info"

# The oldest Kubernetes the chart's API versions work on. policy/v1 PodDisruptionBudget and
# autoscaling/v2 HorizontalPodAutoscaler both went stable in 1.21 and 1.23 respectively, so 1.23
# is the floor at which everything this chart renders exists as a stable API.
MINIMUM_KUBERNETES = (1, 23)

# CNIs known to implement NetworkPolicy, by the DaemonSet name they run in kube-system. This is
# an INFERENCE and the finding says so: the list cannot be exhaustive, a cluster may run something
# it does not name, and a CNI can be present but configured with policy disabled.
ENFORCING_CNI_DAEMONSETS = {
    "calico-node": "Calico",
    "cilium": "Cilium",
    "aws-node": "the Amazon VPC CNI",          # enforces only with the network-policy agent on
    "azure-cni": "Azure CNI",
    "azure-npm": "the Azure Network Policy Manager",
    "kube-router": "kube-router",
    "antrea-agent": "Antrea",
    "weave-net": "Weave Net",
}

# CNIs that are known NOT to enforce NetworkPolicy. Naming them is the whole value: "we could not
# tell" and "we can see that it will not work" are different reports.
NON_ENFORCING_CNI_DAEMONSETS = {
    "kube-flannel-ds": "Flannel",
    "kube-flannel": "Flannel",
}


@dataclass
class Check:
    """One question, its answer, and what to do about it.

    `remedy` is not decoration. A finding that says "KEDA is not installed" leaves the operator to
    search; one that names the Helm command turns the report into the next action, which is the
    difference between a tool that diagnoses and a tool that helps.
    """

    id: str
    status: str
    severity: str
    detail: str
    remedy: str = ""

    def render(self) -> str:
        mark = {PASS: "PASS", FAIL: "FAIL", UNKNOWN: "????"}[self.status]
        line = f"  [{mark}] {self.id}: {self.detail}"
        if self.remedy and self.status != PASS:
            line += f"\n         -> {self.remedy}"
        return line

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "status": self.status, "severity": self.severity,
                "detail": self.detail, "remedy": self.remedy}


def _has_api(facts: cluster_mod.ClusterFacts, *names: str) -> bool | None:
    """Is any of these API resources or groups served? None when the list could not be read.

    MATCHES A RESOURCE NAME **OR** A GROUP, and the distinction is a bug this had before the
    demo output caught it. `kubectl api-resources -o name` prints `<plural>.<group>`:

        scaledobjects.keda.sh          <- a resource name; asking for it works directly
        pods.custom.metrics.k8s.io     <- the GROUP is custom.metrics.k8s.io

    Asking for the group `custom.metrics.k8s.io` with a prefix test therefore never matched, and
    the check reported the API missing on every cluster including one that served it. The test for
    that check still passed, because it only asserted the failure case — a check that is always
    wrong in one direction looks exactly like a check that is right about a broken cluster. It
    took printing the report against a KNOWN-GOOD fixture to see it, which is the argument for
    reading a tool's real output rather than only its assertions.
    """
    if facts.api_resources is None:
        return None
    return any(r == n or r.startswith(f"{n}.") or r.endswith(f".{n}")
               for n in names for r in facts.api_resources)


def _cpu_to_millis(text: str) -> int:
    text = str(text).strip()
    if text.endswith("m"):
        return int(float(text[:-1]))
    return int(float(text) * 1000)


def _memory_to_bytes(text: str) -> int:
    text = str(text).strip()
    units = {"Ki": 1024, "Mi": 1024**2, "Gi": 1024**3, "Ti": 1024**4,
             "K": 1000, "M": 1000**2, "G": 1000**3, "T": 1000**4}
    for suffix, factor in units.items():
        if text.endswith(suffix):
            return int(float(text[: -len(suffix)]) * factor)
    return int(float(text))


def _requested_floor(values: dict) -> tuple[int, int]:
    """CPU millicores and bytes of memory the installation needs at its MINIMUM replica counts.

    The floor, not the ceiling, and the choice matters. A cluster that cannot fit the minimum
    cannot install at all — pods stay Pending — which is a blocker. A cluster that cannot fit the
    maximum merely cannot autoscale all the way, which is a warning about headroom and is
    reported separately. Conflating them would either block installs that are fine or wave
    through ones that cannot start.
    """
    cpu = memory = 0
    tiers = [values.get("api", {})] + list((values.get("workers") or {}).values())
    for tier in tiers:
        requests = (tier.get("resources") or {}).get("requests") or {}
        replicas = int(tier.get("replicaCount") or 0)
        if not requests or not replicas:
            continue
        cpu += _cpu_to_millis(requests.get("cpu", "0")) * replicas
        memory += _memory_to_bytes(requests.get("memory", "0")) * replicas
    return cpu, memory


def _allocatable(facts: cluster_mod.ClusterFacts) -> tuple[int, int]:
    cpu = memory = 0
    for node in facts.nodes or []:
        alloc = (node.get("status") or {}).get("allocatable") or {}
        cpu += _cpu_to_millis(alloc.get("cpu", "0"))
        memory += _memory_to_bytes(alloc.get("memory", "0"))
    return cpu, memory


def _gib(n: int) -> str:
    return f"{n / 1024**3:.1f}Gi"


# ── the checks ────────────────────────────────────────────────────────────────

def check_version(facts) -> Check:
    if facts.server_version is None:
        return Check("cluster.version", UNKNOWN, WARNING,
                     f"could not read the server version (kubectl said {facts.version_text!r})",
                     "Run `kubectl version -o json` and check the serverVersion block.")
    if facts.server_version < MINIMUM_KUBERNETES:
        want = ".".join(str(n) for n in MINIMUM_KUBERNETES)
        return Check("cluster.version", FAIL, BLOCKER,
                     f"Kubernetes {facts.version_text} is older than {want}",
                     f"The chart renders policy/v1 and autoscaling/v2 objects, which need "
                     f"{want} or newer. Upgrade the cluster.")
    return Check("cluster.version", PASS, INFO, f"Kubernetes {facts.version_text}")


def check_namespace(facts, namespace: str) -> Check:
    if facts.namespace_exists is None:
        return Check("cluster.namespace", UNKNOWN, WARNING, f"could not check namespace {namespace!r}")
    if not facts.namespace_exists:
        return Check("cluster.namespace", FAIL, WARNING,
                     f"namespace {namespace!r} does not exist",
                     f"kubectl create namespace {namespace} — or pass --create-namespace to helm.")
    return Check("cluster.namespace", PASS, INFO, f"namespace {namespace!r} exists")


def check_keda(facts, values: dict) -> Check | None:
    """ONE OF THE TWO SILENT FAILURES. Skipped entirely when no tier uses the KEDA scaler, because
    a check that does not apply is noise, and noise is what makes a report stop being read."""
    users = [name for name, tier in (values.get("workers") or {}).items()
             if (tier.get("autoscaling") or {}).get("enabled")
             and (tier.get("autoscaling") or {}).get("scaler") == "keda"]
    if not users:
        return None
    present = _has_api(facts, "scaledobjects.keda.sh")
    if present is None:
        return Check("keda.installed", UNKNOWN, BLOCKER,
                     "could not list the cluster's API resources, so KEDA's presence is unknown",
                     "Without KEDA the ScaledObjects are inert and the worker tiers never scale "
                     "— and nothing reports it. Check by hand: kubectl get crd scaledobjects.keda.sh")
    if not present:
        return Check("keda.installed", FAIL, BLOCKER,
                     f"KEDA is not installed, and {len(users)} worker tier(s) "
                     f"({', '.join(sorted(users))}) are configured to scale on queue depth",
                     "Install KEDA (helm repo add kedacore https://kedacore.github.io/charts && "
                     "helm install keda kedacore/keda -n keda --create-namespace). Until then the "
                     "ScaledObjects apply cleanly and do NOTHING: the tiers stay at their minimum "
                     "replica count while the queue grows, with no error anywhere.")
    return Check("keda.installed", PASS, INFO,
                 f"KEDA is present for {len(users)} autoscaled worker tier(s)")


def check_network_policy(facts, values: dict) -> Check | None:
    """THE OTHER SILENT FAILURE, and the one that cannot be proven.

    No Kubernetes API reports whether NetworkPolicy is enforced. The API server accepts the
    objects regardless; whether anything acts on them is a property of the CNI. So this INFERS
    from what is running in kube-system, and the finding says it is an inference — a check that
    overstates its certainty about a security control is worse than no check, because it ends the
    investigation.
    """
    if not (values.get("networkPolicy") or {}).get("enabled"):
        return None
    if facts.kube_system_daemonsets is None:
        return Check("networkpolicy.enforcement", UNKNOWN, WARNING,
                     "could not list kube-system daemonsets, so the CNI is unknown",
                     "NetworkPolicy objects are accepted by every cluster and enforced only by "
                     "some CNIs. Confirm yours implements them.")
    found = [name for name in facts.kube_system_daemonsets if name in ENFORCING_CNI_DAEMONSETS]
    known_bad = [name for name in facts.kube_system_daemonsets if name in NON_ENFORCING_CNI_DAEMONSETS]
    if known_bad:
        which = ", ".join(sorted({NON_ENFORCING_CNI_DAEMONSETS[n] for n in known_bad}))
        return Check("networkpolicy.enforcement", FAIL, BLOCKER,
                     f"{which} does not implement NetworkPolicy, and this deployment renders "
                     f"policies that would therefore enforce nothing",
                     "The objects will apply cleanly and pod networking will stay fully open, "
                     "with nothing reporting it. Either install a policy-capable CNI, or set "
                     "network.privateWorkers/publicIngress knowingly and record that pod-level "
                     "isolation is not in place.")
    if found:
        which = ", ".join(sorted({ENFORCING_CNI_DAEMONSETS[n] for n in found}))
        return Check("networkpolicy.enforcement", PASS, INFO,
                     f"{which} is running, which implements NetworkPolicy "
                     f"(inferred from kube-system — enforcement itself has no API to query)")
    return Check("networkpolicy.enforcement", UNKNOWN, WARNING,
                 "no CNI this tool recognises is running in kube-system, so whether the rendered "
                 "NetworkPolicies are enforced could not be established",
                 "Enforcement has no API to query. Confirm your CNI implements NetworkPolicy — "
                 "if it does not, the policies apply cleanly and do nothing.")


def check_external_secrets(facts, values: dict, namespace: str) -> list[Check]:
    external = (values.get("secrets") or {}).get("externalSecrets") or {}
    if not external.get("enabled"):
        return []
    checks: list[Check] = []
    present = _has_api(facts, "externalsecrets.external-secrets.io", "secretstores.external-secrets.io")
    if present is None:
        checks.append(Check("externalsecrets.installed", UNKNOWN, BLOCKER,
                            "could not list API resources, so the External Secrets Operator's "
                            "presence is unknown"))
        return checks
    if not present:
        checks.append(Check(
            "externalsecrets.installed", FAIL, BLOCKER,
            f"the External Secrets Operator is not installed, and this deployment resolves its "
            f"connection details through {(values.get('secrets') or {}).get('provider')}",
            "Install it (helm repo add external-secrets https://charts.external-secrets.io && "
            "helm install external-secrets external-secrets/external-secrets -n external-secrets "
            "--create-namespace). Without it the ExternalSecret never syncs, the Secret is never "
            "created, and every pod stays in CreateContainerConfigError."))
        return checks
    checks.append(Check("externalsecrets.installed", PASS, INFO,
                        "the External Secrets Operator is present"))

    wanted = external.get("secretStoreRef") or ""
    if not wanted:
        # A REAL GAP IN THE CONTRACT, reported as what it is rather than papered over. The
        # deployment document has no field naming the SecretStore, so the chart falls back to a
        # name derived from the HELM RELEASE NAME — which acpctl does not know, because the
        # release name is chosen at `helm install` time and appears nowhere in the document.
        #
        # Guessing it would mean duplicating the chart's `acp.fullname` logic here, where it
        # would drift. Listing what the namespace actually holds is worth more anyway: the
        # operator can see whether their store is there and match it themselves, and the answer
        # stays correct however the chart names things.
        present = (", ".join(sorted(facts.secret_stores)) if facts.secret_stores
                   else "none" if facts.secret_stores is not None else "could not list")
        checks.append(Check(
            "externalsecrets.store", UNKNOWN, WARNING,
            "the deployment document cannot name a SecretStore, so the chart derives one from "
            f"the Helm release name — which is chosen at install time. SecretStores in "
            f"{namespace!r}: {present}",
            "Check that one of those is the store the release will name (the chart's default is "
            "<release>-acp-store), or pass --set secrets.externalSecrets.secretStoreRef at "
            "install time to name it explicitly."))
    elif facts.secret_stores is None:
        checks.append(Check("externalsecrets.store", UNKNOWN, WARNING,
                            f"could not list SecretStores in {namespace!r}"))
    elif wanted not in facts.secret_stores:
        checks.append(Check(
            "externalsecrets.store", FAIL, BLOCKER,
            f"SecretStore {wanted!r} does not exist in namespace {namespace!r}",
            f"Create it, pointing at your "
            f"{(values.get('secrets') or {}).get('provider')} backend. The ExternalSecret names "
            f"this store and will not sync without it."))
    else:
        checks.append(Check("externalsecrets.store", PASS, INFO,
                            f"SecretStore {wanted!r} exists in {namespace!r}"))
    return checks


def check_ingress(facts, values: dict) -> Check | None:
    ingress = values.get("ingress") or {}
    if not ingress.get("enabled"):
        return None
    wanted = ingress.get("className") or ""
    if facts.ingress_classes is None:
        return Check("ingress.class", UNKNOWN, WARNING, "could not list IngressClasses")
    if not facts.ingress_classes:
        return Check("ingress.class", FAIL, BLOCKER,
                     "the cluster has no IngressClass, so nothing will serve the rendered Ingress",
                     "Install an ingress controller (ingress-nginx, or your cloud's) before "
                     "installing ACP, or set network.publicIngress to false.")
    if wanted and wanted not in facts.ingress_classes:
        return Check("ingress.class", FAIL, BLOCKER,
                     f"IngressClass {wanted!r} does not exist "
                     f"(available: {', '.join(sorted(facts.ingress_classes))})",
                     "An Ingress naming a class no controller owns is never reconciled, and the "
                     "hostname simply does not resolve to ACP.")
    return Check("ingress.class", PASS, INFO,
                 f"IngressClass available: {', '.join(sorted(facts.ingress_classes))}")


def check_metrics(facts, values: dict) -> list[Check]:
    api = values.get("api") or {}
    autoscaling = api.get("autoscaling") or {}
    if not autoscaling.get("enabled"):
        return []
    triggers = autoscaling.get("triggers") or []
    checks: list[Check] = []
    if "cpu" in triggers:
        present = _has_api(facts, "nodes.metrics.k8s.io", "pods.metrics.k8s.io")
        if present is None:
            checks.append(Check("metrics.server", UNKNOWN, WARNING,
                                "could not list API resources, so metrics-server is unknown"))
        elif not present:
            checks.append(Check(
                "metrics.server", FAIL, BLOCKER,
                "the API's HPA scales on CPU but metrics.k8s.io is not served",
                "Install metrics-server. Without it the HPA reports FailedGetResourceMetric and "
                "holds the replica count wherever it was."))
        else:
            checks.append(Check("metrics.server", PASS, INFO, "metrics.k8s.io is served"))
    if "concurrent-requests" in triggers:
        present = _has_api(facts, "custom.metrics.k8s.io")
        if present is None:
            checks.append(Check("metrics.custom", UNKNOWN, WARNING,
                                "could not list API resources, so the custom metrics API is unknown"))
        elif not present:
            checks.append(Check(
                "metrics.custom", FAIL, WARNING,
                "the API's HPA scales on `concurrent-requests`, a custom metric, but "
                "custom.metrics.k8s.io is not served",
                "Install a metrics adapter that publishes acp_concurrent_requests, or drop that "
                "trigger and scale on CPU alone. Unlike the KEDA case this one is visible: the "
                "HPA reports FailedGetPodsMetric in its status."))
        else:
            checks.append(Check("metrics.custom", PASS, INFO, "custom.metrics.k8s.io is served"))
    return checks


def check_capacity(facts, values: dict) -> Check:
    if facts.nodes is None:
        return Check("capacity.floor", UNKNOWN, WARNING,
                     "could not list nodes, so schedulable capacity is unknown")
    want_cpu, want_mem = _requested_floor(values)
    have_cpu, have_mem = _allocatable(facts)
    if not have_cpu:
        return Check("capacity.floor", UNKNOWN, WARNING, "the cluster reported no allocatable CPU")
    short = []
    if want_cpu > have_cpu:
        short.append(f"CPU (needs {want_cpu}m, cluster has {have_cpu}m allocatable)")
    if want_mem > have_mem:
        short.append(f"memory (needs {_gib(want_mem)}, cluster has {_gib(have_mem)} allocatable)")
    if short:
        return Check("capacity.floor", FAIL, BLOCKER,
                     "the cluster cannot fit ACP at its MINIMUM replica counts: " + "; ".join(short),
                     "Pods will stay Pending. Add nodes, or lower the replica floors in the "
                     "deployment document. Note this compares against total allocatable across "
                     "all nodes and ignores what is already running, so the real shortfall is "
                     "larger than this.")
    return Check("capacity.floor", PASS, INFO,
                 f"the floor fits: needs {want_cpu}m CPU / {_gib(want_mem)}, "
                 f"cluster has {have_cpu}m / {_gib(have_mem)} allocatable "
                 f"(total, ignoring existing workloads)")


def check_read_failures(facts) -> list[Check]:
    """Anything kubectl refused, reported rather than dropped.

    A check that silently did not run is the shape this whole command exists to eliminate; that
    applies to the command's own gaps too.
    """
    return [Check(f"read.{label.replace(' ', '-')}", UNKNOWN, WARNING,
                  f"could not read {label}: {reason}",
                  "Checks depending on this were not performed. Usually a missing RBAC "
                  "permission for your kubeconfig user.")
            for label, reason in sorted(facts.read_failures.items())]


def diagnose(values: dict, facts: cluster_mod.ClusterFacts, *, namespace: str) -> dict[str, Any]:
    """Every check, against one rendered values document and one cluster."""
    if not facts.reachable:
        return {
            "reachable": False,
            "namespace": namespace,
            "checks": [Check("cluster.reachable", UNKNOWN, BLOCKER,
                             facts.unreachable_reason or "the cluster could not be reached",
                             "Nothing below could be checked. This is not a pass.").as_dict()],
            "blockers": 1, "warnings": 0, "unknown": 1, "ok": False,
        }

    checks: list[Check] = [check_version(facts), check_namespace(facts, namespace)]
    for maybe in (check_keda(facts, values),
                  check_network_policy(facts, values),
                  check_ingress(facts, values)):
        if maybe is not None:
            checks.append(maybe)
    checks += check_external_secrets(facts, values, namespace)
    checks += check_metrics(facts, values)
    checks.append(check_capacity(facts, values))
    checks += check_read_failures(facts)

    blockers = [c for c in checks if c.status == FAIL and c.severity == BLOCKER]
    unknown_blockers = [c for c in checks if c.status == UNKNOWN and c.severity == BLOCKER]
    warnings = [c for c in checks if c.status in (FAIL, UNKNOWN) and c.severity != BLOCKER]
    return {
        "reachable": True,
        "namespace": namespace,
        "kubernetes": facts.version_text,
        "checks": [c.as_dict() for c in checks],
        "blockers": len(blockers),
        "unknown": len([c for c in checks if c.status == UNKNOWN]),
        "warnings": len(warnings),
        # AN UNKNOWN BLOCKER IS NOT OK. The check that could not run is precisely the one whose
        # failure would otherwise be silent, so treating "we could not tell whether KEDA is
        # installed" as a pass reproduces the exact bug this command was written to catch.
        "ok": not blockers and not unknown_blockers,
    }
