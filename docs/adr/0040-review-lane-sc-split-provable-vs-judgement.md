# ADR 0040 — Review-lane SCs split: deterministically provable vs. semantic judgement

**Status:** Accepted
**Date:** 2026-08-24
**Related:** P4.0 (auto-apply gate), P4.1 (this split), P4.2 (corpus density), P4.4
(independent verification), ADR 0016 (evidence-based confidence), BACKLOG.md P4.x section.

## Context

The PRD lists eight WCAG criteria as "AI-assessed, reviewer-in-the-loop" and groups them into one
homogeneous lane, proposing a single set of ML experiments (precision/recall sweeps, confidence
calibration, adversarial fixtures) to clear them all. That framing is wrong in a way that matters
for P4.0 (the auto-apply gate) and P4.2 (the corpus-density requirement).

The eight criteria are not equivalent. For some, the detector's FAIL is an objective structural
fact about the OOXML: an attribute is missing, a value is empty, a code is syntactically invalid.
ACP already answers those questions at **1.00 recall / 1.00 precision** with no model. For others,
the FAIL fires on a semantic quality judgement: is the reading order *meaningful*, is the alt text
*correct*, is the heading *descriptive*. No structural check can answer those; only a human, or a
model with measurable quality, can.

Running ML experiments across all eight treats a 1.00-precision structural detector as if it needed
to be improved by a model. It cannot. A language model offered a structurally-checkable attribute
can only add a semantic quality opinion, which is a different claim — and a less verifiable one —
than the structural check that already fired. Sweeping all eight together obscures which experiments
earn their cost and which are wasted.

## Decision

Formally split the eight review-lane criteria into two groups. The split is on a single property:
**whether the detector's FAIL is provable from the OOXML structure alone, without any semantic
interpretation.**

### Group A — Structurally provable FAIL

| SC | What triggers FAIL | What PASS requires |
|----|--------------------|--------------------|
| **1.1.1** (structural part) | Image has no `descr`, or `descr` is a junk pattern (filename, whitespace, short generic) | Every image has a non-junk `descr` or is explicitly marked decorative |
| **2.4.4** | Link text is empty, generic ("click here"), or a bare URL | Link text is non-empty and non-generic |
| **3.1.2** | A text run's language differs from the document language and carries no `xml:lang` | Every foreign-language run carries the correct `xml:lang` attribute |
| **4.1.2** | An interactive control has no accessible name | Every control has a non-empty accessible name |

For Group A:

- The FAIL condition is an **absence or structural error** in the OOXML that the scanner reads
  directly. No inference, no probability.
- The PASS condition is checkable by re-running the same structural detector over the fixed bytes.
  This is what P4.4's independent verification uses for 3.1.2, and what `verify_residual_scs` uses
  for 2.4.4 after link text is applied.
- An LLM offered one of these findings can add a **semantic quality opinion** ("is this alt text
  *good*?") — but that opinion is a separate claim, not an improvement to the FAIL decision itself.
  The FAIL was already correct. The model cannot make it more correct; it can only inject a quality
  assessment that may or may not be reliable.
- **ML experiments do not apply to Group A.** Precision/recall sweeps, confidence calibration and
  adversarial fixture density (P4.2) are irrelevant: the detector already achieves F1 1.00 and a
  model cannot raise that. The experiments earn their cost only in Group B.

### Group B — Semantic judgement FAIL

| SC | What requires judgement |
|----|------------------------|
| **1.1.1** (semantic part) | Is the alt text *accurate and useful*, not merely non-empty and non-junk? |
| **1.3.2** | Is the logical reading order *meaningful* for a reader, not merely left-to-right-then-down? |
| **1.3.3** | Does the instruction rely *solely* on sensory characteristics (shape, colour, position)? |
| **1.4.5** | Is the image of text *essential* (logotype, legal requirement) or substitutable with styled text? |
| **2.4.6** | Is the heading *descriptive* of the section it labels, not merely present? |

For Group B:

- The FAIL fires on a semantic quality judgement that structural analysis cannot settle. A heading
  exists (structural check: PASS) but is it descriptive? That requires reading the section and the
  heading together, and deciding.
- Model quality is the deciding factor. A better-grounded model, a richer evidence package (ADR
  0016, P4.3), and denser adversarial fixtures (P4.2) can move the precision/recall surface here.
- The PRD's experiments — evidence modes A–E, corpus density, confidence calibration — are scoped
  to Group B. Running them on Group A is category error.

### The asymmetry that matters for 1.1.1

1.1.1 straddles both groups deliberately. The structural detector catches *missing or junk* alt
(Group A, F1 1.00). The quality question — is the non-junk alt *correct and useful* — is Group B.
Both parts of the criterion route to human review, but for different reasons:

- Group A finding: "the structural attribute is absent or junk" → provably fixed by supplying any
  non-junk text; verifiable by re-scan. The reviewer confirms the proposed text meets the bar.
- Group B finding: "the alt text exists but may be wrong" → not verifiable by re-scan. A detector
  that passes a wrong but non-junk alt is silencing itself — the 1.1.1 finding disappears while
  the accessibility failure persists. This is the asymmetry that rules out auto-apply for Group B:
  **a wrong alt does not merely fail, it silences the detector.**

## Consequences

- **P4.0** (auto-apply gate) is constrained by this split. Group A SCs are eligible for
  auto-apply once P4.4's independent verification confirms the fix clears the structural re-scan
  — no model output needs to reach the document. Group B SCs are not eligible for auto-apply
  under any model quality argument, because a model-produced value that silently fails is
  undetectable post-hoc.
- **P4.2** (corpus density) experiments apply only to Group B. Sweeping Group A adds denominator
  without adding signal, and `score_assessment.py`'s per-SC ceiling already reports that.
- **P4.4** (independent verification) is fully applicable to Group A (the fix is structural and
  re-checkable) and inapplicable to Group B (re-running the detector after applying a model value
  proves nothing if the model value is wrong — see 1.1.1's silencing asymmetry above).
- **ADR 0016** (confidence model) maps naturally onto this split: Group A findings are `High`
  confidence once the structural check fires; Group B findings are `Medium` until a human confirms
  the semantic quality.
- This ADR does not decide P4.0. It constrains the eligible set: if P4.0 permits auto-apply under
  a specified evidence gate, only Group A SCs can satisfy that gate today. Group B requires a
  separate, higher bar — or a decision that they are permanently human-review-only.
