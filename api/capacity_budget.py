"""The fleet capacity inequality, as arithmetic that runs.

PRD "Settings -> Scheduling" §7, which restates "Automatic Worker Provisioning" §4.C:

    API connections + worker connections + deployment overlap + operational reserve
        <= usable database capacity

That inequality has been evaluated in this repository since #1045's aftermath, but only inside
`tests/test_db_connection_budget.py` — where nothing but a test can call it. The Scheduling
feature needs the same arithmetic at request time (`POST /control/capacity-schedule/validate`
must refuse a schedule before it is saved), so the model lives here, in importable code, and the
test file keeps its role: pinning the numbers the deployed shape actually produces.

WHAT THIS MODULE KNOWS AND WHAT IT REFUSES TO GUESS.

Every pool comes from `store.db_max_conn` — the same function the containers use — rather than
from a restated formula, so a change to the formula moves these numbers instead of silently
invalidating them. Replica ranges, CPU sizes, the server's `max_connections` and the
environment's vCPU quota are all INPUTS. None of them has a default here. That is deliberate:
`docs/db-connection-budget.md` records that `deploy.sh` passes replica flags only on `create`,
so the scripts are not the source of truth for a running deployment, and a default in this
module would be a fourth stale copy of a number that has already gone stale twice. A caller
that cannot supply the vCPU quota gets `vcpu_quota: None` and a stated "not evaluated" —
never a pass.

THE TERM THAT SURPRISES PEOPLE, AND WHY SCHEDULING MAKES IT WORSE. The binding term in this
inequality is not the maximum replica count; it is the DEPLOYMENT OVERLAP, and overlap is driven
by the MINIMUMS. Azure Container Apps runs the outgoing and incoming revisions together during a
rollout, so the realistic worst case is max-of-new plus min-of-old. A schedule that raises warm
floors during business hours therefore raises the fleet's worst case — and it does so only for
the hours in which somebody is most likely to deploy.

That is why `worst_case_tiers` exists and why validation must use it. Validating "the mode we
are in right now" passes at 2am and says nothing about the 10am deploy. A schedule is safe only
if EVERY mode it can be in is safe, evaluated against a rollout.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from store import db_max_conn


@dataclass(frozen=True)
class Tier:
    """One container app: its replica range, its thread count, its pool and its CPU size.

    `threads` is ACP_WORKERS on that app — 0 for the API tier, which runs no local worker
    threads by design (ADR 0013). `db_pool_override` is ACP_DB_MAX_CONN, which
    `rightsize-production.sh` pins at 2 on every worker app precisely so the pool stops tracking
    the thread count.
    """

    name: str
    min_replicas: int
    max_replicas: int
    threads: int = 0
    db_pool_override: int | None = None
    cpu_cores: float = 0.0

    @property
    def pool(self) -> int:
        """One process's connection pool, from the container's own function.

        One process per replica: `uvicorn app:app` carries no `--workers` and the worker tier is
        one process of N threads (verified in deploy/public/Dockerfile).
        """
        env = {"ACP_WORKERS": str(self.threads)}
        if self.db_pool_override is not None:
            env["ACP_DB_MAX_CONN"] = str(self.db_pool_override)
        return db_max_conn(env)


def connections(tiers, *, overlap: bool = True) -> int:
    """Connections the fleet may hold at once.

    `overlap` adds the OUTGOING revision at its MINIMUM replicas. A rolling deploy runs both
    revisions and the incoming one is what scales to max under load, so min-of-old plus
    max-of-new is the realistic worst case rather than a doubling of everything.
    """
    total = sum(t.max_replicas * t.pool for t in tiers)
    if overlap:
        total += sum(t.min_replicas * t.pool for t in tiers)
    return total


def vcpu(tiers, *, overlap: bool = True) -> float:
    """Environment vCPU the fleet may hold at once, on the same overlap reasoning.

    Rounded to three places rather than kept exact: Container Apps allows fractional CPU in
    0.25 steps and a float sum of those is otherwise reported as 50.99999999999999.
    """
    total = sum(t.max_replicas * t.cpu_cores for t in tiers)
    if overlap:
        total += sum(t.min_replicas * t.cpu_cores for t in tiers)
    return round(total, 3)


def worst_case_tiers(tiers, floors_by_mode) -> list[Tier]:
    """The tiers as the WORST mode of a schedule leaves them.

    `floors_by_mode` maps a mode name to `{tier name: min replicas}` — business hours, off
    hours, and any override capacity an administrator may select. The result takes each tier's
    LARGEST floor across every mode, because the overlap term is what a rollout has to survive
    and a rollout can land in any mode.

    A tier no mode mentions keeps the floor it already has, so a partial schedule (one that
    controls the worker tiers and leaves the API alone) is expressible without restating the
    rest of the fleet.
    """
    worst = {}
    for floors in floors_by_mode.values():
        for name, floor in floors.items():
            worst[name] = max(worst.get(name, 0), int(floor))
    out = []
    for tier in tiers:
        floor = worst.get(tier.name)
        if floor is None:
            out.append(tier)
            continue
        # A floor above the ceiling is a caller error, not something to silently clamp: it is
        # one of the PRD's own blocking validations ("a minimum exceeds its maximum") and
        # `evaluate` reports it by name. Carried through unchanged so it can be reported.
        out.append(replace(tier, min_replicas=floor))
    return out


@dataclass(frozen=True)
class Finding:
    """One validation result. `blocking` decides whether a save is refused.

    `detail` states the consequence in numbers rather than in adjectives — the PRD's own rule
    for a warning that does not block ("must state the concrete consequence").
    """

    code: str
    blocking: bool
    detail: str


def evaluate(tiers, *, server_max_connections: int, reserve: int,
             vcpu_quota: float | None = None) -> dict:
    """The PRD §7 check over one fleet shape. Returns findings, never raises on a bad fleet.

    `reserve` is the operational allowance — schema migrations, scripts/monitor.py, an admin
    psql session, Azure diagnostics. A stated allowance, not a measurement; the caller owns it.

    `vcpu_quota` is the Container Apps environment quota. THERE IS NO DEFAULT. No artifact in
    this repository records production's quota, and a plausible-looking number here would be
    indistinguishable from a measured one to every later reader. Passed as None, the vCPU check
    is reported as not evaluated and the fleet's demand is still returned, so an operator who
    reads the quota from Azure can finish the check by hand.
    """
    steady = connections(tiers, overlap=False)
    during_deploy = connections(tiers, overlap=True)
    demand = during_deploy + reserve
    findings: list[Finding] = []

    for tier in tiers:
        if tier.min_replicas > tier.max_replicas:
            findings.append(Finding(
                "min_exceeds_max", True,
                f"{tier.name}: floor {tier.min_replicas} is above its ceiling "
                f"{tier.max_replicas}."))
        if tier.min_replicas < 0 or tier.max_replicas < 0:
            findings.append(Finding(
                "negative_replicas", True,
                f"{tier.name}: replica counts must not be negative."))

    if demand > server_max_connections:
        findings.append(Finding(
            "over_connection_budget", True,
            f"The fleet wants {during_deploy} connections during a revision overlap, plus "
            f"{reserve} reserved, against a server that has {server_max_connections}. Over by "
            f"{demand - server_max_connections}."))

    vcpu_demand = vcpu(tiers, overlap=True)
    if vcpu_quota is None:
        findings.append(Finding(
            "vcpu_quota_unknown", False,
            f"The fleet wants {vcpu_demand} vCPU during a revision overlap. The environment's "
            f"quota was not supplied, so this was NOT checked — read it from Azure before "
            f"applying."))
    elif vcpu_demand > vcpu_quota:
        findings.append(Finding(
            "over_vcpu_quota", True,
            f"The fleet wants {vcpu_demand} vCPU during a revision overlap against a quota of "
            f"{vcpu_quota}. Over by {round(vcpu_demand - vcpu_quota, 3)}."))

    for tier in tiers:
        if tier.max_replicas > 0 and tier.max_replicas == tier.min_replicas:
            findings.append(Finding(
                "ceiling_equals_floor", False,
                f"{tier.name} is pinned at {tier.min_replicas}: a queue scaler attached to it "
                f"cannot add a replica, so queue-driven scaling for this role is inert."))

    return {
        "steady_connections": steady,
        "deploy_connections": during_deploy,
        "reserve": reserve,
        "server_max_connections": server_max_connections,
        "connection_headroom": server_max_connections - demand,
        "vcpu_demand": vcpu_demand,
        "vcpu_quota": vcpu_quota,
        "findings": [f.__dict__ for f in findings],
        "blocked": any(f.blocking for f in findings),
    }
