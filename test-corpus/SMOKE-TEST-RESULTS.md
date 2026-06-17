# Track-A smoke test — first end-to-end scan (2026-06-16)

Pipeline: **Drive (keyless ADC) → download → PDF via devSEAL `PdfAnalyser` (Python,
in-process) + Office via `AcpScan.Cli` (.NET, unchanged analysers) → score → diff
oracle (`manifest.json`).** Harness: `scripts/scan.py` + `spike/dotnet/AcpScan.Cli`.

## What passed (engine + wiring validated)

- **DOCX detection is EXACT vs the oracle** — the moat works:
  - `docx-noncompliant` → all 5: `DOCX-TITLE-001, DOCX-LANG-001, DOCX-ALT-001, DOCX-LINK-001, DOCX-TABLE-001`
  - `docx-moderate` → exactly `DOCX-ALT-001, DOCX-LINK-001`
  - `docx-compliant`, `docx-empty` → clean (0 issues)
- **Error handling 4/4** — `edge-corrupt`, `edge-pdf-as`, `edge-plaintext` (.NET) and
  `pdf-encrypted` (Python) all fail **gracefully** (`succeeded=false`, captured error, no crash).
- **PDF findings sensible** — `pdf-untagged` → 3 issues (score 52); `pdf-titled-lang` →
  title/lang fixes correctly pass, only `pdf.tagged` + `pdf.display-doc-title` remain (score 67).
- **Drive connector path proven** — 8 files read read-only from `acp-demo-corpus`.

## Real rule IDs (pins the previously "approximate" oracle entries)

| Format | Actual rule IDs observed |
|---|---|
| DOCX | `DOCX-TITLE-001 · DOCX-LANG-001 · DOCX-ALT-001 · DOCX-LINK-001 · DOCX-TABLE-001` |
| PPTX | `PPTX-TITLE-001 · PPTX-LANG-001` (alt **not** firing — see below) |
| XLSX | `XLSX-TITLE-001 · XLSX-LANG-001 · XLSX-ALT-001` (alt throws — see below) |
| PDF  | `pdf.tagged · pdf.document-language · pdf.display-doc-title` |

## 🐞 Issues — root-caused

### 1. PPTX alt-text "miss" → RESOLVED (test-corpus bug, engine is correct)
`python-pptx` auto-fills `p:cNvPr@descr` with the image **filename** (`_img.png`), so the
generated picture *had* alt text and the engine correctly didn't flag it. Fixed
`generate.py` to drop `descr`; `pptx-noncompliant` now fires `PPTX-ALT-001` as expected.
- **Engine validated.** Minor devSEAL coverage note: a *filename* used as alt text passes
  the rule (placeholder list is narrow — `{image,picture,photo,slide}`), a real-world miss.

### 2. Engine reports a file CLEAN when a rule couldn't run → REAL DEFECT (ship-relevant)
The Drive-served copy of `xlsx-compliant.xlsx` has a **corrupt `xl/workbook.xml`** — it
fails to decompress in **Info-ZIP, Python zlib, and .NET alike** (genuine bad deflate
stream, not a reader-strictness issue). The .NET engine caught the per-rule exception,
**swallowed it, and returned `succeeded=true` with zero issues** → **false-clean.**
- **Durable finding:** for a *compliance* product, "rule could not evaluate" must surface
  as **degraded / uncertain**, never as a pass. The score/report must reflect unevaluated
  criteria. This is independent of what corrupted the file.
- **Cause of the corruption (open, lower severity):** likely a **one-off in the upload
  path** for this file — `xlsx-noncompliant.xlsx` round-tripped through Drive fine, and
  PDFs did too. The binary upload went through the **Claude Drive MCP connector**, not the
  Drive API directly. **TODO:** re-upload via the real (Drive-API) connector to confirm
  one-off vs systematic; prefer Drive-API-direct for binary fidelity in the demo.

## Fix shipped — incomplete analysis is never a pass

`scripts/result_model.py` classifies every result: **error** (unopenable → unscored),
**uncertain** (≥1 rule threw and was skipped → score is an *upper bound*, cannot be
certified), **analysed** (trustworthy). Re-running the live scan, the previously
"100/clean" `xlsx-compliant` (corrupt Drive copy, **5 rules skipped**) now reports
`uncertain · <=100`, and the compliance gate shows **0 certifiable-clean** — not a false
pass. This is the seed of the Phase-4 rubric.

## Notes

- Scoring is a placeholder rubric (CRITICAL 25 / SERIOUS 15 / MODERATE 8 / MINOR 3,
  floor 0) — replace with the real versioned rubric (Phase 4).
- This run is direct (no Temporal); Temporal orchestration is the productization step.
