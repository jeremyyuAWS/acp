# ADR 0001 — acp architecture: read-only assessment spine on MDK, engines harvested behind the `A11yIssue` contract

| | |
|---|---|
| **Status** | **Accepted** (2026-06-16) |
| **Date** | 2026-06-16 |
| **Owners** | Jeremy (eng) · Deva (partnership) |
| **Supersedes** | — |

## Context

`acp` (Accessibility Compliance Platform) is a **standalone product** Movate is
evaluating with a customer — **devSEAL Technologies**, product *Digital A11y*
(deploy codename *Lumynis*) — who wants to **go to market with Movate if there
is potential**. This is a GTM evaluation, **not** an IP harvest: the customer
owns the engines.

- A **read-only diligence clone** lives at `~/projects/_review-digital-accessibility`
  (single commit, **no LICENSE**, build props assert devSEAL copyright).
- **MVP objective:** a **customer-facing** tool that connects to a prospect's
  content stores (**Google Drive, SharePoint/OneDrive, and similar**),
  inventories them, and **scores each file against a structured WCAG rubric**.
  Read-only assessment only.
- It touches **real customer corporate content** and is shown to prospects, so
  it must run **efficiently** (enterprise estates, up to millions of files) and
  **securely** (the security posture *is* the credibility).

**Diligence finding (verified against the code).** The engines are cleanly
decoupled from the platform. Analysers are DI services depending only on `Core`:

```csharp
// DigitalA11y.Analysers.DotNet/Docx/DocxAnalyser.cs  (read-only: isEditable:false)
Task<AnalyserResult> AnalyseAsync(
    string filePath, string jobId, string fileId, string fileName,
    IEnumerable<string>? disabledRuleIds = null);
// → AnalyserResult { Issues: A11yIssue[], Errors, Succeeded, AnalyserName/Version, ... }
```

All orchestration coupling — Hangfire, the internal poll/claim REST job API,
.NET Aspire, App Insights, EF tenancy middleware — lives in the **outer rings**
(`Worker.DotNet`, `Server`, `Infrastructure`, `AppHost`), which we discard. The
moat (the OpenXML rule engines) is reachable as a stateless library call.

## Decision

**1. Build `acp` as a standalone repo with MDK as *substrate*, not platform.**
Control plane ⊥ execution plane. MDK supplies the runtime, Temporal wiring,
`StorageProvider`, observability/evidence, Azure/cross-cloud deploy, OAuth, and
secrets. The `acp` app (UI / REST / RBAC / rubric) consumes MDK; it does **not**
extend MDK core. (Same call as `~/projects/aop`: MDK-as-sidecar.)

**2. MVP scope = read-only assessment:** `connect → scan → inventory →
score-by-rubric`. **Explicitly out of MVP:** remediation, AI/LLM, HITL,
write-back, and the Node `a11y-mcp` service.

**3. Harvest the inner ring behind a contract; wrap as polyglot Temporal
activity workers.** A **.NET activity worker** hosts the Office analysers on an
`office` task queue; a **Python activity worker** hosts the HTML/PDF analysers
on a `web-pdf` queue. **The internal poll/claim REST job API is deleted —
Temporal task queues replace it.** The workflow routes `file → queue` by type.

**4. Rebuild the platform ring on MDK.** Scan workflow, inventory, rubric config
+ scoring, tenancy, reporting. Their scoring lives in the discardable
`ReportingService`/`BatchRunService`; we **re-implement scoring** as a
first-class, versioned rubric rather than harvest it.

**5. The `A11yIssue` contract becomes a versioned, language-neutral artifact**
(JSON Schema) with **contract tests in CI** to prevent cross-language drift.

**6. The rubric is a versioned, content-addressed config.** Enabled/disabled
rules map to the analyser's `disabledRuleIds`; thresholds map to per-analyser
`*AnalyserOptions`. Resolved **at scan time** and **stamped on the run**
(`rubric_hash`, reusing the ADR 102 prompt-hash identity pattern) →
reproducible scores.

## Security architecture (a *consequence* of the read-only scope)

| Concern | Decision |
|---|---|
| Content access | **Read-only** least-privilege scopes only (`drive.readonly`, Graph `Sites.Read.All`/`Files.Read.All`). Never request write. |
| Document data | **Ephemeral** working copies; documents **never persisted**; only findings + metadata stored. |
| Third-party AI egress | **None.** Scoring is deterministic; no document content leaves to an LLM. |
| Deployment | **Per-customer single-tenant**, deployable into the customer's *own* cloud (MDK cross-cloud) → data never leaves their boundary. |
| Tenant isolation | `tenant_id` + Postgres **RLS** (not Lumynis's per-tenant migrations). |
| Secrets / creds | Key Vault; OAuth tokens encrypted at rest, short-lived. |
| Audit / reproducibility | Immutable evidence trail + `rubric_hash` per run, via the `observability_facts` join surface. |

## Efficiency architecture

- **Temporal fan-out** — one analyze activity per file; stateless workers scale horizontally; crash-resume free.
- **Content-addressed skip** — cache key `(file_revision_hash + rubric_hash)`; re-scans skip unchanged files.
- **Source-API rate limiting** per connector — the real throughput ceiling (Drive/Graph quotas), not CPU.
- **Streaming, paged crawl**; idempotent inventory upsert (first-seen/last-seen).
- **Two runtimes only** for MVP (.NET, Python) — half of Lumynis's operational surface.
- **Sampled/scoped scan mode** for fast prospect time-to-value.

## What we deliberately drop

Hangfire · internal poll/claim REST API · Aspire · App Insights coupling ·
ASP.NET Identity (use MDK + Google OAuth) · per-tenant migrations · Node
`a11y-mcp` and all AI · remediation / HITL / write-back.

## Alternatives considered

- **Wrap-and-host Lumynis as-is** (its `docker-compose`): fastest, but inherits
  4 runtimes + 2 job systems + Azure lock and shows none of Movate's value
  (cross-cloud, scale, data-residency). **Rejected.**
- **Rewrite the engines in Python:** discards the tested OpenXML moat.
  **Rejected.**
- **.NET HTTP sidecar** called by a Python activity (PRD D2): reintroduces the
  synchronous internal API hop we are deleting. **Rejected** in favour of a
  native Temporal **.NET SDK** activity worker; revisit only if the .NET SDK
  path proves problematic.

## Consequences

- Clean separation: Movate owns the platform layer; the customer's engines plug
  in behind a contract. Commercially cleaner — the engines stay **identifiable
  IP behind a seam**, not absorbed into Movate code.
- Polyglot operational surface remains (2 engine runtimes) — **accepted**.
- **Engine reuse approved to proceed.** The diligence repo ships no LICENSE
  (default "all rights reserved"); reuse is governed by the Movate ↔ devSEAL
  commercial relationship, owned outside this ADR. No longer a technical gate.

## Open decisions

- **D1:** ~~license/commercial rights~~ — **resolved**: reuse proceeds, governed
  commercially (no separate LICENSE file). No longer gating.
- **D3:** Drive auth — recommend **domain-wide read-only delegation** for
  org-wide scanning; per-user OAuth for self-serve demos.
- **Drive write-back default** and **remediation** are deferred (not in this MVP).

## Appendix — verified contract surface (from the diligence clone)

- `A11yIssue { Guid IssueId; string RuleId, Title, Description; IssueSeverity
  Severity; IssueCategory Category; WcagCriterion WcagCriterion; IssueLocation
  Location; IssueEvidence Evidence; RemediationType RemediationType; string?
  RemediationGuidance }`
- `AnalyserResult { AnalyserName, AnalyserVersion; DateTimeOffset StartedAt,
  CompletedAt; bool Succeeded; List<A11yIssue> Issues; List<AnalyserError>
  Errors }`
- Office analysers registered via `services.AddDotNetAnalysers(...)`; rules are
  `IDocxRule`/`IPptxRule`/`IXlsxRule` DI collections (Docx ×9, Pptx ×8, Xlsx ×7).
- Read-only document open confirmed (`isEditable: false`); per-rule exception
  isolation and `MaxFileSizeBytes` guard already present.
