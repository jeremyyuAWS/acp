# PRD — ACP Accessibility Conformance Report Workspace

Status: Phases 1–4 delivered · Phases 5–6 planned
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
| 4 | Publication, reviewer sign-off, immutable snapshots, revision history | **delivered** |
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

## Phase 4 — what shipped

**Publication is the one irreversible act in this feature.** An ACR goes into a customer's
procurement file and cannot be recalled, so everything the earlier phases built exists so that
what gets frozen here is true when it is frozen.

**The gate is assembled from parts that already existed** — `acr_validation.validate`,
`acr_authz.may_publish`, `acr_freshness` — rather than a new "can publish?" predicate written for
the endpoint. A second implementation of the gate is how a screen goes green while the real check
is red. `POST /acr/{id}/publish` checks, in this order: the report is not already published; the
**caller** may publish (`acr_authz`, never `core.is_admin`, which returns `True` for every
authenticated user under the default `OPEN_ACCESS=1`); and validation is completely clean. The
role check precedes the readiness check so an unauthorised caller learns nothing about the
report's internal state.

**The digest is a digest, not a signature.** `content_digest` is a recomputable SHA-256 over the
canonical snapshot content — it makes alteration detectable and provides no non-repudiation. It is
re-verified on **every read** of a revision rather than on demand: a tamper-evident record nobody
checks is a record nobody has checked. `api/report.py` carries the same warning for scan reports,
and the rule is the same — never relabel it.

**Revising is the dangerous operation, not publishing.** PRD §19's list of prohibitions ends on
*copy a previous version's "Supports" decisions without freshness validation*, and a revision
exists precisely because the product changed. `acr_publish.carry_forward` re-derives staleness
against the **new** report: a `Supports` claim with no live evidence left returns to
`needs_review`, and the criteria that were reset are **returned to the caller** rather than
silently changed. The three limitation statuses carry with their remarks, because carrying a known
barrier forward understates nothing.

**No approval carries into a revision at all** — an approval granted against the previous revision
was granted for a different product version, and PRD §4.2 requires sign-off on *this* report.
`store.carry_acr_decisions` has no code path to `approval_state`, `reviewer` or `approved_at`.

**Roles do carry, and the distinction is the point.** A role says "this person is authorised to
approve here"; an approval says "this person did approve this criterion, for this version".
Without carrying roles, every revision would need an admin to re-grant them before anyone could
work — and the person revising may not be an admin.

**Separation of duties (PRD §18) is surfaced and never blocks.** The warning fires only when a
second qualified reviewer actually exists, because a warning that nags a one-person team on every
publish teaches them to ignore it. It is recorded in the audit log alongside the publication.

### A Phase 3 bug this phase found

A report whose criteria were all decided **Not Applicable** with explanations was blocked by 55
`incomplete_manual_test_plan` rows — Phase 3 demanded a completed manual plan for criteria a human
had determined did not apply, which would ask someone to run the live-captions plan against a
product with no live audio. Worse, `acr_plans`' own docstring claimed it did not duplicate
`acr_validation`'s evidence judgement, and it did. A decided `Not Applicable` is now recognised as
the human evaluation it is; PRD §10 already requires the explanation, and `acr_validation`
enforces it.

## Deferred out of Phase 1 — and what has since landed

* **The ITI VPAT template and Word export.** Still Phase 5, still gated on a licensing decision.
  What exists today is a structural preview that states on its face that it is not a VPAT, served
  as JSON, HTML and a tagged PDF/UA-1 document.
* **Publication.** Delivered in Phase 4 — see above.
* **Guided manual test plans.** Delivered in Phase 3 — see above.

The heading used to read "Explicitly not delivered in Phase 1" while two of its three bullets
said they had been delivered.

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

Through Phase 4 the only machine-generated judgement is still `acr_rules.may_draft`, which is
deterministic, writes only to `draft_status`, and cannot reach `final_status` —
`store.save_acr_draft_status` has no code path to that column. Re-checked on 2026-09-05: both
callers (bulk axe ingestion and single-evidence attach in `routes/acr.py`) go through that one
function, and both leave the criterion at `needs_review` rather than `decided`, so there is no
evidence-driven path to a decision at all. Phase 2's axe ingestion writes *evidence*, not
judgement; a drafted `Supports` is a suggestion awaiting a person.

## Acceptance criteria — status after Phase 4

Re-checked against the code on 2026-09-05, not carried forward from the previous revision. Three
rows had gone stale: 11 and 12 still deferred to Phase 4 *after* Phase 4 shipped, and 16 still
excepted the snapshot and export tests that now exist. A status table is the artifact people read
*instead of* checking, so where this and the code disagree, the code wins.

Re-run it with `python -m pytest tests/ -k acr`, which sweeps the 18 `test_acr_*.py` files. The
count is deliberately not written down here: the first draft of this line said 373 and the suite
answered 381, because the guard file named below had landed in between. A number in a document is
a claim that decays; the command is one that cannot.

Rows 4, 6–11 and the digest behind 12 were additionally confirmed by mutation on 2026-09-05: the
rule enforcing each was broken in turn and the whole ACR suite run against it, and every one
turned the suite red. The same sweep found exactly one guard that no test defended —
`acr_export_preview._conformance_cell` refusing to print an internal workflow state where a
conformance level goes (§9, the last layer before a customer reads the document). That gap is now
closed by `tests/test_acr_export_preview_guard.py`; it is recorded here because a green suite had
already been read as evidence that the guard worked.

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
| 11 | Only an approver can publish | ✅ `POST /acr/{id}/publish`, gated on `acr_authz.may_publish` and never `core.is_admin` |
| 12 | Publication creates an immutable snapshot | ✅ `acr_snapshot`, digest re-verified on every read |
| 13 | Exported Word document follows the official VPAT structure | ⬜ Phase 5 — blocked on the licensing decision, not on engineering |
| 14 | Generated Word document passes ACP's accessibility checks | ⬜ Phase 5 — depends on 13; the gate is settled below |
| 15 | Report identifies version, methods, tools, environments, reviewers | ✅ required to publish |
| 16 | Automated tests for authorization, decision rules, freshness, validation, snapshots, export | ✅ all six — 18 `test_acr_*.py` files |
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
