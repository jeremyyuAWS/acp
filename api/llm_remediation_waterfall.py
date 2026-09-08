"""Opt-in bounded remediation orchestration. No provider calls or source writes here.

Callbacks are trusted server adapters; model output is untrusted. See the contract
for durable persistence, reservation idempotency, and verifier responsibilities.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from hashlib import sha256
from html.parser import HTMLParser
import json
import re
from typing import Callable


@dataclass(frozen=True)
class Model:
    name: str
    max_cost_usd: str


@dataclass(frozen=True)
class Generation:
    patch: dict
    cost_usd: str
    call_id: str = ""


@dataclass(frozen=True)
class Evidence:
    verifier: str
    objective: bool | None
    issue_resolved: bool | None
    no_content_loss: bool | None
    no_regression: bool | None
    scope_preserved: bool | None
    reasons: tuple[str, ...] = ()

    def accepted(self) -> bool:
        return bool(self.verifier) and all(value is True for value in (
            self.objective, self.issue_resolved, self.no_content_loss,
            self.no_regression, self.scope_preserved))


@dataclass(frozen=True)
class Request:
    operation_id: str
    source: str
    family: str
    mode: str  # hitl or auto
    auto_eligible: bool = False  # server policy, never a model/user patch field
    expected_language: str = ""
    authority_ref: str = ""  # trusted metadata/human decision establishing language


TERMINAL = {"approved", "awaiting_approval", "exception"}
AUTO_FAMILIES = frozenset({"html-root-language"})


def _money(value: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("cost must be a decimal string")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid cost") from exc
    if not amount.is_finite() or amount < 0:
        raise ValueError("cost must be finite and nonnegative")
    return amount


def run_waterfall(
    request: Request,
    models: tuple[Model, Model],
    *,
    generate: Callable[[str, Request], Generation],
    reserve: Callable[[str, str, str], str],
    claim_dispatch: Callable[[str], bool],
    settle: Callable[[str, str], None],
    mark_uncertain: Callable[[str, str], None],
    apply_to_copy: Callable[[str, dict], str],
    verify: Callable[[Request, str], Evidence],
    persist: Callable[[dict], None],
    previous: dict | None = None,
) -> dict:
    """Try each distinct model once, checking independently after each candidate.

    persist must durably atomically commit or raise; its failures propagate and
    block subsequent effects. Caller must lock operation_id across load/run/save.
    Resume of an interrupted attempt stops for reconciliation, never re-calls a
    provider. A terminal snapshot is replayable without any side effects.
    """
    if request.mode not in {"hitl", "auto"} or not request.operation_id:
        raise ValueError("operation_id and mode hitl/auto required")
    if len(models) != 2 or any(not m.name for m in models) or models[0].name == models[1].name:
        raise ValueError("exactly two distinct models required")
    for model in models:
        _money(model.max_cost_usd)
    fingerprint = sha256(json.dumps({"request": asdict(request),
        "models": [asdict(m) for m in models]}, sort_keys=True).encode()).hexdigest()
    state = deepcopy(previous) if previous is not None else {
        "version": 1, "operation_id": request.operation_id, "fingerprint": fingerprint,
        "mode": request.mode, "family": request.family, "status": "ready",
        "attempts": [], "reasons": [], "candidate": None,
    }
    if state.get("version") != 1 or state.get("fingerprint") != fingerprint:
        raise ValueError("snapshot does not match request/models")

    def save() -> None:
        persist(deepcopy(state))

    def stop(reason: str) -> dict:
        state.update(status="exception", candidate=None)
        state["reasons"].append(reason)
        save()
        return deepcopy(state)

    if state["status"] in TERMINAL:
        return state
    if previous is not None and state["status"] != "ready":
        return stop("interrupted_attempt: reconcile reservation/provider usage; do not retry automatically")
    if previous is not None and state["attempts"]:
        return stop("invalid_resume: ready snapshot contains attempts")
    save()
    for number, model in enumerate(models, 1):
        attempt = {"number": number, "model": model.name,
            "idempotency_key": f"{request.operation_id}:{number}",
            "max_cost_usd": model.max_cost_usd, "cost_usd": None,
            "reservation_id": None, "evidence": None, "reasons": [], "status": "reserving"}
        state["attempts"].append(attempt)
        state["status"] = "running"
        save()  # before reserving; interruption can leave an unknown reservation
        try:
            token = reserve(attempt["idempotency_key"], model.name, model.max_cost_usd)
            if not isinstance(token, str) or not token:
                raise ValueError("reservation must return a nonempty ID")
            attempt.update(reservation_id=token, status="dispatching")
        except Exception as exc:
            attempt["reasons"].append(f"reservation_failed:{type(exc).__name__}")
            return stop("cost_failure: reservation not confirmed; generation blocked")
        save()
        try:
            if claim_dispatch(token) is not True:
                raise ValueError("dispatch was not exclusively claimed")
        except Exception as exc:
            attempt["reasons"].append(f"dispatch_denied_or_unknown:{type(exc).__name__}")
            return stop("cost_failure: exclusive dispatch not confirmed; reconcile reservation")
        attempt["status"] = "generating"
        save()
        try:
            generated = generate(model.name, request)
            if not isinstance(generated, Generation):
                raise ValueError("invalid generation envelope")
            cost = _money(generated.cost_usd)
            attempt.update(cost_usd=str(cost), call_id=generated.call_id)
        except Exception as exc:
            attempt["reasons"].append(f"generation_or_usage_unknown:{type(exc).__name__}")
            try:
                mark_uncertain(token, "generation_or_usage_unknown")
            except Exception as mark_exc:
                attempt["reasons"].append(f"uncertainty_record_failed:{type(mark_exc).__name__}")
            return stop("unknown_usage: keep reservation held for reconciliation")
        attempt["status"] = "settling"
        save()
        try:
            settle(token, str(cost))
        except Exception as exc:
            attempt["reasons"].append(f"settlement_failed:{type(exc).__name__}")
            return stop("cost_failure: reconcile held reservation and actual usage")
        if cost > _money(model.max_cost_usd):
            return stop("cost_failure: actual usage exceeded reservation; no approval or further attempts")
        attempt["status"] = "verifying"
        save()
        try:
            candidate = apply_to_copy(request.source, deepcopy(generated.patch))
            if not isinstance(candidate, str):
                raise ValueError("candidate must be text")
            attempt["candidate_sha256"] = sha256(candidate.encode()).hexdigest()
            evidence = verify(request, candidate)
            if not isinstance(evidence, Evidence):
                raise ValueError("invalid independent evidence")
            attempt["evidence"] = asdict(evidence)
        except Exception as exc:
            attempt["reasons"].append(f"application_or_verification_failed:{type(exc).__name__}")
            return stop("unknown_evidence: application/verifier failed")
        if evidence.accepted():
            attempt["status"] = "verified"
            state["candidate"] = candidate
            state["status"] = "awaiting_approval"
            if request.mode == "auto" and request.auto_eligible is True and request.family in AUTO_FAMILIES:
                state["status"] = "approved"
                state["reasons"].append("eligible_fix_independently_verified")
            else:
                state["reasons"].append("human_approval_required")
            save()
            return deepcopy(state)
        attempt["status"] = "rejected"
        attempt["reasons"].extend(evidence.reasons)
        save()
        if any(value is not True and value is not False for value in (
            evidence.objective, evidence.issue_resolved, evidence.no_content_loss,
            evidence.no_regression, evidence.scope_preserved)) or not evidence.verifier:
            return stop("unknown_evidence: independent verification incomplete")
        if evidence.objective is not True:
            return stop("subjective_decision: requires human assessment")
    return stop("attempts_exhausted: both models failed independent verification")


# Deliberately conservative grammar. Other HTML goes to manual review, rather
# than pretending this helper is a general HTML parser or language detector.
_ROOT = re.compile(r'\A(?P<prefix>\s*(?:<!DOCTYPE html>\s*)?)<html(?: lang="[A-Za-z0-9-]+")?>(?P<body>[\s\S]*)</html>(?P<suffix>\s*)\Z')
_LANGUAGE = re.compile(r"[a-z]{2,3}(?:-[A-Z]{2})?\Z")


def apply_html_language(source: str, patch: dict) -> str:
    """Apply a restricted structured patch to an immutable source copy."""
    if set(patch) != {"language"} or not isinstance(patch["language"], str) or not _LANGUAGE.fullmatch(patch["language"]):
        raise ValueError("only a language patch using the supported tag subset is allowed")
    root = _ROOT.fullmatch(source)
    if not root:
        raise ValueError("unsupported root markup")
    return f'{root["prefix"]}<html lang="{patch["language"]}">{root["body"]}</html>{root["suffix"]}'


def verify_html_language(request: Request, candidate: str) -> Evidence:
    """Check exact authorized transformation; never consult model explanations."""
    unknown = Evidence("html-root-language-v1", None, None, None, None, None,
        ("unsupported markup, family, or missing authoritative language evidence",))
    if request.family != "html-root-language" or not request.authority_ref or not _LANGUAGE.fullmatch(request.expected_language):
        return unknown
    try:
        expected = apply_html_language(request.source, {"language": request.expected_language})
        class Roots(HTMLParser):
            starts = 0
            ends = 0
            def handle_starttag(self, tag, attrs):
                if tag == "html":
                    self.starts += 1
            def handle_endtag(self, tag):
                if tag == "html":
                    self.ends += 1
        parser = Roots()
        parser.feed(request.source)
        parser.close()
        if parser.starts != 1 or parser.ends != 1:
            return unknown
    except (ValueError, TypeError):
        return unknown
    exact = candidate == expected
    return Evidence("html-root-language-v1", True, exact, exact, exact, exact,
        ("exact authorized root-language substitution; all other characters preserved",) if exact
        else ("candidate differs from the authorized transformation",))


class BudgetAdapter:
    """Bind a spending ledger to a run; generation never receives this adapter.

    The budget must already exist in USD. pricing_refs are trusted server pricing
    snapshots identifying a verified bound, not values supplied by the model.
    """

    def __init__(self, ledger, owner_id: str, run_id: str, pricing_refs: dict[str, str]):
        self.ledger = ledger
        self.owner_id = owner_id
        self.run_id = run_id
        self.pricing_refs = dict(pricing_refs)

    @staticmethod
    def units(usd: str) -> int:
        return int((_money(usd) * 1_000_000).to_integral_value(rounding=ROUND_CEILING))

    def reserve(self, attempt_id: str, model: str, maximum: str) -> str:
        pricing_ref = self.pricing_refs[model]
        if not pricing_ref:
            raise ValueError("verified pricing reference required")
        self.ledger.reserve(self.owner_id, self.run_id, attempt_id,
            max_cost_units=self.units(maximum), pricing_ref=pricing_ref)
        return attempt_id

    def claim_dispatch(self, token: str) -> bool:
        return self.ledger.claim_dispatch(self.owner_id, self.run_id, token)

    def settle(self, token: str, actual: str) -> None:
        result = self.ledger.settle(self.owner_id, self.run_id, token,
            actual_cost_units=self.units(actual))
        if result.get("state") != "settled":
            raise ValueError("ledger did not confirm settlement within the bound")

    def mark_uncertain(self, token: str, reason: str) -> None:
        self.ledger.mark_uncertain(self.owner_id, self.run_id, token)
