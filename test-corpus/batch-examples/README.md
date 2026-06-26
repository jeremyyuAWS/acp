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
