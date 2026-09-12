# Saved PDF structure repairs

PDF repair uses existing tagged content associations rather than replacing pages or pretending an image-only PDF is fully accessible.

## Writable supported plans

- **Headings:** exact existing tagged `/P` or `/Span` text on the same page can be promoted to `/H1`–`/H6`. The visual font hierarchy provides a proposed level; semantic correctness remains a review decision. A canonical no-heading detector recheck proves structural heading presence, not the correctness of every level.
- **Simple table headers:** proposals identify an existing all-`/TH` first row above a rectangular, all-`/TD` body without spans. The approved plan writes `/Scope /Column`; it does not invent which cells are headers.
- **Complex tables:** an explicit approved `table-headers` plan links a `/TD` to unique existing `/TH` IDs in the same table, resolved through the existing IDTree. Header scope may be explicitly set to Row, Column, or Both. Existing RowSpan/ColSpan and contents stay intact; complex relationships are not guessed.
- **Reading order (retained helper only):** an explicit `reading-order` plan supplies a complete permutation of existing indirect siblings in a Document, Part, Sect, or Div. Only structure traversal order changes. Page operators, individual marked-content identifiers, ParentTree entries and child parent references remain intact. This operation is deliberately not mounted in the normal approval workflow: preserving a requested tag permutation is not independent verification that its semantic reading order is correct.

The common locator is `pdf:struct:<index.path>:<source-digest>`. Values are JSON objects: `{"op":"heading","role":"H1"}`, `{"op":"header-scope","scope":"Column"}`, `{"op":"table-headers","headers":["existing-header-id"]}`, or `{"op":"reading-order","order":[1,0,2]}`. The digest binds the existing whole tree and decoded page content. The writer atomically rejects stale, invalid, cyclic, inconsistent, signed or encrypted inputs. Existing page MCIDs must be unique and correctly mapped through the ParentTree. After saving, page stream equality and the complete edited structure are checked again.

## Canonical verification and partial coverage

The first-party tagged-table detector participates in canonical whole-file assessment and reads real Scope/Headers presence with exact source-bound locators. Scope repairs clear the concrete missing-header relationship finding on rescanning. PDF 1.3.1 is registered as PARTIAL: clean table checks remain REVIEW, because the rest of document relationships and semantic correctness are not established. TAG_TREE describes actual parser capability and is removed for untagged files. Explicit reading-order plans are available to the guarded structural writer but are not mounted as a normal credited 1.3.2 value lane: semantic reading order lacks a complete canonical detector.

## Deliberate unavailable cases

Existing scanned-PDF vision layout assessment and advisory review findings remain available; these describe pages and do not reconstruct an accessible saved PDF.

An untagged/scanned PDF, missing or broken ParentTree/MCIDs, XObject marked content, mixed object/tag sibling order, ambiguous attribute arrays, nested/merged table header inference, and OCR reconstruction cannot be safely handled by these plans. Existing explain-only structure and reading-order maps remain re-authoring instructions. They do not count as edits to a saved copy or proof of complete remediation.

Automatic generation of a tag tree from OCR requires reliable text, font, coordinates, language, grouping, table/form semantics, MCID assignment and independent assistive-technology validation. Adding speculative tags or invisible duplicate text would create false compliance and may damage reading or form behavior. This path remains specifically unavailable rather than silently approved.

Fixture coverage exercises saved-candidate proposal writeback, canonical heading recheck, literal content/page/annotation/form preservation, complex header IDs and spans, explicit sibling order, stale source, invalid atomic batches and broken associations. Fresh whole-document assessment before release remains the final gate; these bounded repairs do not guarantee every native Office/PDF accessibility checker passes.
