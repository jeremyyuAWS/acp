# acp MVP — lean first-cut build plan

**Goal:** a customer-facing tool that connects to a prospect's content store,
inventories it, and **scores each file against a structured WCAG rubric** —
read-only, secure, deployable into the customer's own cloud. See
[ADR 0001](adr/0001-read-only-assessment-spine-on-mdk.md) for the architecture
and rationale.

> **Gate:** nothing in "harvest" lands until **D1 (license)** is resolved in
> writing. Net-new work (Drive connector, workflow, rubric, UI) can start
> against stub engines before then.

## Two paths

| Path | Connectors | File types | LOE |
|---|---|---|---|
| **Lean first cut** | Google Drive | Office (docx/pptx/xlsx) + PDF | **~8–9 eng-weeks** |
| **Full demo MVP** | Drive + SharePoint/OneDrive | + HTML | **~13 eng-weeks** (~6–8 wks calendar, 2 eng) |

This document specs the **lean first cut**; SharePoint/HTML are additive behind
the same seams.

## The engine-as-Temporal-activity seam (verified)

A thin **.NET activity worker** references only `DigitalA11y.Core` +
`DigitalA11y.Analysers.DotNet`, registers the analysers, and exposes one
activity per Office type. No Hangfire, no poll API, no Aspire.

```csharp
// office-activity-worker  (Temporal .NET SDK)
services.AddDotNetAnalysers();            // one-liner DI wireup (verified)

[Activity]
public async Task<AnalyserResult> AnalyseDocx(AnalyseInput in) {
    // in.LocalPath = ephemeral temp copy downloaded by the activity, deleted in finally
    return await _docx.AnalyseAsync(
        in.LocalPath, in.JobId, in.FileId, in.FileName,
        disabledRuleIds: in.Rubric.DisabledRuleIds);   // rubric → disabledRuleIds
}
```

`AnalyserResult.Issues` (`A11yIssue[]`) is serialized back to the workflow as
the versioned JSON contract. The Python `web-pdf` worker mirrors this shape.

## Milestones

| # | Milestone | Exit criteria | ~LOE |
|---|---|---|---|
| **0** | **Repo + MDK seam** — scaffold `acp` on MDK; Temporal Path-A wiring; `tenant_id`+RLS schema; JSON-Schema `A11yIssue` + contract test | `mdk`-based app boots; empty scan workflow runs on Temporal | 1 wk |
| **1** | **Engine activities** — .NET `office` worker (`AddDotNetAnalysers`) + Python `web-pdf` worker (PDF) as Temporal activities; characterization tests lifted from their xUnit suite | one docx + one pdf analysed via Temporal → `A11yIssue[]` | 2.5 wk |
| **2** | **Drive connector + inventory** — read-only OAuth (`drive.readonly`); streaming paged crawl; idempotent `FileRecord` upsert; ephemeral download→analyse→delete | Drive scan produces inventory + per-file findings; documents not retained | 2.5 wk |
| **3** | **Rubric + scoring** — versioned content-addressed rubric (enabled rules → `disabledRuleIds`, thresholds → options); deterministic 0–100 + per-criterion breakdown; stamped `rubric_hash` | toggling a rule/threshold changes the score; re-run reproduces it | 1.5 wk |
| **4** | **UI + security hardening** — inventory browser + score dashboard (lifted React); Key Vault secrets; content-addressed skip; per-connector rate-limit; immutable audit; single-tenant deploy | a prospect connects Drive, runs a scan, sees inventory + score; survives worker kill | 2 wk |

## Non-functionals to prove in the demo

- **Durability:** kill the worker mid-scan → workflow resumes, no duplicate findings (Temporal crash-resume).
- **Security talking points (provable):** read-only scopes · documents never persisted · zero LLM egress · deployable in the customer's tenant.
- **Efficiency:** re-scan of an unchanged estate is near-instant (content-addressed skip); large-estate crawl respects source API quotas.
- **Reproducibility:** two runs at the same `rubric_hash` produce identical scores.

## Deliberately deferred (post-MVP, behind the same seams)

SharePoint/OneDrive connectors · HTML (axe-core, vendored) · remediation +
AI (`a11y-mcp`) · HITL review queue · write-back / Drive revisions ·
PDF/VPAT report export · pptx/xlsx depth tuning.

## Immediate next step

Trace the `AnalyserResult`/`IssueLocation`/`IssueEvidence` shapes and the Python
worker's PDF analyser entry point, then author the JSON-Schema `A11yIssue`
contract (Milestone 0) so both workers serialize to a verified shape.
