"""Reading a RUNNING ACP release — the facts `acpctl status` reasons about.

SEPARATE FROM cluster.py, AND THE SPLIT IS THE TWO COMMANDS' DIFFERENT QUESTIONS. `cluster.py`
gathers cluster-wide capabilities for `doctor`: does this cluster have KEDA, a policy-capable CNI,
enough nodes. This gathers what is deployed in ONE namespace under ONE release. A cluster that
passes doctor may have nothing installed; a healthy installation says nothing about whether the
cluster could take an upgrade. Keeping them apart keeps each command's reads to what it needs.

IT REUSES cluster.run(), WHICH IS THE POINT. That function holds the read-verb allow-list, so
every read here inherits the "acpctl provisions nothing" guarantee automatically. A second
subprocess helper would be a second place for that promise to not apply — which is exactly how
the phase-0 `open()` guard came to miss the kubectl path in the first place.

WHAT IDENTIFIES AN ACP INSTALLATION: `app.kubernetes.io/part-of=acp`, set by the chart's common
labels on every object it renders. Selecting on that rather than on a name prefix means an
operator who installed under a different release name is still found, and a coincidentally-named
Deployment from something else is not.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import cluster as cluster_mod

SELECTOR = "app.kubernetes.io/part-of=acp"


@dataclass
class Workload:
    """One Deployment, reduced to what status asks about."""

    name: str
    component: str                # api | worker | (whatever the chart labels it)
    role: str | None              # the worker role, for worker tiers
    version: str | None           # app.kubernetes.io/version — the release, not the image string
    profile: str | None           # acp.mova.io/profile — which deployment profile installed this
    platform: str | None          # acp.mova.io/platform
    image: str
    desired: int | None           # spec.replicas; ABSENT when an autoscaler owns it
    ready: int
    available: int
    updated: int
    conditions: list[dict] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        """Ready is what matters, and it is compared against the OBSERVED desired count rather
        than against the document. A tier the autoscaler has taken to 7 is healthy at 7/7; the
        question of whether 7 is the right number is drift, and belongs to the other half."""
        target = self.desired if self.desired is not None else self.ready
        return self.ready > 0 and self.ready >= target


@dataclass
class InstallationFacts:
    found: bool = False
    workloads: list[Workload] = field(default_factory=list)
    pods_not_ready: list[dict] = field(default_factory=list)
    migration_job: dict | None = None
    scaled_objects: list[str] | None = None
    read_failures: dict[str, str] = field(default_factory=dict)


def _label(obj: dict, key: str) -> str | None:
    return ((obj.get("metadata") or {}).get("labels") or {}).get(key)


def _workload(dep: dict) -> Workload:
    spec, status = dep.get("spec") or {}, dep.get("status") or {}
    containers = ((spec.get("template") or {}).get("spec") or {}).get("containers") or [{}]
    return Workload(
        name=(dep.get("metadata") or {}).get("name", "?"),
        component=_label(dep, "app.kubernetes.io/component") or "?",
        role=_label(dep, "acp.mova.io/worker-role"),
        version=_label(dep, "app.kubernetes.io/version"),
        profile=_label(dep, "acp.mova.io/profile"),
        platform=_label(dep, "acp.mova.io/platform"),
        image=containers[0].get("image", ""),
        # None, not 0, when the field is absent. The chart OMITS spec.replicas on an autoscaled
        # tier (setting both would make every upgrade reset the count to the floor), so absent
        # means "an autoscaler owns this" — a distinction that decides how drift is judged.
        desired=spec.get("replicas"),
        ready=int(status.get("readyReplicas") or 0),
        available=int(status.get("availableReplicas") or 0),
        updated=int(status.get("updatedReplicas") or 0),
        conditions=status.get("conditions") or [],
    )


def _unhealthy_pod(pod: dict) -> dict | None:
    """A pod worth reporting, with the reason a human needs — or None when it is fine.

    REPORTS THE CONTAINER-LEVEL REASON, not just the phase. `Running` with a container in
    CrashLoopBackOff is the single most common way an install is broken, and the pod phase alone
    calls that Running. An operator reading "1 pod Running" about a container restarting every
    thirty seconds has been told the opposite of what is happening.
    """
    meta, status = pod.get("metadata") or {}, pod.get("status") or {}
    name = meta.get("name", "?")
    phase = status.get("phase", "?")
    statuses = status.get("containerStatuses") or []
    restarts = sum(int(c.get("restartCount") or 0) for c in statuses)

    waiting = [c["state"]["waiting"] for c in statuses
               if (c.get("state") or {}).get("waiting")]
    if waiting:
        reason = waiting[0].get("reason") or "Waiting"
        return {"pod": name, "phase": phase, "reason": reason,
                "message": waiting[0].get("message") or "", "restarts": restarts}
    if phase == "Pending":
        # The scheduler's message is the useful part — "Insufficient cpu" tells an operator what
        # to fix, where "Pending" tells them only that something is wrong.
        conditions = [c for c in (status.get("conditions") or []) if c.get("status") == "False"]
        message = conditions[0].get("message", "") if conditions else ""
        return {"pod": name, "phase": phase, "reason": "Pending", "message": message,
                "restarts": restarts}
    if phase not in ("Running", "Succeeded"):
        return {"pod": name, "phase": phase, "reason": phase, "message": "", "restarts": restarts}
    if not all(c.get("ready") for c in statuses) and statuses:
        return {"pod": name, "phase": phase, "reason": "NotReady",
                "message": "the container is running but failing its readiness probe",
                "restarts": restarts}
    return None


def gather(*, namespace: str, context: str | None = None) -> InstallationFacts:
    facts = InstallationFacts()

    def read(args, label):
        proc = cluster_mod.run(args, context=context)
        if proc.returncode != 0:
            message = (proc.stderr or proc.stdout or "").strip().splitlines()
            facts.read_failures[label] = message[0] if message else f"kubectl exit {proc.returncode}"
            return None
        import json
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            facts.read_failures[label] = f"unparseable JSON: {exc}"
            return None

    deployments = read(["get", "deployments", "-n", namespace, "-l", SELECTOR, "-o", "json"],
                       "deployments")
    if deployments is not None:
        facts.workloads = [_workload(d) for d in deployments.get("items", [])]
        facts.found = bool(facts.workloads)

    pods = read(["get", "pods", "-n", namespace, "-l", SELECTOR, "-o", "json"], "pods")
    if pods is not None:
        facts.pods_not_ready = [p for p in (_unhealthy_pod(pod) for pod in pods.get("items", []))
                                if p is not None]

    jobs = read(["get", "jobs", "-n", namespace, "-l", SELECTOR, "-o", "json"], "jobs")
    if jobs is not None:
        for job in jobs.get("items", []):
            if _label(job, "app.kubernetes.io/component") == "migrations":
                st = job.get("status") or {}
                facts.migration_job = {
                    "name": (job.get("metadata") or {}).get("name", "?"),
                    "succeeded": int(st.get("succeeded") or 0),
                    "failed": int(st.get("failed") or 0),
                    "active": int(st.get("active") or 0),
                }

    # Only ask when KEDA is served; otherwise kubectl answers with a confusing "no resource type"
    # that reads as a permissions failure.
    resources = cluster_mod.run(["api-resources", "-o", "name"], context=context)
    if resources.returncode == 0 and any(
            line.strip().startswith("scaledobjects.keda.sh")
            for line in resources.stdout.splitlines()):
        scaled = read(["get", "scaledobjects", "-n", namespace, "-l", SELECTOR, "-o", "json"],
                      "scaledobjects")
        if scaled is not None:
            facts.scaled_objects = [s["metadata"]["name"] for s in scaled.get("items", [])]
    else:
        # None means "not asked / not knowable", which status must not read as "none exist" —
        # the second would make it report every autoscaled tier as missing its scaler.
        facts.scaled_objects = None

    return facts
