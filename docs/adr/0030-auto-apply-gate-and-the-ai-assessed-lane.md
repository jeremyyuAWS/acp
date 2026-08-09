# ADR 0030 — The auto-apply gate: what evidence lets ACP write a fix, and what it still may not certify

Status: Proposed
Date: 2026-08-09

## Context

### The question that prompted this, and why the obvious framing is wrong

The proposal on the table is an "AI-assessed lane": for the eight `.docx` criteria currently
restricted to REVIEW, let a calibrated local model produce PASS/FAIL under an evidence gate,
rather than routing everything to a human. The framing assumes ACP has no such lane and needs
one built.

It has one. `store.get_auto_apply_validated()` is a platform setting, default **OFF**, and when
on it applies an *ungrounded* vision alt draft inline — but only when an **independent second
reading by a different model** (`ACP_ALT_VALIDATOR_MODEL`) returns `consistent`. It is wired for
both `remediate_office` and `remediate_pdf`, the provenance string on the resulting fix says
exactly how it was arrived at, and the post-fix re-scan still decides whether the criterion
actually cleared.

So the decision is not *whether to build an auto-apply lane*. It is **under what evidence the
existing switch may be turned on, and for which criteria** — and, separately, whether anything
here licenses moving REVIEW to PASS. Those two have been discussed as one thing and they have
very different costs.

### What the measurements say

Four vision models were run through the Verified Remediation Rate harness
(`scripts/score_remediation.py`) against the labelled corpus on 2026-08-09:

| model | size | VRR | regressions | integrity damage | left with nothing |
|---|---|---|---|---|---|
| `qwen2.5vl:3b` | 3.2 GB | 50% | 0% | 0% | 0 |
| `qwen2.5vl:7b` | 6.0 GB | 50% | 0% | 0% | 0 |
| `qwen2.5vl:32b` | 21 GB | 50% | 0% | 0% | 0 |
| `moondream` | 1.7 GB | 50% | 0% | 0% | **3** |

**Identical, from 1.7 GB to 21 GB.** That is not evidence that model size does not matter; it is
evidence that *the model's output never reached a document*. `auto_apply_validated` was off (the
harness has no Store, so the lookup raises and falls through to the proposal path), so every
ungrounded draft became a review card. The model changed what a reviewer saw and never what the
document got.

Two things follow, and both are load-bearing for this ADR:

- **Every model/prompt/evidence/routing experiment returns this same table until the gate moves.**
  A benchmark comparing 3B against 32B under the current default is measuring the deterministic
  engine four times.
- **The one place models did differ was safety, not quality.** `moondream` left three documents
  with no draft at all — the violation is still reported by the scan, so nothing is lost from
  *assessment*, but the reviewer gets no help. That is the axis a scorecard should rank on, and
  "VRR" alone does not show it.

### The eight REVIEW-lane criteria are two different problems

On the labelled corpus the deterministic engine scores **recall 1.00 and precision 1.00** on
1.1.1, 2.4.4, 3.1.2 and 4.1.2 with no model involved at all. They are not in REVIEW because
detection is unreliable. They are in REVIEW because a review-lane detector is not permitted to
certify (`assessment_policy._certify`, citing ADR 0016). That is a policy fact, not a capability
fact, and it splits the eight cleanly:

**Group A — the negative is deterministically provable.** 1.1.1, 2.4.4, 3.1.2, 4.1.2. "Does every
image carry a non-junk `descr` or a decorative marker?" is a yes/no question over the OOXML. A
model cannot improve that answer; it can only add a semantic opinion about *quality*, which is a
different and less verifiable claim.

**Group B — the negative requires judgement.** 1.3.2 (is the reading order *meaningful*), 1.3.3,
1.4.5 (is this image of text *essential*), 2.4.6 (is this heading *descriptive*), and the hard
half of 1.1.1 (is this alt text *correct*). Only here does model quality decide the answer.

### Verification completeness is the axis that actually decides auto-apply

Whether a fix may be written without a human depends on whether ACP can check the fix afterwards
— not on how good the model is:

| criterion | after the fix, can deterministic code confirm it is CORRECT? |
|---|---|
| **3.1.2** language of parts | **Yes, fully.** Set `w:lang="fr-FR"`, re-run langdetect on the span. No model prose is trusted. |
| 1.3.1 / 1.4.3 / 2.4.2 / 3.1.1 | already deterministic in both directions; auto-applied today |
| **2.4.4** link text | **Partly.** Uniqueness and non-junk are checkable; accuracy to the target is not. |
| **1.1.1** alt text | **No.** That an alt *exists* is checkable. That it is *true* is not. |

The 1.1.1 row carries an asymmetry that is easy to state and easy to forget:

> A missing alt is a defect that appears on every future scan. A confidently wrong alt is a defect
> that appears on none of them — because writing it **silences the detector**. Auto-applying an
> unverifiable alt does not merely risk being wrong; it destroys the evidence that anything was
> ever wrong.

`moondream` scoring **0.36** on factual accuracy is the concrete floor: a model that will fluently
describe a document it cannot read.

### The corpus cannot yet support the gate that has been proposed

A production bar of "PASS precision ≥ 99%" needs roughly **300 clean observations per criterion**
to defend. By the rule of three, *n* trials with zero observed failures bound the true rate at
about `3/n` at 95% confidence. The current corpus presents **21 seeded violations in total** — so
even at zero observed false passes it licenses a bound of **~14%**, an order of magnitude weaker
than the gate, and it would read as validated. `score_assessment.py` prints this ceiling on every
run for exactly that reason.

## Decision

**Separate the two permissions, and move only the cheaper one.**

### 1. Auto-apply and auto-certify are different rights, granted on different evidence

- **Auto-apply** (writing a fix without a human) is reversible and re-checkable. A wrong fix costs
  a re-scan and a revert. It is gated on **verification completeness**, per criterion.
- **Auto-certify** (a REVIEW-lane criterion returning PASS) is a **legal representation**. It feeds
  a VPAT/ACR asserted to a customer who is themselves under Section 508 and ADA obligations. The
  bar is not "is the model accurate enough" but "would we defend this number in a complaint
  response."

**No criterion moves from REVIEW to PASS under this ADR.** ADR 0016's gate stands unchanged.

### 2. Auto-apply is granted per criterion, by whether the fix can be verified

- **3.1.2 — GRANTED (docx and pptx).** The fix is metadata (`w:lang`), and the verification is
  complete: re-run the same detector on the same span. Nothing the model wrote is trusted, only
  which language a deterministic detector reports. This is the only criterion where auto-apply
  adds no unverified claim at all.
  No new machinery is needed and that is the point of granting this one first: the proposer
  (`proposals.propose_language_parts`) is already deterministic, the applier
  (`apply_text_values.py`) already writes `w:lang` on approved values, and the post-fix re-scan
  already decides whether the criterion cleared. What changes is that a deterministic proposal
  stops waiting for a human to confirm what a detector can confirm.
  **Not xlsx**: SpreadsheetML has no run-level language element, so no write can satisfy 3.1.2
  there. That is a schema fact, not a coverage gap (`apply_text_values.py:43-47`).
- **2.4.4 — NOT YET.** Partial verification. Revisit when a check exists for "does this text
  describe *this* destination", which is a real detector, not a threshold.
- **1.1.1 ungrounded — REMAINS OFF BY DEFAULT.** `auto_apply_validated` stays opt-in, per
  deployment, with the consistency cross-check required. The grounded (OCR-anchored) path is
  unchanged and continues to auto-apply, because its answer key is the image's own text.
- **Group B generally — NOT ELIGIBLE.** Nothing whose correctness cannot be re-derived from the
  document may be written without a human.

### 3. What a deployment must satisfy before enabling `auto_apply_validated`

The switch exists; this is the evidence to turn it on, and it is deliberately about the
*installation*, not about the model in the abstract:

1. A **distinct** validator model is configured (`ACP_ALT_VALIDATOR_MODEL` ≠ the drafting model).
   A model checking itself is a self-assessment, not a measurement.
2. The corpus regression gate (`tests/test_docx_corpus_regression_gate.py`) is green on that
   deployment's engine build.
3. The operator has accepted, in writing, that an auto-applied alt suppresses the 1.1.1 finding
   for that image on future scans.

### 4. Reporting must distinguish the three provenances

An applied fix already carries a provenance string. The three are not equivalent and must not be
collapsed in the UI or the certification PDF: *transcribed from the image's own text* (grounded),
*confirmed by an independent second reading* (cross-checked), *drafted and approved by a human*.

## Consequences

- **The model comparison becomes measurable — and only for 1.1.1 and only where the switch is on.**
  Every routing/cascade/prompt experiment stays a measurement of the deterministic engine until
  then. Any benchmark report must state which mode it ran in; `score_remediation.py` already
  refuses to present a cross-model table when zero model calls occurred, which is the same
  failure wearing a different hat.
- **Group A needs an ADR, not an experiment.** Whether 1.1.1/2.4.4/3.1.2/4.1.2 may certify on
  deterministic evidence alone is a policy question about what "we checked every image" licenses.
  It is deliberately out of scope here and is the natural successor to this ADR.
- **The corpus must reach ~300 observations per criterion before any PASS-precision bar is
  claimed.** The fixtures are generated, so this is parameterising `gen_sc_corpus.py`'s builders
  to sample densely around each decision boundary — not authoring 300 documents by hand.
- **`moondream` should not be a default anywhere.** Not for VRR — it matched the others — but for
  leaving three documents with no draft, and for 0.36 factual accuracy. Its cost lands on the
  reviewer, where a scorecard averaging over documents does not show it.

## Alternatives considered

**Turn `auto_apply_validated` on by default now.** Rejected. The consistency cross-check is a real
measurement, but the corpus behind it bounds the error rate at ~14%, and the failure mode for
1.1.1 is a silenced detector rather than a visible defect. Enabling it globally on that evidence
would be justified by the mechanism's design rather than by its measured behaviour.

**Move the Group A criteria to PASS on deterministic evidence.** Deferred, not rejected. It is the
strongest available argument — those four score 1.00/1.00 with no model — but it changes what a
conformance certificate asserts, and bundling it with an auto-apply decision would hide a legal
question inside a remediation one.

**Gate on model-reported confidence.** Rejected. A local model's `"confidence": 0.97` in a JSON
blob is not a calibrated probability, and ADR 0016 exists because ACP shipped fabricated
percentages once already. Any threshold must be derived from measured precision per bucket, with
enough observations per bucket to mean anything.

**Keep everything as it is and report the limitation.** Rejected for 3.1.2 specifically: its fix
is fully verifiable, so routing it to a human is asking someone to confirm what a detector can
confirm — the definition of the low-value review work the lane is supposed to remove.
