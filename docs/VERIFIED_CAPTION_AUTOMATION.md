# Verified caption automation

Automatic writing requires evidence about the image itself. A successful model
response, OCR text presence, a second model agreeing, or an accessibility checker
finding an alt attribute does not establish that a caption is accurate.

## Independent caption gate

`caption_validation.validate_caption` approves only a closed caption grammar for
exact flat raster facts: a solid canonical color, or one/two isolated canonical
colored circles or squares on white. Colors use an exact palette. Transparent,
animated, oversized, malformed, muted-color and unsupported images remain manual.
Additional, negated or scoped claims remain unverified. Missing OCR observations
cannot disprove a model's numbers; an explicit global denial of observed numeric
values is a contradiction.

This intentionally narrow gate does not validate chart interpretation, photographs,
author intent or whole-document accessibility. Its canonical caption and evidence
must be bound to the exact image and value used by the writer.

## Exact PDF figure evidence

The PDF integration must associate a unique figure MCID with the correct page and
ParentTree entry and the single raster painted for that figure. Whole-page renders
must never supply figure captions. Unsupported graphics, ambiguous tags, clipping,
masks, transparency, nonuniform scaling and color transforms remain manual.
Content/image decoding must be bounded before allocating decoded data.

Generate drafts from the extracted raster only. Recompute the association and
caption evidence against the current corrected artifact before standing approval.
Writing changes only the exact figure's alt text; source content and rendering
must remain preserved. Existing descriptions must remain untouched.

## Verification-driven model retry

The Office retry integration targets a single approved image caption in a file
that fails independent pixel verification. An unrelated missing image, unavailable checker, corrupt file
or unknown caption meaning does not justify a stronger-model retry.

The initial scope retries the first frozen model with the next distinct model
already approved for the run. Other model positions and multiple simultaneous
caption changes remain outside this retry path. Raw image facts must match the
Office presentation: stretched, cropped, repeated, rotated, flipped, grouped or
effect-transformed images remain manual. Unsupported storage identities stop
before generation.

Use at most the next distinct model tier already frozen and approved for the run.
Restore the original run authority in approved-value workers, preserve budget
reservations, and require settled usage. Uncertain paid dispatch is not replayed.
Cancellation, changed consent, a changed review or a replaced artifact stops work.
If no independently verified replacement is available, retain the previous saved
file rather than delivering an objectively wrong caption as remaining work.

Retain the failed bytes and store replacement candidates immutably. Commit the
replacement pointer only after exact read-back, actual corrected-file reassessment
and an artifact/authority comparison. Give the replacement a distinct approval and
writer identity. Preserve the original failed outcome and supersede only its exact
obligation; unrelated review obligations remain outstanding.

## Validation limits

Synthetic live GPU tests correctly captioned solid colors but misdescribed a chart
and simple shapes. Transport success therefore cannot serve as caption verification.
Real format fixtures and the actual managed approval/write/reassessment paths are
required before shipping these integrations. Publication can include recorded
remaining work; it does not certify accessibility.
