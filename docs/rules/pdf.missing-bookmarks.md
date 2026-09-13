# pdf.missing-bookmarks — Navigation bookmarks advisory

**WCAG:** 2.4.5 Multiple Ways (Level AA)
**Severity:** REVIEW (no score penalty)
**Fix mode:** human-only
**Source:** `engine/pdf-analyser/analysers/rules/pdf/bookmarks.py`

## What it checks

PDFs with at least 10 pages are checked for an `/Outlines` dictionary containing a `/First` entry. Shorter PDFs are not flagged. Outline depth, section coverage, labels and destination correctness are not established by this presence check.

Missing bookmarks do not mean a document title is missing. Title metadata and viewer title display have separate 2.4.2 checks.

## Why it matters

Bookmarks help users jump to sections in long documents. [W3C technique PDF2](https://www.w3.org/WAI/WCAG22/Techniques/pdf/PDF2) relates to 2.4.5 as an advisory technique; it is not itself a mandatory conformance requirement. Consequently this detector records a navigation advisory rather than declaring a WCAG failure from absence alone.

## Fix mode rationale

Where useful, re-export the source document with heading-based bookmarks or add a meaningful outline in a PDF editor. Check that labels identify the sections and destinations point to the correct content. The detector does not establish these semantics and does not approve a generated outline.

## Unit test recipe

`tests/test_pdf_bookmarks_not_title.py` builds real 50-page PDFs to verify that:

- A nonempty title and enabled title display pass 2.4.2 even without bookmarks.
- Missing bookmarks produce a separate 2.4.5 REVIEW advisory when selected.
- A real outline clears the advisory.
- Genuine missing title metadata or viewer title display still fail 2.4.2.
- Short PDFs do not produce the advisory.

## Failure modes

- A single vague or misdirected bookmark passes this presence check; destination and semantic coverage require inspection.
- A useful alternate navigation method may exist without bookmarks. This signal remains advisory and does not independently establish a conformance failure.
