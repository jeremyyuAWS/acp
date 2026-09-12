# Synthetic PDF AI quality evaluation

The benchmark compares six repository-generated PDF forms across three fixed arms: the selected provider's catalog balanced model with extracted context, its catalog quality model with the same extracted context, and that same quality model with the exact native PDF. Production model settings remain unchanged. A model being in a higher catalog tier does not establish that it produces better answers.

Fixtures cover clear labels on two pages, section-specific labels, an existing widget value that must not become its name, a missing external label, document instruction injection, and unrelated adjacent prose. The expected labels are frozen by the fixture author, not inferred from model output. Unresolved ambiguous labels are counted separately from useful applied fixes.

Each response uses the real document-wide request contract and production validation. Valid edits run through the real PDF field-name writer. Scores record correct actionable proposals, justified unresolved findings, wrong semantic values, unsupported operations, exact saved SHA-256, page content/geometry and form-state preservation, measured latency, actual token cost and cost per useful applied fix. Invalid contracts are not counted as useful fixes. All unchanged content streams and field state must survive application.

Before dispatch, the runner persists the full ceiling for all 18 attempts. It narrows context/output bounds to 32,768/2,048 below existing verified catalog limits and enforces a $2 aggregate reservation cap. There is no fallback, transport retry, customer input, database migration or scan mutation. Missing usage or uncertain transport retains the reservation and stops the entire benchmark. A completed partial-quality response can be scored, but a truncated response is accounted as unusable.

Offline fixture preparation does not fabricate scores. Live execution requires legitimate configured provider credentials and current administrator governance, read from a read-only database query or a fresh, explicit non-secret operations snapshot. The latter expires after ten minutes before admission and identifies provider, enabled state, configured model, endpoint and exact environment secret reference. Credentials remain in subprocess memory and HTTP headers only; they never appear in reports or error output.

Example offline preparation:

```
python scripts/run_pdf_quality_evaluation.py --output /tmp/pdf-quality-prepared
```

The live option executes paid requests and must use a new output directory. Existing output is deliberately refused, so restarting cannot silently replay prior calls. The machine-readable `evaluation.json` includes every reservation, attempt, measured result and summary. Source PDFs, exact manifests, retained synthetic responses and saved candidates accompany it.

This form-focused evaluation does not establish broad PDF remediation quality, correct figure descriptions, tag-tree repair, full accessibility conformance or performance on customer documents. It is a repeatable initial evaluation of the supported accessible-name write path.

## Actual September 12 run

Current read-only production governance confirmed Anthropic enabled, Haiku 4.5 as its configured model, and the exact `ANTHROPIC_API_KEY` reference. The live benchmark reserved **$1.290240** for all 18 attempts before dispatch.

The batch stopped after two calls as required by its uncertain-accounting rule:

| Arm / first case | Actual result | Measured cost | Latency |
| --- | --- | --- | --- |
| Haiku extracted / clear two-page form | Correct-looking label strings, but invalid production contract: code-fenced JSON and string locators rather than manifest locator objects. No useful applied fix credited. | $0.003079 | 3.345 s |
| Sonnet extracted / same PDF | Post-transport strict response rejection; accounting uncertain. No retry or subsequent paid dispatch. | Unknown; reservation held | 6.265 s |
| Remaining comparisons | Not dispatched | No additional measured charges | — |

The exact post-transport Sonnet failure cause was not retained and cannot be inferred from its `ValueError`. A future evaluation should retain sanitized response-structure/accounting diagnostics before strict rejection. It must resolve the uncertain attempt first, rather than silently replaying it. The benchmark does **not** establish a model-quality winner or completion of the six-document comparison. Machine-readable partial evidence is retained in `docs/pdf-ai-quality-results-2026-09-12.json`.

The initial two-call pilot ordered the schema after the manifest, unlike production. This is an additional protocol limitation; these results must not be presented as a production-model comparison. The repaired runner reuses the production prompt builder and retains sanitized provider response/accounting diagnostics before validation. The original uncertain attempt has not been retried.
