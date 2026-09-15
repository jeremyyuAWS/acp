# Quality-first review and verification

Quality-first uses stronger cloud models directly. It can cost more and take longer; it does not imply that every proposed fix is correct or safe to publish.

## Source beside the proposal

The mounted remediation inbox compares each recorded source thumbnail and location with its proposed fix. A thumbnail is evidence, not a complete document preview: missing or low-resolution evidence is named explicitly. Existing edit and approval actions remain available. Reviewers should open the source document when fine details cannot be read.

Recognized Quality-first raster charts require individual confirmation of series, year, sign, value and units. OCR can contain every correct number while associating it with the wrong series. This was observed in a model-generated PowerPoint description. These relationships are not declared verified from token presence. Explicitly uncertain image descriptions remain reviewable rather than receiving automatic write credit. Native chart-data derivation remains separate.

## Saved-file checks

Plain Office alt-description changes are read back from the saved package and checked against the approved values. Every other package part must remain unchanged before the later approved transformations/stamping. A failed check preserves the prior copy and leaves the requested values unapplied. Existing PDF preservation checks and accessibility rescans remain in force.

This checks write scope and persistence, not semantic truth or full visual conformance. Mixed decorative/crop changes follow their existing separate checks; no universal claim of pixel identity is made for Office documents.

## Repeatable quality benchmark

Prepare five real synthetic sources without network access or paid generation:

```sh
python scripts/run_quality_first_benchmark.py --prepare /tmp/acp-quality-sources
```

The suite covers a multiseries chart with negative values, table header/value associations, raster-only PDF transcription, two-column reading order, and an ambiguous chart. `requests.json` contains source hashes and prompts, never reference answers. Feed the source files and requests through the candidate being evaluated and capture the exact response schema as a JSON array. Do not silently repair an unusable response or omit a failed case.

```sh
python scripts/run_quality_first_benchmark.py \
  --manifest /tmp/acp-quality-sources/requests.json \
  --responses /tmp/candidate-responses.json \
  --candidate 'provider/model snapshot' --prompt-revision 'revision identifier' \
  --output /tmp/acp-quality-results.json
```

Each result is bound to its case and original file hash. Missing responses count as failures; changed sources or duplicate/unknown cases are rejected. The scorer checks structured facts by their associations, so a list of all the right numbers with swapped years fails. Decimal spelling and percentage-unit aliases are normalized without dropping negative signs or currency units.

**A passing probe is not an approved remediation.** The structured facts can be correct while the free-text description is wrong. Compare descriptions to their source separately and exercise the application’s saved-file checks and rescans. Record any semantic adjudication alongside the unchanged raw score. Five synthetic designs cannot establish general model superiority.

For the existing native PDF saved-file benchmark, use `scripts/run_pdf_quality_evaluation.py`. Its scorer now accepts exactly the complete JSON fences accepted by the production parser; it still rejects surrounding prose, wrong identity, and unsupported operations. Offline preparation never manufactures model scores. Explicit live runs retain their independent spending controls; these code changes do not authorize new spending.

## Validation policy

Before changing a model or prompt, rerun the same versioned fixtures and compare factual probes, uncertainty handling, preserved content and review effort. Keep raw responses, model snapshot, prompt revision and costs. Do not promote a model on the missing-alt-text detector alone or automatically add a second reviewer to every fix: the earlier broad review experiment reduced useful completion.
