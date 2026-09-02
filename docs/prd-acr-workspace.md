# PRD — ACP Accessibility Conformance Report Workspace

Status: Phases 1–3 delivered · Phases 4–6 planned
Design decisions: [ADR 0047](adr/0047-acr-workspace-data-model.md)

## Purpose

Let ACP customers and internal accessibility teams produce an evidence-backed Accessibility
Conformance Report (ACR) using the official ITI VPAT® structure — collecting evidence, evaluating
applicable criteria, documenting limitations, obtaining human approval, and exporting an
accessible report.

**It must never claim that automated scans alone establish accessibility compliance.**

## Scope of the evaluated product

The ACR is about **ACP's own web application**, evaluated against **WCAG 2.2 Levels A and AA**.

This is not the same subject as the rest of ACP, and the distinction is the feature's central
integrity constraint. `docs/conformance-report.md` already states it: *"this report covers the
conformance of the platform's own web UI, not the conformance of customer documents it
remediates."* Automated evidence therefore comes from **axe-core runs over ACP's own screens**
(the runner already exists — `frontend/src/A11ySelfCheck.jsx`), never from document scan findings.

## Product principles

1. **Evidence before claims.** Every conformance statement links to evidence, a documented manual
   evaluation, or an explicit explanation.
2. **Human approval is mandatory.** ACP may recommend a draft status; it must not publish without
   an authorised reviewer approving every applicable criterion.
3. **Automated testing is incomplete.** An automated pass never automatically produces "Supports".
   Criteria needing keyboard, screen-reader, visual, cognitive, content or usability judgement
   enter a manual review queue.
4. **Honest limitations.** "Partially Supports" and "Does Not Support" are valid results. Make
   limitations visible rather than optimising for a compliance score.
5. **Reproducibility.** A published ACR identifies the product version, environment, workflows,
   dates, tools, assistive technologies, browsers, evidence and reviewers behind its conclusions.
6. **Preserve the official template.** Use the ITI VPAT template as the export foundation; do not
   recreate, rename or materially alter its structure, marks, instructions, terminology or tables.

## Conformance vocabulary

Final statuses are exactly the four VPAT terms and nothing else:

`Supports` · `Partially Supports` · `Does Not Support` · `Not Applicable`

ACP's internal workflow states (`not_evaluated`, `needs_review`, `decided`) live in a **separate
column** and are never exported as a conformance level.

## Decision rules

**Supports** requires: the behaviour evaluated; required automated *and* manual methods completed;
no unresolved failure contradicting the claim; supporting evidence attached; a human confirming it.

**Partially Supports** requires remarks naming what supports the criterion, what does not, the
affected functionality, the user impact, any workaround, and the remediation status.

**Does Not Support** requires remarks naming the affected functionality and the limitation.

**Not Applicable** requires an explanation of why the criterion does not apply.

**Not evaluated** is internal only. A report with applicable criteria in that state cannot publish.

## Evidence and freshness

Evidence records carry type, criterion, result, method, tester, timestamp, product version,
environment, workflow, browser and assistive technology, notes, attachments, and related records.
Automated evidence additionally preserves the tool name, tool version, rule ID, tested view, the
original result, **and a declared coverage** — how much of the criterion the technique reaches.

Evidence is **stale** when it belongs to a different product version, its component changed after
testing, its validity window elapsed, a regression contradicts it, or a resolved finding reopened.
Stale records stay visible for audit history and cannot independently support publication.

## Delivery phases

| Phase | Scope | Status |
|---|---|---|
| 1 | Domain model, standards catalog, decision rules, validation, roles, thin vertical slice | **delivered** |
| 2 | Evidence workspace — **rescoped**, see below | **delivered** |
| 3 | Guided manual test plans, tester metadata, and the publish gate that consumes them | **delivered** |
| 4 | Publication validation, reviewer sign-off, immutable snapshots, revision history | planned |
| 5 | Vendored ITI VPAT 2.5Rev template + accessible Word export + export accessibility gate | planned |
| 6 | Section 508, EU and International editions | planned |

## Phase 1 — what shipped

**Standards catalog.** `config/wcag-2.2-aa.json`, generated from the W3C Recommendation by
`scripts/gen_wcag_catalog.py`: 55 criteria, 31 Level A + 24 Level AA, content-hashed so a report
records the exact criteria set it was built from.

**Domain and rules.** `acr_catalog`, `acr_model`, `acr_rules`, `acr_freshness`, `acr_validation`,
`acr_authz`, `acr_export_preview`. The decision rules reuse `assessment.CAN_CERTIFY_PASS` — the
same coverage gate the document pipeline uses (ADR 0031) — rather than re-deriving the idea.

**Persistence.** Seven additive tables (ADR 0047), schema v5.

**API.** `/acr` and ten sub-routes: report CRUD, criterion detail with refusal reasons, evidence
attachment, decision, approval, validation, audit, and a draft structural export.

**UI.** A Conformance tab: report list, overview, criteria matrix, criterion detail, validation,
and the draft export preview.

**Vertical slice.** WCAG 1.4.3 Contrast (Minimum) end to end — chosen because it is the criterion
where ACP genuinely has an automated check against its own UI, so the slice runs on real evidence
rather than a fabricated demo result.

## Phase 2 — what shipped, and why it is not what the table originally said

Phase 2 was planned as "report CRUD, criteria navigation, evidence attachment, decision rules,
validation". **Phase 1's vertical slice delivered all five** — 14 endpoints and 18 store methods —
so building Phase 2 as written would have re-implemented working code. It was rescoped to what was
actually missing to use the workspace across all 55 criteria rather than one.

**Bulk axe-core ingestion** (`api/acr_axe.py`, `POST /acr/{id}/evidence/axe`). Phase 1 attached
evidence one row at a time, which is right for a keyboard test and hopeless for automation. The
design turns on axe's four result buckets not being three passes and a fail:

| axe bucket | becomes | why |
|---|---|---|
| `violations` | `fail` | a real defect |
| `passes` | `pass` | the rule's checks held |
| `incomplete` | `blocked` | axe could not decide; mapping this to a pass turns "I don't know" into "it conforms" |
| `inapplicable` | **not evidence at all** | a page with no `<video>` says nothing about whether the product captions its videos |

Every row declares PARTIAL coverage, so ingesting a perfectly green axe run still moves nothing to
"Supports". `preview: true` reports what would be written without writing it — the interesting part
of the operation is what it drops, and `acr_evidence` is append-only.

**Report metadata editor** (`AcrMetadataForm.jsx`). Phase 1 shipped the PATCH endpoint and a
read-only Overview, so no report could reach a publishable state through the UI at all — §16's
gate could never open. Which fields are required is derived from the validation endpoint's own
blockers rather than a second hardcoded list, so the form cannot mark a field optional that the
publish gate refuses.

**Evidence gaps** (`GET /acr/{id}/gaps`, PRD §7.8), split into three kinds because each implies
different work: no evidence at all, automated-only (a tool looked; still a gap), stale-only.

**Applicability marking** (PRD §9) and criteria filtering. Applicability is deliberately unable to
write a conformance status — marking a criterion inapplicable is workspace triage, not the
"Not Applicable" decision a customer reads, and it does not let a report publish undecided.

## Phase 3 — what shipped

**The manual test plan catalog** (`config/acr-manual-test-plans.json`, generated by
`scripts/gen_acr_plan_catalog.py`). **21 plans covering all 55 criteria.**

It is **derived from the WCAG 2.2 Recommendation, not transcribed from PRD §14**, which this
repository does not contain. Presenting an invented list as §14's would be a fabricated citation
in a compliance feature — the class of thing §19 forbids — so the artifact says so on its face in
`_meta.derivation`, and adopting the real §14 catalog later is a change to that one file. The
derivation yields 21 plans rather than the 20 the PRD names; bending a group to reach a number
this repo cannot verify would be fake precision.

**Why every criterion gets a plan**, measured rather than assumed: axe-core 4.12.1 publishes rules
for **23 of the 55 criteria — 32 have no axe rule at all.** And the 23 get no pass either, because
every `acr_axe` row declares `Coverage.PARTIAL` while `CAN_CERTIFY_PASS` is `{FULL}` (ADR 0031).
Automation finishes no criterion, so every applicable one needs a human. Each plan carries the
split, so a tester can see where automation gave a partial answer and where it said nothing at all.

**The seam Phase 1 left, now closed.** `acr_validation.validate()` has accepted a
`manual_plan_status` map and defined the `incomplete_manual_test_plan` blocker since Phase 1, and
nothing ever supplied it — the category produced no rows rather than pretend it knew.
`routes/acr.py` now passes the real map. **This is the only change in the feature's history that
makes publication harder**, and it is pinned by a test that reads the call site, because a
regression there is otherwise silent.

Note where that blocker actually bites, which is sharper than it looks: `validate()` short-circuits
a criterion with no final status, so the blocker's target is the dangerous case — a criterion
somebody has **decided** while the manual evaluation behind it is unfinished.

**A run is complete when three things hold**: every step has a recorded outcome, a tester is named,
and every metadata field the plan itself declares is present. Required-ness is per-plan — a
screen-reader plan asks for the AT by name; a reflow plan does not — and a plan may only demand
fields `acr_evidence` can actually store, asserted by the generator, so a run cannot look
reproducible while the durable record drops what it recorded.

**Completing a plan is not a pass.** A failing step finishes a step: completeness is about whether
the tester looked, never about what they found. A product that fails a criterion must still be able
to finish evaluating it.

**Persistence.** One additive table, `acr_manual_step` (schema v8). The run's environment lives on
the `acr_evidence` row it produces rather than in a second copy.

## Explicitly not delivered in Phase 1

* **The ITI VPAT template and Word export.** Phase 5, gated on a licensing decision. The Phase 1
  export is a structural preview that states on its face that it is not a VPAT.
* **Publication.** The snapshot table, the immutability boundary and the validation gate exist and
  are tested; the publish endpoint is Phase 4.
* **Guided manual test plans.** Delivered in Phase 3 — see above.

## Non-goals

The feature must not: advertise ACP as legally certified; guarantee compliance; treat a scan score
as a conformance level; publish automatically; conceal known failures; modify a published
snapshot; generate invented manual-testing evidence; use an LLM to fabricate remarks, results or
remediation claims; or copy a previous version's "Supports" decisions without freshness validation.

## AI assistance boundaries

A model may summarise attached evidence, draft remarks from cited evidence, identify gaps, suggest
manual tests, explain contradictions and draft limitation language. AI-generated text must be
marked as a draft, cite its evidence, never create a test result, never select or approve a final
status, never publish, and remain editable by a person.

In Phase 1 the only machine-generated judgement is `acr_rules.may_draft`, which is deterministic,
writes only to `draft_status`, and cannot reach `final_status` — `store.save_acr_draft_status` has
no code path to that column.

## Acceptance criteria — Phase 1 status

| # | Criterion | Status |
|---|---|---|
| 1 | Create a WCAG-edition ACR for a named ACP version | ✅ |
| 2 | System creates the complete applicable WCAG A/AA matrix | ✅ 55 criteria |
| 3 | Scan findings attachable as criterion evidence | ⬜ superseded — see "Scope of the evaluated product" |
| 4 | Automated passes are not treated as proof of Supports | ✅ |
| 5 | Manual results recordable with environment and tester | ✅ |
| 6 | Every final status has evidence or a required explanation | ✅ |
| 7 | The three limitation statuses require remarks | ✅ |
| 8 | An unresolved failure blocks Supports unless newer evidence resolves it | ✅ |
| 9 | Stale evidence is visible but cannot satisfy publication | ✅ |
| 10 | Reports with unevaluated applicable criteria cannot publish | ✅ |
| 11 | Only an approver can publish | ✅ gate + roles; publish endpoint is Phase 4 |
| 12 | Publication creates an immutable snapshot | ⬜ Phase 4 (table + edit boundary shipped) |
| 13 | Exported Word document follows the official VPAT structure | ⬜ Phase 5 |
| 14 | Generated Word document passes ACP's accessibility checks | ⬜ Phase 5 |
| 15 | Report identifies version, methods, tools, environments, reviewers | ✅ required to publish |
| 16 | Automated tests for authorization, decision rules, freshness, validation, snapshots, export | ✅ except snapshot/export (Phases 4–5) |
| 17 | UI has keyboard, focus, screen-reader, reflow and automated accessibility tests | ✅ |
| 18 | No existing scan, assessment, remediation or reporting workflow regresses | ✅ `test_acr_no_regression.py` |

Item 3 is the one deliberate departure from the PRD as written, and it is a scope correction
rather than a gap: ACP's scanner analyses customer documents, while the ACR's subject is ACP's own
UI, so attaching a document finding as evidence for an ACP conformance claim would produce exactly
the unsupported claim §3 of the PRD opens by naming. The evidence model is source-agnostic, so a
future report *about the document pipeline* can attach scan findings with no schema change.

## Phase 5 note — the export accessibility gate

PRD §16 requires the generated Word document to pass ACP's applicable document accessibility
checks. Measured against a real `.docx` with `rule_registry.evaluate`, **no docx registration
declares `Coverage.FULL`** — so `PASS` is unreachable by construction and an "all PASS" gate would
never go green. The honest gate is **"no FAIL"**, with every `REVIEW` surfaced for the approver to
sign off. ACP's docx analyser already covers heading structure, table header rows, document
language, document title, link text and alt text, so this is a real check rather than a formality.
