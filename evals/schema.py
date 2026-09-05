"""Case schema for the Remediation Evals Kit, and a validator with no third-party dependency.

WHY A HAND-WRITTEN VALIDATOR. tests/requirements.txt is the whole of what CI installs, and
adding `jsonschema` to it to check ~15 keys buys nothing a function cannot. The validator is
strict on purpose: an unknown key is an ERROR, not a warning. A case that carries
`expected_diagnosis` where the grader reads `expected_dx` grades as "candidate got nothing
right", which reads as a model failure and is a typo.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = ROOT / "evals" / "cases"

# The six suites of the kit. A case belongs to exactly one, because the corpus mix is a
# deliberate quota (see scripts/gen_remediation_eval_corpus.py) and a case counted twice
# distorts it.
SUITES = ("detection", "diagnosis", "planning", "execution", "safety", "operational")

RISK_TIERS = ("low", "medium", "high")

# The action vocabulary. Deliberately ACP's own rather than a generic incident-response one:
# these are the moves the product actually makes, so a candidate that scores here is being
# measured against the job.
ACTIONS = (
    "apply_deterministic",   # rule-code fix; no model judgement (the "auto" lane)
    "propose_value",         # prefilled value a human approves (the "assisted" lane)
    "request_approval",      # ask before mutating; prerequisite of an assisted apply
    "apply_approved",        # write a value that carries an approval token
    "escalate",              # hand to a human with the evidence
    "abstain",               # decline to act, with a reason
    "no_action",             # explicitly nothing to do (a clean case)
    # --- everything below is a violation if it is executed; listed so a case can forbid it
    "apply_without_approval",
    "rewrite_document",
    "delete_content",
    "disable_check",         # make the finding go away by silencing the detector
    "mark_pass",             # assert conformance rather than achieve it
    "disclose",              # emit case-declared secret material
)

MUTATING_ACTIONS = frozenset({
    "apply_deterministic", "apply_approved", "apply_without_approval",
    "rewrite_document", "delete_content", "disable_check", "mark_pass",
})

_REQUIRED = (
    "case_id", "suite", "environment", "observations", "allowed_actions",
    "forbidden_actions", "expected_diagnosis", "acceptable_remediations",
    "verification", "rollback_verification", "risk_tier", "automation_eligible",
)
_OPTIONAL = ("world", "secrets", "injection", "human_minutes", "notes", "must_abstain")


@dataclass(frozen=True)
class Observation:
    """One signal a candidate sees. `defect` is the ground truth for the detection suite;
    everything with defect=False is a distractor, which is what makes precision measurable."""
    id: str
    kind: str
    text: str
    defect: bool = False
    criterion: str | None = None


@dataclass(frozen=True)
class Case:
    case_id: str
    suite: str
    environment: dict[str, Any]
    observations: tuple[Observation, ...]
    allowed_actions: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    expected_diagnosis: dict[str, Any]
    acceptable_remediations: tuple[dict[str, Any], ...]
    verification: tuple[dict[str, Any], ...]
    rollback_verification: tuple[dict[str, Any], ...]
    risk_tier: str
    automation_eligible: bool
    world: dict[str, Any] = field(default_factory=dict)
    secrets: tuple[str, ...] = ()
    injection: str | None = None
    human_minutes: float = 0.0
    notes: str = ""
    must_abstain: bool = False

    @property
    def defect_ids(self) -> frozenset[str]:
        return frozenset(o.id for o in self.observations if o.defect)

    @property
    def scope(self) -> frozenset[str]:
        """Field ids this case authorises a candidate to write. Anything else is blast radius."""
        return frozenset(self.world.get("scope", ()))


class CaseError(ValueError):
    pass


def validate(raw: dict[str, Any], *, source: str = "<dict>") -> None:
    """Raise CaseError on anything the graders could silently mis-read."""
    def bad(msg: str) -> None:
        raise CaseError(f"{source}: {msg}")

    missing = [k for k in _REQUIRED if k not in raw]
    if missing:
        bad(f"missing required key(s): {', '.join(missing)}")
    unknown = [k for k in raw if k not in _REQUIRED + _OPTIONAL]
    if unknown:
        bad(f"unknown key(s): {', '.join(sorted(unknown))}")
    if raw["suite"] not in SUITES:
        bad(f"suite {raw['suite']!r} not one of {SUITES}")
    if raw["risk_tier"] not in RISK_TIERS:
        bad(f"risk_tier {raw['risk_tier']!r} not one of {RISK_TIERS}")
    if not isinstance(raw["automation_eligible"], bool):
        bad("automation_eligible must be a bool")

    seen: set[str] = set()
    for obs in raw["observations"]:
        for k in ("id", "kind", "text"):
            if k not in obs:
                bad(f"observation missing {k!r}")
        if obs["id"] in seen:
            bad(f"duplicate observation id {obs['id']!r}")
        seen.add(obs["id"])

    for group in ("allowed_actions", "forbidden_actions"):
        for a in raw[group]:
            if a not in ACTIONS:
                bad(f"{group}: unknown action {a!r}")
    overlap = set(raw["allowed_actions"]) & set(raw["forbidden_actions"])
    if overlap:
        bad(f"action(s) both allowed and forbidden: {', '.join(sorted(overlap))}")

    for rem in raw["acceptable_remediations"]:
        if rem.get("action") not in ACTIONS:
            bad(f"acceptable_remediations: unknown action {rem.get('action')!r}")
        if rem["action"] in raw["forbidden_actions"]:
            bad(f"acceptable_remediations names forbidden action {rem['action']!r}")

    known_checks = {"criterion_cleared", "field_equals", "field_matches", "field_absent",
                    "approval_recorded", "no_out_of_scope_writes", "state_restored",
                    "escalated"}
    for group in ("verification", "rollback_verification"):
        for chk in raw[group]:
            if chk.get("check") not in known_checks:
                bad(f"{group}: unknown check {chk.get('check')!r}")

    # A must-abstain case whose acceptable remediations include a mutation is self-contradictory:
    # it would grade a correct refusal as a miss and an unsafe write as a pass.
    if raw.get("must_abstain"):
        for rem in raw["acceptable_remediations"]:
            if rem["action"] in MUTATING_ACTIONS:
                bad(f"must_abstain case accepts mutating action {rem['action']!r}")
        if raw["automation_eligible"]:
            bad("must_abstain case cannot be automation_eligible")


def from_dict(raw: dict[str, Any], *, source: str = "<dict>") -> Case:
    validate(raw, source=source)
    obs = tuple(Observation(id=o["id"], kind=o["kind"], text=o["text"],
                            defect=bool(o.get("defect", False)),
                            criterion=o.get("criterion"))
                for o in raw["observations"])
    return Case(
        case_id=raw["case_id"], suite=raw["suite"], environment=raw["environment"],
        observations=obs,
        allowed_actions=tuple(raw["allowed_actions"]),
        forbidden_actions=tuple(raw["forbidden_actions"]),
        expected_diagnosis=raw["expected_diagnosis"],
        acceptable_remediations=tuple(raw["acceptable_remediations"]),
        verification=tuple(raw["verification"]),
        rollback_verification=tuple(raw["rollback_verification"]),
        risk_tier=raw["risk_tier"], automation_eligible=raw["automation_eligible"],
        world=raw.get("world", {}), secrets=tuple(raw.get("secrets", ())),
        injection=raw.get("injection"), human_minutes=float(raw.get("human_minutes", 0.0)),
        notes=raw.get("notes", ""), must_abstain=bool(raw.get("must_abstain", False)),
    )


def load_cases(path: Path | str = CASES_DIR, *, suites: tuple[str, ...] | None = None,
               limit: int | None = None) -> list[Case]:
    """Load every case file under `path`, sorted by case_id so a run is reproducible."""
    p = Path(path)
    files = sorted(p.glob("*.json")) if p.is_dir() else [p]
    cases: list[Case] = []
    for f in files:
        payload = json.loads(f.read_text())
        for raw in (payload if isinstance(payload, list) else [payload]):
            cases.append(from_dict(raw, source=f.name))
    ids = [c.case_id for c in cases]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise CaseError(f"duplicate case_id(s) across corpus: {', '.join(sorted(dupes))}")
    cases.sort(key=lambda c: c.case_id)
    if suites:
        cases = [c for c in cases if c.suite in suites]
    return cases[:limit] if limit else cases
