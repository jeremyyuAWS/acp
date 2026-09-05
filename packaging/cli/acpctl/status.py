"""`acpctl status` — is the running installation healthy, and is it still what the document says?

TWO QUESTIONS, AND THE SECOND IS THE ONE NOTHING ELSE ANSWERS. Health is visible in `kubectl get
pods`, and an operator who wants only that has better tools. What no other tool can check is
DRIFT: whether the release actually running matches the deployment document.

That matters because `acpctl values` stamps this on every file it renders:

    edit the deployment document and regenerate, or the two disagree and the document
    stops being the record of what was installed

which is a claim nothing verified until now. A `kubectl scale`, a hand-edited values file, a
partially-applied upgrade — each leaves the document describing an installation that no longer
exists, silently, and the document is what the next operator reads before making a change.

AUTOSCALING IS NOT DRIFT, and getting that wrong would sink the whole feature. The obvious check
compares deployed replicas against the document's `replicaCount`, and it fires on every healthy
autoscaled tier: a KEDA tier configured 3-10 and currently at 7 is the system working exactly as
designed. A drift report that is red on every correct installation is one that gets ignored, and
then the real drift is ignored with it. So for an autoscaled tier the question is whether the
count is INSIDE its range; outside it means someone scaled by hand or the ScaledObject is gone,
which is drift worth reporting.

THE WRONG DOCUMENT IS CHECKED FIRST. Every comparison below is meaningless if the operator passed
a document describing a different installation — and the output would be a long list of confident,
entirely bogus drift. The chart labels each object with its profile and platform, so that case is
detectable, and it is checked before anything else so the report can say "this document does not
describe this installation" instead of fifteen false findings.
"""
from __future__ import annotations

from typing import Any

from .doctor import BLOCKER, FAIL, INFO, PASS, UNKNOWN, WARNING, Check
from .installation import InstallationFacts

# The worker tier keys in a deployment document, mapped to the role label the chart stamps.
# Imported rather than re-listed so a new tier cannot exist in one and not the other.
from .inventory import TIER_ROLE


def _tier_for(workload, values: dict) -> tuple[str, dict] | tuple[None, None]:
    """Which values block describes this workload."""
    if workload.component == "api":
        return "api", values.get("api") or {}
    for key, role in TIER_ROLE.items():
        if workload.role in (role, key):
            return key, (values.get("workers") or {}).get(key) or {}
    return None, None


def check_installed(facts: InstallationFacts, namespace: str) -> Check:
    if facts.read_failures.get("deployments"):
        return Check("install.present", UNKNOWN, BLOCKER,
                     f"could not list deployments in {namespace!r}: "
                     f"{facts.read_failures['deployments']}",
                     "Nothing below could be established. Usually a missing RBAC permission.")
    if not facts.found:
        return Check("install.present", FAIL, BLOCKER,
                     f"no ACP workloads found in namespace {namespace!r}",
                     "Nothing is installed here, or it was installed into a different namespace. "
                     "`acpctl status -n <namespace>` selects on app.kubernetes.io/part-of=acp.")
    return Check("install.present", PASS, INFO,
                 f"{len(facts.workloads)} ACP workload(s) in {namespace!r}")


def check_document_matches(facts: InstallationFacts, values: dict) -> Check | None:
    """Is this document even about this installation?

    Checked BEFORE any comparison, because a mismatched document turns every finding below into a
    confident falsehood. An operator with several environments passes the wrong file eventually,
    and the useful response is to say so once — not to list fifteen differences as though the
    cluster had drifted, which is a report that sends somebody to "fix" a healthy installation.

    Compared on PROFILE AND PLATFORM rather than on the release name, because those are properties
    of the deployment the chart stamps on every object, and because two environments of the same
    profile (staging and production, both `standard` on `azure`) SHOULD compare cleanly — they
    differ by namespace and cluster, which the operator already chose when they ran the command.
    This catches the mistake that produces nonsense, not every possible mix-up.
    """
    deployment = values.get("acpDeployment") or {}
    want_profile, want_platform = deployment.get("profile"), deployment.get("platform")
    seen_profiles = {w.profile for w in facts.workloads if w.profile}
    seen_platforms = {w.platform for w in facts.workloads if w.platform}
    if not (seen_profiles or seen_platforms):
        return None                      # nothing labelled; nothing to compare, so say nothing

    mismatches = []
    if want_profile and seen_profiles and want_profile not in seen_profiles:
        mismatches.append(f"profile {want_profile!r} vs {', '.join(sorted(seen_profiles))}")
    if want_platform and seen_platforms and want_platform not in seen_platforms:
        mismatches.append(f"platform {want_platform!r} vs {', '.join(sorted(seen_platforms))}")
    if mismatches:
        return Check("document.matches", FAIL, BLOCKER,
                     "this document does not describe the installation in this namespace: "
                     + "; ".join(mismatches),
                     "Every comparison below would be against the wrong baseline. Check that you "
                     "passed the document for THIS environment, and the right --namespace.")
    return Check("document.matches", PASS, INFO,
                 f"the document matches the installed profile and platform "
                 f"({'/'.join(sorted(seen_profiles | seen_platforms))})")


def check_release(facts: InstallationFacts, values: dict) -> Check:
    """The running release against the document's.

    COMPARED ON THE VERSION LABEL, NOT ON THE IMAGE STRING. `acpctl install` resolves and pins
    digests, so a correctly-installed release runs `repo@sha256:...` while the document says a
    tag — comparing image strings would call every properly-pinned installation drifted, which is
    precisely backwards. The chart stamps app.kubernetes.io/version from the tag, so the label
    survives pinning and is the honest comparison point.
    """
    want = str((values.get("image") or {}).get("tag") or "")
    running = {w.version for w in facts.workloads if w.version}
    if not running:
        return Check("release.version", UNKNOWN, WARNING,
                     "the workloads carry no app.kubernetes.io/version label, so the running "
                     "release could not be read",
                     "Either they were not installed by this chart, or by a version of it that "
                     "predates the label.")
    if len(running) > 1:
        return Check("release.version", FAIL, BLOCKER,
                     f"the installation is running MORE THAN ONE release at once: "
                     f"{', '.join(sorted(running))}",
                     "An upgrade is in progress or one stalled part-way. Mixed versions against "
                     "one database are only safe while a rollout is actually running (ADR 0045's "
                     "additive-migration window); a stuck one should be finished or rolled back.")
    have = running.pop()
    if want and have != want:
        return Check("release.version", FAIL, BLOCKER,
                     f"the cluster is running {have} but the document describes {want}",
                     "The document is meant to be the record of what was installed. Either "
                     "upgrade the release, or correct the document — but do not leave them "
                     "disagreeing, because the document is what the next change is based on.")
    return Check("release.version", PASS, INFO, f"running {have}, as the document describes")


def check_replicas(facts: InstallationFacts, values: dict) -> list[Check]:
    """Replica drift, judged differently for autoscaled and fixed tiers.

    THIS IS WHERE THE OBVIOUS IMPLEMENTATION IS WRONG. Comparing the running count against the
    document's `replicaCount` flags every healthy autoscaled tier — a tier set 3-10 and sitting
    at 7 is the autoscaler doing its job, not a deviation. A report red on every correct install
    trains an operator to skip it.
    """
    checks: list[Check] = []
    for workload in sorted(facts.workloads, key=lambda w: w.name):
        key, tier = _tier_for(workload, values)
        if tier is None:
            checks.append(Check(f"replicas.{workload.name}", UNKNOWN, WARNING,
                                f"{workload.name} is running but the document does not describe "
                                f"a tier for it",
                                "Either the document is for a different installation, or this is "
                                "left over from an older release that had a tier since removed."))
            continue
        autoscaling = tier.get("autoscaling") or {}
        # `desired` is None exactly when the chart omitted spec.replicas, which it does only for
        # an autoscaled tier — so the two ways of detecting autoscaling agree, and a disagreement
        # between them is itself worth reporting rather than silently picking one.
        current = workload.desired if workload.desired is not None else workload.ready
        if autoscaling.get("enabled"):
            low, high = autoscaling.get("minReplicas"), autoscaling.get("maxReplicas")
            if low is None or high is None:
                continue
            if not (low <= current <= high):
                checks.append(Check(
                    f"replicas.{key}", FAIL, WARNING,
                    f"{workload.name} is at {current} replica(s), outside its configured "
                    f"{low}-{high}",
                    "Either something scaled it by hand — which the autoscaler will undo, or "
                    "fight — or its ScaledObject is missing so nothing is holding the range."))
            else:
                checks.append(Check(f"replicas.{key}", PASS, INFO,
                                    f"{workload.name} at {current}, within its {low}-{high} range"))
        else:
            want = tier.get("replicaCount")
            if want is not None and current != want:
                checks.append(Check(
                    f"replicas.{key}", FAIL, WARNING,
                    f"{workload.name} is at {current} replica(s); the document says {want}",
                    "This tier has no autoscaler, so nothing should be changing its count. "
                    "Either it was scaled by hand or the document is stale."))
            else:
                checks.append(Check(f"replicas.{key}", PASS, INFO,
                                    f"{workload.name} at {current}, as the document describes"))
    return checks


def check_scalers(facts: InstallationFacts, values: dict) -> Check | None:
    """Every tier the document autoscales should have a ScaledObject.

    The silent failure from `doctor`, seen from the other side: doctor asks whether KEDA is
    installed before the fact; this asks whether the scalers are actually THERE afterwards. A
    ScaledObject deleted by a partial upgrade leaves the tier pinned at whatever it happened to
    be, with nothing reporting it.
    """
    wanted = [name for name, tier in (values.get("workers") or {}).items()
              if (tier.get("autoscaling") or {}).get("enabled")
              and (tier.get("autoscaling") or {}).get("scaler") == "keda"]
    if not wanted:
        return None
    if facts.scaled_objects is None:
        return Check("scalers.present", UNKNOWN, WARNING,
                     "KEDA is not served by this cluster, or its resources could not be listed, "
                     f"so the {len(wanted)} expected ScaledObject(s) could not be checked",
                     "Run `acpctl doctor` — a missing KEDA leaves the ScaledObjects inert with no "
                     "error anywhere.")
    if len(facts.scaled_objects) < len(wanted):
        return Check("scalers.present", FAIL, WARNING,
                     f"{len(wanted)} worker tier(s) are configured to autoscale but only "
                     f"{len(facts.scaled_objects)} ScaledObject(s) exist",
                     "The tiers without one will sit at whatever replica count they currently "
                     "have, and nothing will report it.")
    return Check("scalers.present", PASS, INFO,
                 f"{len(facts.scaled_objects)} ScaledObject(s) present")


def check_health(facts: InstallationFacts) -> list[Check]:
    checks: list[Check] = []
    for workload in sorted(facts.workloads, key=lambda w: w.name):
        if workload.healthy:
            continue
        target = workload.desired if workload.desired is not None else "?"
        checks.append(Check(
            f"health.{workload.name}", FAIL, BLOCKER,
            f"{workload.name}: {workload.ready} of {target} replica(s) ready",
            "See the pod findings below for why."))
    for pod in facts.pods_not_ready:
        detail = f"{pod['pod']}: {pod['reason']}"
        if pod["restarts"]:
            detail += f" after {pod['restarts']} restart(s)"
        if pod["message"]:
            detail += f" — {pod['message'][:200]}"
        checks.append(Check(f"pod.{pod['pod']}", FAIL, BLOCKER, detail))
    if not checks and facts.workloads:
        ready = sum(w.ready for w in facts.workloads)
        checks.append(Check("health.pods", PASS, INFO,
                            f"every workload is ready ({ready} pod(s))"))
    return checks


def check_migration(facts: InstallationFacts) -> Check | None:
    """The migration hook's outcome, which decides whether the release is sound at all.

    Helm's hook already blocks a release whose migration failed, so a FAILED job here means the
    install did not complete — and the previous version may still be serving. That is worth
    saying explicitly, because the workloads can look perfectly healthy while being the OLD ones.
    """
    job = facts.migration_job
    if job is None:
        # The chart's hook-delete-policy removes it on success, so absence is the NORMAL state
        # after a clean install. Reporting it as a problem would make every healthy installation
        # look broken.
        return None
    if job["failed"]:
        return Check("migration.result", FAIL, BLOCKER,
                     f"the schema migration job {job['name']} failed",
                     "The release was stopped at its pre-upgrade hook, so what is running may be "
                     "the PREVIOUS version — healthy-looking and not what you deployed. Read the "
                     f"job's logs: kubectl logs job/{job['name']}")
    if job["active"]:
        return Check("migration.result", UNKNOWN, WARNING,
                     f"the schema migration job {job['name']} is still running",
                     "The release is mid-flight; re-run status when it settles.")
    return Check("migration.result", PASS, INFO, "the schema migration completed")


def report(values: dict, facts: InstallationFacts, *, namespace: str,
           reachable: bool = True, unreachable_reason: str = "") -> dict[str, Any]:
    if not reachable:
        return {
            "reachable": False, "installed": False, "namespace": namespace,
            "checks": [Check("cluster.reachable", UNKNOWN, BLOCKER,
                             unreachable_reason or "the cluster could not be reached",
                             "Nothing was checked. This is not a healthy installation; it is no "
                             "information at all.").as_dict()],
            "blockers": 1, "warnings": 0, "unknown": 1, "ok": False,
        }

    present = check_installed(facts, namespace)
    checks: list[Check] = [present]
    if present.status == PASS:
        wrong_document = check_document_matches(facts, values)
        if wrong_document is not None:
            checks.append(wrong_document)
        # A MISMATCHED DOCUMENT STOPS THE COMPARISON RATHER THAN COLOURING IT. Health is still
        # worth reporting — it does not depend on the document at all — but release and replica
        # drift measured against the wrong baseline is worse than no answer, because it reads as
        # a cluster problem and sends somebody to change a healthy installation.
        if wrong_document is not None and wrong_document.status == FAIL:
            checks += check_health(facts)
            return _summarise(checks, namespace=namespace, installed=True)
        checks.append(check_release(facts, values))
        checks += check_health(facts)
        checks += check_replicas(facts, values)
        for maybe in (check_scalers(facts, values), check_migration(facts)):
            if maybe is not None:
                checks.append(maybe)
        for label, reason in sorted(facts.read_failures.items()):
            checks.append(Check(f"read.{label}", UNKNOWN, WARNING,
                                f"could not read {label}: {reason}",
                                "Checks depending on it were not performed."))

    return _summarise(checks, namespace=namespace, installed=present.status == PASS)


def _summarise(checks: list[Check], *, namespace: str, installed: bool) -> dict[str, Any]:
    blockers = [c for c in checks if c.status == FAIL and c.severity == BLOCKER]
    unknown_blockers = [c for c in checks if c.status == UNKNOWN and c.severity == BLOCKER]
    warnings = [c for c in checks if c.status in (FAIL, UNKNOWN) and c.severity != BLOCKER]
    return {
        "reachable": True,
        "installed": installed,
        "namespace": namespace,
        "checks": [c.as_dict() for c in checks],
        "blockers": len(blockers),
        "unknown": len([c for c in checks if c.status == UNKNOWN]),
        "warnings": len(warnings),
        # Same rule as doctor: a blocking check that could not RUN has established nothing, and
        # reporting it as healthy is the failure this whole family of commands exists to avoid.
        "ok": not blockers and not unknown_blockers,
        "drifted": any(c.id.startswith(("release.", "replicas.", "document.")) and c.status == FAIL
                       for c in checks),
    }
