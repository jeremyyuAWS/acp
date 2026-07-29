# ADR 0023 — Two-axis assessment model: classify by customer outcome, not by technology

Status: **Proposed** (2026-07-14)
Date: 2026-07-14
Supersedes the first draft of this ADR ("Review-Recommended assessment lane"), which introduced the 🟡 lane as a single fourth value bolted onto the existing capability table. This revision keeps that lane but reframes the whole model: **assessment and remediation are two independent axes**, and the customer-facing classification is by *outcome*, not by *implementation technology*.
Related: [ADR 0016](0016-evidence-based-confidence.md) (**the governing constraint** — a 🟡 Review row is a real, evidence-backed detection or it does not exist; no fabricated percentages), [ADR 0018](0018-slide-page-rasterization-and-shape-geometry.md) (the rasterization/geometry seam the render-gated 🟡 detectors ride), [ADR 0005](0005-server-side-remediation.md) (`remediation_capability` — the table this splits in two), [ADR 0002](0002-assessment-transparency-spec.md) (per-criterion transparency contract), [ADR 0020](0020-discover-assess-phase-separation.md) (Assess is where "how did this document do, per criterion" is answered).

## Context

`api/remediation_capability.py` holds one value per `(format × WCAG criterion)` — `auto` | `assisted` | `human` — and the whole Assess UI is derived from it. That single value silently answers **two different questions at once**, and conflating them makes the model both harder to explain and, in places, dishonest:

- `auto` means *ACP determines pass/fail deterministically* **and** *a deterministic fix clears it*.
- `assisted` means *ACP detects the problem* **and** *an AI/OCR proposer drafts the fix a human approves*.
- `human` is the worst offender: it lumps together *"ACP produced a definite finding but only a person can re-author the fix"* (reading level, link-purpose wording, justified text) with *"ACP cannot assess this criterion at all"* (keyboard operability of a static file). Those are opposite statements about what ACP knows.

The value is also expressed in **implementation vocabulary** — deterministic vs. OCR vs. vision vs. heuristic. That is exactly the wrong axis for a customer, who does not care *how* ACP reached a verdict, only *what the verdict means for their workflow*: do I trust it, do I check it, or do I do it myself?

## Decision

**Model every `(format × criterion)` pair on two independent axes, and surface both in customer-outcome language.**

### Axis 1 — Assessment: *Can ACP determine compliance?*

| Lane | Meaning | Customer experience |
|---|---|---|
| 🟢 **Auto** | ACP can confidently determine PASS **and** FAIL automatically, from a deterministic or computable structural fact. | No human needed to assess. |
| 🟡 **Review Recommended** | ACP cannot certify a pass, but detects concrete evidence of a likely issue and escalates it with that evidence + recommended remediation. | Human confirms ACP's evidence and approves the outcome. |
| 🔴 **Human-only** | ACP cannot collect enough evidence to say anything — the criterion depends on author intent, subjective judgement, or runtime behaviour. | Human assesses from scratch. |

The decision rule that separates them — and the honest test for 🟢 — is **"can ACP certify a PASS, not just detect a FAIL?"**

```
                     Can ACP assess this criterion?
                                 │
              ┌──────────────────┴──────────────────┐
       can certify pass & fail            cannot certify a pass
              │                                      │
          🟢 Auto                        Can ACP detect evidence of risk?
                                      ┌───────────────┴───────────────┐
                                     yes                              no
                                      │                               │
                          🟡 Review Recommended                 🔴 Human-only
```

A criterion where ACP can only ever *detect a failure but never confirm a pass* (image alt **adequacy**, link-text **quality**, colour-only meaning, focus order, non-text contrast) is **🟡, not 🟢** — even when the failing case is detected deterministically. Presence of an alt attribute is deterministic; whether the alt is *correct* is a judgement, so 1.1.1 can never be 🟢.

### Axis 2 — Remediation: *If it fails, how is the fix produced?*

Evaluated **only after** an assessment yields (or a human confirms) a FAIL. Orthogonal to Axis 1.

| Path | Meaning |
|---|---|
| ⚡ **Automatic** | A deterministic remediator clears the finding; verified by re-scan. |
| 🤖 **AI-assisted** | An AI/OCR proposer drafts a fix a human approves with one click. |
| 👤 **Human** | Genuine re-authoring; no tool can responsibly guess the answer. |
| — **None** | Nothing to remediate (assessment was 🔴, or the criterion carries no fix lane). |

The power of the split is that the axes vary independently. **1.4.4 Resize Text** is 🟡 assess / 👤 remediate (ACP flags likely clipping but cannot rewrite the document to guarantee reflow). **2.4.2 Page Title** is 🟢 assess / ⚡ remediate. **1.1.1** is 🟡 assess / 🤖 remediate (ACP can't certify alt quality, but can draft it). None of those three is expressible in the old single-value model without lying about one axis.

### Honesty guardrails (ADR 0016, non-negotiable)

1. **🟡 is earned by evidence.** Every Review outcome names the concrete artifact it found (control type + count, the colour-only cells, the low-contrast shape + measured ratio). No evidence → no 🟡 → the criterion is genuinely N/A for that file.
2. **🟡 never claims a pass.** Per file it resolves to REVIEW (signal present) or N/A (no signal) — never PASS. We flagged a risk; we did not verify conformance.
3. **No fabricated remediation and no fabricated numbers.** A 🟡 criterion offers no ACP fix it can't stand behind, and never a made-up confidence %.
4. **Assessment ≠ certification in the rollup.** The certifiable headline counts **🟢 only**. 🟡 is reported as an honest *superset* ("meaningful guidance on N of 20"), visually distinct from "ACP can certify M of 20". 🟡 findings are advisory and never block Publish; they are recorded on the certificate as reviewed-and-accepted.

### Per-file conditionality

Axis-1 lanes are the *format-level* capability ("ACP has a 🟢/🟡 method for this pair"). The *per-document* outcome is what the detector actually finds: a 🟡 criterion resolves to a REVIEW finding when its detector fires and to N/A-for-this-file when it does not — mirroring how a 🟢 criterion resolves to PASS or FAIL.

## Recommended reclassification — the 20 document-core criteria

Proposed mapping for `DOCUMENTS_20` × {docx, xlsx, pptx, pdf}, derived by applying the rule above to the current detectors/remediators. **This table is the input to the reclassification audit (task #174), which round-trip-verifies every cell against the real engines before it becomes the contract.** Cells flagged ⚠ need that verification most.

Each cell is `assessment / remediation`.

| SC | Criterion | docx | xlsx | pptx | pdf |
|----|-----------|------|------|------|-----|
| 1.1.1 | Non-text Content | 🟡/🤖 | 🟡/🤖 | 🟡/🤖 | 🟡/🤖 |
| 1.3.1 | Info & Relationships | 🟢/⚡ | 🟢/⚡ | 🟢/⚡ | 🟡/🤖 ⚠ |
| 1.3.2 | Meaningful Sequence | 🟡/🤖 | 🟢/⚡ | 🟡/⚡ ⚠ | 🟡/🤖 |
| 1.3.3 | Sensory Characteristics | 🟡/🤖 | 🟡/🤖 | 🟡/🤖 | 🟡/🤖 |
| 2.4.6 | Headings & Labels | 🟡/⚡ ‡ | 🟡/🤖 | 🟡/🤖 | 🟡/🤖 |
| 3.1.1 | Language of Page | 🟢/⚡ | 🟢/⚡ | 🟢/⚡ | 🟢/⚡ |
| 3.1.2 | Language of Parts | 🟡/🤖 | 🟡/🤖 | 🟡/🤖 | 🟡/🤖 |
| 1.4.4 | Resize Text | 🟡/👤 ⚠ | 🟡/👤 ⚠ | 🟡/👤 ⚠ | 🟡/👤 ⚠ |
| 1.4.5 | Images of Text | 🟡/🤖 | 🟡/🤖 | 🟡/🤖 | 🟡/🤖 |
| 1.4.10 | Reflow | 🟡/👤 ⚠ | 🟡/👤 ⚠ | 🟡/👤 ⚠ | 🟡/👤 ⚠ |
| 1.4.12 | Text Spacing | 🟡/👤 ⚠ | 🟡/👤 ⚠ | 🟡/👤 ⚠ | 🟡/👤 ⚠ |
| 1.4.1 | Use of Color | 🟡/👤 | 🟡/👤 | 🟡/👤 | 🟡/👤 |
| 1.4.3 | Contrast (Minimum) | 🟢/⚡ | 🟢/⚡ | 🟢/⚡ | 🟢/⚡ |
| 1.4.11 | Non-text Contrast | 🟡/👤 | 🟡/👤 | 🟡/👤 | 🟡/👤 |
| 2.4.2 | Page/Doc Titled | 🟢/⚡ | 🟢/⚡ | 🟢/⚡ | 🟢/⚡ |
| 2.4.3 | Focus Order | 🔴/— ⚠ | 🔴/— ⚠ | 🟡/👤 | 🔴/— ⚠ |
| 2.4.4 | Link Purpose (In Context) | 🟡/🤖 | 🟡/🤖 | 🟡/🤖 | 🟡/🤖 |
| 2.1.1 | Keyboard | 🔴/— | 🔴/— | 🔴/— | 🔴/— |
| 2.1.2 | No Keyboard Trap | 🟡/👤 † | 🟡/👤 † | 🟡/👤 † | 🔴/— ⚠ |
| 4.1.2 | Name, Role, Value | 🟡/👤 † | 🟡/👤 † | 🟡/👤 † | 🟡/👤 † |

‡ docx 2.4.6 was proposed 🟢/⚡ here and shipped that way; the audit's Correction 2 revised it to **🟡/⚡**. Its detector (`DOCX_HEADING_SKIP`) judges heading *levels*, not whether a heading describes its section, so the ⚡ remediator clearing every finding it raises never certified the criterion — see [0023-reclassification-audit.md](0023-reclassification-audit.md#correction-2-docx-246-headings-and-labels--). This is the one cell where the audit changed the proposed matrix.

† per-file conditional on the interactive-control detector (ADR 0023 Phase 1a, already shipped for office; `2.1.2`/`2.4.3`/`4.1.2` on a file with **no** controls resolve to N/A, not a finding). PDF AcroForm control detection (`pdf_form_field_checks`) already backs `4.1.2` and can extend to `2.1.2`.

Reading the result honestly: **ACP can *assess* far more than the old model implied — the human dependency is mostly in *remediation*, not assessment.** Almost every old `human` entry is really 🟢-or-🟡 assess / 👤 remediate. The genuinely-🔴 set is small: keyboard operability and focus order on static, control-free files.

## Blast radius / compatibility

- **Capability contract changes shape.** `CAPABILITY[fmt][sc]` goes from a string to `{assessment, remediation}`. `test_remediation_capability.py` round-trip proof now asserts both fields; `test_capability_frontend_sync.py` + `frontend/src/capability.js` re-sync to the new shape. **This is a breaking change to an internal contract — flag it in the PR** (no public `--json` / API surface depends on it directly; the Assess UI does, and moves in lockstep).
- **New per-file outcome `REVIEW`** in `scan_rule_traces` + the estate breakdown, ranked between HUMAN and GAP. `store._rule_outcome` becomes review-aware (`REVIEW_FORMATS`, advisory `severity="REVIEW"` at a zero rubric weight — already shipped). `get_certification_facts` gains a `review` bucket; its invariant becomes `evaluated + not_evaluated + review == catalog_size`.
- **Detectors are new `office_structure` checks** behind the existing `checks_for` seam; the interactive-control detector (2.1.2/4.1.2) already landed. No storage-schema change — REVIEW findings ride existing `issue_records` / `scan_rule_traces` rows.
- **Publish gate unaffected** — Review is advisory and never blocks certification.

## Alternatives considered

- **Keep one value, add `review` as a fourth lane.** (The first draft of this ADR.) Rejected — it leaves the assessment/remediation conflation in place, so `human` stays ambiguous and 1.4.4-style "detect-but-can't-fix" criteria still can't be expressed honestly. The two-axis split is the real fix.
- **Derive the assessment lane mechanically from the old value** (`auto`→🟢, `assisted`→🟡, `human`→🔴). Rejected — wrong in both directions: many `assisted` criteria detect deterministically (they're 🟢 on Axis 1 with a 🤖 fix), and most `human` criteria *are* assessed (🟢/🟡 assess, 👤 remediate). The reclassification is genuine per-rule judgement (task #174), not a remap.
- **Show implementation technology** (deterministic/OCR/vision) to customers. Rejected — that is the axis customers don't care about; it leaks internals and obscures the two questions they actually have.

## Rollout (phased — see tasks #173–186)

1. **Phase 0 — lock the model.** This ADR (#173) → reclassification audit (#174) → split `CAPABILITY` into two fields + contract tests + `capability.js` mirror (#175).
2. **Phase 1 — backend outcome.** `REVIEW_FORMATS` + review-aware `_rule_outcome` (#176); `get_certification_facts` review bucket + invariant (#177).
3. **Phase 2 — two-layer UI.** `statusIn` returns the assessment lane decoupled from remediation (#178); coverage matrix with separate Assessment + Remediation columns (#179); two-tile estate scorecard + customer-outcome wording (#180); the Rule × Format 🟢🟡🔴 grid (#181).
4. **Phase 3 — 🟡 detectors.** ✅ interactive controls 2.1.2/4.1.2 (shipped); 1.4.1 Use of Color (#182), 2.4.3 Focus Order (#183), 1.4.11 Non-text Contrast (#184).
5. **Phase 4 — render-gated 🟡** (1.4.4/1.4.10/1.4.12 + 1.4.3 hybrid), behind ADR 0018 (#185).
6. **Phase 5 — ship + verify live** (#186).

Target end-state for the 20 document-core criteria: **🟢 ~6 auto-assessable · 🟡 ~11–12 review-recommended · 🔴 ~2 human-only** on assessment, with the remediation axis independently reading **⚡ / 🤖 / 👤** — the certifiable headline (🟢) held honestly separate from the guidance superset (🟢 + 🟡).
