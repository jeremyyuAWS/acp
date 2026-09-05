"""Cost accounting and the budget gate.

THE TARGET, stated once so nothing has to re-derive it: **100,000 calls per US$1**, i.e.
US$1e-5 per call = 0.001 US cents per call. Everything here reports in those units, because
"cents" at this scale rounds to zero and hides the whole question.

Three pricing shapes, because the ladder spans three cost structures:

  free              rule code. Zero marginal cost per call; the only rung that clears the
                    budget by construction.
  per_token         a hosted API. Cost is a function of the prompt you actually sent, which is
                    why the harness records tokens rather than assuming a nominal call size.
  local_amortised   a self-hosted model. There is no per-call invoice, so the honest unit is
                    occupancy: seconds of a machine that costs `usd_per_hour` to keep running.
                    A 2s draft on a $1.10/hr GPU host is US$6.1e-4 — 61x the budget. That is
                    the finding, not a modelling artefact.

CACHING IS COUNTED, NOT ASSUMED. A repeated (candidate, prompt) pair costs zero on the second
occurrence, and the report shows the hit rate that produced the blended figure. This is the only
mechanism in the kit that can carry a model-backed tier under 0.001c/call, so it is measured
rather than claimed: turn the cache off with `--no-cache` and the same run reports the
uncached truth.
"""
from __future__ import annotations

from dataclasses import dataclass

TARGET_CALLS_PER_DOLLAR = 100_000
TARGET_USD_PER_CALL = 1.0 / TARGET_CALLS_PER_DOLLAR      # 1e-5 USD = 0.001 US cents


@dataclass(frozen=True)
class Pricing:
    kind: str = "free"                 # free | per_token | per_call | local_amortised
    usd_per_1k_in: float = 0.0
    usd_per_1k_out: float = 0.0
    usd_per_call: float = 0.0
    usd_per_hour: float = 0.0
    note: str = ""

    def usd(self, *, tokens_in: int = 0, tokens_out: int = 0, latency_s: float = 0.0) -> float:
        if self.kind == "free":
            return 0.0
        if self.kind == "per_call":
            return self.usd_per_call
        if self.kind == "per_token":
            return (tokens_in / 1000.0) * self.usd_per_1k_in + \
                   (tokens_out / 1000.0) * self.usd_per_1k_out
        if self.kind == "local_amortised":
            return latency_s * self.usd_per_hour / 3600.0
        raise ValueError(f"unknown pricing kind {self.kind!r}")


# Published list prices, USD per 1k tokens, recorded WITH the date they were read so a stale
# number is visible rather than authoritative. Provider-neutral by design: the kit's answer is a
# routing table, and a routing table that can only name one vendor is a procurement document.
#
# Nothing here is fetched at runtime. A price that moves is a one-line edit and a re-run.
PRICE_BOOK: dict[str, Pricing] = {
    # kind=per_token entries: (input, output) per 1k tokens.
    "hosted-frontier": Pricing("per_token", 0.015, 0.075, note="frontier tier, list 2026-09"),
    "hosted-mid": Pricing("per_token", 0.003, 0.015, note="mid tier, list 2026-09"),
    "hosted-small": Pricing("per_token", 0.0008, 0.004, note="small hosted tier, list 2026-09"),
    "hosted-nano": Pricing("per_token", 0.0001, 0.0004, note="cheapest hosted tier, list 2026-09"),
    # A self-hosted rung. $1.10/hr is a single mid-range GPU instance kept warm; change it to
    # your own number, it is the input that decides whether local beats hosted.
    "local-gpu": Pricing("local_amortised", usd_per_hour=1.10, note="one warm GPU host"),
    "local-cpu": Pricing("local_amortised", usd_per_hour=0.10, note="CPU-only container"),
    # Named vendor tiers, first-party list prices per 1M tokens converted to per 1k, with the
    # date the price was read. A named tier is preferred over the generic rungs above when the
    # candidate is that model: the generic ones are order-of-magnitude placeholders, and a
    # report that says "hosted-mid" cannot be checked against an invoice.
    "anthropic-opus-5": Pricing("per_token", 0.005, 0.025, note="Claude Opus 5, list 2026-06-24"),
    "anthropic-sonnet-5": Pricing("per_token", 0.002, 0.010,
                                  note="Claude Sonnet 5, list 2026-06-24"),
    "anthropic-haiku-4-5": Pricing("per_token", 0.001, 0.005,
                                   note="Claude Haiku 4.5, list 2026-06-24"),
    "free": Pricing("free", note="deterministic rule code"),
}


@dataclass
class Ledger:
    """Running cost/latency totals for one candidate over one corpus pass."""
    calls: int = 0
    billable_calls: int = 0
    cache_hits: int = 0
    retries: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    latency_s: float = 0.0
    usd: float = 0.0

    def record(self, pricing: Pricing, *, calls: int, tokens_in: int, tokens_out: int,
               latency_s: float, retries: int = 0, cached: bool = False) -> None:
        self.calls += calls
        self.retries += retries
        self.latency_s += latency_s
        if cached:
            self.cache_hits += calls
            return
        self.billable_calls += calls
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self.usd += pricing.usd(tokens_in=tokens_in, tokens_out=tokens_out, latency_s=latency_s)

    @property
    def usd_per_call(self) -> float:
        return self.usd / self.calls if self.calls else 0.0

    @property
    def cents_per_call(self) -> float:
        return self.usd_per_call * 100.0

    @property
    def calls_per_dollar(self) -> float:
        return float("inf") if self.usd <= 0 else self.calls / self.usd

    @property
    def cache_hit_rate(self) -> float:
        return self.cache_hits / self.calls if self.calls else 0.0

    def usd_per_verified_fix(self, verified: int) -> float:
        """The number that decides deployment. A candidate that is cheap per call and verifies
        nothing has an infinite cost per fix, and this is where that shows up."""
        return float("inf") if verified <= 0 else self.usd / verified

    def meets_budget(self, target_usd_per_call: float = TARGET_USD_PER_CALL) -> bool:
        return self.usd_per_call <= target_usd_per_call


def fmt_usd_per_call(usd: float) -> str:
    """0.001c is four zeros into a cents figure; print the unit the target is written in."""
    if usd <= 0:
        return "$0 (0.0000c/call, unbounded calls/$)"
    return f"${usd:.3e}/call ({usd * 100:.5f}c/call, {1.0 / usd:,.0f} calls/$)"


# A deliberately CONSERVATIVE per-call token estimate for the pre-flight, above what the local
# runs actually measured (~760 in / ~200 out). A budget guard that under-estimates is worse than
# none: it green-lights the run that overspends. These are the numbers a preflight quotes; the
# ledger still bills what the API reports.
ESTIMATE_TOKENS_IN = 900
ESTIMATE_TOKENS_OUT = 300
ESTIMATE_LATENCY_S = 3.0


def estimate_run_usd(pricing: Pricing, calls: int, *, tokens_in: int = ESTIMATE_TOKENS_IN,
                     tokens_out: int = ESTIMATE_TOKENS_OUT,
                     latency_s: float = ESTIMATE_LATENCY_S) -> float:
    """What a run of `calls` calls would cost at list price, before any cache hits.

    Cache hits only ever make it cheaper, so this is an upper bound on a run whose prompts
    repeat — which is the direction a spend guard has to err in.
    """
    return max(0, calls) * pricing.usd(tokens_in=tokens_in, tokens_out=tokens_out,
                                       latency_s=latency_s)


def required_cache_hit_rate(uncached_usd_per_call: float,
                            target: float = TARGET_USD_PER_CALL) -> float:
    """What fraction of calls must be cache hits for this tier to clear the budget.

    Blended cost is (1 - h) * uncached, so h = 1 - target/uncached. Returns 0.0 when the tier
    already clears it and 1.0 when no achievable hit rate does (a tier 100x over budget needs
    99% of its traffic to be repeats, which is a statement about the workload, not the model).
    """
    if uncached_usd_per_call <= target:
        return 0.0
    return min(1.0, 1.0 - target / uncached_usd_per_call)
