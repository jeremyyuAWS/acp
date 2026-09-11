# Integration handoff notes

## Exact test results

```
$ python -m pytest experiments/document_wide_ai -c experiments/document_wide_ai/pytest.ini
53 passed in 0.79s
```

Breakdown by file (via `--collect-only`):

| File | Tests | Covers |
|---|---:|---|
| `test_contracts.py` | 6 | manifest/envelope (de)serialization, malformed-envelope rejection |
| `test_packaging_and_manifest.py` | 11 | extraction, limits, `document_too_large`, criteria filtering |
| `test_validator.py` | 14 | every rejection reason, conflicts, model_omitted, prompt injection |
| `test_applier_and_recheck.py` | 8 | real adapter apply, immutability, regression rejection, recheck |
| `test_harness_end_to_end.py` | 3 | one-request-per-package, full PDF+DOCX run, cost comparison |
| `test_acceptance_edge_cases.py` | 11 | every remaining PRD fixture scenario (see below) |

Zero network calls, zero provider calls, zero DB access in any test — the only "model"
involved is `request/mock_provider.py`, which is pure Python.

Acceptance-criterion fixture coverage (PRD "Include fixtures for..."): repeated text
✅, multiple findings on one target ✅, findings outside selected criteria ✅,
visual-only evidence ✅ (schema-level — see "What's NOT built" below), extraction
failure ✅, oversized input ✅, partial model responses ✅. Additionally: unknown IDs,
stale hashes, ambiguous/mismatched locators, out-of-scope edits, conflicts, malformed
output, and document prompt injection — all in `test_validator.py` /
`test_acceptance_edge_cases.py`.

## Sample outcome report

`docs/sample_reports/pdf_mixed_outcomes.json` — a 3-finding synthetic PDF run showing
one applied-pending-review, one rejected (empty value), one left unresolved by the
model, plus the cost-comparison figures. Regenerate with the harness directly:

```python
from experiments.document_wide_ai.evaluation.harness import run_pipeline
# ... see tests/test_harness_end_to_end.py for a complete minimal example
```

## Supported operations

See `docs/ADAPTER_INVENTORY.md` — two operations, both backed by reused, unmodified
production adapters (`api.remediate_pdf.apply_pdf_field_name`,
`api.apply_alt.apply_alt_text`).

## What's NOT built (deliberately, per PRD scope)

- **Visual evidence packaging.** `contracts.v1.Evidence` and `EvidenceKind.IMAGE` exist
  in the schema and are unit-tested, but no packager actually extracts page images —
  neither allowlisted operation needs visual evidence, so building that pipeline now
  would be speculative. `api.remediate_office.image_bytes_for_locator` is the reusable
  primitive to build on when a vision-requiring operation is added.
- **Automatic chunking / oversized-document splitting.** `document_too_large` is
  returned; nothing retries with a smaller package.
- **Retry / repair requests.** One request per package. A malformed or partial response
  is reported, never re-requested.
- **Live prompt caching, real pricing, paid benchmarking.** `request/builder.py` builds
  a stable, cache-ready prefix (the manifest's own JSON serialization, order-independent
  of the instruction suffix) but nothing calls a real caching API or prices anything.
  `evaluation/cost.py` reports character/token *estimates* and structural request-count
  comparisons only — every field that would require a real provider call is `None` and
  documented as such (`provider_cost_usd`, `is_estimate=True`).
- **PDF `/Figure` alt text (`apply_pdf_figure_alt`) and DOCX form-field names
  (`apply_field_name.apply_docx_field_name`).** Both are safe, reusable adapters (see
  the inventory) not exercised here purely for fixture-construction cost, not safety.

## Required integration seams (for the deferred, separately scoped production task)

1. **Manifest source.** `packaging/manifest_builder.py` builds findings from a fresh
   extraction of the candidate bytes. Production integration must instead source findings
   from the real assessment pipeline (the *latest saved candidate* and findings assessed
   against those exact bytes — PRD §1), not re-derive them ad hoc. That means swapping
   `build_pdf_manifest`/`build_docx_manifest`'s finding-construction internals for a call
   into the real finding/locator store, while keeping the `DocumentContextManifest`
   shape as the seam.
2. **Provider dispatch.** `request/mock_provider.py`'s `generate(request) -> envelope`
   interface is the seam a real provider adapter implements. It must go through ACP's
   existing spending reservation and attempt-lineage controls (`api/ai_spending_budget.py`,
   `api/ai_generation_chain.py`, ADR 0056) — this prototype must not and does not build a
   second budget system.
3. **Allowlist growth.** Adding an operation means: (a) confirm a production adapter is
   pure/isolable (see the inventory's rejection criteria), (b) add an `OperationSpec` to
   `application/allowlist.py`, (c) add a packager fact + finding construction, (d) add an
   `application/applier.py` branch, (e) add a fixture and tests before it ships.
4. **Visual evidence.** When an operation needs it, extend `contracts.v1.Evidence`
   usage: a packager must record `source_locator` + `reason` for every image, and the
   request builder must bound total image count (`packaging/limits.py::max_images`).
5. **Approval/release policy.** This prototype has no concept of human review, approval,
   or publish — `recheck/report.py`'s `Outcome.APPLIED_SEMANTIC_REVIEW_NEEDED` is a
   report label, not a workflow state. Wiring it into HITL review, `ai_standing_approval`,
   or `automatic_release` is entirely out of scope here and must be designed against
   ADR 0056's existing rules, not around them.
6. **Selected-SC and source-revision binding.** Open PR #1966 ("Preserve selected SC
   scope and saved remediation edits through release") touches exactly this area in
   production files (`api/assessment_selection.py`, `api/remediate_office.py`,
   `Remediate.jsx`, etc.) — none of which this prototype touches. Re-check that PR's
   status before wiring `selected_criteria`/`assessment_revision` into anything real.

## Honesty notes carried into the outcome report

- A detector accepting a non-empty `/TU` or `descr=` value never establishes the
  AI-authored text is *correct* — both allowlisted operations write free-text,
  human-facing content, so a detector pass always routes to
  `applied_semantic_review_needed`, never a bare "passed" (PRD §6, and see ADR 0056's
  own equivalent caveat about `_apply_one_value_kind`).
  `Outcome.APPLIED_DETECTOR_PASSED` exists in the enum for a future non-semantic
  operation; nothing in this allowlist produces it today.
- `Outcome.CANDIDATE_REJECTED` applies to *every* finding on a document the moment
  application detects a regression or a re-open failure — never a partial candidate.
- `Outcome.VERIFICATION_UNAVAILABLE` is used, never a silent pass, whenever recheck
  itself cannot run (e.g. the saved candidate fails to reopen after a for-otherwise-valid
  apply — see `recheck/rechecker.py`).
