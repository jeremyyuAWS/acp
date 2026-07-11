# ADR 0012 — Own the Office analysers; fix the language rules

Status: Accepted
Date: 2026-07-08

## Context

The Office (docx/pptx/xlsx) scan path compiles the partner DigitalA11y .NET analysers
via a thin CLI (`spike/dotnet/AcpScan.Cli`) and ships the built DLLs into the deploy
image (`deploy/public/Dockerfile` copies `spike/.../bin/Release/net10.0/`). Until now the
CLI referenced the analyser projects from a checkout **outside** this repo
(`~/projects/_review-digital-accessibility`), and the partner code was treated as a
pinned, unmodifiable build artifact.

That posture blocked real fixes. Concretely, the three language rules were wrong:

- `Docx/Pptx/Xlsx DocumentLanguageRule` (WCAG 3.1.1) read **only**
  `PackageProperties.Language` — the optional `dc:language` *metadata*. WCAG 3.1.1 asks for
  the *programmatically-determinable content language*, which OOXML stores in the content:
  docx `w:lang` (style `docDefaults` + runs), pptx `a:rPr/@lang` (on essentially every text
  run). Result: **false positives** on properly-authored files whose content language was
  set but whose metadata was blank — and our Python remediator could only mask it by
  stuffing `dc:language`, and gave up entirely on files with no core-properties part.
- `Docx/LanguageOfPartsRule` flagged **every** 20+ word run lacking an explicit `w:lang` —
  i.e. ordinary single-language paragraphs, since Word does not stamp `w:lang` on every run.
  A false-positive flood; the real 3.1.2 concern is only a passage in a *different* language.

The partner will not ship these fixes, so we take ownership.

## Decision

1. **Vendor** the two projects the CLI needs — `DigitalA11y.Analysers.DotNet` and
   `DigitalA11y.Core`, plus their `Directory.Build.props` / `Directory.Packages.props` — into
   `engine/office-analysers/`, tracked in this repo. Repoint `AcpScan.Cli.csproj` at the
   owned copy. The full upstream solution stays out of tree (`digital-accessibility/` remains
   gitignored); only the live-path projects are owned. `bin`/`obj` stay gitignored; the deploy
   rebuilds the DLLs locally and copies them into the image as before.
2. **Fix the language rules** to read the real signal:
   - `DocumentLanguageRule` (docx + pptx): conformant when EITHER the metadata OR a content
     language (docx style-default/run `w:lang`; pptx run/end-paragraph `@lang`) is present.
     xlsx keeps the metadata check — a spreadsheet has no per-cell content language, so
     metadata is the only/correct signal there.
   - `LanguageOfPartsRule`: only flag a long run whose dominant Unicode **script** differs
     from the document's dominant script (Latin vs CJK/Cyrillic/Arabic/…) and which carries
     no language of its own — a deterministic, low-false-positive signal.

WCAG 3.1.2 is not yet a distinct rubric criterion, so `LanguageOfPartsRule` continues to
report under `SC_3_1_1`; modelling 3.1.2 separately is deferred (it ripples into the Python
rubric/coverage).

## Consequences

- Fixes are now in-repo, version-controlled, and reproducible from a clean checkout; no
  dependency on an external clone.
- Scan results change corpus-wide: docx/pptx files that declared a content language but no
  metadata no longer false-fail 3.1.1, and ordinary single-language docs no longer false-fail
  language-of-parts. Genuine failures (no language anywhere; a foreign-script passage) still
  fire. Verified end-to-end in `tests/test_office_language_rules.py` (self-skips without the
  .NET toolchain).
- We now maintain ~28 analyser rules. A follow-up audit of the remaining rules for
  WCAG-correctness bugs is planned (Phase 2). First audit result: pptx table-header
  parity for WCAG 1.3.1 is **already covered** by the vendored `Pptx/Rules/TableHeaderRule.cs`
  (rule `PPTX-TABLE-001`, the analogue of the docx/xlsx `TableHeaderRule`) — no duplicate
  first-party detector was added; the behaviour is pinned by
  `tests/test_pptx_engine_detection.py`. See https://github.com/mova-io/acp/pull/7.
- The Python remediator's `dc:language` stuffing is now largely redundant for well-authored
  files; it remains a valid fallback and is unchanged here.
