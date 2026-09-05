"""The run loop: candidates x cases x repeats, with the meter running.

REPEATS ARE THE POINT, not a formality. A model that fixes a case on two runs in three is not a
90%-accurate model, it is a 67% one, and a single pass cannot tell those apart. The default is
three; the report carries the spread, and a candidate whose per-repeat scores disagree is
flagged as nondeterministic rather than averaged into a clean-looking number.

THE CACHE IS PER-REPEAT, deliberately. Caching across repeats would make repeats 2 and 3 free
AND identical, which would zero the variance the repeats exist to measure. Within a repeat it
models the real deployment: an estate has thousands of identical 'click here' links, and the
second one is a cache hit, not a second inference.
"""
from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from typing import Iterable

from .candidates import Candidate, Response
from .cost import Ledger
from .graders import CaseResult, grade_case
from .schema import Case


@dataclass
class RepeatResult:
    index: int
    results: list[CaseResult] = field(default_factory=list)
    ledger: Ledger = field(default_factory=Ledger)


@dataclass
class RunResult:
    candidate: str
    tier: int
    pricing_kind: str
    repeats: list[RepeatResult] = field(default_factory=list)
    wall_s: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def all_results(self) -> list[CaseResult]:
        return [r for rep in self.repeats for r in rep.results]

    @property
    def ledger(self) -> Ledger:
        total = Ledger()
        for rep in self.repeats:
            total.calls += rep.ledger.calls
            total.billable_calls += rep.ledger.billable_calls
            total.cache_hits += rep.ledger.cache_hits
            total.retries += rep.ledger.retries
            total.tokens_in += rep.ledger.tokens_in
            total.tokens_out += rep.ledger.tokens_out
            total.latency_s += rep.ledger.latency_s
            total.usd += rep.ledger.usd
        return total


def run(candidate: Candidate, cases: Iterable[Case], *, repeats: int = 3,
        cache: bool = True) -> RunResult:
    cases = list(cases)
    out = RunResult(candidate=candidate.name, tier=candidate.tier,
                    pricing_kind=candidate.pricing.kind)
    t0 = time.perf_counter()
    for i in range(repeats):
        rep = RepeatResult(index=i)
        seen: dict[str, Response] = {}
        for case in cases:
            key = candidate.prompt_key(case)
            if cache and key in seen:
                resp = copy.deepcopy(seen[key])
                resp.cached = True
                resp.latency_s = 0.0
            else:
                try:
                    resp = candidate.respond(case)
                except Exception as e:            # a candidate that throws is a result, not a crash
                    out.errors.append(f"{case.case_id}: {type(e).__name__}: {e}")
                    resp = Response(plan=[], parse_error=f"{type(e).__name__}: {e}")
                if cache and not resp.parse_error:
                    seen[key] = copy.deepcopy(resp)
            before = rep.ledger.usd
            rep.ledger.record(candidate.pricing, calls=resp.calls, tokens_in=resp.tokens_in,
                              tokens_out=resp.tokens_out, latency_s=resp.latency_s,
                              retries=resp.retries, cached=resp.cached)
            result = grade_case(case, resp)
            result.candidate = candidate.name
            result.usd = rep.ledger.usd - before
            rep.results.append(result)
        out.repeats.append(rep)
    out.wall_s = time.perf_counter() - t0
    return out
