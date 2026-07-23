# Proposed amendment to ADR 0028 — add veraPDF and axe-core as local corroboration engines

**Status:** Draft, for hand-off to the ADR 0028 thread (branch `docs/adr-0028-corroboration-engines`, currently Proposed, not yet Accepted). Written standalone, not committed to that branch, to avoid a concurrent-edit collision — this is input for that thread to fold in, amend, or reject.

**Origin:** Spikes run against this repo's own code and fixtures, documented in full at [`docs/spikes/2026-07-17-verapdf-spike.md`](../spikes/2026-07-17-verapdf-spike.md) and [`docs/spikes/2026-07-17-axe-core-spike.md`](../spikes/2026-07-17-axe-core-spike.md). This doc summarizes the decision-relevant findings and proposes two changes to ADR 0028's scope and one correction to its stated justification.

**Update 2026-07-21:** the veraPDF spike was re-run against ACP's current code (see the dated section at the end of that doc) and the 4.1.2 AcroForm claim below needed correcting — ACP's own `office_structure.py` shipped a native `/TU` check on 2026-07-15, independently of veraPDF or Adobe, closing that specific signal before this amendment was even drafted. The Phase 0 case below still holds — corroboration + PDF/UA breadth, not 4.1.2 gap-closing — but change 2's tag-tree justification needed the same correction; both are marked inline.

## Proposed change 1: add a Phase 0 — local, open-source engines before Adobe

ADR 0028's phasing starts at **A — Adobe adapter, native PDFs only**. Propose inserting a phase before it:

- **Phase 0 — veraPDF (PDF/UA-1 and -2) + axe-core (HTML), both local, both open source, both already spiked against ACP's own fixtures with working code.**
- Neither requires the governance machinery ADR 0028 correctly insists on for Adobe (org-level opt-in, egress visibility, metered-cost scoping, admin-entered credentials) — they run entirely inside the tenant, no document ever leaves the box. That's not a minor convenience; it's the difference between "ship immediately" and "ship after a customer-facing opt-in decision, pricing confirmation, and a credentials-handling review."
- Concretely spiked, not theoretical:
  - **veraPDF** (dual GPLv3+/MPLv2+ — adopt under MPLv2 alone, no copyleft exposure on ACP's own code regardless of deployment shape) corroborates ACP's existing 1.3.1/2.4.2/3.1.1 findings on ACP's own untagged PDF fixture, with finer per-content-item granularity than ACP's current rules surface — re-confirmed live 2026-07-21 against ACP's current combined pipeline, byte-identical results. **Correction:** the 4.1.2 AcroForm `/TU` gap this bullet originally said UA1 "directly closes" is now closed independently — `office_structure.py`'s own `pdf_form_field_checks()` (shipped 2026-07-15) catches the identical field on the identical fixture ACP's own live pipeline now returns `PDF_FORM_NO_ACCESSIBLE_NAME` on `dob_field`, confirmed by direct re-run, not inferred. veraPDF's UA1 signal there is now corroboration from a second engine, not new coverage; the real remaining 4.1.2 gap is `/FT` and `/V`, which neither ACP's native check nor veraPDF's demonstrated UA1 rule cover. UA2 still does not show the equivalent failure on the identical fixture — that asymmetry is unchanged and still unresolved.
  - **axe-core** (MPL-2.0, already proven in the `movate-ada-web` sibling repo, one afternoon to port) is genuinely complementary to ACP's HTML rules, not redundant: both agree on 1.1.1/3.1.1, but axe-core structurally cannot catch vague-but-present link text the way ACP's own deny-list heuristic does, while ACP's HTML pipeline has *zero* landmark/ARIA-region coverage today, which axe-core closes on day one.
- Sequencing this first doesn't block or compete with the Adobe work — Phase A (Adobe) can start in parallel once pricing/beta gating is confirmed (ADR 0028's own stated precondition, item X4). Phase 0 just doesn't have to wait for that confirmation, since it has no external dependency to gate on.

## Proposed change 2: correct the tag-tree justification for Adobe

ADR 0028's Context section, justification #2 for Adobe, states it "reads the tag tree ACP's pdfplumber/pdfium engines do not: tagged-PDF structure, tab order, table headers within tags, figure alt from tags, bookmarks."

This overstates the current gap. Per the codebase map done for the veraPDF spike, ACP's existing `worker-python` PDF rules **already read the tag tree** for four of those five examples: `tagged_pdf.py` (StructTreeRoot/MarkInfo), `table_headers.py` (table headers within tags), `image_alt_text.py` (figure alt from tags), `bookmarks.py` (Outlines). Tab order (PDF 2.4.3, `/Tabs`) is the one genuinely-unbuilt item in that list, and it's a cheap, well-defined native build — not something that requires an external engine.

**Correction (2026-07-21):** this section originally named AcroForm field accessibility (4.1.2 `/T`/`/TU`) as the one tag-tree gap Adobe would genuinely close. That's narrower now — ACP's own `pdf_form_field_checks()` already reads `/TU` natively (confirmed live against the same fixture used to make this claim originally). The gap Adobe (or veraPDF) would still close is `/FT` and `/V` specifically, the two AcroForm properties V3's fuller spec calls for that nothing in ACP checks today. Recommend naming that narrower gap, or dropping the AcroForm justification in favor of Adobe's actual differentiators (Matterhorn Protocol's full 136-failure-condition coverage, the "recognizable name" trust value, and whatever it independently corroborates beyond what veraPDF already covers once Phase 0 ships).

## What this amendment does NOT propose changing

Everything else in ADR 0028 stands as written and this doesn't relitigate it: the reconciliation rules (ACP native wins where it has a verdict; disagreement surfaces as 🟡 with both verdicts, never a silent pick), the org-level opt-in + provenance + Trust Panel governance for Adobe specifically, the convert-then-check lane's export-vs-source-fact labeling discipline, and vendor APIs staying benchmark-only. Those apply to Adobe and vendor SaaS precisely because they involve document egress and cost — veraPDF and axe-core don't, so they don't need that governance layer, but they also don't substitute for Adobe's Matterhorn-scale coverage or its recognizable-name trust value once a customer wants that specifically.

## Recommendation if this thread wants to act on it

1. Fold Phase 0 in as written above, or rewrite it in this thread's own voice — the spike docs are the evidence trail either way.
2. Correct or drop the tag-tree justification in the Context section.
3. Resolve the open UA1-vs-UA2 AcroForm question with a properly-tagged form-bearing fixture before committing to which veraPDF profile ships (this spike's fixture was deliberately untagged to isolate the question, and got a clean UA1 answer, but couldn't rule in or out UA2's behavior under tagged conditions).
