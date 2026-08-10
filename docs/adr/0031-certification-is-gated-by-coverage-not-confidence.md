# ADR 0031 — Certification is gated by coverage, not confidence: what would let a REVIEW criterion become PASS

Status: Proposed
Date: 2026-08-09

Successor to ADR 0030, which ended by naming this decision: *"Whether 1.1.1/2.4.4/3.1.2/4.1.2 may
certify on deterministic evidence alone is a policy question… the natural successor to this ADR."*
Revisits ADR 0016 (a review-lane detector does not certify a pass) — and concludes it was right,
for a reason the "AI-assessed lane" framing had obscured.

## Context

### The question, in the form it is usually asked

For the `.docx` criteria stuck at REVIEW, may a good-enough model — or a good-enough deterministic
check — produce PASS, instead of routing every clean document to a human? ADR 0030 answered the
auto-*apply* half (write a fix under a verification gate) and deferred the auto-*certify* half
(return PASS). This ADR is that half.

It is usually asked as a question about **confidence**: is the detector, or the model, accurate
enough to be trusted with a PASS? Reading the code says that is the wrong axis.

### Certification is already gated by COVERAGE, in code, today

`rule_registry.result_for` (api/rule_registry.py:183) turns a detector's findings into a verdict,
and the branch that matters is two lines:

```python
if reg.coverage in CAN_CERTIFY_PASS:      # == {Coverage.FULL}
    ... PASS on a clean scan ...
if reg.coverage in NEEDS_REVIEW_ON_CLEAN: # == {Coverage.PARTIAL, Coverage.HEURISTIC}
    ... REVIEW on a clean scan ...
```

`CAN_CERTIFY_PASS` is exactly `{FULL}`. So a clean scan certifies a pass **iff the detector's
declared coverage is FULL**, and confidence — `Confidence.HIGH` and all — never enters this
decision. A detector can be exact and still not certify, because exactness and completeness are
different properties. `result_for` says so in its own comment: *"Partial coverage limits what a
CLEAN result can claim."*

This reframes every REVIEW-lane criterion. It is not at REVIEW because we distrust the detector's
answer. It is at REVIEW because the detector answers a **narrower question than the criterion
asks**, and a clean result to a narrow question does not certify the wide one.

### What the Group-A detectors actually declare

ADR 0030's "Group A" — the four that score recall 1.00 / precision 1.00 on the corpus with no model
— every one of them is `coverage=PARTIAL`, and each registration's own `reason` names the part it
does not look at:

| criterion | coverage | what a clean scan does NOT prove (from the registration `reason`) |
|---|---|---|
| 4.1.2 | PARTIAL | content controls are named; **ActiveX controls, embedded OLE objects and other form content are not examined** |
| 1.1.1 | *(not in registry — see below)* | embedded images carry alt/decorative; charts, SmartArt, grouped shapes, objects are a wider "non-text content" |
| 2.4.4 | *(not in registry)* | link text is non-vague; whether it describes **this** destination is not checked |
| 3.1.2 | *(not in registry)* | foreign passages of ≥12 words are flagged; a short unmarked foreign phrase is under the floor |

The 1.00/1.00 on the corpus is real and it is not enough — not because 21 seeded violations bound
the error at only ~14% (they do; ADR 0030 §"The corpus cannot yet support the gate"), but for a
prior reason: the corpus measures the detector on the **subset it examines**. A perfect score on
"are the content controls named" is silent about the ActiveX control in the same document. No
number computed over the examined subset can certify the unexamined remainder.

### There are two REVIEW mechanisms, and Group A straddles them

A latent inconsistency, surfaced while grounding this ADR: only **four** docx criteria are in the
capability registry (`4.1.2, 1.4.1, 1.4.11, 2.1.2`) and get their REVIEW verdict from the coverage
gate above. `1.1.1, 2.4.4, 3.1.2` are **not in the registry** — they are declared through
`store.RULE_FORMATS` and reach REVIEW through the older `assessment_policy` path (ADR 0016's
`_certify`). Same outcome, two code paths. So "Group A" is certified-blocked by two different
mechanisms that happen to agree today, which is exactly the "two disagreeing tables" hazard the
registry migration was meant to end (ADR 0023 / #144).

### The two groups, seen through coverage rather than through models

- **Group A — deterministic FULL is ACHIEVABLE.** The unexamined remainder is finite and
  machine-readable. 4.1.2's remainder is "ActiveX/OLE controls"; 3.1.2's is "passages under the
  12-word floor"; 1.1.1's is "non-image non-text content." Each is a detector one could write.
  Reaching `Coverage.FULL` here is engineering, not judgement — and when it is reached, the same
  `result_for` line already certifies the pass with no further decision.

- **Group B — deterministic FULL is IMPOSSIBLE.** 1.3.2 (is the reading order *meaningful*), 1.4.5
  (is this image of text *essential*), 2.4.6 (is this heading *descriptive*), and the hard half of
  1.1.1 (is this alt text *correct*). No read of the XML settles these. Here — and only here — a
  model is the only thing that can cover the judgement, so the **model's measured precision IS the
  coverage**. This is where an "AI-assessed lane" is actually a lane, and it is downstream of the
  Group-A work, not a substitute for it.

## Decision

### 1. Coverage is the single certification gate. ADR 0016 stands, restated.

A `(criterion, format)` may return PASS on a clean scan **iff its detector declares
`Coverage.FULL`**. ADR 0016's "a review-lane detector does not certify" is correct and is now
stated precisely: *a detector below FULL coverage does not certify, because a clean result to a
partial question does not answer the whole one.* Confidence never certifies; only completeness
does.

**No criterion moves from REVIEW to PASS under this ADR.** Every Group-A detector is PARTIAL today.

### 2. Consolidate the two REVIEW mechanisms into the coverage gate.

Migrate `1.1.1, 2.4.4, 3.1.2` (docx) into the capability registry with `Coverage.PARTIAL` and a
`reason` that names their remainder, the same shape as the 4.1.2 registration. This changes no
verdict — they stay REVIEW — but it removes the parallel `assessment_policy` path for them, so
every criterion is certified-gated by one mechanism a reader can inspect. This is a prerequisite
for graduation: a criterion cannot cross to FULL through a gate it does not use.

### 3. The graduation criteria, per group.

A `(criterion, format)` earns PASS when, and only when:

- **Group A:** its detector reaches `Coverage.FULL` — every failure mode the format can realize is
  examined, with the registration's `reason` reduced to nothing — **and** the corpus demonstrates
  zero false-PASS at a defensible n (ADR 0030: ~300 observations, which is P4.2's densification,
  not 300 hand-authored files). Coverage first; the corpus confirms the coverage claim.

- **Group B:** a **calibrated** model whose per-criterion PASS-precision is **measured** at or above
  the certification bar (proposed ≥99%) over ≥~300 labelled observations, honouring the abstention
  and asymmetry rules below. The model does not need to be trusted; its precision needs to be
  measured, per criterion, with enough observations for the number to mean something. Until that
  measurement exists, Group B is not eligible, and ADR 0030 already established the corpus is an
  order of magnitude too small to produce it.

### 4. The 1.1.1 asymmetry is a hard constraint on Group B, not a footnote.

From ADR 0030, and load-bearing here: a wrong PASS on alt text **silences the detector** — the
defect appears on no future scan, because the presence of *an* alt is what the check reads. So any
Group-B PASS lane must (a) hold its corpus to adversarial cases where a fluent-but-wrong answer is
the failure, and (b) carry a higher precision bar than a criterion whose wrong PASS stays visible.
A certificate is a legal representation (VPAT/ACR under Section 508/ADA); the bar is "would we
defend this number in a complaint response," not "is the model usually right."

## Consequences

- **The "AI-assessed lane" is correctly located: it is a Group-B mechanism, downstream of
  coverage.** A perfect model does not unlock a PARTIAL criterion — it still has not looked at the
  ActiveX control. This is the single most useful thing this ADR says, because it stops the lane
  being proposed as a shortcut around coverage work it cannot replace.
- **Group A has a concrete, model-free backlog to PASS**, and it is coverage work: an ActiveX/OLE
  reader (4.1.2), a sub-threshold language check (3.1.2), a non-image non-text walk (1.1.1), a
  link-describes-its-target check (2.4.4). Each is a detector, each moves its criterion one step
  toward `Coverage.FULL`, and none needs a model or a policy change — `result_for` certifies
  automatically once coverage is FULL.
- **P4.2 (corpus density) is a precondition for BOTH paths**, so it is not optional Phase-4 polish
  — it is the evidence half of every future PASS claim.
- **Migrating the three legacy criteria removes a real inconsistency** and is worth doing
  regardless of the certification question.

## Alternatives considered

**Certify Group A now, on the 1.00/1.00 corpus.** Rejected, on two independent grounds. The
statistical one (ADR 0030): 21 violations bound the error at ~14%, not ≤1%. The deeper one (this
ADR): the detectors are PARTIAL, so the score measures the examined subset, and no amount of corpus
fixes a coverage gap. Both must be closed, and coverage is the one the framing had hidden.

**Build the Group-B AI-assessed lane now.** Rejected. No calibrated per-criterion precision
measurement exists, the corpus is ~10× too small to produce one, and coverage — not model quality —
is the nearer blocker for the criteria closest to PASS. Building the lane first optimises the part
that is not on the critical path.

**Overturn ADR 0016 — let a high-confidence review detector certify.** Rejected, and it is the
tempting wrong answer. `Confidence.HIGH` on a `Coverage.PARTIAL` detector means "the subset I
examine, I read exactly" — a confident report about part of the criterion. Certifying on it would
assert the whole criterion on evidence about a fraction of it, which is precisely what
`result_for` refuses and what ADR 0016 was written to prevent.

**Leave the two REVIEW mechanisms as they are.** Rejected. They agree today by coincidence of
values, not by construction; the registry migration exists to make agreement structural, and
leaving `1.1.1/2.4.4/3.1.2` on the legacy path keeps a second source of truth for the most
consequential verdict ACP emits.
