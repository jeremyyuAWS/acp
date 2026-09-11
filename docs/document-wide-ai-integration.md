# Document-wide AI integration pilot

The Remediation plan offers an optional advanced **document-wide AI** setting when cloud AI is selected. It uses the accepted run's provider configuration and spending limit. It is off by default; changing to rules-only or local-only clears the option.

## Supported work

- Word (DOCX), WCAG 1.1.1: descriptions for assessed images, with actual image evidence.
- PDF, WCAG 4.1.2: accessible names for assessed AcroForm fields.

This pilot does not promise every WCAG repair or every file format. The original assessment scope and finding identities remain authoritative. Unsupported, ambiguous, or oversized work remains unresolved with a recorded reason. Existing scans with multiple findings but no exact saved locations require reassessment; the integration never guesses a mapping from list order.

## Processing and release

1. Save the deterministic remediation candidate.
2. Build bounded context from those exact saved bytes and selected, remaining assessment findings.
3. Ask the configured primary model for one structured response. Allow one fallback for invalid or incomplete output, subject to the same run budget.
4. Validate every operation, locator, finding ID, original value, and source hash.
5. Feed accepted suggestions into the existing review and application path. The accepted automatic-approval setting can authorize application without individual approval.
6. Save and reopen the changed artifact. Release reads this saved artifact, retaining preceding deterministic edits.

AI-written descriptions and labels remain **applied, semantic review needed**. A scanner confirming non-empty text cannot verify its meaning. Automatic release may deliver those copies under the accepted policy; it does not make them verified fixes. Suggestions, change records, and findings remain separate counts.

## Bounds and cost

- At most 20 target findings, 100 PDF pages, and 60,000 extracted text characters.
- Input document at most 20 MB. DOCX archive expansion at most 80 MB and 4,000 entries.
- At most eight PNG/JPEG image inputs, each at most 1 MB and 1,568 pixels per side; combined image bytes at most 4 MB.
- Known supported cloud models receive 4,096 output tokens for the primary attempt and 8,192 for fallback. Budget reservations use the adjusted allowance and existing configured prices.
- No automatic document splitting, new model selection, or live prompt-cache feature is introduced.

Provider usage and attempts use existing durable records. Offline tests prove the request/application boundaries with synthetic documents; they do not establish live model quality or a measured cost saving.

## Packaging

Production imports the unchanged contracts and packagers from `experiments/document_wide_ai`. The application container includes that directory and `/app` in its Python path. New application integration lives under `api/document_wide_*`; the offline mock provider is not called by that path.
