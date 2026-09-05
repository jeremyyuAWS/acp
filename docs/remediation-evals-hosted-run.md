# Hosted-model run — the three Claude tiers against the Remediation Evals Kit

**Run:** started 2026-09-04 23:30 UTC, finished 2026-09-05 00:45 UTC (~75 min wall) ·
**Corpus:** the shipped 100 cases · **Repeats:** 3 · **Report:**
[`evals/reports/2026-09-04-hosted-ladder.json`](../evals/reports/2026-09-04-hosted-ladder.json)
(the file is named for the date the run was launched; it groups with the local-model reports it
is compared against below)

**Result in one line: the hosted tier is the first to record zero critical safety violations, and
Sonnet 5 is the first candidate of any kind to beat rule code on VARR — and all three still fail
their gates, on autonomous-action precision and on cost.**

The ladder now routes **20% of cases to a paid model** where the local run routed 0%. That is the
first non-zero autonomous coverage the kit has measured. It is also 178x over the cost budget.

---

## Setup

| | |
|---|---|
| Models | `claude-haiku-4-5`, `claude-sonnet-5`, `claude-opus-5`, via the official `anthropic` SDK (1.4.0) |
| Baseline | `rules-only` — ACP's deterministic auto lane, $0/call |
| Repeats | 3 (300 case-runs per candidate) |
| Corpus | 100 cases — detection 9, diagnosis 22, execution 11, operational 10, planning 18, safety 30 · risk high 33, medium 36, low 31 · must-abstain 15 · automation-eligible 67 |
| | 59 routing categories (format × criterion) over docx 33, html 15, pdf 18, pptx 20, xlsx 14 |
| Pricing | list price from `evals/cost.PRICE_BOOK`, **read 2026-06-24** — Opus 5 $0.005/$0.025, Sonnet 5 $0.002/$0.010, Haiku 4.5 $0.001/$0.005 per 1k in/out. Nothing is fetched at runtime; a moved price is a one-line edit and a re-run. |
| Prompt | the kit's own, unmodified — one call per case, no few-shot examples, no per-criterion phrasing |
| Spend | pre-flight estimate $5.7600, cap `--max-spend-usd 8.00`, **actual $6.2799** |

900 calls were issued; **756 were billed** (16% of prompts repeat within a repeat and hit the
harness cache). Credential arrived as `ACP_ANTHROPIC_KEY` and was mapped to `ANTHROPIC_API_KEY`
for the run; the pre-flight reported `key: env:ANTHROPIC_API_KEY` on all three paid rungs.

**No rung was dropped.** All four ran to completion, zero candidate errors, zero unusable outputs.

## Headline

| candidate | VARR | fix rate | critical | rollback | auto-precision | abstention | c/call | calls/$ | $/verified fix | gates |
|---|---|---|---|---|---|---|---|---|---|---|
| `rules-only` | 45% | 63% | **3** | 100% | 97% | 100% | 0.00000 | ∞ | $0.00 | **FAIL** (1 of 5) |
| `anthropic:claude-haiku-4-5` | 16% | 43% | **0** | 100% | 29% | 97% | 0.12292 | 814 | $1.12e-02 | **FAIL** (2 of 5) |
| `anthropic:claude-sonnet-5` | **49%** | 65% | **0** | 100% | 58% | 99% | 0.47735 | 209 | $1.46e-02 | **FAIL** (2 of 5) |
| `anthropic:claude-opus-5` | 44% | 61% | **0** | 100% | 52% | 96% | 1.49301 | 67 | $5.09e-02 | **FAIL** (2 of 5) |

`rules-only`'s 3 critical violations are **one defect counted three times** — all three land in
`docx:1.3.1`, one per repeat. It is the pseudo-heading case from the kit's first run, unchanged:
the 1.3.1 table-header playbook fires on a pseudo-heading and writes `table.headerRow`, outside
that case's scope. Critical counts scale with `--repeats`, so this run's 3 and the local run's 1
are the same rate, not a regression. Any comparison of critical counts across runs with different
repeat counts has to normalise first.

## Per stage

| candidate | detect P | detect R | detect F1 | diagnosis | Brier | planning | unusable | latency/case |
|---|---|---|---|---|---|---|---|---|
| `rules-only` | 100% | 100% | 1.00 | 100% | 0.403 | 99% | 0 | 0.00s |
| `claude-haiku-4-5` | 71% | 100% | 0.79 | 42% | **0.836** | 99% | 0 | 2.23s |
| `claude-sonnet-5` | 92% | 100% | 0.95 | 47% | 0.673 | 99% | 0 | 4.84s |
| `claude-opus-5` | 91% | 100% | 0.93 | 48% | 0.659 | 100% | 0 | 7.79s |

Three things the stage split shows that the headline does not:

- **Detection recall is 100% on all three, and precision is what separates them.** Haiku finds
  everything and over-reports (71% precision); Sonnet and Opus over-report about half as much.
  Nothing here fails by missing violations.
- **Envelope compliance is a solved problem at this tier.** Zero unusable outputs across 900
  calls, against 12–62 per 100 for the unconstrained local models. No constrained decoding was
  used or needed.
- **Calibration is worse than rule code, on every hosted rung.** Brier 0.659–0.836 against
  `rules-only`'s 0.403, and Haiku is the worst calibrated candidate in this run. Confidence
  values from these models are not usable as a routing signal as they stand — which matters,
  because a confidence-gated auto lane is the obvious next design and this says it would be
  gated on noise.

## Risk tiers

Case counts are 3x the corpus because they are case-runs across 3 repeats.

| candidate | high (99) | medium (108) | low (93) |
|---|---|---|---|
| `rules-only` | 40% VARR, 0 crit, 100% abst | 0% VARR, **3 crit**, 100% abst | 77% VARR, 0 crit, 100% abst |
| `claude-haiku-4-5` | 7% VARR, 0 crit, 98% abst | 0% VARR, 0 crit, 96% abst | 32% VARR, 0 crit, 100% abst |
| `claude-sonnet-5` | 60% VARR, 0 crit, 100% abst | 56% VARR, 0 crit, 98% abst | 39% VARR, 0 crit, 100% abst |
| `claude-opus-5` | 53% VARR, 0 crit, **93% abst** | 43% VARR, 0 crit, 100% abst | 40% VARR, 0 crit, 100% abst |

The inversion is worth naming: **`rules-only` scores 0% VARR on the medium tier and the two larger
models score 43–56%**, while rule code beats every model on the low tier (77%). The tiers are not
ordered by difficulty for a model the way they are for a rule engine. Opus's 93% abstention on the
high tier is its weakest cell and the reason its overall abstention (96%) sits closest to the 95%
gate.

## Gates — which failed, why, and what a fix would target

Five gates, all pre-declared in `evals/report.Gates`. None were overridden for this run.

| gate | threshold | rules-only | haiku | sonnet | opus |
|---|---|---|---|---|---|
| no critical safety violations | 0 | **FAIL** (3) | PASS (0) | PASS (0) | PASS (0) |
| rollback correctness | ≥0.95 | PASS (1.00) | PASS (1.00) | PASS (1.00) | PASS (1.00) |
| autonomous-action precision | ≥0.90 | PASS (0.97) | **FAIL** (0.29) | **FAIL** (0.58) | **FAIL** (0.52) |
| abstention correctness | ≥0.95 | PASS (1.00) | PASS (0.97) | PASS (0.99) | PASS (0.96) |
| cost per call | ≤$1e-5 | PASS ($0) | **FAIL** ($1.23e-3) | **FAIL** ($4.77e-3) | **FAIL** ($1.49e-2) |

**Autonomous-action precision is the binding safety gate, and it is not close.** The metric is the
share of autonomous actions that were both verified and violation-free. Haiku acted 114 times and
was right 29% of the time; Sonnet acted 170 times at 58%; Opus 168 times at 52%. Note what this is
*not*: it is not unsafe action — critical violations are zero and abstention passes on all three.
These models decline the cases they are told to decline. They then act, wrongly but harmlessly, on
a large share of the ones they are allowed to touch. The failure is wasted work and wrong edits
caught by verification, not damage.

A fix would target the gap between *acting* and *acting correctly*: the models act nearly twice as
often as they succeed. The two levers this run can see are (a) the diagnosis stage, at 42–48%
against rule code's 100% — a plan built on a wrong root cause executes and fails verification, and
(b) calibration, since a model that knew which of its actions were the 50% would clear the gate by
escalating the rest. Neither was attempted here.

**Cost fails by two to three orders of magnitude** — see the economics section.

`rules-only` fails only the critical-violation gate, on the single known 1.3.1 defect. Fixing that
one rule would make the free tier the only candidate in this run that passes every gate.

## The routing ladder

For each of the 59 categories, the cheapest tier that is safe there — safe meaning, within that
category: zero critical violations, abstention correct, and every eligible case verified.

| routed to | categories | cases | share of traffic |
|---|---|---|---|
| `rules-only` (free) | 34 | 50 | 50% |
| `anthropic:claude-sonnet-5` | 5 | 12 | 12% |
| `anthropic:claude-opus-5` | 3 | 8 | 8% |
| **human** | 17 | 30 | 30% |
| `anthropic:claude-haiku-4-5` | **0** | **0** | **0%** |

**Blended: $1.779e-03/call (0.178c/call, 562 calls/$) at 70% autonomous coverage.**

Both halves of that sentence are required. The local run met the budget at $0/call by automating
nothing; this run misses the budget by 178x while automating 70% of traffic, 20% of it on a paid
model. Neither figure means anything alone.

**Haiku earned nothing, and the reason is specific.** It was safe in 20 of 59 categories — but in
every one of those, `rules-only` was also safe, and free. Its incremental coverage over rule code
is **0 categories, 0 cases**. The cheapest paid rung is not the entry point to the ladder here; it
is dominated. Sonnet adds 5 categories (12 cases) beyond rule code, Opus adds 6 (14 cases), and
Opus wins only the 3 where Sonnet was not safe.

What each paid rung earned:

| category | cases | routed to | $/case | |
|---|---|---|---|---|
| `docx:2.4.4` | 4 | sonnet | $2.91e-03 | |
| `html:2.4.4` | 5 | sonnet | $3.03e-03 | |
| `html:3.1.2` | 1 | sonnet | $4.85e-03 | under-sampled |
| `pptx:3.1.2` | 1 | sonnet | $4.57e-03 | under-sampled |
| `xlsx:2.4.4` | 1 | sonnet | $4.92e-03 | under-sampled |
| `docx:1.4.3` | 2 | opus | $1.74e-02 | |
| `pdf:1.4.3` | 5 | opus | $1.74e-02 | |
| `xlsx:1.1.1` | 1 | opus | $1.49e-02 | under-sampled |

The pattern is legible, with one half of it much better evidenced than the other:

- **Sonnet earns link text (2.4.4) properly** — 3 of that criterion's 4 categories, 10 cases,
  and its two largest (docx 4, html 5) are adequately sampled. This is the strongest paid-tier
  result in the run.
- **Opus earns contrast (1.4.3) on docx and pdf** — 7 cases, both adequately sampled.
- **Sonnet's language-of-parts (3.1.2) wins are weak.** Both are single under-sampled cases,
  and the one 3.1.2 category with more than one case (`docx:3.1.2`, 2 cases) went to free rule
  code. Do not read this as "Sonnet earns 3.1.2".

The two well-evidenced wins are judgement calls over content — is this link text meaningful,
which of these colours preserves authorial intent — which is the category of work rule code
cannot key on. Of the 20 paid cases, **16 sit in adequately-sampled categories and 4 do not**;
the four are marked above and should not be routed on.

The 17 human-routed categories are the ones where no tier was safe. Three patterns in them:

- **`1.1.1` (alt text): 3 of its 4 categories go to a human** — docx, pdf and pptx. The fourth,
  `xlsx:1.1.1`, is Opus's, and it is a single under-sampled case.
- **`1.3.3` (sensory characteristics): all 4 categories go to a human**, one case each. Nothing
  in this run was safe on any of them, at any tier.
- **`docx:1.3.1`** — where rule code has the known pseudo-heading defect and no model covered
  for it.

That also sharpens the contrast finding. Opus earns `1.4.3` on **docx and pdf** (7 cases between
them, both adequately sampled) but *not* on html, pptx or xlsx, which go to a human. "Opus earns
contrast" is true per-format, not per-criterion — which is exactly why the ladder's routing unit
is format × criterion rather than criterion alone.

## Economics against 100,000 calls per US$1

The kit's target is $1e-5/call = 0.001c/call. Measured this run, uncached:

| tier | $/call | calls/$ | multiple of target | max share of traffic that fits the budget |
|---|---|---|---|---|
| `rules-only` | $0 | ∞ | — | 100% |
| `claude-haiku-4-5` | $1.463e-03 | 683 | **146x** | 0.68% |
| `claude-sonnet-5` | $5.683e-03 | 176 | **568x** | 0.18% |
| `claude-opus-5` | $1.777e-02 | 56 | **1,777x** | 0.06% |

The last column is the answer to "what share could sit on this rung with the rest on rule code":
with rule code at $0, a paid share *f* at cost *c* blends to *f·c*, so *f* ≤ $1e-5/*c*.

**This is the finding.** The ladder wants 20% of traffic on a paid tier at a mean $8.895e-03/case.
The budget permits **0.112%** at that price — a **178x** gap, which is exactly the shortfall the
report prints. Closing it by caching alone needs a **99.4% hit rate** on the paid share; this run
measured 16%, and a 99% figure is a claim about how repetitive the estate is, not about the model.
Routing does not close it either: routing is already optimal here by construction, and the blended
figure *is* the routed one.

The honest reading is that the 100,000 calls/$1 target and a model-backed lane are, at list price
and with this prompt, incompatible by two orders of magnitude — and that the gap is far too large
for prompt shortening to bridge. What the target *is* compatible with is the shape this run
actually found: **50% of traffic on free rule code, and a paid tier reserved for the sub-1% of
calls where it earns its cost.** That is a different product decision from "route 20% to Sonnet",
and this run cannot tell you which categories the sub-1% should be, because the categories where
a model wins are 12% of traffic, not 0.1%.

Note the derivation is from measured tokens, not from list price and a nominal call. Measured
per billed call: Haiku 289 in / 235 out, Sonnet 392 / 490, Opus 392 / 632.

## Against the local-model run

Same 100 cases, same graders, same gates
([`2026-09-04-local-models-constrained.json`](../evals/reports/2026-09-04-local-models-constrained.json),
[writeup](remediation-evals-local-model-run.md)). The local run used `--repeats 1`, so critical
violations below are normalised to **per 100 cases** to be comparable.

| candidate | VARR | critical /100 | abstention | categories earned |
|---|---|---|---|---|
| `rules-only` (local run) | 45% | 1 | 100% | 34 |
| `qwen2.5:0.5b` | 0% | 48 | 61% | 0 |
| `qwen2.5:0.5b+schema` | 0% | **86** | 76% | 0 |
| `llama3.2:1b` | 0% | 9 | 18% | 0 |
| `llama3.2:1b+schema` | 0% | 6 | 67% | 0 |
| `claude-haiku-4-5` | 16% | **0** | 97% | **0** |
| `claude-sonnet-5` | **49%** | **0** | 99% | **5** |
| `claude-opus-5` | 44% | **0** | 96% | **3** |

- **VARR 0% → 49%.** No local model verified a single fix. Sonnet verifies 49% and is the first
  candidate in the kit's history to beat `rules-only` (45%) — by 4 points, with a per-repeat
  spread of 11 points, so "beats rule code" is not a claim this run can make confidently. See
  variance below.
- **6–86 critical violations → 0.** Every hosted rung, every repeat. This is the cleanest
  separation in the comparison and it is not marginal.
- **18–76% abstention → 96–99%.** All three clear the 95% gate the local models failed by 20–77
  points. The must-abstain cases are the `lane=human` criteria — reading level, keyboard traps,
  reflow — and these models decline them reliably.
- **0% → 20% of traffic on a model.** The local ladder routed 50% to a human and 50% to rule
  code. This one routes 30% to a human, 50% to rule code, 20% to a model.

`rules-only` reproduced exactly across the two runs — VARR 0.4478 in both, the same single 1.3.1
defect — which is the control that makes the rest of the comparison worth reading.

The direction the two runs agree on: **cost is not the binding constraint at either end of the
ladder.** The local models were cheap and unsafe; these are safe and expensive. Both fail. What
changed is which gate does the failing.

## Variance across the 3 repeats

| candidate | VARR per repeat | sd | flagged |
|---|---|---|---|
| `rules-only` | 0.448, 0.448, 0.448 | 0.000 | — |
| `claude-haiku-4-5` | 0.209, 0.134, 0.149 | 0.032 | **nondeterministic** |
| `claude-sonnet-5` | 0.433, 0.493, 0.537 | 0.043 | **nondeterministic** |
| `claude-opus-5` | 0.478, 0.418, 0.418 | 0.028 | **nondeterministic** |

**All three hosted candidates were flagged nondeterministic; `rules-only` was not.** This is the
repeats earning their keep. A single pass would have reported Sonnet anywhere from 43% to 54% and
Haiku anywhere from 13% to 21%, and any of those would have been written down as *the* number.

The spread matters for one claim in particular. Sonnet's 49% mean beats rule code's 45%, but its
own repeats span 43–54% — the lead is smaller than the run-to-run noise, and a 3-repeat mean is
too thin to resolve it. **"Sonnet beats rule code on VARR" is not established by this run.** What
is established is that it is in the same range, which no previous candidate was.

Nothing else was resampled: the ladder, the gates and the cost figures are computed from the
pooled 300 case-runs and carry no interval at all.

## What these numbers do not show

- **42 of 59 categories (71%) are under-sampled** — a single case each, which is 42% of the
  corpus by case count. The report labels them and refuses to route on them, and the two figures
  are easy to conflate: *42% of cases* and *71% of categories* are the same fact counted two ways.
  A per-category routing choice in that 71% is a coin flip with a table around it, including 4 of
  the 8 categories routed to a paid tier above.
- **One prompt, zero-shot, unmodified.** No few-shot examples, no per-criterion phrasing, no
  system prompt. The diagnosis scores (42–48%) are a measurement of this prompt on these models,
  not of the models.
- **List price, read 2026-06-24.** No batch pricing, no prompt caching at the API level, no
  committed-use discount. Every dollar figure moves if any of those apply; the ranking does not.
- **The harness cache is per-repeat and hit 16%.** That models an estate with repeated content.
  A real estate's hit rate is a property of the estate and has to be measured there.
- **VARR is over automation-eligible cases only** (67 of 100). It is not a share of the corpus.
- **Latency is single-call and sequential.** 2.23s/7.79s per case says nothing about throughput
  under concurrency.
- **Zero critical violations is over 900 calls on 100 cases.** It is a strong result at this
  sample size and it is not a bound on rare behaviour.
- **The run cost $6.2799 against a $5.7600 pre-flight estimate** — see below. Nothing in the
  measured results depends on that, but the spend guard does.

## Next steps — named, not taken

Nothing was tuned for this run. Every item below is left as-is in the code deliberately; changing
any of them in response to this run and re-reporting the same numbers would be tuning to the test.

1. **`estimate_run_usd` is not an upper bound, and `--max-spend-usd` guards it.** The docstring
   says "cache hits only ever make it cheaper, so this is an upper bound". Measured: the estimate
   was $5.7600 and the run cost **$6.2799 (1.09x)** despite a 16% cache hit rate. The estimator
   assumes 900 in / 300 out (`ESTIMATE_TOKENS_IN/OUT`); Opus actually returned **632 output tokens
   per call**, 2.1x nominal, and output is priced 5x input, so the low input assumption does not
   offset it. Opus alone came in at **1.24x** its estimate. This run stayed under the $8.00 cap so
   nothing was harmed, but a run sized to its cap would have exceeded it — the guard is checked
   against the estimate before the first call and never against actual spend. Fixing this means
   either raising the nominal output assumption, or metering spend during the run and stopping at
   the cap. It is a spend-safety defect, not a measurement defect.
2. **Autonomous-action precision is the gate to attack**, via diagnosis quality (42–48%) rather
   than via safety — the models are already safe and already abstain correctly.
3. **Calibration is unusable as a routing signal** (Brier 0.659–0.836, worse than rule code's
   0.403). A confidence-gated auto lane is the natural next design and this run says it would be
   gated on noise.
4. **Haiku is dominated and could be dropped from the ladder** — 0 incremental categories over
   free rule code. Worth one more run before concluding it, since it is a cheap rung and a
   different prompt might change it.
5. **Fix the `docx:1.3.1` pseudo-heading rule** and `rules-only` passes all five gates. It is also
   the one category where rule code's defect forced cases to a human that nothing else covered.
6. **Sample the 42 single-case categories** before any of this table is used for production
   routing.

## Reproduce

```bash
pip install anthropic
export ANTHROPIC_API_KEY=...          # see the note below on the variable name
python scripts/run_remediation_evals.py --repeats 3 --max-spend-usd 8.00 \
  -c rules-only -c anthropic:claude-haiku-4-5 -c anthropic:claude-sonnet-5 \
  -c anthropic:claude-opus-5 \
  --json evals/reports/$(date +%F)-hosted-ladder.json
```

~75 minutes for 900 calls, sequential. Confirm the credential is visible before spending anything:

```bash
python scripts/run_remediation_evals.py --estimate-only --repeats 3 \
  -c rules-only -c anthropic:claude-haiku-4-5 -c anthropic:claude-sonnet-5 \
  -c anthropic:claude-opus-5
```

The `key:` column must read `env:ANTHROPIC_API_KEY`. If it reads `missing (...)`, stop — the run
would otherwise proceed and score the rung as unusable output rather than as an auth failure.

**On the variable name, for anyone running this in a cloud session:** `ANTHROPIC_API_KEY` set in
the environment editor did not reach the container on three prior attempts, and the editor warns
that this specific name "won't be used to authenticate requests". Setting it under a different
name (here `ACP_ANTHROPIC_KEY`) and mapping it at the start of the run works:

```bash
export ANTHROPIC_API_KEY="$ACP_ANTHROPIC_KEY"
```

`key_source()` exists precisely so this is answerable from the log rather than by assumption.
