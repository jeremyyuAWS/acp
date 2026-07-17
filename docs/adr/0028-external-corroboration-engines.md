# ADR 0028 — External corroboration engines: Adobe PDF/UA checker + convert-then-check for Office

**Status:** Proposed (2026-07-15)

## Context

ACP's differentiator is being the easiest product to trust, and one thing that compounds trust is
**independent corroboration** — a second, reputable engine agreeing with (or honestly disagreeing
with) ACP's own verdicts. The customer (Deva) has asked about three integration options for document
checking; this ADR takes a position on all three.

**Adobe's PDF Accessibility Checker API** runs Acrobat's ~32 checks grounded in the Matterhorn
Protocol (PDF/UA — 31 checkpoints, 136 failure conditions) and reports each item as **passed /
failed / needs manual check**, as JSON, with page scoping. Two facts make it a near-perfect fit:

1. Its three-way verdict maps 1:1 onto ACP's assessment lanes (ADR 0023):
   `passed → Automatically Verified · failed → Needs Remediation · needs manual check → 🟡 Needs
   Review`. Even its two always-manual items (colour contrast, reading order) match where ACP has
   drawn its own honesty boundary.
2. It reads the **tag tree** ACP's pdfplumber/pdfium engines do not: tagged-PDF structure, tab order
   (pdf 2.4.3 is ⚪ today), table headers within tags, figure alt from tags, bookmarks — and it makes
   **PDF/UA conformance** itself reportable, a sellable line next to WCAG.

**For Office files** three approaches exist:

- **Custom OOXML parsing** — *this is what ACP already is*: the .NET Office CLI + the
  `office_structure` OOXML engine (ADR 0001/0012) implement the named example checks (alt via
  `docPr descr`, heading sequence, table header rows) and dozens more, plus the render-verified
  measured layer (ADR 0024) that no static parser reaches. Native Office coverage is 14–18 of the
  20-core per format, per-criterion honest. It stays the **primary Office verdict**: local (no
  document egress), deterministic, and already maintained.
- **Convert-then-check** — export the Office file to tagged PDF, run the PDF checker on the export.
  The proxy is **lossy in both directions**: converters mask source errors (synthesized tags) and
  introduce artifacts (reading-order quirks), so a finding on the export is a fact about *that
  export*, not the source file. But when the customer **publishes** PDF exports, the export IS the
  deliverable and checking it is checking the real thing. Operationally near-free: LibreOffice
  Office→PDF conversion is already in ACP's image (the render pipeline).
- **Third-party vendor APIs** (PREP/ContinuA11Y, Crawford Technologies) — native-Office checkers
  that overlap ACP's own engine, with per-document cost and document egress.

## Decision

Add external corroboration engines behind the existing engine seam (ADR 0001's `A11yIssue` engine
pattern — the .NET CLI is precedent), with **engine provenance on every finding**, org-level opt-in
for any document egress, and hard reconciliation rules that preserve one source of truth.

1. **Adobe PDF Accessibility Checker for native PDFs** — a new adapter (`api/adobe_checker.py`,
   REST via `httpx`, no SDK dependency) mapping the JSON report into the SC-keyed outcome model:
   `passed → PASS` (with `engine: adobe` provenance), `failed → FAIL`, `needs manual check → REVIEW`.
   PDF/UA (Matterhorn) becomes a reportable conformance dimension.
2. **Reconciliation (one source of truth):** where ACP has its own deterministic measurement, **ACP's
   wins**; Adobe adds outcomes only where ACP has none (the tag-tree rules); when both engines assess
   and disagree, the criterion surfaces as 🟡 review carrying **both verdicts** — never a silent pick.
3. **Convert-then-check for Office** — an opt-in corroboration lane, not a source verdict: LibreOffice
   converts (already in-image), Adobe checks the export, findings are stamped
   `engine: adobe · target: PDF export (LibreOffice)` and land in 🟡 review. The native OOXML +
   render-verified engine remains the primary Office verdict. Exception: estates that **publish** PDF
   exports may treat the export check as first-class — because there the export is the deliverable.
4. **Vendor APIs: benchmark, not runtime.** Run ACP against PREP/Crawford on a shared corpus to
   calibrate detectors and produce corroboration evidence; integrate a vendor only if a specific
   enterprise deal demands it.
5. **Governance:** document egress to Adobe is **org-level opt-in, default OFF**, refused under an
   offline-only policy, and visible in provenance + the Trust Panel ("Methods used") — the ADR 0019
   governance pattern applied to a document processor. Adobe credentials are admin-entered secrets.
6. **Cost scoping:** the API is metered per document transaction; corroboration runs on an explicit
   scope (native PDFs, certification candidates, or a named folder) — never every file on every scan.

### Phases (ship order)
- **A** — Adobe adapter + report→lane mapping + org opt-in flag, native PDFs only.
- **B** — provenance in the Trust Panel + reconciliation rules + the convert-then-check lane.
- **C** — Adobe **Autotag** as a remediation engine for untagged PDFs, validated by the checker
  (composes with ADR 0027's scanned-PDF work: Autotag fixes, checker + ACP re-validate).
- **D** — vendor benchmark corpus (ACP vs PREP/Crawford) as a calibration + evidence exercise.

## Honesty guardrails (ADR 0016, non-negotiable)
1. **Provenance on every finding** — which engine, which target (source file vs PDF export), when.
2. **An export finding is never a source-file fact.** Convert-then-check results are labeled as facts
   about the export and never silently merged into the native verdict.
3. **No silent reconciliation.** Engine disagreement is surfaced as review with both verdicts.
4. **Egress is opt-in and visible.** No document leaves the tenant without an org-level decision,
   and the Trust Panel shows when a cloud engine participated.
5. **Adobe "passed" is honest to certify as Automatically Verified** — Matterhorn checks are
   machine-verifiable and the engine is reputable — but it carries its provenance, and criteria Adobe
   marks "needs manual check" stay 🟡 exactly like ACP's own review lane.

## Blast radius / compatibility
- **No storage-schema change** — findings ride the existing PASS/FAIL/REVIEW lanes; provenance
  travels in the finding detail + report (as the AI provenance does today).
- **New external dependency (SaaS):** metered pricing and current beta/sales-gating must be
  **confirmed with Adobe before Phase A commits** — recorded here as an open precondition.
- **No new shipped dep** — REST via `httpx`; avoids the SDK licence question entirely (rule 8).
- **Native paths untouched** — the OOXML, render-verified, and pdfplumber engines are unchanged;
  corroboration is additive and default-off.

## Alternatives considered
1. **Make Adobe the primary PDF engine.** Rejected — egress + per-document cost as a baseline, and it
   surrenders the local-first posture; ACP's own engine stays primary with Adobe as corroboration.
2. **Integrate a native-Office vendor API (PREP/Crawford).** Rejected for runtime — near-total overlap
   with ACP's own engine, plus egress + cost + reselling a competitor's verdict; kept as a benchmark.
3. **Ship the Adobe SDK.** Rejected — the REST surface is small; `httpx` keeps the dependency tree and
   licence posture clean.
4. **Skip corroboration entirely.** Rejected — independent-engine agreement is a trust differentiator
   competitors rarely offer, and the tag-tree coverage gain for PDFs is real.

## Target end-state
A PDF's Accessibility Status can say, with provenance: *"verified by ACP's engine and corroborated by
Adobe's PDF/UA checker"* — and where the engines disagree, the reviewer sees both verdicts instead of
a silent choice. Office files keep their deeper native verdict, with an optional, honestly-labeled
check of the published PDF export. PDF/UA joins WCAG as a reportable standard, and the Trust Panel's
"Methods used" line grows a second, independent name — the kind of evidence auditors weight most.
