"""Running the registry against one target and assembling the report.

THE RUNNER MAKES THREE DECISIONS, and they are the ones that keep the report honest:

  1. A scenario whose required capabilities the target did not grant is SKIPPED, with a reason
     naming the missing capabilities. It is not attempted and then reported as broken.
  2. A scenario that raises is UNKNOWN, never fail. An exception means the suite fell over — a
     surface returned a shape nobody expected, a helper hit an edge — and nothing about the target
     was established by it. Reporting a suite bug as a target failure sends an operator to debug
     their cluster because our code has an AttributeError.
  3. Every result is timed, and the timings come from the backend's clock rather than `time`, so
     the fake's deterministic clock produces a deterministic report.

`NotAuthorized` IS DELIBERATELY NOT CAUGHT. It means a scenario asked for an effect the descriptor
never granted, which decision 1 should have made impossible — a bug in the scenario's `requires`
set. Swallowing it as `unknown` would leave the suite quietly attempting unauthorised mutations on
every target and reporting them as inconclusive.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .backend import ExecutionBackend, NotAuthorized
from .context import ArtifactSink, ScenarioContext
from .report import (Outcome, ScenarioResult, assert_no_secrets, build_report)
from .scenarios import REGISTRY, Scenario, mandatory_for
from .target import Target


@dataclass
class SuiteRun:
    report: dict
    results: list[ScenarioResult]

    @property
    def claim(self) -> dict:
        return self.report["supportClaim"]


def run_scenario(scn: Scenario, ctx: ScenarioContext) -> ScenarioResult:
    backend = ctx.backend
    started = backend.utcnow()
    t0 = backend.monotonic()
    missing = ctx.target.missing(scn.requires)
    if missing:
        outcome = Outcome.skipped(
            f"this target does not grant {', '.join(missing)}, which this scenario needs. "
            f"Nothing was attempted, and nothing about the target was established.",
            missingCapabilities=missing)
    else:
        try:
            outcome = scn.run(ctx)
        except NotAuthorized:
            raise
        except Exception as exc:                       # noqa: BLE001 — see the module docstring
            outcome = Outcome.unknown(
                f"the scenario raised {exc.__class__.__name__}: {exc}. That is a fault in the "
                f"suite, not a finding about the target.")
    return ScenarioResult(
        id=scn.id, title=scn.title, state=outcome.state, started_at=started,
        duration_seconds=max(0.0, backend.monotonic() - t0), detail=outcome.detail,
        artifacts=tuple(outcome.artifacts), evidence=dict(outcome.evidence))


def run_suite(*, target: Target, backend: ExecutionBackend,
              artifacts: ArtifactSink | None = None,
              scenario_ids: Sequence[str] | None = None) -> SuiteRun:
    """Run every registered scenario (or a named subset) and build the report.

    A SUBSET STILL REPORTS AGAINST THE FULL MANDATORY LISTS, which is what makes `--scenario` safe
    to expose. Running one scenario and reporting `mvpEligible: true` because the one thing you
    ran passed is the same "eligible because nothing else ran" failure the whole format exists to
    prevent; here the five scenarios that did not run appear in `mandatoryFailures` as absent, and
    the claim is false with a reason that says so.
    """
    sink = artifacts if artifacts is not None else ArtifactSink()
    ctx = ScenarioContext(target=target, backend=backend, artifacts=sink)
    chosen = [REGISTRY[sid] for sid in scenario_ids] if scenario_ids else list(REGISTRY.values())

    started_at = backend.utcnow()
    results = [run_scenario(scn, ctx) for scn in chosen]
    finished_at = backend.utcnow()

    report = build_report(
        target=target, results=results,
        scenario_ids=[s.id for s in chosen],
        mandatory_for_mvp=mandatory_for("mvp"),
        mandatory_for_supported=mandatory_for("supported"),
        started_at=started_at, finished_at=finished_at)

    # THE LAST THING BEFORE ANYONE SEES IT. Scenario evidence is written by ten functions and may
    # one day carry a response body or a command's stderr; the grep is what catches a credential
    # that no field-level discipline anticipated. It raises rather than scrubbing — see report.py.
    assert_no_secrets(report, target.secret_values())
    return SuiteRun(report=report, results=results)
