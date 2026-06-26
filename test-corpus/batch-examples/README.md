# Batch test files

Four hand-built HTML documents that land in known Remediation-program batches.
The program buckets each file by its **top (highest-severity) finding**, so each
file below is crafted to have exactly one severity tier of issue.

| File | Injected issue | WCAG | Severity | Lands in |
|------|----------------|------|----------|----------|
| `batch1-critical-missing-alt.html` | image with no `alt` | 1.1.1 | **CRITICAL** | **Batch 1** · CRITICAL auto-fix |
| `batch2-serious-missing-lang.html` | no `lang` + empty link | 3.1.1 / 2.4.4 | **SERIOUS** | **Batch 2** · SERIOUS HITL review |
| `batch3-moderate-vague-link.html` | "click here" / "read more" | 2.4.4 | **MODERATE** | **Batch 3** · MODERATE sweep |
| `batch0-compliant.html` | none | — | — | **N/A** · excluded (certifiable) |

## Office / PDF examples

| File | Injected issue | Severity | Lands in | Verified? |
|------|----------------|----------|----------|-----------|
| `batch1-critical-image-no-alt.pdf` | image XObject, no alt | **CRITICAL** | **Batch 1** | structure checked (image present, no `/Lang`); engine confirm on scan |
| `batch2-serious-untagged.pdf` | untagged + no language | **SERIOUS** | **Batch 2** | structure checked (no `/Lang`); engine confirm on scan |
| `batch2-serious-no-title.docx` | document title stripped | **SERIOUS** | **Batch 2** | built by mutating the compliant docx; engine confirm on scan |

**Honest caveats on these three:**
- Unlike the HTML files (verified against the in-repo engine), the **Office (.NET)
  and PDF engines don't run in the build environment**, so batch placement here is
  *expected* — confirm by scanning.
- **Batch 3 (MODERATE-only) and clean Office/PDF aren't included**: PDFs generated
  with reportlab are always untagged (a SERIOUS finding), so a moderate-only or
  fully-clean PDF isn't producible that way; a CRITICAL/MODERATE docx needs a real
  authoring tool. Use the **HTML** files for precise Batch 3 / N-A coverage.
- For broad Office/PDF batch coverage you already have it: your **200-file corpus**
  populated all three batches (80 / 69 / 10) with real Office + PDF documents.

## How to test
1. Upload all four to your Drive folder (or drop them in `test-corpus/files/`).
2. Run a scan (Background on).
3. Open **Remediate** → the program shows one file in each of Batch 1/2/3 and the
   compliant one under N/A.

Notes:
- The HTML engine assigns these severities deterministically, so the batch
  placement is stable.
- These exercise the *batching* logic. Batch 1's "auto-fix" label is about how
  CRITICAL items are typically handled per source type; the HTML alt-text fix
  itself is AI-assisted (semantic), so with AI off it routes to human review.
