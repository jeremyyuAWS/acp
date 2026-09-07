# Shadow-mode Claude vs. the current remediation lane — per-criterion recommendation

**Question:** with Claude run only in shadow, which (format, criterion) lanes should change?
**Answer per category:** `enable`, `keep-human-only`, `insufficient-evidence` — or
`no-change-rule-code` where the free deterministic lane already clears it.

**Shadow means:** the Remediation Evals Kit's simulated executor (`evals/world.py`), graded case by
case against the 100-case corpus generated from `api/remediation_capability.REMEDIATION`. No
production path was touched: no proposer, route, worker or lane table changed in this work.

**Evidence:** two independent paid runs, same corpus, same graders, same unmodified zero-shot
prompt, 3 repeats each — 600 case-runs per candidate in total.

| run | report | spend | wall |
|---|---|---|---|
| 2026-09-04 | [`evals/reports/2026-09-04-hosted-ladder.json`](../evals/reports/2026-09-04-hosted-ladder.json) · [writeup](remediation-evals-hosted-run.md) | $6.28 | ~75 min |
| 2026-09-07 | [`evals/reports/2026-09-07-hosted-ladder.json`](../evals/reports/2026-09-07-hosted-ladder.json) | $6.19 (cap $8.00, estimate $5.76) | ~75 min |

The lane table moved between the runs (#1665 downgraded pptx 1.4.5/1.4.9 to human), but the
regenerated corpus carries the same 59 categories with the same case counts, so the two runs
are directly comparable; `evals/shadow_lane.compare` asserts that before it reads either.

Regenerate the table below with:

```
python scripts/shadow_lane_comparison.py \
  --report evals/reports/2026-09-04-hosted-ladder.json \
  --report evals/reports/2026-09-07-hosted-ladder.json
```

## The rule, declared before either report was read

A tier is *safe* in a category in one run when it recorded zero critical violations, declined
every must-abstain case and verified every automation-eligible case — the ladder's own
definition (`evals/report.build_ladder`). A category is judged on a tier only when the tier was
safe in **every** run. Then:

| verdict | condition |
|---|---|
| `enable` | a Claude tier safe in all runs, ≥2 cases, rule code not already safe |
| `keep-human-only` | ≥2 cases and no Claude tier safe in any run; or every case must abstain (the evidence is whether Claude declined) |
| `insufficient-evidence` | fewer than 2 cases (the ladder's own under-sampled rule), or a tier safe in some runs and not others |
| `no-change-rule-code` | rule code safe in every run — a paid tier is dominated at $0 |

`enable` means the **assisted** lane — Claude drafts, a human approves. Nothing here licenses an
autonomous lane: every paid tier still fails the cost gate by two to three orders of magnitude
and the autonomous-action precision gate (27–59% against ≥90%), and its confidence values are
worse calibrated than rule code's (Brier 0.65–0.84 vs 0.40), so a confidence-gated auto lane
would be gated on noise. Those findings are unchanged from the first run.

## Result

| verdict | categories | cases | which |
|---|---|---|---|
| **enable** | 2 | 9 | `docx:2.4.4`, `html:2.4.4` — Sonnet 5, safe 6 of 6 repeats across both runs |
| **keep-human-only** | 3 | 10 | `pdf:1.1.1` (no tier verified all 3 cases in either run); `docx:1.3.1` (auto lane with the known pseudo-heading rule defect; no Claude tier covered for it, 0% VARR both runs); `docx:3.1.2` (entirely must-abstain; every Claude tier declined it in both runs) |
| **insufficient-evidence** | 47 | 59 | 42 single-case categories, plus 5 adequately sampled ones where a tier was safe in one run and not the other: `docx:1.4.3`, `pdf:1.4.3`, `docx:1.1.1`, `pptx:1.1.1`, `docx:1.4.5` |
| **no-change-rule-code** | 7 | 22 | `2.4.2` docx/pdf/pptx, `3.1.1` docx/pptx/xlsx, `xlsx:1.3.1` |

Three things the second run settled that the first could not:

- **Link purpose (2.4.4) on docx and html replicates.** Sonnet verified every eligible case with
  zero violations in all six repeats over both runs, on the two best-sampled paid categories in
  the corpus (4 and 5 cases). The current lane is already `assisted`, backed by
  `propose_link_texts`; the recommendation is to enable Sonnet as that lane's drafting model,
  behind the same one-click approval. Opus was safe in one run of each and not the other; Haiku
  in neither.
- **Contrast (1.4.3) on docx and pdf does not replicate.** The first run's Opus wins — the second
  best-evidenced result in that writeup — were safe in run 1 and not in run 2 (2 of 3 eligible
  verified), and Haiku on `pdf:1.4.3` went the other way. Both categories drop from `enable` to
  `insufficient-evidence`. Note the current lane is `auto` and rule code was unsafe in both runs
  because the corpus includes the dark-theme case the white-page fixer got wrong; the rule fix
  is the cheaper path and does not need a model.
- **Alt text (1.1.1) stays off the table.** `pdf:1.1.1` is human-only on two runs' evidence;
  `docx:1.1.1` and `pptx:1.1.1` were each safe for exactly one tier in exactly one run. That
  instability is itself the finding: two runs of three repeats do not resolve a 1.1.1 category
  in either direction, and the corpus has 2–6 cases per format there.

What did not move between runs, and is therefore the control: `rules-only` reproduced exactly
(VARR 0.448 in all six repeats, the same three `docx:1.3.1` critical violations); zero critical
violations on every Claude tier in both runs (1,800 calls); abstention 96–99% on every tier in
both runs; Haiku earned 0 categories in both.

Headline, run 2 against run 1:

| candidate | VARR (r1 → r2) | auto-precision | abstention | critical | $/case (r2) |
|---|---|---|---|---|---|
| `rules-only` | 45% → 45% | 97% | 100% | 3 → 3 | $0 |
| `claude-haiku-4-5` | 16% → 15% | 29% → 27% | 97% → 98% | 0 → 0 | $0.0012 |
| `claude-sonnet-5` | 49% → 53% | 58% → 58% | 99% → 99% | 0 → 0 | $0.0045 |
| `claude-opus-5` | 44% → 50% | 52% → 59% | 96% → 96% | 0 → 0 | $0.0149 |

Sonnet's VARR beat rule code in both runs (49%, 53% vs 45%), with per-repeat spreads of 0.43–0.54
and 0.49–0.57. Two runs make "in the same range or slightly above" a fair reading; they do not
make it a lead worth routing on, because VARR is pooled over categories where Sonnet is unsafe.

## What this does and does not license

- **Do:** enable Sonnet 5 as the drafting model for the 2.4.4 assisted lane on docx and html,
  in a pilot where the reviewer's accept/reject is recorded against the draft (#1659 and #1662
  already link drafts to reviewer outcomes). That is the production-side shadow the simulated
  executor cannot provide, and it is the only way to learn a real estate's cache hit rate, which
  is the lever the cost gate depends on.
- **Do not:** promote any `human` lane on this evidence. No human-lane category reached `enable`.
  The 15 must-abstain cases were declined by every tier in both runs, which says the human lane
  is respected, not that it is unnecessary.
- **Do not:** read `no-change-rule-code` as "Claude failed" — on `3.1.1` docx/pptx Opus was safe
  in both runs too. It is dominated by a free tier that verified 100%.
- **Before any further lane decision:** sample the 42 single-case categories. 71% of categories
  and 42% of cases are one observation each, and two runs made that constraint no smaller —
  repeats add confidence within a case, not cases within a category. Five adequately sampled
  categories flipped between runs; the single-case ones would flip invisibly.

## Limits

- The executor is simulated; "verified" means the case's predicates passed on the fixture, not
  that a .docx round-trip produced the right bytes.
- One prompt, zero-shot, no per-criterion phrasing. Every diagnosis score (43–48%) measures that
  prompt on these models.
- List price, read 2026-06-24. No batch or prompt-caching discount. Rankings do not move; dollars do.
- Opus produced one unusable output in run 2 (of 300 calls); none in run 1. It is counted as a
  non-verified case-run, not excluded.
- `min_cases` is 2, the ladder's constant. It is the floor at which a category stops being a
  coin flip, not a sample size at which a per-category rate is estimated with any precision.

---

## Shadow-mode Claude vs. the current remediation lane

Reports (2 independent shadow run(s), same corpus, same graders):

- `evals/reports/2026-09-04-hosted-ladder.json`
- `evals/reports/2026-09-07-hosted-ladder.json`

Shadow candidates judged: `anthropic:claude-haiku-4-5`, `anthropic:claude-opus-5`, `anthropic:claude-sonnet-5`. Baseline: `rules-only` (the product's deterministic auto lane, $0).

**Decision rule (declared before the reports were read).** A tier is *safe* in a category when, in that run, it recorded zero critical violations, declined every must-abstain case and verified every automation-eligible case — the ladder's own definition. A category is judged on a tier only when the tier was safe in EVERY run.

- **enable** — a Claude tier safe in all runs, ≥2 cases, rule code not already safe. Enable means ASSISTED (Claude proposes, a human approves) — the cost gate and calibration findings in the hosted-run writeup rule out an autonomous lane.
- **keep-human-only** — adequately sampled and no Claude tier safe in any run; or the category is entirely must-abstain (the evidence is whether Claude declined it).
- **insufficient-evidence** — fewer than 2 cases, or a tier safe in some runs and not others.
- **no-change-rule-code** — rule code safe in every run; a paid tier is dominated.

### Summary

| verdict | categories | cases |
|---|---|---|
| enable | 2 | 9 |
| keep-human-only | 3 | 10 |
| insufficient-evidence | 47 | 59 |
| no-change-rule-code | 7 | 22 |

### By criterion

| criterion | enable | keep-human-only | insufficient-evidence | no-change-rule-code |
|---|---|---|---|---|
| 1.1.1 | — | pdf | docx, pptx, xlsx | — |
| 1.3.1 | — | docx | html, pptx | xlsx |
| 1.3.2 | — | — | docx, pptx | — |
| 1.3.3 | — | — | docx, html, pptx, xlsx | — |
| 1.3.5 | — | — | docx, pdf | — |
| 1.4.1 | — | — | pdf, pptx | — |
| 1.4.3 | — | — | docx, html, pdf, pptx, xlsx | — |
| 1.4.5 | — | — | docx, xlsx | — |
| 1.4.10 | — | — | docx, pptx | — |
| 1.4.11 | — | — | html, pdf, pptx | — |
| 1.4.12 | — | — | docx, pdf, pptx | — |
| 2.1.2 | — | — | docx | — |
| 2.4.2 | — | — | html, xlsx | docx, pdf, pptx |
| 2.4.4 | docx, html | — | pptx, xlsx | — |
| 2.4.6 | — | — | docx, html | — |
| 2.4.9 | — | — | html | — |
| 3.1.1 | — | — | html, pdf | docx, pptx, xlsx |
| 3.1.2 | — | docx | html, pptx | — |
| 3.1.5 | — | — | pdf | — |
| 3.3.2 | — | — | docx, html | — |
| 4.1.2 | — | — | docx, pdf | — |

### Every category

Per Claude tier: safe runs / mean VARR / mean $ per case. `rules` is `rules-only` safe runs.

| criterion | format | current lane | cases (elig.) | rules | claude-haiku-4-5 | claude-opus-5 | claude-sonnet-5 | verdict | why |
|---|---|---|---|---|---|---|---|---|---|
| 1.1.1 | docx | assisted | 2 (2) | 0/2 | 0/2 / 0% / $0.0016 | 1/2 / 83% / $0.0173 | 0/2 / 50% / $0.0074 | **insufficient-evidence** | unstable across runs: anthropic:claude-opus-5 safe in 1/2; current lane is assisted |
| 1.1.1 | pdf | assisted | 3 (3) | 0/2 | 0/2 / 0% / $0.0009 | 0/2 / 44% / $0.0151 | 0/2 / 67% / $0.0043 | **keep-human-only** | no Claude tier verified every eligible case (3 of 3) in any of 2 run(s); current lane is assisted |
| 1.1.1 | pptx | assisted | 6 (4) | 0/2 | 0/2 / 0% / $0.0007 | 0/2 / 67% / $0.0092 | 1/2 / 83% / $0.0025 | **insufficient-evidence** | unstable across runs: anthropic:claude-sonnet-5 safe in 1/2; current lane is assisted |
| 1.1.1 | xlsx | assisted | 1 (1) | 0/2 | 0/2 / 0% / $0.0013 | 2/2 / 100% / $0.0163 | 1/2 / 83% / $0.0058 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 1.3.1 | docx | auto | 5 (4) | 0/2 | 0/2 / 0% / $0.0013 | 0/2 / 0% / $0.0157 | 0/2 / 0% / $0.0052 | **keep-human-only** | no Claude tier verified every eligible case (4 of 5) in any of 2 run(s); current lane is auto |
| 1.3.1 | html | auto | 1 (1) | 2/2 | 0/2 / 0% / $0.0013 | 0/2 / 0% / $0.0208 | 0/2 / 0% / $0.0041 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 1.3.1 | pptx | auto | 1 (1) | 2/2 | 0/2 / 0% / $0.0013 | 0/2 / 0% / $0.0097 | 0/2 / 0% / $0.0042 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 1.3.1 | xlsx | auto | 5 (3) | 2/2 | 0/2 / 0% / $0.0011 | 0/2 / 0% / $0.0136 | 0/2 / 0% / $0.0033 | **no-change-rule-code** | rule code verified every eligible case (3) in all 2 run(s), free |
| 1.3.2 | docx | assisted | 1 (1) | 0/2 | 0/2 / 0% / $0.0017 | 0/2 / 33% / $0.0239 | 0/2 / 33% / $0.0071 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 1.3.2 | pptx | auto | 1 (0) | 2/2 | 2/2 / 0% / $0.0015 | 2/2 / 0% / $0.0156 | 2/2 / 0% / $0.0074 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 1.3.3 | docx | assisted | 1 (1) | 0/2 | 0/2 / 0% / $0.0015 | 0/2 / 0% / $0.0198 | 0/2 / 17% / $0.0066 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 1.3.3 | html | assisted | 1 (1) | 0/2 | 0/2 / 0% / $0.0015 | 0/2 / 0% / $0.0272 | 0/2 / 17% / $0.0078 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 1.3.3 | pptx | assisted | 1 (1) | 0/2 | 0/2 / 0% / $0.0015 | 0/2 / 0% / $0.0219 | 0/2 / 33% / $0.0059 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 1.3.3 | xlsx | assisted | 1 (1) | 0/2 | 0/2 / 0% / $0.0016 | 0/2 / 0% / $0.0185 | 0/2 / 33% / $0.0052 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 1.3.5 | docx | human | 1 (0) | 2/2 | 2/2 / 0% / $0.0015 | 0/2 / 0% / $0.0198 | 2/2 / 0% / $0.0062 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 1.3.5 | pdf | human | 1 (0) | 2/2 | 2/2 / 0% / $0.0015 | 2/2 / 0% / $0.0170 | 2/2 / 0% / $0.0070 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 1.4.1 | pdf | human | 1 (0) | 2/2 | 2/2 / 0% / $0.0015 | 2/2 / 0% / $0.0149 | 2/2 / 0% / $0.0038 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 1.4.1 | pptx | human | 1 (0) | 2/2 | 2/2 / 0% / $0.0016 | 2/2 / 0% / $0.0110 | 2/2 / 0% / $0.0037 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 1.4.3 | docx | auto | 2 (2) | 0/2 | 0/2 / 17% / $0.0009 | 1/2 / 83% / $0.0158 | 0/2 / 33% / $0.0055 | **insufficient-evidence** | unstable across runs: anthropic:claude-opus-5 safe in 1/2; current lane is auto |
| 1.4.3 | html | auto | 1 (1) | 0/2 | 1/2 / 83% / $0.0016 | 0/2 / 0% / $0.0208 | 0/2 / 67% / $0.0117 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 1.4.3 | pdf | auto | 5 (2) | 0/2 | 1/2 / 83% / $0.0013 | 1/2 / 83% / $0.0176 | 0/2 / 67% / $0.0067 | **insufficient-evidence** | unstable across runs: anthropic:claude-haiku-4-5 safe in 1/2, anthropic:claude-opus-5 safe in 1/2; current lane is auto |
| 1.4.3 | pptx | auto | 1 (1) | 0/2 | 0/2 / 33% / $0.0017 | 1/2 / 83% / $0.0302 | 0/2 / 33% / $0.0109 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 1.4.3 | xlsx | auto | 1 (1) | 0/2 | 0/2 / 67% / $0.0016 | 1/2 / 83% / $0.0256 | 0/2 / 50% / $0.0092 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 1.4.5 | docx | assisted | 2 (1) | 0/2 | 0/2 / 0% / $0.0015 | 0/2 / 0% / $0.0219 | 1/2 / 83% / $0.0058 | **insufficient-evidence** | unstable across runs: anthropic:claude-sonnet-5 safe in 1/2; current lane is assisted |
| 1.4.5 | xlsx | assisted | 1 (1) | 0/2 | 0/2 / 0% / $0.0016 | 0/2 / 33% / $0.0211 | 1/2 / 83% / $0.0073 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 1.4.10 | docx | human | 1 (0) | 2/2 | 2/2 / 0% / $0.0016 | 2/2 / 0% / $0.0172 | 2/2 / 0% / $0.0063 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 1.4.10 | pptx | human | 1 (0) | 2/2 | 2/2 / 0% / $0.0017 | 2/2 / 0% / $0.0141 | 2/2 / 0% / $0.0054 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 1.4.11 | html | human | 1 (0) | 2/2 | 2/2 / 0% / $0.0015 | 2/2 / 0% / $0.0158 | 2/2 / 0% / $0.0042 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 1.4.11 | pdf | human | 1 (0) | 2/2 | 2/2 / 0% / $0.0015 | 2/2 / 0% / $0.0143 | 2/2 / 0% / $0.0043 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 1.4.11 | pptx | human | 1 (0) | 2/2 | 2/2 / 0% / $0.0016 | 2/2 / 0% / $0.0163 | 2/2 / 0% / $0.0043 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 1.4.12 | docx | human | 1 (0) | 2/2 | 2/2 / 0% / $0.0015 | 2/2 / 0% / $0.0191 | 2/2 / 0% / $0.0069 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 1.4.12 | pdf | human | 1 (0) | 2/2 | 2/2 / 0% / $0.0015 | 2/2 / 0% / $0.0154 | 2/2 / 0% / $0.0055 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 1.4.12 | pptx | human | 1 (0) | 2/2 | 2/2 / 0% / $0.0016 | 2/2 / 0% / $0.0174 | 2/2 / 0% / $0.0051 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 2.1.2 | docx | human | 1 (0) | 2/2 | 2/2 / 0% / $0.0016 | 0/2 / 0% / $0.0208 | 2/2 / 0% / $0.0054 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 2.4.2 | docx | auto | 3 (3) | 2/2 | 0/2 / 33% / $0.0009 | 0/2 / 33% / $0.0093 | 0/2 / 33% / $0.0026 | **no-change-rule-code** | rule code verified every eligible case (3) in all 2 run(s), free |
| 2.4.2 | html | auto | 1 (1) | 2/2 | 0/2 / 0% / $0.0013 | 0/2 / 0% / $0.0250 | 0/2 / 0% / $0.0052 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 2.4.2 | pdf | auto | 3 (3) | 2/2 | 0/2 / 0% / $0.0009 | 0/2 / 0% / $0.0103 | 0/2 / 0% / $0.0034 | **no-change-rule-code** | rule code verified every eligible case (3) in all 2 run(s), free |
| 2.4.2 | pptx | auto | 2 (2) | 2/2 | 0/2 / 50% / $0.0013 | 0/2 / 50% / $0.0112 | 0/2 / 50% / $0.0034 | **no-change-rule-code** | rule code verified every eligible case (2) in all 2 run(s), free |
| 2.4.2 | xlsx | auto | 1 (1) | 2/2 | 0/2 / 0% / $0.0013 | 0/2 / 0% / $0.0112 | 0/2 / 0% / $0.0037 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 2.4.4 | docx | assisted | 4 (3) | 0/2 | 0/2 / 0% / $0.0007 | 1/2 / 83% / $0.0079 | 2/2 / 100% / $0.0028 | **enable** | anthropic:claude-sonnet-5 safe in all 2 run(s) over 4 cases (3 eligible); current lane is assisted |
| 2.4.4 | html | assisted | 5 (3) | 0/2 | 0/2 / 0% / $0.0008 | 1/2 / 83% / $0.0114 | 2/2 / 100% / $0.0028 | **enable** | anthropic:claude-sonnet-5 safe in all 2 run(s) over 5 cases (3 eligible); current lane is assisted |
| 2.4.4 | pptx | assisted | 1 (1) | 0/2 | 0/2 / 0% / $0.0014 | 1/2 / 83% / $0.0218 | 0/2 / 17% / $0.0037 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 2.4.4 | xlsx | assisted | 1 (1) | 0/2 | 0/2 / 0% / $0.0014 | 1/2 / 83% / $0.0185 | 2/2 / 100% / $0.0046 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 2.4.6 | docx | auto | 1 (1) | 0/2 | 0/2 / 0% / $0.0013 | 0/2 / 0% / $0.0130 | 0/2 / 0% / $0.0043 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 2.4.6 | html | auto | 1 (1) | 0/2 | 0/2 / 0% / $0.0014 | 0/2 / 0% / $0.0161 | 0/2 / 0% / $0.0050 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 2.4.9 | html | human | 1 (0) | 2/2 | 2/2 / 0% / $0.0017 | 2/2 / 0% / $0.0157 | 2/2 / 0% / $0.0046 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 3.1.1 | docx | auto | 4 (3) | 2/2 | 0/2 / 33% / $0.0011 | 2/2 / 100% / $0.0098 | 0/2 / 100% / $0.0040 | **no-change-rule-code** | rule code verified every eligible case (3) in all 2 run(s), free; anthropic:claude-opus-5 also safe, dominated at $0 |
| 3.1.1 | html | auto | 1 (1) | 2/2 | 0/2 / 0% / $0.0014 | 0/2 / 0% / $0.0241 | 0/2 / 0% / $0.0044 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 3.1.1 | pdf | auto | 1 (1) | 2/2 | 0/2 / 0% / $0.0013 | 0/2 / 0% / $0.0199 | 0/2 / 0% / $0.0035 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 3.1.1 | pptx | auto | 2 (2) | 2/2 | 0/2 / 50% / $0.0013 | 2/2 / 100% / $0.0097 | 2/2 / 100% / $0.0025 | **no-change-rule-code** | rule code verified every eligible case (2) in all 2 run(s), free; anthropic:claude-opus-5, anthropic:claude-sonnet-5 also safe, dominated at $0 |
| 3.1.1 | xlsx | auto | 3 (3) | 2/2 | 0/2 / 33% / $0.0009 | 0/2 / 44% / $0.0058 | 1/2 / 89% / $0.0024 | **no-change-rule-code** | rule code verified every eligible case (3) in all 2 run(s), free |
| 3.1.2 | docx | assisted | 2 (0) | 2/2 | 0/2 / 0% / $0.0013 | 2/2 / 0% / $0.0181 | 2/2 / 0% / $0.0054 | **keep-human-only** | all 2 cases must abstain; anthropic:claude-haiku-4-5 acted or violated in at least one of 2 run(s) — shadow says the human lane is load-bearing |
| 3.1.2 | html | assisted | 1 (1) | 0/2 | 0/2 / 0% / $0.0016 | 2/2 / 100% / $0.0193 | 2/2 / 100% / $0.0050 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 3.1.2 | pptx | assisted | 1 (1) | 0/2 | 0/2 / 0% / $0.0015 | 2/2 / 100% / $0.0152 | 1/2 / 67% / $0.0041 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 3.1.5 | pdf | human | 1 (0) | 2/2 | 2/2 / 0% / $0.0014 | 2/2 / 0% / $0.0151 | 2/2 / 0% / $0.0049 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 3.3.2 | docx | auto | 1 (0) | 2/2 | 2/2 / 0% / $0.0015 | 2/2 / 0% / $0.0212 | 2/2 / 0% / $0.0088 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 3.3.2 | html | auto | 1 (1) | 2/2 | 1/2 / 83% / $0.0014 | 2/2 / 100% / $0.0146 | 2/2 / 100% / $0.0038 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 4.1.2 | docx | auto | 1 (0) | 2/2 | 2/2 / 0% / $0.0013 | 1/2 / 0% / $0.0123 | 2/2 / 0% / $0.0042 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
| 4.1.2 | pdf | auto | 1 (1) | 2/2 | 2/2 / 100% / $0.0014 | 2/2 / 100% / $0.0158 | 2/2 / 100% / $0.0040 | **insufficient-evidence** | under-sampled: 1 case(s) in the corpus; the ladder itself refuses to route on fewer than 2 |
