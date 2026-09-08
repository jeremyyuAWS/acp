"""The acceptance report: the contract, the eligibility rule, and the redaction guarantee.

THE ELIGIBILITY RULE IS THE POINT OF THE WHOLE ARTIFACT. Everything else here is bookkeeping.

    mvpEligible is true ONLY when every scenario in mandatoryForMvp has state == "pass".

`skip` is not a pass. `unknown` is not a pass. A run in which nothing could be executed reports
`mvpEligible: false` with a reason that NAMES the scenarios that did not pass — because the
failure mode this format exists to prevent is a green report produced by a suite that did nothing.
That failure is easy to ship by accident and almost impossible to notice afterwards: the report
looks identical to a real pass, and the only difference is in states nobody aggregated.

WHY `skip` AND `unknown` ARE SEPARATE STATES rather than one "did not pass". They are different
facts about different things, and an operator does different work about each:

    skip     the TARGET cannot host this scenario (no fault injection, no previous release).
             Nothing is wrong; the claim is simply not available on this target yet.
    unknown  the SUITE could not establish an answer — a probe errored, the build does not serve
             a surface the scenario needs, a timeout. Somebody has to go and look.

Collapsing them would make "we did not try" and "we tried and could not tell" the same line in a
report that a support decision is made from. `acpctl doctor` reached the same conclusion for the
same reason (packaging/cli/acpctl/doctor.py, "Three outcomes, not two"); this file adds the fourth
state because a suite, unlike a preflight check, can be pointed at a target that was never meant
to host half of it.

NO SECRET REACHES THE FILE, AND THAT IS CHECKED RATHER THAN PROMISED. `Target.as_report_block()`
is an allow-list of five fields, and `assert_no_secrets` then greps the SERIALISED report for
every credential value the descriptor carried and refuses to write a file containing one. Two
mechanisms, because the first is a discipline and the second is a test: a field added next
quarter that quietly carries a token past the allow-list still trips the grep.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import REPORT_API_VERSION, REPORT_KIND, SUITE_VERSION

PASS, FAIL, SKIP, UNKNOWN = "pass", "fail", "skip", "unknown"
STATES = (PASS, FAIL, SKIP, UNKNOWN)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "report.schema.json"


class SecretLeak(RuntimeError):
    """A value from the target descriptor was found in the serialised report.

    Raised, never logged-and-continued: the report is a file that gets attached to tickets and
    mailed to customers, and the one outcome worse than no report is a report with a token in it.
    """


@dataclass(frozen=True)
class Outcome:
    """What a scenario body returns. Four constructors, so the state is chosen deliberately.

    `evidence` is the free-form block a reader needs to believe the state: the versions observed,
    the counts compared, the artifact locations. It is what makes a `pass` auditable six months
    later, and it is why the schema leaves it open rather than pinning a shape per scenario.
    """

    state: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)
    artifacts: tuple[str, ...] = ()

    @classmethod
    def passed(cls, detail: str, **evidence: Any) -> "Outcome":
        return cls(PASS, detail, evidence)

    @classmethod
    def failed(cls, detail: str, **evidence: Any) -> "Outcome":
        return cls(FAIL, detail, evidence)

    @classmethod
    def skipped(cls, detail: str, **evidence: Any) -> "Outcome":
        return cls(SKIP, detail, evidence)

    @classmethod
    def unknown(cls, detail: str, **evidence: Any) -> "Outcome":
        """The result could not be established. NEVER used for "the target misbehaved" — that is
        `failed`. Using it for both would mean a broken target and an unreachable one produce the
        same report, and only one of them is somebody's outage."""
        return cls(UNKNOWN, detail, evidence)

    def with_artifacts(self, paths: Iterable[str]) -> "Outcome":
        return Outcome(self.state, self.detail, self.evidence, tuple(paths))


@dataclass
class ScenarioResult:
    id: str
    title: str
    state: str
    started_at: datetime
    duration_seconds: float
    detail: str
    artifacts: tuple[str, ...] = ()
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "state": self.state,
            "startedAt": _iso(self.started_at),
            "durationSeconds": round(float(self.duration_seconds), 3),
            "detail": self.detail,
            "artifacts": list(self.artifacts),
            "evidence": self.evidence,
        }


def _iso(moment: datetime) -> str:
    """RFC3339 with a `Z`, because that is what every other timestamp in this repo's operational
    output uses and a mixed-format field is a field consumers parse twice."""
    text = moment.isoformat()
    return text.replace("+00:00", "Z")


def summarize(results: Sequence[ScenarioResult], mandatory: Iterable[str]) -> dict[str, Any]:
    counts = {state: sum(1 for r in results if r.state == state) for state in STATES}
    by_id = {r.id: r.state for r in results}
    mandatory_ids = list(dict.fromkeys(mandatory))
    # EVERY mandatory scenario that did not PASS, whatever the reason — a missing one included.
    # The field is read as "what stands between this target and the claim", and a mandatory
    # scenario that skipped stands there just as squarely as one that failed. The per-scenario
    # `state` says which it was; hiding skips here would produce the contradiction that makes a
    # report unreadable: zero failures and no eligibility, with nothing connecting the two.
    mandatory_failures = [sid for sid in mandatory_ids if by_id.get(sid) != PASS]
    return {
        "pass": counts[PASS], "fail": counts[FAIL],
        "skip": counts[SKIP], "unknown": counts[UNKNOWN],
        "mandatoryFailures": mandatory_failures,
    }


def support_claim(results: Sequence[ScenarioResult], *, mandatory_for_mvp: Sequence[str],
                  mandatory_for_supported: Sequence[str]) -> dict[str, Any]:
    """The two eligibility booleans and the reason, derived from states alone.

    `supportedEligible` requires the MVP set as well as its own: `supported` is a superset claim,
    and a target that could restore a backup but cannot register a worker is not supported by any
    reading. Making that explicit here rather than assuming the caller passes a combined list is
    what stops a future edit from producing a target certified for disaster recovery and nothing
    else.

    An EMPTY mandatory list yields false, not vacuous truth. `all([])` is true, and a mandatory
    list that arrived empty through a bug would otherwise certify anything at all — the exact
    "eligible because nothing ran" failure, arriving through the rule rather than the results.
    """
    by_id = {r.id: r.state for r in results}
    mvp_missing = [sid for sid in mandatory_for_mvp if by_id.get(sid) != PASS]
    sup_missing = [sid for sid in mandatory_for_supported if by_id.get(sid) != PASS]

    mvp_eligible = bool(mandatory_for_mvp) and not mvp_missing
    supported_eligible = (mvp_eligible and bool(mandatory_for_supported) and not sup_missing)

    if not mandatory_for_mvp:
        reason = ("no mandatory scenarios were declared for the MVP claim, so nothing was "
                  "established; a claim needs a list to check against")
    elif mvp_missing:
        reason = ("not eligible for a Kubernetes MVP claim: " +
                  _name_states(mvp_missing, by_id) +
                  ". Only `pass` counts — a skipped or unknown scenario has established nothing.")
    elif sup_missing:
        reason = ("eligible for a Kubernetes MVP claim; not eligible for `supported`: " +
                  _name_states(sup_missing, by_id) +
                  ". Only `pass` counts — a skipped or unknown scenario has established nothing.")
    else:
        reason = ("every mandatory scenario passed for both claims on this target and this "
                  "release")
    return {"mvpEligible": mvp_eligible, "supportedEligible": supported_eligible, "reason": reason}


def _name_states(ids: Sequence[str], by_id: dict[str, str]) -> str:
    """`worker-restart did not run (missing), backup-restore skipped` — ids AND what happened.

    Naming the ids is not a nicety. The report is often read by somebody who did not run the
    suite, and "3 mandatory scenarios did not pass" sends them to grep the scenarios array by
    hand — which is where the reader who does not bother concludes it was probably fine.
    """
    parts = []
    for sid in ids:
        state = by_id.get(sid)
        parts.append(f"{sid} {state}" if state else f"{sid} did not run (missing from the results)")
    return ", ".join(parts)


def build_report(*, target, results: Sequence[ScenarioResult], scenario_ids: Sequence[str],
                 mandatory_for_mvp: Sequence[str], mandatory_for_supported: Sequence[str],
                 started_at: datetime, finished_at: datetime,
                 suite_version: str = SUITE_VERSION) -> dict[str, Any]:
    """Assemble the report. Pure: it reads results and a target, and touches nothing."""
    release = target.release
    duration = (finished_at - started_at).total_seconds()
    mandatory_all = list(dict.fromkeys(list(mandatory_for_mvp) + list(mandatory_for_supported)))
    return {
        "apiVersion": REPORT_API_VERSION,
        "kind": REPORT_KIND,
        "target": target.as_report_block(),
        "release": {
            "version": release.version,
            "revision": int(release.revision),
            "pinned": bool(release.pinned),
            "components": {name: dict(entry) for name, entry in release.components.items()},
        },
        "suite": {
            "version": suite_version,
            "scenarioIds": list(scenario_ids),
            "mandatoryForMvp": list(mandatory_for_mvp),
            "mandatoryForSupported": list(mandatory_for_supported),
        },
        "startedAt": _iso(started_at),
        "finishedAt": _iso(finished_at),
        "durationSeconds": round(duration, 3),
        "scenarios": [r.as_dict() for r in results],
        "summary": summarize(results, mandatory_all),
        "supportClaim": support_claim(
            results, mandatory_for_mvp=mandatory_for_mvp,
            mandatory_for_supported=mandatory_for_supported),
    }


# ── the schema, and the evaluator that enforces it ────────────────────────────

def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _validator_class():
    """acpctl's JSON Schema evaluator, reused rather than reimplemented.

    WHY REUSE. `packaging/cli/acpctl/jsonschema_mini.py` already implements exactly the keyword
    subset this repository's schemas use, and `tests/test_packaging_schema.py` keeps it honest.
    A second evaluator here would be a second thing to keep in step with the first, and the way
    that failure shows up is the worst kind: an evaluator that ignores a keyword reports a
    document as VALID, so the drift is invisible until a malformed report is consumed downstream.

    Both packages ship in the same air-gapped bundle (PRD §17), so the import is available
    wherever the suite runs. The sys.path insert covers being run from a checkout without
    PYTHONPATH set for both directories.
    """
    try:
        from acpctl.jsonschema_mini import Validator
    except ImportError:
        cli_dir = SCHEMA_PATH.parent.parent / "cli"
        if str(cli_dir) not in sys.path:
            sys.path.insert(0, str(cli_dir))
        from acpctl.jsonschema_mini import Validator
    return Validator


def validate_report(report: dict) -> list[tuple[str, str]]:
    """(path, message) pairs. Empty means the report satisfies the published contract."""
    return _validator_class()(load_schema()).validate(report)


# ── redaction ─────────────────────────────────────────────────────────────────

def assert_no_secrets(report: dict, secrets: Iterable[str]) -> None:
    """Refuse to emit a report containing any of `secrets`.

    THE GREP IS THE GUARANTEE, not the allow-list above it. Scenario evidence is written by ten
    different functions and may one day include a response body, a kubectl error, a helm output —
    any of which can carry a token that no field-level discipline anticipated. So the check is on
    the SERIALISED text, after everything has been assembled, and it fails the run rather than
    scrubbing: a suite that silently rewrote its own evidence would hide the fact that a scenario
    is collecting secrets, and the scenario would go on doing it.

    Very short values are ignored. A one-character "credential" would match everywhere and turn
    every run into a false leak — and the failure mode of a check that fires constantly is that
    somebody removes it.
    """
    text = json.dumps(report, sort_keys=True)
    for secret in secrets:
        value = str(secret).strip()
        if len(value) < 6:
            continue
        if value in text:
            raise SecretLeak(
                f"a value from the target descriptor appears in the report "
                f"({len(value)} characters, starting {value[:2]!r}). The report is a document "
                f"that leaves the customer's control; find which scenario's evidence carries it "
                f"and stop collecting it, rather than scrubbing it here.")


def dump(report: dict) -> str:
    """Stable JSON: sorted keys and a trailing newline, so two runs diff cleanly and a report can
    live in git next to the target descriptor that produced it."""
    return json.dumps(report, indent=2, sort_keys=True) + "\n"
