"""The Azure scale policy a schedule implies — PRD §6.4, and review finding R7.

§6.4 is a PROHIBITION with no named replacement: scheduled transitions must not change the
Container App template, because every such update creates a revision that can restart a worker
holding a document. The obvious implementation — a cron job calling `az containerapp update`
twice a day — is exactly what it forbids.

The mechanism is two KEDA rules on one app, and KEDA taking the maximum of what they ask for.
These tests hold the composition, because getting it wrong produces a policy that looks right and
means the opposite: a cron rule read as a CEILING would cap overnight capacity at zero and turn
AC 8 (an overnight queue can scale above the off-hours baseline) into a silent regression.
"""
from __future__ import annotations

import re
import sys
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

import capacity_policy as cp  # noqa: E402
import capacity_schedule as cs  # noqa: E402

LANES = {"discovery": ("scan_discover", "scan_folder"),
         "assess": ("scan_file", "scan_finalize"),
         "remediate": ("remediate_file", "publish_file")}


def sched(**overrides) -> cs.Schedule:
    return replace(cs.PROPOSED, enabled=True, **overrides)


def by_app(schedule=None) -> dict:
    return {p.app: p for p in cp.policy_for(schedule or sched(), LANES)}


# ── the composition ──────────────────────────────────────────────────────────────────────────

def test_the_schedule_is_a_floor_and_the_queue_can_still_exceed_it():
    """§6.1 and AC 8 in one object.

    minReplicas is the OFF-HOURS floor, so overnight capacity never drops below it; the cron rule
    asks for the business-hours floor only during the window; the queue rule can ask for more at
    any hour, and KEDA takes the maximum. A reading that made the cron rule a ceiling would cap
    the overnight queue at the off-hours floor, which is the regression this asserts against.
    """
    assess = by_app()["acp-assess"]
    assert assess.min_replicas == cs.PROPOSED.off_hours["assess"] == 1
    assert assess.max_replicas == cs.PROPOSED.maximums["assess"] == 10
    kinds = {r.type for r in assess.rules}
    assert kinds == {"cron", "postgresql"}
    cron = next(r for r in assess.rules if r.type == "cron")
    assert cron.metadata["desiredReplicas"] == str(cs.PROPOSED.business_hours["assess"]) == "5"
    # The ceiling is maxReplicas, never the cron rule's number.
    assert int(cron.metadata["desiredReplicas"]) < assess.max_replicas


def test_the_cron_window_is_the_schedules_own_window_in_its_own_timezone():
    cron = next(r for r in by_app()["acp-assess"].rules if r.type == "cron")
    assert cron.metadata["timezone"] == "America/Los_Angeles"
    assert cron.metadata["start"] == "0 6 * * 1,2,3,4,5"
    assert cron.metadata["end"] == "0 20 * * 1,2,3,4,5"


def test_the_policy_carries_an_iana_zone_rather_than_an_offset():
    """AC 4 at the platform level. KEDA evaluates the window in local wall-clock time, so the
    policy follows daylight saving exactly as capacity_schedule.next_transition does. A UTC
    offset here would drift an hour twice a year against a tab that stayed correct — and only
    the tab would be right."""
    cron = next(r for r in by_app()["acp-assess"].rules if r.type == "cron")
    assert "/" in cron.metadata["timezone"], "not an IANA zone"
    assert not re.match(r"^[+-]\d", cron.metadata["timezone"])


def test_monday_is_cron_day_one_and_sunday_is_zero():
    """Cron day-of-week is Sunday-first; capacity_schedule.DAYS is Monday-first. Getting the
    mapping wrong shifts the whole business week by a day and produces a policy that is entirely
    plausible and entirely wrong."""
    weekend = next(r for r in by_app(sched(days=("sat", "sun"))).values().__iter__().__next__().rules
                   if r.type == "cron")
    assert weekend.metadata["start"].endswith(" 0,6")


def test_a_schedule_with_no_days_cannot_produce_a_cron_rule():
    with pytest.raises(ValueError):
        cp.cron_rule(sched(days=()), 5)


# ── rules that would do nothing are not emitted ──────────────────────────────────────────────

def test_no_cron_rule_when_the_business_floor_matches_the_off_hours_floor():
    """A cron rule asking for the number minReplicas already guarantees can never change
    anything, and every rule is a line in a revision somebody has to read."""
    flat = sched(business_hours={**cs.PROPOSED.business_hours, "assess": 1})
    assess = by_app(flat)["acp-assess"]
    assert [r.type for r in assess.rules] == ["postgresql"]


def test_a_disabled_schedule_emits_no_cron_rule_but_keeps_the_queue():
    """Disabling the schedule must not disable autoscaling. The queue rule is what keeps accepted
    work moving, and it has nothing to do with the time of day."""
    off = by_app(replace(cs.PROPOSED, enabled=False))["acp-remediate"]
    assert [r.type for r in off.rules] == ["postgresql"]


def test_only_the_queue_driven_services_get_a_queue_rule():
    """web scales on HTTP and gpu on demand; neither reads the jobs table."""
    apps = by_app()
    assert not [r for r in apps["acp-app"].rules if r.type == "postgresql"]
    assert not [r for r in apps["acp-ollama"].rules if r.type == "postgresql"]
    for app in ("acp-assess", "acp-remediate"):
        assert [r for r in apps[app].rules if r.type == "postgresql"], app
    # acp-discovery is a third case, and its own test says why it has none.
    assert not [r for r in apps["acp-discovery"].rules if r.type == "postgresql"]


# ── the queue rule must land on the rule that already exists ─────────────────────────────────

def test_discovery_gets_no_queue_rule_because_this_repo_cannot_see_its_scale_configuration():
    """The one entry that would have been a guess.

    No discovery queue rule exists in this repository, and rightsize-production.sh's only comment
    on that tier claims a CPU rule no script here creates. Since
    `az containerapp update --scale-rule-name` REPLACES the rules array, emitting a generated
    `discovery-queue` would silently remove a hand-applied rule if one exists — trading a scaler
    that works for one nobody asked for, with no error and no record.
    """
    assert "discovery" not in cp.QUEUE_RULE_NAMES
    discovery = by_app()["acp-discovery"]
    assert not [r for r in discovery.rules if r.type == "postgresql"]
    # The tier still gets its floors and ceiling from the schedule, and its cron rule.
    assert discovery.max_replicas == cs.PROPOSED.maximums["discovery"]
    assert [r.type for r in discovery.rules] == ["cron"]


def test_the_queue_rule_names_match_what_is_already_deployed():
    """NOT DERIVABLE FROM THE SERVICE KEY, and that is the trap. Production's remediate rule is
    `remediation-queue` while the service is `remediate`; an f-string would generate
    `remediate-queue`, and applying that would leave the app carrying BOTH — the old rule still
    asking on the old query, and the new one beside it, invisible outside the scale block."""
    script = (ROOT / "deploy/public/rightsize-production.sh").read_text()
    deployed = set(re.findall(r"--scale-rule-name\s+(\S+)", script))
    for service, name in cp.QUEUE_RULE_NAMES.items():
        if name in deployed:
            continue
        pytest.fail(f"{service}'s rule is generated as {name!r}, which is not one of the names "
                    f"rightsize-production.sh applies ({sorted(deployed)}) — applying it would "
                    f"add a second rule rather than replace the first")


def test_the_queue_rule_carries_the_phase_one_claim_predicate():
    """The predicate fixed in Phase 1 must survive into the policy Phase 3 applies, or the fix
    is undone the first time a schedule is published."""
    import queue_scaler
    rule = next(r for r in by_app()["acp-remediate"].rules if r.type == "postgresql")
    assert queue_scaler.CLAIMABILITY_SQL in rule.metadata["query"]
    for job_type in LANES["remediate"]:
        assert job_type in rule.metadata["query"]
    assert rule.auth == {"connection": "database-url"}


# ── what applying costs ──────────────────────────────────────────────────────────────────────

def test_applying_a_schedule_is_one_command_per_app_and_nothing_per_transition():
    """§6.4's actual requirement. Publishing may cost one reviewed revision per app; the 06:00
    and 20:00 transitions must cost nothing, and they do, because nothing about the app changes
    at those times — KEDA simply computes a different number."""
    policy = cp.policy_for(sched(), LANES)
    commands = cp.az_commands(policy, resource_group="rg", subscription="sub")
    assert len(commands) == len(policy)
    names = [c[c.index("--name") + 1] for c in commands]
    assert names == [p.app for p in policy]
    assert len(set(names)) == len(names), "an app would be updated twice in one publish"


def test_the_commands_are_argv_lists_and_carry_the_subscription():
    """tests/test_az_subscription_scope.py exists because a command pasted without
    --subscription runs against whatever the operator's CLI defaults to."""
    commands = cp.az_commands(cp.policy_for(sched(), LANES),
                              resource_group="rg", subscription="sub-123")
    for args in commands:
        assert isinstance(args, list) and all(isinstance(a, str) for a in args)
        assert args[args.index("--subscription") + 1] == "sub-123"
        assert args[args.index("--resource-group") + 1] == "rg"


def test_no_command_embeds_a_connection_string():
    """The queue rule references a SECRET by name (`connection=database-url`). A policy that
    inlined the value would put a credential into every audit row and every rendered command."""
    rendered = " ".join(" ".join(c) for c in cp.az_commands(
        cp.policy_for(sched(), LANES), resource_group="rg", subscription="sub"))
    assert "connection=database-url" in rendered
    assert "postgres://" not in rendered and "password" not in rendered.lower()
