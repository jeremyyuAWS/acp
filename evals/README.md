# `evals/` — the Remediation Evals Kit

Provider-neutral harness for **"which is the cheapest tier that can safely do this remediation?"**
Budget: **100,000 calls per $1** ($1e-5/call = 0.001c/call).

```
python scripts/run_remediation_evals.py                 # default run, no network, ~1s
python scripts/gen_remediation_eval_corpus.py --check    # corpus is current
python -m pytest tests/test_remediation_evals_kit.py     # the graders still bite
```

| file | what it holds |
|---|---|
| `schema.py` | the case schema and a strict validator (unknown key = error) |
| `cases/` | 100 generated cases: 40 common, 20 malformed, 15 must-abstain, 15 adversarial, 10 novel |
| `candidates.py` | `rules-only`, scripted stubs, `ollama:`, `hosted:` — one method to add a provider |
| `world.py` | the simulated fixture a plan is executed against, plus the inverse log for rollback |
| `graders.py` | deterministic graders, one per stage of the loop |
| `judge.py` | the optional model judge, off by default, reports its own human agreement |
| `cost.py` | pricing shapes, the price book, the budget gate |
| `harness.py` | candidates x cases x repeats, with the meter running |
| `report.py` | VARR, hard gates, risk-tier breakdown, the routing ladder |

| `rescan.py` | product-predicate detectors over field state; cleared vs. regressed as separate facts |
| `review.py` | the review loop: proposal → reviewer oracle → apply → re-scan, with the meter running |
| `adversarial/` | 32 production-like cases across alt text, headings/labels, link purpose, document language, semantic structure — ambiguous and unsafe ones included |

Full documentation: [`docs/remediation-evals-kit.md`](../docs/remediation-evals-kit.md).

The adversarial review-loop set has its own runner and page:

```
python scripts/run_adversarial_claude_evals.py                 # offline, ~1s
python scripts/gen_adversarial_claude_evals.py --check          # set is current
```

[`docs/adversarial-claude-evals.md`](../docs/adversarial-claude-evals.md) — accepted unchanged /
after editing / rejected or refused / applied / cleared after re-scan / regressions / latency and
cost, per candidate and per category.
