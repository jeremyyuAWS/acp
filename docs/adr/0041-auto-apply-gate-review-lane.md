# ADR 0041 — Auto-apply gate for the AI-assessed review lane

**Status:** Accepted
**Date:** 2026-08-24
**Related:** ADR 0040 (Group A / Group B split), P4.1, P4.4 (independent verification),
P4.0 (this decision), BACKLOG.md P4.x section.

## Context

The PRD asks whether the review lane may ever auto-apply a fix without a human in the loop.
The question has been stuck at `[?]` — a design decision, not an engineering gap — while the
measurement evidence accumulated below it:

- `score_remediation.py` scored `qwen2.5vl` 3B, 7B, 32B and `moondream` at an identical **50%
  VRR / 0% regression / 0% damage**. That 50% is structural: the honesty split routes every
  ungrounded vision draft to `proposals` (human review), so the model changes what a reviewer
  *sees*, never what the document *gets*. No model parameter sweep can move that number while
  the gate stays closed, which is why a sweep across four models reads as "parameter count does
  not matter" when it actually means "no output reached a document."

- A precedent already ships: **grounded (OCR-anchored) alt text auto-applies today**. When the
  engine has a structural transcript of the image text, it applies the alt directly — no human
  touch required. The question for P4.0 is whether to generalise that mechanism to the other
  Group A SCs, not whether to invent one.

- ADR 0040 formalised the split that makes this question answerable: Group A SCs have FAIL
  conditions that are structural OOXML facts (an attribute is absent or junk). A fix is a
  structural attribute write. A pass can be confirmed by re-running the same structural
  detector. Group B SCs require semantic quality judgement; no structural re-check is possible
  after the fix. See ADR 0040 for the full split and the 1.1.1 silencing asymmetry.

## Decision

**Auto-apply is permitted for Group A SCs, subject to the P4.4 independent verification
gate.** Group B SCs are permanently human-review-only under the current evidence gate.

### The evidence gate (Group A)

A fix may be auto-applied when ALL of the following hold:

1. **The SC is in Group A** (1.1.1 structural part, 2.4.4, 3.1.2, 4.1.2). The FAIL condition
   is a structural OOXML fact; the fix is a structural attribute write.

2. **The hitl_queue row carries `validated=True`**, set by P4.4's independent verifier. The
   verifier re-runs the structural detector on the proposed fix value — independently of the
   generator — and confirms the fix would clear the check. The generator and verifier may not
   be the same code path (P4.4 enforces this for 3.1.2 via `verify_language_part`).

3. **The fix is re-checkable by re-scan.** After the fix is applied, the structural detector
   must return no finding for that criterion on that element. This is the same confirmation
   P4.4's independent verification performs before the fix reaches the queue.

When these three conditions hold, no model output reaches the document. The fix is the
structural attribute value the verifier confirmed; the model (if one was involved) proposed
the candidate, but the verifier's structural re-check is the gate that lets it through.

### Why Group B is permanently human-review-only

ADR 0040 identified the asymmetry: for Group B, a model-produced value that is wrong does not
cause a finding — it silences the detector. A wrong but non-junk alt text makes 1.1.1
disappear while the accessibility failure persists. Re-running the structural detector after
applying the fix proves nothing: the detector passes a wrong alt because the wrong alt is
structurally valid. There is no post-hoc signal that the fix was bad.

The same asymmetry applies to every Group B SC:

- 1.3.2: a reading-order fix that looks structurally valid is undetectable as wrong after
  application.
- 1.3.3: a rewritten instruction that removes sensory language may still be ambiguous; no
  structural check confirms the rewrite preserved intent.
- 1.4.5: an "essential" classification that is wrong lets a substitutable image-of-text stay;
  structural re-scan cannot detect the classification error.
- 2.4.6: a rewritten heading that passes the presence check may still be undescriptive; the
  engine cannot confirm quality, only presence.

No model confidence score, corpus density result, or evidence-mode experiment changes this.
The asymmetry is a property of the SC's checking mechanism, not of the model's quality.
Group B requires a human in the loop for every fix, indefinitely.

### The grounded alt precedent, generalised

The existing OCR-anchored alt path already satisfies the gate:
- The SC (1.1.1 structural part) is Group A.
- The fix (alt = OCR transcript) is confirmed checkable by re-scan (non-empty, non-junk descr).
- The "verifier" is the engine's own junk-pattern check on the transcript before it is written.

P4.4 generalises this shape to 3.1.2: the generator (`propose_language_parts`) proposes a
`xml:lang` value; the verifier (`verify_language_part`) re-runs `detect_langs` on the segment
text independently and confirms the code matches. The gate is the same gate.

Extending auto-apply to 2.4.4 (link text) and 4.1.2 (accessible name) follows the same
pattern: propose a fix, run the structural detector on the proposed value, set
`validated=True` if it passes, apply directly. No model output needs review; only the
structural check does.

## Consequences

- **Routing change** (implementation): `apply_alt.py` and the equivalent for 2.4.4 / 4.1.2
  should check `hitl_queue.validated` before deciding whether to auto-apply or route to human
  review. This is the code change P4.0 unlocks; it does not change the detection logic.

- **P4.2 / P4.3 experiments** are scoped to Group B only. Running precision/recall sweeps on
  Group A would measure a structural check whose score is already 1.00 and cannot be raised by
  a model; see ADR 0040.

- **The 50% VRR number will move** once the gate opens for Group A SCs beyond the grounded-alt
  path that already ships. It will not move for Group B.

- **Score interpretation changes.** After this gate, a sweep that still shows 50% VRR on
  Group B SCs is evidence about model quality on semantic judgements, not about the gate. The
  two numbers should be reported separately.

- **This ADR does not authorise a blanket auto-apply policy.** It authorises auto-apply for
  Group A SCs that pass the three-condition gate. Any SC added to Group A after this ADR, or
  any expansion of the gate beyond structural re-scan, requires a new ADR.
