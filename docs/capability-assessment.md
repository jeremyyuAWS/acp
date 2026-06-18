<p align="left">
  <img src="https://raw.githubusercontent.com/mova-io/mova-cli/main/mova-io%20logo.png" alt="mova.io" height="48" />
</p>

# Accessibility Compliance Platform — Capability Assessment & WCAG Coverage / LOE Analysis

**Prepared by:** Movate · mova.io platform team
**Audience:** DevSeal GTM evaluation
**Date:** 2026-06-18
**Standard in scope:** WCAG 2.1 + 2.2 (Level A / AA target; AAA noted as optional)
**Companion artifact:** [`WCAG_Coverage_LOE_Analysis.xlsx`](./WCAG_Coverage_LOE_Analysis.xlsx) — the full 87-criterion matrix this report summarizes.

---

## 1. Executive summary

mova.io is an end-to-end accessibility **compliance platform** — not a point scanner. It crawls an enterprise document estate, classifies and prioritizes every artifact, assesses it against WCAG, **prescribes a next action with an effort estimate**, remediates the mechanical findings automatically, escalates the judgement calls to humans, and then **monitors continuously** and produces an audit-grade evidence trail. The partner's automated scanner is one input to this pipeline, not the product.

Analyzing the supplied **WCAG 2.1 + 2.2 checklist (87 success criteria)** against the platform's current coverage produced one decisive finding:

> **The net-new work to reach full legal conformance is almost entirely _agentic (AI)_ and _human-in-the-loop_ — not more automated checks.** Automated Level A/AA is a largely solved, partner-covered space. mova.io's differentiated value (and the remaining build) lives in the semantic AI checks, the document-format coverage, and the review-and-evidence workflow that a raw scanner cannot provide.

**Level of effort to close the gap to Required (Level A/AA) conformance: ≈ 51–95 engineering-days (~2.5–4.5 months for one engineer, or ~2–3 months for a 2-engineer pod plus a part-time accessibility SME).** Full AAA coverage roughly doubles that and is **not recommended** — it is not legally required and is dominated by manual criteria.

---

## 2. The 10-stage compliance workflow

mova.io implements the full conformance lifecycle. The partner scanner contributes to stages 4–5 only.

| # | Stage | What it does | Maturity in prototype |
|---|-------|--------------|------------------------|
| 1 | **Discover & Inventory** | Connectors crawl all sources; capture file type, owner, size, age, traffic, version lineage | Demonstrated |
| 2 | **Classify & Prioritize** | Auto-tag by content, risk (PII, legal-hold), and public exposure | Demonstrated |
| 3 | **Retain / Archive / Delete** | Recommend keep / archive / delete from metadata (superseded, stale, low-traffic) | Demonstrated |
| 4 | **Assess Accessibility** | Multi-engine WCAG assessment across PDF / Office / web | Demonstrated (simulated engines) |
| 5 | **Risk Scoring & Findings** | Unified 0–100 score + finding detail (counts, impact, level), risk-weighted | Demonstrated |
| 6 | **Automated Remediation** | Auto-fix mechanical findings (alt text, headings, language, titles), then re-validate | Designed |
| 7 | **Human-in-the-Loop (HITL)** | Route low-confidence / sensitive fixes to a reviewer queue with approve / edit / reject | Demonstrated (workflow) |
| 8 | **Re-validate & Verify** | Re-run all engines, confirm score lift before publish | Designed |
| 9 | **Publish / Replace / Archive** | Replace in place or publish a new compliant version; notify owners | Designed |
| 10 | **Monitor & Report** | Continuous re-scan, drift/regression alerts, SLA coverage, audit-grade evidence trail | Demonstrated |

**Foundation services:** MDK orchestration (Temporal) · document store · metadata + vector index · AI validation services · security & governance (Key Vault, RBAC, policies) · observability & audit.

### Prescriptive guidance — the prototype's signature capability

For every document the platform now resolves metadata + findings into a **single recommended action** carrying a **confidence, an effort estimate (ETA), the fix mode, and a plain-language rationale**:

- **Auto-remediate** — mechanical findings, no human needed.
- **Remediate + review** — a human approves the AI fix (critical finding on a public page, contrast/link judgement, or sensitive content).
- **Human review** — a rule could not be auto-evaluated.
- **Archive / Keep · monitor** — including a deliberate *"archive instead of remediate"* for stale, low-traffic, superseded documents — the platform optimizes effort, not just flags problems.
- **Manual rebuild** — unreadable source.

These roll up into an **estate action plan** ("≈ 22.6 hrs of remediation across 98 documents · 46% fully automatic · saves ≈ 128 hrs vs. manual"), and feed the monitoring tab's remediation backlog.

---

## 3. DevSeal (partner) capability assessment

**Assessed role:** DevSeal provides the **automated WCAG detection engine** for web content — the deterministic, machine-evaluable Level A/AA checks (an axe-core-class capability). In the coverage model this is the **"Partner baseline"** layer: **19 success criteria**.

**Representative partner-covered criteria** (automated, Level A/AA): Orientation (1.3.4), Identify Input Purpose (1.3.5), Contrast Minimum/Non-text (1.4.3, 1.4.11), Reflow (1.4.10), Resize/Text Spacing (1.4.4, 1.4.12), Bypass Blocks (2.4.1), Multiple Ways (2.4.5), Label in Name (2.5.3), Target Size (2.5.8), Language of Parts (3.1.2), Consistent Navigation/Identification/Help (3.2.3, 3.2.4, 3.2.6), Labels or Instructions (3.3.2), Parsing (4.1.1).

**What the partner does _not_ provide** (and where mova.io adds value):

| Gap | Why it matters |
|-----|----------------|
| **Document formats** (PDF / DOCX / PPTX / XLSX) | Partner scanners are web/DOM-oriented; enterprise estates are mostly documents. |
| **Agentic / semantic checks** | "Is the alt text *meaningful*?", "Are headings *descriptive*?", "Is the link purpose clear *in context*?" — requires an LLM evaluator, not a rule. |
| **Human-in-the-loop workflow** | 48 of 87 criteria can only be confirmed by a person; the partner returns findings, not a managed review + sign-off + evidence trail. |
| **Lifecycle orchestration** | Discovery, prioritization, remediation, re-validation, publish, monitoring, audit — the platform around the scan. |

> ⚠️ **To validate:** the 19-criterion partner baseline is an **assumption**. Obtain DevSeal's published success-criterion coverage list and reconcile it against the matrix's `Coverage Source` column. If DevSeal is web-only (likely), the 19 automated checks become **net-new for document formats** — see the conditional workstream in §5.

---

## 4. WCAG 2.1 + 2.2 coverage analysis

The checklist's own **"Validation Approach"** column is the single most important signal — it determines whether a criterion can be a check at all, and therefore the cost to add it.

### 4.1 The 87 criteria, by dimension

| By conformance level | Count | | By validation approach | Count | | By legal requirement | Count |
|---|---|---|---|---|---|---|---|
| Level A | 32 | | Automated | 32 | | Required | 50 |
| Level AA | 24 | | Automated + Agentic | 7 | | Optional | 31 |
| Level AAA | 31 | | Human / AT (manual) | 48 | | Recommended | 6 |
| **Total** | **87** | | **Total** | **87** | | **Total** | **87** |

Two structural facts drive everything below:

1. **Only 39 of 87 criteria (45%) are machine-evaluable at all.** The other **48 are "Human / AT"** — they cannot be turned into a pass/fail check. "Adding a check" there means building a **detector + routed human-review workflow**, not an automated rule.
2. **All 50 legally-Required criteria are Level A/AA.** AAA (31 criteria) is entirely Optional/Recommended — the conformance target is the **56 A/AA criteria**, and the **50 Required** ones are the must-haves.

### 4.2 Coverage today

| Coverage source | Criteria | Meaning |
|-----------------|----------|---------|
| 🟢 **Shipped (prototype)** | 8 | Validated by the platform today (1.1.1, 1.3.1, 1.3.2, 1.4.3, 2.1.1, 2.4.2, 2.4.4, 3.1.1) |
| 🟣 **Partner baseline** | 19 | Automated Level A/AA provided by DevSeal (assumption) |
| 🟠 **mova.io net-new** | 60 | Beyond the partner — the build scope |

---

## 5. Level of effort to close the gap

**Estimating basis:** blended senior engineer; per-criterion build cost by tier; *≈ weeks = midpoint ÷ 5*. Only **net-new** criteria carry effort.

### 5.1 By build tier (net-new only)

| Tier | What you build | Criteria | LOE (dev-days) |
|------|----------------|----------|----------------|
| **Tier 1 · Deterministic** | Rule against the parsed document model; ×4 formats | 10 | 10–30 |
| **Tier 2 · Agentic AI** | LLM evaluator **+ golden eval set + confidence calibration + HITL escalation** | 4 | 16–32 |
| **Tier 3 · HITL workflow** | Detector / pre-screen + routed human review + evidence capture | 46 | 46–92 |
| **Total** | | **60** | **72–154** |

### 5.2 By phase (recommended sequence)

| Phase | Scope | Criteria | LOE (dev-days) | ≈ weeks |
|-------|-------|----------|----------------|---------|
| **0 · Foundation** | Coverage audit vs. DevSeal, lock the check contract, golden corpus | — | 5–8 | 1–2 |
| **1 · Agentic (Required A/AA)** | Semantic AI checks — sensory characteristics, headings & labels | 2 | 8–16 | 2–3 |
| **2 · HITL (Required A/AA)** | Pre-screen + review workflow for the manual Required criteria | 23 | 23–46 | 5–9 |
| **+ HITL platform hardening** | Queue, evidence, sign-off (largely built) | — | 15–25 | 3–5 |
| **→ Required A/AA conformance** | **8 → 50 criteria** | | **🟢 51–95** | **~10–19** |
| **3 · Optional / AAA** | Everything not legally required | 35 | 41–92 | 8–18 |
| **→ Full 87-criterion coverage** | | | **92–187** | **~18–37** |

### 5.3 Conditional workstream — document-format automated parity

If DevSeal is **web-only** (to be confirmed), the 19 "Partner baseline" checks must be re-implemented for PDF/Office: **19 criteria × ~1–2.5 dev-days = ~19–48 dev-days**. This is the single biggest swing factor in the estimate and depends entirely on the §3 validation.

### 5.4 Assumptions, risks & caveats

- **Tier 2 is the schedule risk, not Tier 1.** Agentic checks are cheap to prototype and expensive to make *trustworthy*; most of the cost is the eval harness and confidence thresholds, not the prompt. Under-scoping this ships false confidence.
- **"Human / AT" criteria are never fully automated** — they carry a recurring **reviewer-minutes run-cost**, which ties into the per-document ETA model already in the platform. Build cost ≠ operating cost.
- **Multi-format multiplies Tier 1** — one criterion is up to four implementations (HTML / PDF / Office).
- **The net total swings on the partner-coverage assumption.** Validate §3 before committing to a number.
- An **accessibility SME is non-negotiable** for Phases 1–2; they own the golden sets and review rubrics.

---

## 6. Recommendations

1. **Validate the partner baseline first (Phase 0).** Get DevSeal's SC-level coverage; it moves the estimate by tens of dev-days. Decide build-vs-integrate per automated criterion.
2. **Scope to Required Level A/AA (50 criteria).** This is the legal bar (ADA Title II, Section 508, EAA). Defer AAA indefinitely.
3. **Lead with the differentiators, not the scanner.** The platform's value is the agentic checks, document coverage, HITL workflow, and continuous monitoring + evidence — exactly what a raw partner scan cannot do.
4. **Sequence by legal risk:** Required A/AA → public-facing & high-traffic first (the platform already prioritizes these).
5. **Treat HITL as a product, not a queue.** The reviewer workflow, evidence capture, and sign-off are reused across 25+ Required criteria; harden it once.

---

## 7. Appendix

**Data sources**
- `WCAG 2.1 + 2.2 Checklist V4.xlsx` — 87 success criteria with validation approach (customer-supplied).
- [`WCAG_Coverage_LOE_Analysis.xlsx`](./WCAG_Coverage_LOE_Analysis.xlsx) — generated coverage matrix + LOE model (Summary · Coverage Matrix · By Tier).
- mova.io prototype (`acp`) — live coverage view at **Assess → WCAG coverage**.

**Method.** Each criterion was classified by `Coverage Source` (shipped / partner / net-new), `Build Tier` (deterministic / agentic / HITL), and roadmap `Phase`, with low/high dev-day estimates per tier. Totals are computed in the spreadsheet; figures here are midpoints rounded for planning. Estimates are planning-grade (±), not a fixed bid.

*Effort figures are engineering build estimates and exclude design, QA, program management, and ongoing human-review operating cost.*
