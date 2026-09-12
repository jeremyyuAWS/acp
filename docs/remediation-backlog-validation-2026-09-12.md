# Remediation backlog implementation and validation

## Implemented

- Optional native Word tracked-change companion and coverage JSON, separate from the accepted corrected copy. Evidence binds the cached source, published corrected artifact and companion hashes. Text revisions are tracked where representable; unsupported metadata/structural changes are disclosed, never presented as fully tracked.
- Approved source-anchored repairs to existing PDF headings and table header scope/associations. Automatic suggestions cover only unambiguous existing headings and rectangular table header scope. The normal approval job saves the repaired PDF and records criterion-specific evidence; stale or invalid plans remain unwritten. Explicit reading-order repair code is retained and tested separately, but is not mounted in the product application path because semantic order cannot yet be freshly verified.
- Plain-language PDF structural proposal summaries with unchanged approved plan and source lineage.
- Responsive styling checks on actual representative app screens and progress/drawer/release controls, using isolated worktree browser fixtures.
- Review action row reduced to the auto-apply AI switch. Successful server-confirmed enablement displays a green approval notice. Manual work and invalid/stale proposals remain exceptions.
- Default Microsoft drive discovery now persists the actual parent drive identity. Older eligible scans expose metadata-only recovery: fresh Microsoft permission, exact source IDs/names/timestamps and recorded checksums are verified before an atomic NULL-only drive backfill. No reassessment, file mutation or publishing approval occurs. Recovery rechecks the same selection and never retries an uncertain POST.
- Native Word companions accept canonical Microsoft QuickXor source checksums, verified against cached original bytes. This noncryptographic provider check complements ownership/version guards and exact corrected-artifact SHA-256; it is not a cryptographic signature.
- Repeatable six-case PDF model evaluation harness sharing the production prompt, with upfront cost reservation and strict response validation. Production prompt explicitly requires exact locator objects and unfenced JSON.

## Validation evidence and limits

- Native Word Accessibility Assistant on synthetic negative/positive controls: missing alt text 1 before, 0 after the supported writer; corrected control shows no reported issues. This does not certify every customer document.
- Independent veraPDF positive/negative controls behave as expected. Existing tagged table-header repairs remove a specific PDF/UA failure while preserving content; the repair fixture still has other PDF/UA failures. See `native-checker-validation.md` and retained raw results.
- Live model pilot stopped after two calls. Haiku returned an invalid contract; Sonnet usage could not be recovered. No further paid calls occurred, no full comparison completed and no quality winner is claimed. See `PDF_AI_QUALITY_EVALUATION.md`.

## Remaining external or broader work

- The reported 147-file customer scan was identified: all 147 had completed assessment and source item IDs/timestamps, while drive IDs were absent. Frozen Discovery confirms a default-drive selection. No source content or corrected bytes were inspected. Runtime recovery still requires the active user's fresh Microsoft connection; no live repair or publication is claimed before that executes. This scan has not yet admitted remediation, so its real corrected-byte/batch delivery audit remains pending.
- Acrobat native checker validation requires an available Acrobat installation/session.
- Untagged/scanned PDF reconstruction and ambiguous complex table or reading-order reconstruction remain unsupported automatic repairs. Existing assessment, explicit supported plans and remaining-work reporting remain available.
- The complete paid model comparison remains pending resolution of the pilot accounting uncertainty.
- A Discover-to-publish setup wizard is a proposed next flow, not part of this implementation.
