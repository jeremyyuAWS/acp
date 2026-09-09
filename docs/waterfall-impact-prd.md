# PRD: Show what the AI waterfall contributes to remediation

Date: 2026-09-08
Status: Approved design, partially implemented. The checkpoint below describes the current implementation; the remaining sections retain the target requirements. Deployment is tracked separately.

## Implementation checkpoint — 2026-09-08

- The plan chart and saved-suggestion drawer are implemented in `RemediationImpactCard`, `RemediationWaterfallImpact` and `RemediationAISuggestions`. They distinguish projected work from saved outputs and show actual original/proposed content with exact recorded model attribution when available.
- Managed text generation now retains bounded, owner/scan/run-scoped attempt records: actual output, input/output hashes, model, provider, purpose, status and spending evidence. Completed settled drafts replay without another paid call; retained settled empty/truncated first attempts can resume at fallback. Refusal or unknown usage cannot authorize another model. Oversized or missing content remains explicitly unavailable. Trace replay does not book the same model charge again.
- Immutable proposal snapshots preserve stored versions and source-excerpt hashes. Exact trace IDs connect them to producing attempts. These excerpt hashes are not full document revisions. Existing human-review and verification events remain distinct from proof that an exact proposal version was successfully applied.
- Optional review by a different configured model, followed by at most one optional final review, is implemented within the approved run's existing spending limit. Review comments do not replace the generated draft. The configured models currently share the selected provider; cross-provider review remains future work. Every resulting AI suggestion still requires a person’s approval.
- `RemediationRunInsights` loads retained history only when opened and provides paginated records. Its contribution counts are **saved proposal versions**, including revisions, not unique findings, additional verified fixes or a reconciled fixed-findings total. Draft, fallback and reviewer activity remain distinguishable; opening or paging history makes no paid requests.

**Remaining prerequisites:** collect and validate representative, versioned reliability data for each supported model/reviewer configuration and change family, and establish exact proposal-version/source-revision verification lineage. These are required before calibrated impact estimates or threshold-based automatic application can be enabled. A threshold preference can be captured with the run; it is not an operational automatic-approval permission. Current generic text proposals remain human-reviewed, and unavailable estimates or verified-fix counts are not reported as zero. The target reconciled results chart and unique-finding contribution measures below remain outstanding.

## Purpose

Help a nontechnical user answer: “What can rules fix, what extra help did AI provide, and what still needs me?” Show the contribution of successive models without treating a suggestion as a completed fix. Preserve the rules-only route so document delivery can proceed independently of AI.

## Recommended experience

Place an **Impact of your remediation plan** panel below the two plan questions. Use simple horizontal bars with labels and counts, following the visual style of the supplied reconciliation chart. Avoid a technical Sankey diagram or an accessibility score.

Provide two views: **Before you start** and **Results**. Before starting, show only supported routing forecasts; after starting, show measured outcomes from the selected run. Keep the scope, units, timestamp and preview/results label visible.

### Before you start

Show a single stacked bar for the selected unresolved findings:

| Segment | Visible explanation |
| --- | --- |
| Rule-based fixes ready | Supported fixes under your selected approval settings. These are not applied yet. |
| AI may help | Supported work that AI can try. A useful suggestion is not guaranteed. |
| Needs a person | Content decisions or work without a supported automated route. |
| Cannot plan yet | Missing evidence or other blockers prevent a reliable plan. |

Every finding belongs to exactly one segment. Rule-based proposals requiring approval remain identifiable in details; selecting “Review every change” must not imply they will apply automatically. “AI may help” is eligibility, not predicted success. When eligibility cannot be measured, show “Not yet known” instead of a sized segment or zero. In that case show available counts individually and explain why a complete bar is unavailable.

Show the process underneath in plain language:

**Try rules → Ask AI for remaining supported work → Review the suggestion → Apply approved changes and check the result**

Selecting Rules only removes future AI attempts from the plan. Neither toggling options nor opening the chart starts a run or makes paid requests. Keep the existing **Approve plan and start** action.

### Results

Use a reconciled outcome bar for the same fixed baseline of selected findings:

| Segment | Counting rule |
| --- | --- |
| Fixed and checked | Applied changes with qualifying verification evidence. Split rule-based and AI-assisted in details. |
| Suggestions awaiting review | Current, usable proposals not yet approved by a person. |
| Approved, awaiting completion | Approved proposals awaiting application or verification. |
| Still needs work | Rejected suggestions, failed verification, unsupported work, and other unresolved cases. |
| Still processing | Work with an active attempt. |
| Outcome unavailable | Records that cannot yet be reconciled. |

The segments must sum to the baseline. A failure may move an item back into unresolved work. Newly discovered findings are reported separately from this baseline; they must not silently change its denominator.

Below it, show **What each AI step added** as horizontal bars on a common scale:

| Row | Meaning |
| --- | --- |
| First AI: suggestions ready | Unique baseline findings covered by a usable first-model proposal. |
| Next AI: additional suggestions | Unique findings with a usable fallback proposal after the earlier attempt produced no usable proposal. |
| AI reviewer: checked suggestions | Suggestions reviewed by another model; this overlaps the generation rows and is displayed in a separate group. |

Use “additional suggestions” only with recorded attempt lineage. Do not claim causal improvement over rules from unrelated before/after runs. Revisions to an existing proposal are not additional findings. A second model being called is not evidence it helped.

Illustrative fixture only, never customer data: 100 baseline findings = 30 fixed and checked + 20 suggestions awaiting review + 5 approved awaiting completion + 35 still needing work + 8 processing + 2 unavailable. Of the 20 awaiting review, 15 came from the first model and 5 from fallback. A separate reviewer may have checked 12 of those 20; do not add 12 to the total.

Each bar opens the matching findings and files using existing drawers. Provide a table alternative with the same values. Use text labels, visible counts, sufficient contrast, keyboard operation and focus indicators; do not rely on color or mouseover. Respect reduced motion. At narrow widths, stack labels above bars. Never use bar width alone to communicate small nonzero counts.

## Inspect what each model generated

Make **AI may help** a keyboard-accessible drilldown labeled **See findings and AI details**. Before execution, it shows affected files, the issue in plain language, the task AI could attempt, and the configured model sequence when available. State **No suggestion generated yet**. Configured models are planned, not evidence of a call. Opening the drawer must never generate or regenerate a suggestion.

After execution, use **View AI suggestions** from the results chart and preserve access to the same finding history. Organize the drawer as file → finding → suggestion, with the latest proposal first and an expandable **What each AI did** timeline.

For each finding show:

- **Original and proposed change:** relevant source excerpt and actual stored generated content side by side, highlighting edits. Include page, slide, sheet or element location when available. Use a readable before/after view for images and structured changes. Do not replace the suggestion with a generic summary.
- **Who generated it:** provider, exact recorded model/version, time and role—draft, fallback, review or final review. Show each recorded attempt in order, including attempts producing no usable suggestion, and the reason another model was tried.
- **What changed between models:** each stored proposal version and a comparison with the previous version. Distinguish a new draft from a reviewer comment; do not imply the reviewer authored unchanged text.
- **Review result:** accepted, revision requested or unable to judge, with the model's concise recorded explanation and cited evidence. Show user-facing review output, not hidden reasoning or an invented explanation.
- **Current decision:** awaiting your approval, approved by you, approved under your policy, rejected, applied awaiting checks, or fixed and checked. Link the applicable threshold and checks, and identify the exact proposal version they cover.
- **Spending:** measured cost by attempt and total for this finding only when attribution is supported. Label shared/batched costs and outstanding or unknown amounts; never multiply a shared call's cost across findings.

Keep existing authorized review actions available: approve, edit or reject the current suggestion. Viewing history does not approve anything. Editing creates a new version and invalidates earlier version-specific review evidence as required by policy. Show rejected and superseded suggestions in history, not as current recommendations.

Persistence must retain owner-scoped generated artifacts and review outputs linked to attempt, proposal version and source revision under the existing document access and retention rules. Render generated text safely as content; never execute generated HTML or follow embedded instructions. If an output was not retained, say **Generated content unavailable** and retain known attempt metadata without reconstructing the missing text. Older attempts lacking exact model identity say **Model details unavailable**.

Acceptance checks: planned models are never presented as completed attempts; opening the drawer makes no paid request; two models' different drafts and a third model's review remain distinguishable; missing content is not fabricated; source edits invalidate stale review evidence; unauthorized users cannot retrieve another owner's outputs; and generated HTML displays without executing.

## Optional AI review and escalation

User-requested extension: a stronger or different model can check a proposed change before it reaches the person. Separate this from the current generation fallback.

Proposed bounded workflow:

1. Rules handle supported deterministic work under the approved policy.
2. A configured generation model drafts remaining supported work. Existing bounded fallback may try another model when the response is unusable and spending permits.
3. An optional reviewer model checks the source, proposed change and applicable criteria. It returns structured findings: acceptable, revision needed, or unable to judge, with reasons and evidence references.
4. On disagreement, allow at most one final adjudication or revision step. Stop on unresolved disagreement, refusal, missing evidence, unknown usage, exhausted budget or the configured attempt limit. A refusal must not trigger provider hopping to bypass it.
5. Route the resulting proposal to a person by default. If the user has enabled the supported threshold policy described below, evaluate every policy gate before authorizing application. Apply only after the required person or policy approval, then run existing verification.

Use **AI reviewed — awaiting your approval** for proposals routed to a person and **Approved under your policy — awaiting completion** for proposals that meet every automatic-application gate. Model agreement does not establish correctness or accessibility compliance. Preserve the original proposal, each review and any revision; reviewing a previous version must not mark the latest version reviewed. Documents and generated text are untrusted content, never instructions to the reviewer.

An explicitly selected different provider can provide a second perspective, but requires configuration and permission for that provider to receive document content. The current transport requires both generation models to use the owner-selected provider; cross-provider review is new work, not a capability to advertise as live.

The current execution path keeps AI at draft-for-review. The user has requested a configurable human-review threshold as an extension. This requires execution-service changes as well as UI; it is not available merely by adding a chart or a reviewer. Deterministic checks can establish objective properties; subjective content choices still need judgment.

## User-controlled human-review threshold

Question: **When should a person review AI changes?**

| Choice | Plain-language description |
| --- | --- |
| Review all AI changes — default | You approve each AI suggestion before it is applied. |
| Automatically apply eligible, checked changes | Apply supported changes only when they meet your review threshold and all required checks. Send everything else to a person. |

For the second choice, show **Minimum validated reliability**, the eligible change types, the selected reviewer, and a maximum spend for this run. Explain: “This is based on evaluated results for this type of change. It is not the AI's own confidence and does not guarantee each change is correct.” Do not invent a default percentage before calibration establishes an appropriate floor. Until calibration and enforcement are available, disable this option with “Available after validation is configured.”

Define a policy-controlled threshold T from 0–100%, constrained by an administrator-set minimum for each supported change family. Eligibility requires ALL of the following:

- The user explicitly selected automatic application for the run and the change family is permitted.
- An independent reviewer accepted the exact proposal version; unresolved disagreement cannot be overridden by a high score.
- Objective pre-application validation passed and all required source evidence is present.
- A versioned evaluation for the applicable model/reviewer configuration and change family supplies a calibrated reliability measure at or above T. Use a documented statistical lower confidence bound, with a required sample size and freshness period, rather than a raw model confidence score. This is cohort evidence, not certainty about an individual change.
- The proposal has no hard-review condition and the source has not changed since validation.

Hard-review conditions include subjective meaning changes, unsupported changes, missing or expired calibration, failed checks, conflicting reviews and stale evidence. The user cannot lower a threshold to bypass these conditions. If no calibrated measure applies, route to a person. Scope and eligible families must be explicit; never assume all AI outputs qualify.

The approval button authorizes this bounded run policy. Store its threshold, permitted families and evaluation version with the run. Later settings edits must not silently broaden an already approved run. Apply eligible changes through the existing controlled writer and verify afterward; unsuccessful verification remains unresolved and follows the existing recovery path. Never count a policy-approved change as fixed before verification.

In the preview, show **Eligible under your threshold**, **Still needs your approval**, and **Eligibility not yet known** when evidence supports these counts. Do not make paid review calls to populate a slider preview. In results, distinguish **Approved by you** from **Approved under your policy** in details and audit history. Show why a finding crossed or failed the threshold.

Boundary tests must cover just below, equal to and above T; equality qualifies only if every other gate passes. A high score plus failed validation, missing calibration or reviewer disagreement always requires a person. A policy change mid-run, stale proposal version or retry must never apply work under broader permissions than the recorded approval.

## Data and implementation requirements

Current evidence: `api/remediation_impact.py` exposes automatic/review/manual/blocked routes and finding counts. These are routing forecasts, not model success rates. The pending integration's `api/llm_waterfall_provider.py` returns attempt IDs, models, costs and draft/deferred outcomes. Its nonempty text result alone is insufficient evidence of a usable, approved or verified remediation. A durable joined outcome feed is required before showing measured contribution.

Proposed read-only aggregation contract:

- Identity: owner-scoped run ID, immutable scope/assessment revision, baseline finding identities, snapshot revision and timestamp.
- Coverage: complete/partial/unavailable, reconciliation reason, total baseline finding instances and selected file count.
- Preview: mutually exclusive route counts, selected policy, AI eligibility availability and explanation.
- Outcomes: unique finding state, proposal ID and version, rule/AI origin, originating model tier, review state, approval evidence, application and verification references.
- Attempts: stable operation and attempt IDs, generation/review/adjudication purpose, parent attempt, model/provider, status and reason. Deduplicate retries; one proposal covering multiple findings must map explicitly to those instances.
- Spending: settled generation and review costs, outstanding reservations, unknown charges and remaining run allowance. Show reservations separately from actual spend; missing cost is unknown, never zero.

Aggregate on the server from durable records. Apply owner access controls to both totals and drilldowns. Do not expose source content or prompts in chart telemetry. When evidence cannot be joined, report unavailable rather than infer success. Older runs without lineage show “AI step breakdown unavailable for this run.”

Freeze the baseline at run start; invalidate stale preview requests after scope or policy changes. During execution retain the last good snapshot with its timestamp and an updating/error message. Chart loading or failure must not prevent the existing rules-only workflow from proceeding.

## Delivery stages

1. **Plan chart:** reuse verified route data, plain-language labels, accessible table and drilldowns. AI incremental impact remains explicitly unknown. Add after the current release.
2. **Measured contribution:** persist/join attempt, proposal, approval and verification evidence; ship results chart and generation contribution breakdown.
3. **AI reviewer and threshold:** first ship the bounded reviewer in review-all mode; then enable user thresholds only for calibrated change families with server-enforced policy approval, separately tracked spend and review outcomes.
4. **Estimated impact:** only after representative evaluated outcomes exist, offer a labeled range for additional usable suggestions and expected cost. Show sample size, applicable formats/change types, date and uncertainty; hide estimates for unsupported populations. No initial promises of hours saved or compliance percentages.

## Acceptance criteria

- Fixture counts reconcile exactly, including partial results, rejection, failed verification, pending approval and retry replay.
- AI-generated, AI-reviewed, human-approved and verified-applied states are distinguishable. None can masquerade as another.
- Five additional fallback findings are counted as five even if retries or revisions create multiple attempts.
- Review activity is shown separately from mutually exclusive outcome totals.
- Preview changes make no paid requests; Rules only and a zero budget cannot initiate paid AI work.
- Unknown eligibility, missing provenance, unavailable cost and incomplete assessment never become zeros or passed checks.
- Scope switching cannot display a previous selection's counts. Drilldown totals agree with chart counts.
- All chart information is available by keyboard and in text; touch users can access explanations without hovering.
- Reviewer disagreement stops at the bounded limit. Approval and spending controls remain enforced by the execution service.
- Chart failure does not block the existing document delivery path.

## Success measures

Measure whether users can correctly distinguish “suggested” from “fixed and checked” in usability sessions; chart-to-finding drilldown usage; reconciliation errors; fallback-produced suggestions subsequently accepted or edited by people; verification outcomes by origin; and settled spending per accepted suggestion. Track reviewer disagreement and reviewer errors against human decisions. These are product-quality measures, not an accessibility score or proof of release readiness.
