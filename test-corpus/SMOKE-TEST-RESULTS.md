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

## 🐞 Issues identified (the point of the smoke test)

1. **PPTX alt-text rule never fires.** `pptx-noncompliant` embeds a picture with no alt
   text; engine returns only TITLE+LANG, deterministically. DOCX alt-text works, so this
   is PPTX-specific. **TODO:** confirm engine gap vs. synthetic-file issue (verify the
   `p:cNvPr@descr` is actually empty in the generated pptx).
2. **XLSX `XLSX-ALT-001` throws on the Drive-stored copy** of `xlsx-compliant.xlsx` —
   not reproduced across 2 local runs. The AltText rule (ClosedXML) appears fragile to
   Drive's OOXML round-trip. **TODO:** download the Drive copy, diff vs local, repro the
   exception, harden the rule.

## Notes

- Scoring is a placeholder rubric (CRITICAL 25 / SERIOUS 15 / MODERATE 8 / MINOR 3,
  floor 0) — replace with the real versioned rubric (Phase 4).
- This run is direct (no Temporal); Temporal orchestration is the productization step.
