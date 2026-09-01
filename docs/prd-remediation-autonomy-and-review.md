# PRD — Remediation Autonomy and Review by Exception

**Product:** ACP  
**Scope:** Remediate, model evaluation, verification, and audit evidence  
**Status:** Proposed  
**Owner outcome:** Replace hundreds of repetitive approvals with safe automatic remediation and a small, meaningful exception queue.

## 1. Problem

The current Remediate experience can turn one assessment into hundreds of review rows. In the observed production run, 265 findings across 265 documents entered human review, largely for the same WCAG criterion. Several rows had no usable proposed value. A person cannot reasonably inspect this volume with care, and bulk approval would only disguise that the review did not happen.

The product currently treats too many findings as equivalent:

- deterministic changes that ACP can prove and re-check;
- model-generated changes with strong evidence and low impact;
- repeated instances of the same pattern;
- ambiguous or high-impact changes that need individual judgement;
- findings for which ACP has no actionable proposal.

The result is review fatigue, low trust, and a queue whose size encourages rubber-stamping.

## 2. Product outcome

**ACP fixes what it can prove, groups what it can generalize, samples what it can monitor, and asks a person only about material uncertainty.**

The default Remediate view becomes a run summary with three clear outcomes:

1. **Applied automatically** — corrected copies created and independently re-checked.
2. **Review by exception** — a small queue of ambiguous, novel, or high-impact proposals.
3. **Needs authoring** — no safe proposal exists; ACP explains what a person must supply.

The interface must never render hundreds of individual rows as the primary experience.

## 3. Principles

- **Evidence earns autonomy.** Model size or self-reported confidence never grants auto-apply by itself.
- **Independent verification is mandatory.** The generator and verifier cannot be the same judgement.
- **Originals remain unchanged.** ACP produces versioned corrected copies with rollback evidence.
- **Semantic changes receive stricter treatment than structural changes.** A structurally valid alt description can still be wrong.
- **Review effort is a budget.** The system ranks exceptions to fit a stated review budget rather than forwarding every uncertain item.
- **No proposal is not a review task.** Items with an empty “after” value go to Needs authoring, not Needs review.
- **Repeated work is reviewed as a pattern.** Review one representative cluster and apply the decision only where the cluster evidence matches.

## 4. Decision policy

Each proposed fix receives a policy decision from server-side evidence. The UI displays the decision and its basis; the client does not calculate eligibility.

### Tier A — auto-apply

All conditions must hold:

- the change is deterministic or belongs to an approved, independently verifiable lane;
- the corrected artifact passes the relevant post-fix detector;
- document integrity checks pass and no unrelated regression is detected;
- the change is reversible and the original is retained;
- the rule, format, model, and verifier versions are recorded;
- the lane meets its release precision target on a held-out evaluation set.

Initial Tier A includes the deterministic fixes already represented by the “ACP applies” lane. Expansion follows ADR 0041 and requires criterion-specific evidence.

### Tier B — sample and monitor

For a mature, low-impact pattern with strong production evidence:

- ACP applies the eligible cluster automatically;
- a configurable sample is routed to review;
- a rejected sample pauses that policy and routes the remaining cluster to review;
- drift, model changes, or a new document pattern reset the sampling rate upward.

Tier B is disabled until the policy has enough reviewed examples to measure precision with a useful confidence interval.

### Tier C — grouped approval

Use one review decision for a cluster only when the items share:

- criterion and document format;
- proposal strategy and model version;
- evidence type;
- normalized before/after pattern;
- risk class.

The reviewer sees representative examples, cluster size, exceptions, and the scope of the decision. “Approve pattern” never applies outside the displayed cluster.

### Tier D — individual review

Reserve individual review for:

- semantic ambiguity;
- public-facing or high-impact content;
- low evidence quality or disagreement between evaluators;
- novel patterns with insufficient history;
- changes that may alter meaning, reading order, legal language, or clinical intent.

### Tier E — needs authoring

Use when ACP has no substantive proposed value. Show the source location, the failed criterion, guidance, and an authoring control. Do not label the item “AI-drafted.”

## 5. Remediate experience

### Run summary

Lead with outcomes rather than a queue:

- **186 automatic fixes ready** — primary action: **Run automatic fixes**.
- **48 covered by 6 review patterns** — primary action: **Review 6 patterns**.
- **12 exceptions need individual review**.
- **19 need authoring**.

While processing, use the same live behavior as Assess: queued, claimed, processing, completed, failed, elapsed time, current file, and a link to Monitor. The counts must update from durable server state.

### Review workspace

- Default to grouped patterns, not individual files.
- Show a maximum review budget and explain why each exception crossed the threshold.
- Provide representative before/after examples and easy access to outliers.
- Keep document preview, decision controls, status summary, and audit trail in separate scroll regions.
- Support keyboard review and preserve the reviewer’s place.
- Never show an empty proposed value as an approvable fix.

### Completion

Show:

- documents fixed and independently verified;
- sampled items accepted or rejected;
- exceptions still open;
- failures with retry actions;
- corrected-copy destination and rollback access;
- a downloadable audit record of every policy and human decision.

## 6. Model strategy

A stronger model is a candidate generator, not an automatic promotion to a higher autonomy tier.

Evaluate at least the current model and one stronger multimodal model through the existing provider gateway. The evaluation corpus must include PDF, DOCX, XLSX, and PPTX examples plus domain-sensitive material. Blind human grading should measure:

- proposal correctness and completeness;
- harmful or meaning-changing edits;
- unsupported claims and hallucinations;
- preservation of document context;
- consistency across repeated patterns;
- abstention quality;
- latency and cost per accepted fix;
- post-fix accessibility outcome;
- reviewer acceptance without editing.

Select per criterion and format rather than naming one global “best” model. A model change creates a new policy version and temporarily increases sampling.

## 7. Release gates

Exact thresholds are configurable by criterion and risk class, but production defaults require:

- zero known destructive regressions in the release corpus;
- 100% pass on file-integrity and rollback checks;
- at least 99% precision for low-impact Tier B candidates before sampling is allowed;
- no auto-apply for semantic Group B changes without a separately approved verifier and ADR;
- automatic policy suspension when sampled-review precision falls below threshold;
- complete provenance for generator, verifier, evidence, policy, and output artifact.

Recall is secondary: ACP may abstain and ask for review. It may not lower the evidence bar to reduce queue size.

## 8. Success measures

- Reduce individual review items by at least 80% on representative POC scans.
- Keep median individual-review queue at 20 items or fewer per run.
- At least 95% of automatic fixes pass independent post-fix validation.
- Zero source-file overwrites.
- Zero critical regressions in sampled production review.
- At least 90% reviewer acceptance for grouped proposals without edits.
- Remediation progress becomes visible within 2 seconds of enqueue and refreshes at least every 2 seconds while active.
- Every terminal run reconciles queued, completed, failed, and canceled counts.

## 9. Delivery phases

### Phase 1 — usable automation

- Wire the existing deterministic batch card to the durable Remediate queue.
- Show live batch progress and terminal failures.
- Route empty proposals to Needs authoring.
- Group the review queue by criterion, format, and proposal pattern.
- Fix responsive pane containment and screenshot presentation.

### Phase 2 — policy service and evaluation

- Persist server-owned autonomy decisions and evidence.
- Build the blind evaluation corpus and model comparison harness.
- Add stronger-model candidates through the provider gateway.
- Establish criterion-specific thresholds and audit dashboards.

### Phase 3 — review by exception

- Enable approved Tier B sampling policies.
- Add automatic suspension and rollback.
- Add review budgets, outlier selection, and drift-triggered sampling.

## 10. Non-goals

- Auto-approving every model draft.
- Using a confidence percentage as proof of correctness.
- Modifying source documents in place.
- Hiding unresolved findings to make the queue appear smaller.
- Treating one reviewer’s approval as universal training data without scope and provenance.

## 11. Open decisions

- Which stronger multimodal models can run within the required Azure data boundary?
- Which criteria have an independent semantic verifier strong enough to move beyond grouped review?
- What review budget should be the default for the POC: 10, 20, or a percentage of findings?
- Which document classes must always require individual review because of clinical, legal, or executive risk?
- How many accepted examples are required before a pattern becomes eligible for sampling?

