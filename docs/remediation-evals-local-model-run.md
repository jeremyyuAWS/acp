# First real-model run — two local models against the Remediation Evals Kit

**Date:** 2026-09-04 · **Corpus:** the shipped 100 cases · **Repeats:** 1 · **Report:**
[`evals/reports/2026-09-04-local-models.json`](../evals/reports/2026-09-04-local-models.json)
(re-render it with `evals.report.render_markdown` — the stored artifact is the raw run output
and predates the coverage field described below, which the renderer derives from it)

**Result in one line: neither local model earned a single category.** Both fail every safety
gate, and the routing ladder sent 50% of the corpus to a human and the other 50% to rule code —
**0% of cases went to a model**.

A second run added **constrained decoding** as the control for the format failures below. It
fixed the format completely and changed no gate: [jump to it](#constrained-decoding--the-control-run).

---

## Setup

| | |
|---|---|
| Host | 4 vCPU, 15 GB RAM, **no GPU** (the session container) |
| Runtime | Ollama 0.33.3, native, CPU inference |
| Models | `qwen2.5:0.5b` (397 MB), `llama3.2:1b` (1.3 GB) |
| Baseline | `rules-only` — ACP's deterministic auto lane, $0/call |
| Pricing | `local-cpu`: $0.10/hr of occupancy. Change that rate and every dollar figure moves; the ranking does not. |
| Prompt | the kit's own, unmodified — one call per case, temperature 0, `num_predict` 400 |

`llama3.1:8b` (what ACP ships for text) was not run: on 4 CPU cores it is minutes per case, and
the two rungs below it already answer the question.

## Headline

| candidate | VARR | fix rate | critical violations | rollback | auto-precision | abstention | c/call | calls/$ | gates |
|---|---|---|---|---|---|---|---|---|---|
| `rules-only` | **45%** | 63% | 1 | 100% | 97% | 100% | 0.00000 | ∞ | FAIL (1 critical) |
| `ollama:qwen2.5:0.5b` | **0%** | 20% | **48** | 100% | 0% | 61% | 0.01746 | 5,726 | FAIL (4 of 5) |
| `ollama:llama3.2:1b` | **0%** | 7% | **9** | 95% | 0% | 18% | 0.02999 | 3,335 | FAIL (4 of 5) |

## Per stage — where each one actually breaks

| candidate | detect P | detect R | detect F1 | diagnosis | Brier | planning | unusable output | latency/case |
|---|---|---|---|---|---|---|---|---|
| `rules-only` | 100% | 100% | 1.00 | 100% | 0.403 | 99% | 0 | 0.00s |
| `qwen2.5:0.5b` | 9% | 17% | 0.11 | 1% | 0.407 | 41% | **12 / 100** | 6.29s |
| `llama3.2:1b` | 15% | 38% | 0.21 | 5% | 0.184 | 18% | **62 / 100** | 10.79s |

Two different failure modes, and the stage split is what separates them:

- **`llama3.2:1b` mostly fails to answer at all** — 62 of 100 responses carried no usable JSON
  object. It is safer (9 critical violations) largely because it acted 7 times.
- **`qwen2.5:0.5b` answers confidently and wrongly** — it acted autonomously 52 times, earning
  48 critical violations, and its diagnosis score is 1%: it copies the response template's
  placeholders back verbatim (`"criterion": "X.Y.Z"`, `"severity": "A|AA|AAA"`, the filename as
  the component). A schema-shaped reply that carries no content is the worst case for a
  downstream pipeline, because it parses.

**Neither abstains reliably**, which is the finding that matters most: on the 15 must-abstain
cases plus the ineligible ones, abstention correctness is 61% and 18% against a 95% gate. These
are the cases where a WCAG criterion is `lane=human` in ACP's own table — reading level,
keyboard traps, reflow — and a plausible-looking value silently overwrites authorial intent.

## Cost — the budget is the smaller problem

At `local-cpu` pricing, per call:

| | c/call | calls per $1 | vs. 100,000 target | cache hit rate it would need |
|---|---|---|---|---|
| `qwen2.5:0.5b` | 0.01746 | 5,726 | 17x over | **95%** |
| `llama3.2:1b` | 0.02999 | 3,335 | 30x over | **97%** |
| `rules-only` | 0 | ∞ | clears | — |

Measured cache hit rate this run: 15% and 8%. So even the cheapest useful-looking rung is an
order of magnitude away on cost — and it would not matter if it were free, because its VARR is 0.

For reference, the named hosted tiers now in the price book (list, read 2026-06-24) at the same
700-in/60-out call: Claude Haiku 4.5 **0.1c/call (1,000 calls/$)**, Sonnet 5 0.2c, Opus 5 0.5c.
Against a 0.001c budget, Haiku-class is 100x over per call — which does not rule it out, but does
bound it: **at most ~1% of calls can reach that tier** with the rest on rule code.

## What the ladder did — and the kit change it forced

Routing outcome: **34 categories → `rules-only`, 25 categories → human, 0 → a model.**

The report's summary line said `Blended: $0/call — target 100,000 calls/$ MET`. That was true
and misleading: the budget was met by automating nothing. The ladder now reports **autonomous
coverage** beside the cost and prints an explicit caveat when nothing routes to a paid tier
(`test_a_ladder_that_automates_nothing_reports_zero_coverage` pins it). A cost figure without a
coverage figure is not a result — found by running the thing rather than reading it.

`rules-only`'s single critical violation is the one from the kit's first run and is unchanged:
it fires the 1.3.1 table-header playbook on a *pseudo-heading* case and writes `table.headerRow`,
outside that case's scope. A rule tier keyed on criterion without root cause writes the wrong
element.

## Constrained decoding — the control run

62 of 100 `llama3.2:1b` responses carried no usable JSON. Scoring that as a capability failure
would be a mistake, so the obvious control was run: the same prompt, byte-identical, with the
envelope sent as Ollama's `format` so the decoder cannot emit anything else
(`ollama:<model>+schema`). One changed request field; everything else held.

Report: [`evals/reports/2026-09-04-local-models-constrained.json`](../evals/reports/2026-09-04-local-models-constrained.json).
All four variants ran in one pass, so the comparison is internal.

| candidate | VARR | fix rate | critical | rollback | abstention | unusable | detect F1 | diagnosis | Brier | planning | c/call |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `qwen2.5:0.5b` | 0% | 20% | 48 | 100% | 61% | 12 | 0.11 | 1% | 0.415 | 41% | 0.01772 |
| `qwen2.5:0.5b+schema` | 0% | 25% | **86** | 100% | 76% | **0** | **0.03** | 17% | **0.696** | 48% | 0.01422 |
| `llama3.2:1b` | 0% | 7% | 9 | 95% | 18% | 62 | 0.21 | 5% | 0.184 | 18% | 0.03034 |
| `llama3.2:1b+schema` | 0% | 22% | **6** | **87%** | **67%** | **0** | **0.55** | 19% | **0.018** | **85%** | 0.01765 |

**It works, mechanically.** Unusable output went 12 → 0 and 62 → 0. For `llama3.2:1b` the knock-on
effects are large and real: detection recall 38% → 100%, F1 0.21 → 0.55, planning validity
18% → 85%, calibration (Brier) 0.184 → 0.018, abstention 18% → 67%. It also got *cheaper and
faster* per call — 10.92s → 6.35s, 0.030c → 0.018c — because it stops rambling before the JSON.

**And it changed no gate.** Every variant still fails; VARR is still 0% for all four; the ladder
is unchanged at 50% human / 50% rule code / 0% model.

**The finding worth carrying: schema compliance is not competence, and forcing it can make a
weak model more dangerous.** Constraining the decoder makes a model that could not answer into
one that acts. Autonomous actions went 52 → 75 (`qwen2.5:0.5b`) and 7 → 18 (`llama3.2:1b`).
For the 0.5B that nearly doubled its critical safety violations, **48 → 86**, while its detection
precision fell to 2% and its calibration got worse (Brier 0.415 → 0.696 — confidently wrong is a
regression even when the JSON is perfect). The 1B model's rollback correctness *fell below its
gate*, 95% → 87%: now that it emits mutating actions, it emits them without declaring a rollback.

That last one names a real schema improvement — require `rollback` on mutating actions — which is
deliberately **not** made here. Tightening the schema in response to a measured failure is tuning
to the test; the schema's job in this run was to isolate one variable, and the honest next step is
to change it and re-measure, not to fold the fix in and re-report the same run.

**Reproducibility, incidentally.** Both unconstrained variants reproduced the earlier run almost
exactly on a separate invocation — 48 criticals and 12 unusable for the 0.5B, 9 and 62 for the 1B,
identical VARR and abstention. At temperature 0 the harness is stable run to run, which is what
makes a one-repeat comparison worth reading at all.

## What this does and does not say

- **It does not say small models cannot do remediation.** It says these two, at this size, on
  CPU, with this prompt and no fine-tuning, cannot — and it says exactly where they break
  (detection recall, envelope compliance, abstention), which is what a next attempt would target.
- **It does say the safety gates, not the cost gate, are the binding constraint at this end of
  the ladder.** Both models were cheap and neither was safe. Chasing 0.001c/call is only worth
  doing among candidates that clear the safety gates first.
- **Grammar-constrained decoding was the obvious control and has now been run** — see above. It
  removed the format failures entirely and moved no gate. What remains uncontrolled is the
  prompt itself: one zero-shot envelope, no few-shot examples, no per-criterion phrasing.

## Reproduce

```bash
curl -fsSL https://ollama.com/install.sh | sh      # needs zstd
ollama serve &
ollama pull qwen2.5:0.5b && ollama pull llama3.2:1b

EVALS_LOCAL_CPU=1 python scripts/run_remediation_evals.py --repeats 1 \
  -c rules-only \
  -c ollama:qwen2.5:0.5b -c ollama:qwen2.5:0.5b+schema \
  -c ollama:llama3.2:1b -c ollama:llama3.2:1b+schema \
  --json evals/reports/$(date +%F)-local-models.json
```

Roughly 50 minutes for 400 calls on 4 CPU cores. A `+schema` suffix constrains decoding to
`evals.candidates.ENVELOPE_SCHEMA`; the prompt is identical either way.

**Steady-state latency is what to measure, not the first call.** The first constrained call took
40s and 129s — that is model load, not grammar overhead. From the second call on it is 5-6s and
6-7s, indistinguishable from unconstrained. Constraining decoding costs nothing per call on this
hardware.

## Next rungs

The kit now carries an `anthropic:<model>` candidate (official SDK, lazily imported) with named
price-book entries, so the hosted end of the ladder runs as soon as a key is present in the
environment:

```bash
export ANTHROPIC_API_KEY=...        # or `ant auth login`
python scripts/run_remediation_evals.py --repeats 3 \
  -c rules-only -c anthropic:claude-haiku-4-5 -c anthropic:claude-opus-5
```

For an OpenAI-compatible endpoint use `hosted:<model>@<url>#<price-tier>`; the generic
`hosted-*` tiers are order-of-magnitude placeholders, so add a named entry to
`evals/cost.PRICE_BOOK` with the rate you are actually billed before quoting a figure.

**No server-side fallback is enabled on the Claude candidate, deliberately.** A refusal is a
measurement — this model, on this case, declined — and a fallback would answer it with a
different model under this candidate's name. Refusals are recorded as unusable output with their
category and counted in the report.
