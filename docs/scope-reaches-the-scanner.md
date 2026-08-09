# Scoping the SCAN, not just the score

**Status:** proposed · **Date:** 2026-08-08 · **Related:** ADR 0007 (fan-out), ADR 0011
(incremental fingerprinting), ADR 0020 (discover/assess separation)

## The problem, precisely

`scan_scope` gates which **criteria** are evaluated. It has never gated which **files are read**.

`api/routes/scans.py` contains no reference to `scan_scope` or `in_scope`. The scanner enumerates
on extension alone — `api/scanner.py:512` (`exts`, the SharePoint/Drive set) and `:876` (local,
`OFFICE + (".pdf",) + HTML_EXTS`) — and the only scope filtering happens afterwards, in
`_scoped_for_scoring`, which trims *findings* from a file that has already been downloaded,
opened, rasterised, OCR'd and stored.

So an operator who scopes to `.docx` still causes every PDF in the estate to be fetched and read.
The UI then hides them (`visibleForFileTypes`, #196), which is what makes this invisible: the
screen agrees with the operator and the server does not.

### Why this is a healthcare problem, not a performance one

The customer is a hospital. The documents are the PHI. "We read every PDF anyway and discarded
the findings" is a data-minimisation answer no security reviewer accepts, and it is the honest
description of today's behaviour. The reading is not incidental either — the PDF path rasterises
pages and runs OCR, so the text of an out-of-scope clinical document is extracted, held in
memory, cached to blob (`upload_render`) and potentially traced to Langfuse.

Making the filter real is the difference between "we assess only Word documents" and "we open
everything and score only Word documents."

## What changes

**One helper, in `assessment_policy` beside `active_scope` and `_file_format`:**

```python
def formats_in_scope(scope) -> frozenset[str] | None
```

Returns the union of every format any criterion is scoped to, or `None` for "no restriction".
`None` — not the full set — so callers cannot confuse "unset" with "all four", which is the
distinction `in_scope` and `visibleForFileTypes` already turn on.

**Applied at enumeration, at every source.** Four sites, and missing one is how this half-works:

| source | site | note |
|---|---|---|
| local | `scanner.py:876` | the demo corpus |
| SharePoint | `scanner.py:587` via `exts` | |
| Google Drive | the mimeType allow-list (`scanner.py:62-72`) | maps mime → ext first |
| upload | `Upload.jsx` → single-file route | scope should reject, not silently accept |

### The trap: HTML is not in the scope universe

`scan_scope`'s format axis is the four document formats — `gen_scope_presets.py`'s `_DOC_FORMATS`
excludes `html` deliberately. So a naive intersection ("keep files whose format is in scope")
would stop scanning HTML the moment anyone scoped to `.docx`, because html can never appear in a
scope map.

**HTML must be exempt from this filter**, and the exemption needs a comment saying why, or the
next person removes it as an inconsistency.

## What must NOT change

- **Empty scope means no restriction.** Same semantics as `in_scope` and `visibleForFileTypes`:
  a fresh workspace scans everything. Anything else turns "unset" into "assess nothing", which is
  the inverse of the operator's intent and the bug #187 exists to prevent.
- **Discovery still reports what it skipped.** See below — this is the part most likely to be
  dropped for being extra work, and it is the part that keeps the feature honest.

## Report the skips — do not silently shrink the estate

`_list_files` already threads a `scope_out` dict recording `kept` and `truncated`. Add
`skipped_out_of_scope`, and surface it in Discover:

> *"312 documents · 47 PDFs not read (out of scope)"*

Without this, narrowing the scope makes the estate quietly smaller and an operator cannot tell a
scoped scan from a source that lost files. This codebase has been bitten repeatedly by exactly
that shape — a number that changed for a reason nobody could see. It is also the line that
answers "did you look at everything?" in an audit.

## Consequences worth deciding before building

1. **Scan diffs compare populations, not estates** (ADR 0009). A scan scoped to `.docx` diffed
   against an unscoped one will read as "45 documents disappeared". The diff needs to carry the
   scope, or refuse to compare across differing scopes.
2. **Incremental fingerprinting caches file lists** (ADR 0011). A scope change must invalidate
   that cache, or the first scan after narrowing returns the old population.
3. **Certification meaning.** `Publish` certifies against what was assessed. Scoping the scan
   makes the certificate narrower in a way `ScopeBanner` already states — but the PDF report's
   `_scope_section` (the negative-assurance text) should name the formats not read, not just the
   criteria not evaluated.

## Test plan

The load-bearing test is not a unit test:

- **A `.docx`-only scan must not download a PDF.** Assert on the fetch, not the result — a test
  that only checks the file list would pass against today's behaviour, since today's list is
  filtered client-side anyway.
- Empty scope scans every format (the no-restriction case).
- HTML is scanned under a `.docx`-only scope (the exemption).
- `skipped_out_of_scope` counts what was skipped, and Discover renders it.
- A scope change invalidates the incremental cache.

## Size

Small-to-medium. One helper, four call sites, one counter threaded through to the UI, five tests.
The risk is not the code — it is the three consequences above, which are decisions rather than
implementation.

## Recommendation

Build it. Of everything outstanding it is the only item that is simultaneously a **correctness**
fix (the filter does what it says), a **security** improvement (PHI not read when out of scope),
and a **performance** win (a `.docx` scan stops opening every PDF in the estate). Nothing else on
the list is all three.
