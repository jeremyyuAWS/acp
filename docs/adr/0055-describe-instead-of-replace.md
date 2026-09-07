# ADR 0055 — Describe-instead-of-replace: a 1.4.5 image the reviewer keeps

**Status:** Proposed — design only; no lane implements it in this change
**Date:** 2026-09-07
**Related:** #1665 (the pptx 1.4.5 lane downgraded to HUMAN), #1715 (the replacement writer that
clears it), #1724 (`apply_pptx_image_of_text` recorded as retired), ADR 0040 (provable vs.
judgement review lanes), ADR 0031 (certification gated by coverage). Premises measured in
`tests/test_describe_instead_of_replace.py`.

## Context

WCAG 1.4.5 asks for **real text instead of a picture of text**. #1715 shipped the fix that
delivers exactly that: `apply_pptx_image_replacement` swaps the `<p:pic>` for a text box and
deletes the media part — necessary, because `ocr._ooxml_images` walks the ZIP namelist and never
opens a slide, so an orphaned raster keeps the finding firing.

That is the right fix when the picture *should* go. It is the wrong fix, and sometimes a
destructive one, when the reviewer decides the picture must **stay**:

- **The writer refuses it.** An image referenced by a layout or master, nested in a `<p:grpSp>`,
  or with no `<a:xfrm>` of its own is returned unresolved by design. The reviewer sees a card
  they cannot action.
- **The styling carries meaning.** A scanned signature block, a stamped seal, a typographic
  device — replacing it with a text box loses the thing that made it worth including.
- **It is a 1.4.9 chart.** 1.4.5 exempts charts (`ocr._looks_like_chart`); 1.4.9 is AAA and
  exempts nothing. Replacing a chart with its axis labels destroys information, which is why the
  replacement lane is scoped to 1.4.5 alone. For 1.4.9, describing is the *only* honest
  non-destructive outcome.

The reviewer's two current options are **replace** or `essential_exception` (a logo or brand
mark). Neither is "keep this image, and describe it". That decision has no cell in the model.

### What happens today, measured

Both ways a reviewer can express the decision are wrong, and neither fails loudly.
`tests/test_describe_instead_of_replace.py` pins both.

**Branch one — the reviewer records a `resolution`.** Every resolution promises the document no
prose, and `_row_is_resolved` enforces that for a good reason: #43 fixed a bug where approving
"Mark as decorative" wrote `descr="Mark as decorative"` onto the picture. So the description is
stored on the row and dropped by every accessor:

| | |
|---|---|
| `proposals[0].approved_value` | the reviewer's description — *stored* |
| `_row_approved_values` | `{}` |
| `approved_images_of_text_values` | `{}` |
| `approved_alt_values` | `{}` |
| `count_unapplied_approved_values` | `0` |
| `mark_file_compliant_if_reviewed` | **`True`** |

The file is certified 100/100 conformant with the image untouched **and** undescribed. This is
precisely the defect `mark_file_compliant_if_reviewed`'s own docstring records — "marked a PPTX
100/100 and conformant with WCAG 1.1.1 while its ten images were still undescribed" — arriving
through a new door. Nothing in the row is specific to the spelling `described`: the predicate
tests only that the column is non-empty, so every resolution behaves this way.

**Branch two — the reviewer records no resolution.** Now the value flows, to
`approved_images_of_text_values`, which `handlers` hands to `apply_pptx_image_replacement`. The
picture the reviewer chose to keep is deleted, and prose *about* the image is written where the
image's *own words* belong. **A description is not a transcript** — "A slide titled Q3 revenue,
in the brand's display face, reading: revenue rose 12%" is not what 1.4.5 asks to be put in the
document as text. Nothing in the row distinguishes the two intents: same locator, same
`rule_id`, same shape of value.

The model's two axes are each strictly exclusive of the other. `resolution` is judgement without
a value; `approved_value` is a value without judgement. Describe-instead-of-replace needs the
one cell of the cross product that does not exist.

## Decision

**Model the decision as it actually is: a judgement that resolves 1.4.5, plus a NEW 1.1.1
obligation.** Not as a value-bearing resolution.

The reviewer who keeps an image of text and describes it is doing two separable things. They are
deciding that this document will not carry the words as text — a judgement, and the honest
resolution of the 1.4.5 finding. And they are authoring alt text for an image, which is a 1.1.1
obligation the document did not previously have (the picture was flagged for 1.4.5, not 1.1.1).
Splitting them along that seam is what makes every existing guarantee hold unchanged.

### Three parts

**1. A new value-free resolution, `described_not_replaced`,** valid on 1.4.5 and 1.4.9 rows.
It joins the existing `RESOLUTIONS` vocabulary in `api/routes/hitl.py` and carries no text, so
`_row_is_resolved`'s contract — and the #43 fix it exists to preserve — is untouched.

Unlike `decorative` and `essential_exception`, this resolution is **conditional**: it is honest
only once the description has actually been written. Part 3 is what makes that true rather than
asserted.

**2. On that resolution, enqueue a 1.1.1 row carrying the description,** with the locator
translated from the 1.4.5 proposer's `image N` to the alt lane's `part#rIdN`.

**3. The description then travels the already-proven 1.1.1 alt lane** —
`store.approved_alt_values` → `apply_alt_text` → `_apply_one_value_kind` with
`scs_to_clear={"1.1.1"}`, the lane `tests/test_remediation_verified_pptx_alt.py` proves end to
end. No new writer, no new verification path.

### Why the split is the load-bearing choice

Everything awkward about this feature dissolves at that seam:

- **Certification becomes correct by construction.** The new 1.1.1 row is unapproved and
  unapplied, so `count_unapplied_approved_values` counts it and
  `mark_file_compliant_if_reviewed` refuses until the description is written *and* a re-scan
  confirms 1.1.1 cleared. Branch one's silent false certification closes with **no change to
  either function.**
- **The verify gate works, because it is asked a question it can answer.** `scs_to_clear` is
  `{"1.1.1"}`, which *can* clear: alt text written → the structural detector passes. Had the
  description been credited against 1.4.5, it could never clear — the raster is still there by
  the reviewer's own decision — so the row would stay unapplied forever and the file would wedge
  permanently. That is the dead end this design exists to avoid, and it is invisible until you
  ask which criterion the re-scan is being asked about.
- **The audit trail stays honest.** The 1.4.5 finding is recorded as resolved by judgement, and
  the 1.1.1 fix as a written, verified value. A certification report can say what actually
  happened, rather than implying a 1.4.5 fix that was deliberately not made.

### The one capability that does not exist

The locator translation. The 1.4.5 proposer mints `image N` (a media index mirroring
`ocr._ooxml_images`); `apply_alt.parse_locator` cannot read it at all, requiring a `#`.

**This is exactly the retired module's unique capability.** `apply_pptx_image_of_text`'s
`_media_index` and `_slide_rels` already perform the resolution: media index → canonical media
path → the `rId` a slide uses to reference it. So #1724's retirement record is revived as a
**resolver**, not as a writer — `_patch_pics`, the half that duplicates `apply_alt_text`, stays
retired, because the alt lane already does that job and has a round-trip fixture behind it.

The destination shape resolves today and was verified rather than assumed:
`apply_alt.resolve_target` matches an `r:embed` fragment to the same element as the shape name.
That check found a stale claim in `store._row_proposal_locators` asserting the opposite — that
an rId locator "reaches no element" — which this change corrects. A design that trusted that
docstring would have rejected its own best route.

## Consequences

- `apply_pptx_image_of_text` stops being retired **in part**: its resolver is used, its writer is
  not. `tests/test_apply_pptx_image_of_text_retired.py` will fail on the import, which is its
  designed reminder — it should be narrowed to the writer, not deleted.
- One reviewer decision produces two audit rows. The review inbox must present that as one
  action, not two cards; the second row is a consequence of the first, not an independent ask.
- A described image is **1.4.5 not-fixed-by-choice and 1.1.1 fixed**. Any surface that reports
  per-criterion outcomes must be able to say that. This is a reporting question, not a data one —
  both facts are already in the row — but it is not free, and it is not designed here.
- 1.4.9 gains its first non-destructive outcome. The lane stays HUMAN for replacement; describing
  is the only automated write it can honestly offer.

## Alternatives considered

**A — Relax `_row_is_resolved` to let a resolution carry a value.** The smallest diff and the
worst idea. That predicate governs three call sites (`_row_approved_values`,
`_row_companion_files`, `_row_owes_no_document_content`) and is the guard that stops a card's UI
label reaching the document as alt text (#43). Weakening it globally to serve one new decision
re-opens a fixed bug on every other one.

**B — Follow the `decorative` precedent: a resolution plus a dedicated accessor.**
`approved_decorative_locators` already reads resolution-bearing rows directly, bypassing
`_row_approved_values`, so a parallel `approved_described_values` would fit the house style. It
fails on the half the precedent does not cover: `decorative` writes a *marking* and owes the
document no content, so `_row_owes_no_document_content` returning `True` is correct for it and
wrong here. Certification would still fire before the description was written — branch one's
defect, preserved. Closing that needs a second exception threaded through the counters, which is
more surface than option C for a worse result.

**C — Enqueue a 1.1.1 row (chosen).** More moving parts at the seam, none afterwards: no
counter, no gate, no writer and no verification path changes. The cost is the locator
translation, which is a bounded, testable function over machinery that already exists.

**D — Do nothing; tell reviewers to use `essential_exception`.** Rejected as dishonest. That
exception says the image is an essential logo or brand mark exempt from 1.4.5. A scanned
signature block or a chart is neither, and recording it as one puts a false statement in the
audit trail that a certification report will repeat.

## What this ADR does not decide

- **The review-card interaction.** Whether "keep and describe" is a third button, or a mode the
  editor switches into, is a design-board question. The backend contract above holds either way.
- **Whether the description should be OCR-seeded.** `ai._transcribed_alt` already feeds the
  transcript into the vision alt draft when the picture is prose, so a draft plausibly exists.
  Whether it is the *right* draft for a reviewer who has just decided the picture stays is worth
  measuring before assuming.
- **Whether `_row_proposal_locators` should extend to `evidence`.** The stale docstring corrected
  here was the stated reason it does not. The exclusion is now known to be a conservative scope
  rather than an impossibility, and deciding it needs its own verification — it would give
  deferred rows' images the decorative marking they are currently denied.
- **docx and xlsx.** The same reviewer decision exists for both. Nothing here is pptx-specific
  except the locator translation, which is.
