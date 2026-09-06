"""A capacity schedule as an Azure scale policy — set once, transitioning by itself.

PRD §6.4 is the requirement this module exists for, and it is a prohibition:

    Scheduled transitions must be handled by a persistent scaling policy, such as combined cron
    and queue rules. ACP must not run an external script every morning and evening that changes
    the Container App template. Such updates create revisions and risk worker restarts.
    Publishing or editing the schedule may create one reviewed configuration revision. Ordinary
    schedule transitions must not.

The PRD does not say what replaces the script, and the obvious implementation — a cron job that
calls `az containerapp update` twice a day — is precisely the one it forbids. Review finding R7
named the mechanism; this is it.

**Two KEDA rules on one app, and KEDA takes the maximum of what they ask for.**

  * a `cron` rule that asks for the BUSINESS-HOURS floor during the window and nothing outside it
  * the existing `postgresql` queue rule (api/queue_scaler.py), which asks for whatever the
    claimable backlog needs, at any hour
  * `minReplicas` set to the OFF-HOURS floor, `maxReplicas` to the service's ceiling

That composition is the PRD's §6.1 and §6.4 in one object. Off-hours the cron rule is silent, so
the floor is minReplicas and the queue may still scale above it — which is §6.1's "scheduled
capacity is a floor, not a ceiling" and AC 8's overnight burst. During business hours the cron
rule holds the warm floor without anything being deployed, and the queue can still ask for more.
Nothing changes at 06:00 except what KEDA computes, so the transition creates no revision.

**DST is the platform's problem too, and it is handled in the same place.** The cron rule carries
an IANA `timezone`, so KEDA evaluates the window against local wall-clock time exactly as
`capacity_schedule.next_transition` does. Storing a UTC offset here would drift by an hour twice
a year against a schedule the tab renders correctly — the two would disagree and only the tab
would be right.

**What this module does NOT do.** It builds and renders a policy; it applies nothing. Whether an
`az` call is made, and by whom, is the caller's decision — which keeps the shape of the policy
testable without a subscription, and keeps the one place that spends Azure money in the route
that is admin-gated and audited.
"""
from __future__ import annotations

from dataclasses import dataclass

import capacity_schedule as sched
import queue_scaler

# Cron day-of-week is 0-6 with 0 = Sunday. `capacity_schedule.DAYS` is Monday-first because that
# is how the schedule editor reads. Getting this mapping wrong shifts the whole business week by
# a day and produces a policy that looks entirely plausible.
_CRON_DOW = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}


@dataclass(frozen=True)
class ScaleRule:
    name: str
    type: str
    metadata: dict
    auth: dict | None = None

    def as_dict(self) -> dict:
        out = {"name": self.name, "type": self.type, "metadata": dict(self.metadata)}
        if self.auth:
            out["auth"] = dict(self.auth)
        return out


@dataclass(frozen=True)
class AppPolicy:
    """One Container App's complete scale configuration under a schedule."""

    app: str
    service: str
    min_replicas: int
    max_replicas: int
    rules: tuple[ScaleRule, ...]

    def as_dict(self) -> dict:
        return {"app": self.app, "service": self.service,
                "min_replicas": self.min_replicas, "max_replicas": self.max_replicas,
                "rules": [r.as_dict() for r in self.rules]}


def _cron_days(days) -> str:
    """`mon..fri` -> `1,2,3,4,5`. A comma list rather than a collapsed range.

    A range is prettier and `1-5` and `1,2,3,4,5` mean the same thing, but a collapse has to
    decide what to do with a non-contiguous week (mon, wed, fri) and gets it subtly wrong far
    more easily than a list does. This is a machine-read field.
    """
    known = sorted({_CRON_DOW[d] for d in days if d in _CRON_DOW})
    if not known:
        raise ValueError("a cron scale rule with no days would never fire")
    return ",".join(str(d) for d in known)


def cron_rule(schedule: sched.Schedule, desired: int) -> ScaleRule:
    """The time-based half: hold `desired` replicas warm during the business-hours window.

    `desiredReplicas` is what the rule ASKS FOR while the window is open, not a ceiling — KEDA
    takes the maximum across triggers, so the queue rule can still ask for more at 10am. That is
    what makes a schedule a floor (§6.1) rather than the cap a naive reading would build.
    """
    hour, minute = schedule.start.split(":")
    end_hour, end_minute = schedule.end.split(":")
    days = _cron_days(schedule.days)
    return ScaleRule(
        name="business-hours",
        type="cron",
        metadata={
            # An IANA zone, never an offset: KEDA evaluates the window in local wall-clock time,
            # so the policy follows daylight saving the same way the schedule does. An offset
            # here would disagree with the tab by an hour for half the year.
            "timezone": schedule.timezone,
            "start": f"{int(minute)} {int(hour)} * * {days}",
            "end": f"{int(end_minute)} {int(end_hour)} * * {days}",
            "desiredReplicas": str(desired),
        },
    )


def queue_rule(service: str, job_types) -> ScaleRule:
    """The demand-based half, unchanged from Phase 1 — including its claim predicate.

    THE NAME MUST MATCH WHAT IS ALREADY DEPLOYED, and it is not derivable from the service key.
    Production's remediate rule is `remediation-queue` — deploy/public/rightsize-production.sh —
    while the service is called `remediate`. An `f"{service}-queue"` would generate
    `remediate-queue`, and applying that would leave the app carrying BOTH rules: the old one
    still asking for replicas on the old query, and the new one beside it. Two queue rules on one
    app is not a doubled scale-up (KEDA takes the maximum), but it is a rule nobody intends,
    invisible except in the scale block, and it survives every later edit.
    """
    return ScaleRule(
        name=QUEUE_RULE_NAMES[service],
        type="postgresql",
        metadata={"query": queue_scaler.depth_query(job_types),
                  "targetQueryValue": str(QUEUE_TARGETS[service])},
        auth={"connection": "database-url"},
    )


# The rule name each service's queue scaler carries in Azure. Read from what is deployed rather
# than generated from the service key: see queue_rule's docstring for what generating it costs.
# tests/test_capacity_policy.py holds these against rightsize-production.sh.
QUEUE_RULE_NAMES = {"assess": "assess-queue", "remediate": "remediation-queue"}

# DISCOVERY IS DELIBERATELY ABSENT, and it is the one entry that would be a guess.
#
# No discovery queue rule exists anywhere in this repository. rightsize-production.sh's only
# comment on that tier says "Discovery can use its existing CPU scale rule" — a rule no script
# here creates, so it was either applied out of band or does not exist, and this repository
# cannot tell which. docs/runbooks/verify-capacity-scalers.md §1 is the read that answers it.
#
# That matters because `az containerapp update --scale-rule-name` REPLACES the rules array. If
# discovery does carry a CPU rule applied by hand, emitting a `discovery-queue` rule here would
# silently remove it — trading a scaler that works for one nobody asked for, with no error and
# no record. Adding discovery is a one-line change once §1 has been run; guessing now is not.
#
# It also matches the PRD's own Phase 1 scope, which names Remediate (repair) and Assess (add)
# and says nothing about Discovery.

# Queued claimable jobs per replica, per lane. Remediate's 4 is the reviewed production value
# (deploy/public/rightsize-production.sh); assess's 8 reflects shorter per-job work. Both are
# tuning constants for PRD Phase 4 to revisit against measurements, not derived facts.
QUEUE_TARGETS = {"discovery": 4, "assess": 8, "remediate": 4}


def policy_for(schedule: sched.Schedule, lane_job_types: dict) -> list[AppPolicy]:
    """The whole fleet's scale policy under one schedule.

    `lane_job_types` maps service -> the job types that lane claims (api/core.py's own tuples,
    passed in rather than imported so this module stays testable without the application).

    A service gets a cron rule only when the schedule is ENABLED and its business-hours floor is
    actually higher than its off-hours floor. A cron rule asking for the number minReplicas
    already guarantees is a rule that can never change anything — and every rule is a line in a
    revision somebody has to read.
    """
    policies = []
    for service, app in sched.SERVICE_APPS.items():
        ceiling = schedule.maximums.get(service)
        if ceiling is None:
            continue
        off = int(schedule.off_hours.get(service, 0))
        business = int(schedule.business_hours.get(service, off))
        rules: list[ScaleRule] = []
        if schedule.enabled and business > off:
            rules.append(cron_rule(schedule, business))
        # GATED ON QUEUE_RULE_NAMES, not on lane_job_types. A lane having job types says the
        # queue is meaningful for it; having a NAME says this repository knows which rule it
        # would be replacing. Discovery has the first and not the second — see the comment on
        # QUEUE_RULE_NAMES for why generating a name there is the one guess that can destroy
        # a working scaler.
        if service in QUEUE_RULE_NAMES and service in lane_job_types:
            rules.append(queue_rule(service, lane_job_types[service]))
        policies.append(AppPolicy(app=app, service=service, min_replicas=off,
                                  max_replicas=int(ceiling), rules=tuple(rules)))
    return policies


def az_commands(policy: list[AppPolicy], *, resource_group: str, subscription: str) -> list[list[str]]:
    """The `az` invocations that would apply this policy — rendered, never run.

    ONE PER APP, and that is the whole point: applying a schedule is a handful of configuration
    updates made once, and every transition after that happens inside KEDA. A design that met the
    same requirement with a morning and an evening call would produce two revisions a day,每 one
    of which can restart a worker holding a document.

    Rendered as argv lists rather than a shell string so a caller cannot accidentally build a
    command through a shell, and so a test can assert the arguments rather than parse them back
    out of a string.
    """
    out = []
    for app in policy:
        args = ["containerapp", "update", "--subscription", subscription,
                "--resource-group", resource_group, "--name", app.app,
                "--min-replicas", str(app.min_replicas),
                "--max-replicas", str(app.max_replicas)]
        for rule in app.rules:
            args += ["--scale-rule-name", rule.name, "--scale-rule-type", rule.type,
                     "--scale-rule-metadata"]
            args += [f"{k}={v}" for k, v in rule.metadata.items()]
            for key, value in (rule.auth or {}).items():
                args += ["--scale-rule-auth", f"{key}={value}"]
        out.append(args)
    return out
