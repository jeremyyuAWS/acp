"""The single source of truth for *how* each (document format, WCAG criterion) is actioned.

`store.RULE_FORMATS` says WHICH formats a criterion is evaluated on. This table says, for each
of those in-scope pairs, which REMEDIATION LANE it lands in — the honest answer to "what happens
to this finding?". Three lanes, defined by who does the work and whether a human ever has to:

  "auto"     — a deterministic remediator clears the finding and it no longer fires on re-scan.
               No human, no model. (Word/Excel title, language, table headers, contrast, …)
  "assisted" — an AI or OCR proposer emits a *prefilled* fix a human approves with one click.
               Never silently applied — the value is a machine guess a person confirms.
               (image alt text, images-of-text OCR, language-of-parts, link-purpose, …)
  "human"    — routed to review with guidance; genuine re-authoring is required and no tool can
               responsibly guess the answer (reading level, media alternatives, PDF re-tagging).

Why this exists: the product claims Word and Excel are "100% actioned" — every in-scope finding
gets *some* action. That claim is only trustworthy if it is provable and cannot silently drift as
detectors and remediators change. `tests/test_remediation_capability.py` proves EVERY entry here
against the real remediators and detectors: each "auto" entry is triggered on a fixture, run
through `remediate_office` / `remediate_pdf` / `remediate_html`, re-scanned, and asserted to no
longer fire; each "assisted" entry is asserted to make its proposer emit a proposal; and the key
set is asserted to equal `store.RULE_FORMATS` exactly (no orphans in either direction). If a lane
here is wrong, that test goes red — so this file can never quietly overstate what the tool does.

Every lane below was DERIVED by running that round-trip, not copied from a catalog. Notably:
  * docx/xlsx clear their whole auto set on the gen_demo_fixtures corpus (the "100% actioned"
    proof). Only reading level (3.1.5) and, for docx, justified text (1.4.8), link purpose
    (2.4.4/2.4.9) and section headings (2.4.10) stay human — none has a deterministic fix.
    xlsx 3.1.2 joined them for a DIFFERENT reason worth distinguishing: not "no fix was built"
    but "the format has no element to write into". A human lane can mean either, and only the
    first is a backlog item.
  * html clears several criteria *incidentally*: darkening low-contrast text (1.4.3) also clears
    the AAA contrast finding (1.4.6); labelling a bare control (1.3.1) also clears 3.3.2 and 4.1.2.
    Those are marked "auto" because the re-scan proves they clear, not because a fixer is named
    after them.
  * pdf sets language/title/outline deterministically, and recolours failing TEXT fill colours
    in the content streams (1.4.3, clearing 1.4.6 incidentally — text-scoped, shapes untouched).
    "auto" here is a real but PARTIAL lane, and the honest-partial rule is why it still counts:
    the fixer measures each colour against the background structurally resolved behind its own
    glyphs, and abstains where structure can't answer (text over an image) or where one colour
    is painted on backgrounds that pull opposite ways. What it abstains on stays a finding and
    routes to a human — it is never recoloured on an assumption, which is what the earlier
    white-page model did (it turned compliant white-on-dark text into an AA failure).
    Structure (re-tagging) can't be auto-written, but an untagged PDF gets a deterministic
    heading-map proposal (font-size rank) a human confirms — assisted, like figure alt and
    reading order (which are AI proposals). 4.1.2 form-field names are the SAME honest-partial
    shape as 1.4.3: `_fix_pdf_form_fields` copies a meaningful field name (/T) into the
    accessible name (/TU), which is a mechanical restatement of data already sitting in the
    field dictionary — no model, no human, ADR-0016 safe — and the same abstention rule refuses
    a generic auto-name ("Text1", "fld_03"), which stays a finding and routes to a per-field
    review card whose approved value `apply_pdf_field_name` writes back into /TU. Note that the
    ASSESSMENT axis deliberately does NOT follow this lane to 🟢: the detector reads AcroForm
    fields and nothing else, never the tagged-structure components 4.1.2 also covers, so the
    cell is overridden to 🟡 review below. pdf 2.4.4 is the counter-example that fixes the
    rule's edge: a descriptive label IS derivable from the link target, but no PDF write-back
    can put it in the file, and a proposal nobody can honour is not an assisted lane. It is
    "human" — assessed, explained, re-authored by a person (see remediate_pdf.py).

Reconciliation with the earlier sparse version
----------------------------------------------
A parallel implementation (branch claude/infallible-wright-7f1a6a) modelled the same idea as a
SPARSE table — only auto/assisted listed, absent == human — with helpers mode_for/auto_scs/
as_dict and a frontend mirror (frontend/src/capability.js). This module is the reconciled
successor: same helper API (mode_for/auto_scs/as_dict/FORMATS, below, so its route + frontend keep
working unchanged), but a DENSE table proven by round-trip rather than by scanning remediator
source. The dense form is a strict superset — every key the sparse version had, plus the explicit
"human" entries — so those helpers behave identically for existing callers.

Two lane calls are CORRECTED here because the round-trip proof contradicts the sparse version's
conservative guesses (both verified live against the built .NET engine — see the contract test):
  * docx 3.1.1 — sparse said "human (engine-blocked: the dc:language write doesn't satisfy the
    docx language rule)". FALSE: writing docProps/core.xml dc:language DOES clear docx 3.1.1 on
    re-scan. It is "auto". (Independently corroborated by the docx-311-already-fixed note.)
  * pptx 1.4.3 / 1.4.6 — sparse said "human (recolour present but not engine-round-trip
    verified)". It now IS verified: _remediate_pptx_slides' recolour clears both on re-scan, so
    they are "auto".
  * html 1.1.1 — sparse said "assisted". Corrected to "human": the office/pdf alt proposers
    OCR/vision the EMBEDDED image bytes, but an HTML <img> only references an external file the
    remediator never fetches, so no proposer emits a prefilled value — it is routed to review.
    (Office/pptx/xlsx/pdf 1.1.1 stay "assisted", where a proposer does back it.)
Frontend follow-up (a different session owns frontend/, untouched here): frontend/src/capability.js
and tests/test_capability_frontend_sync.py on the other branch encode the old values and must be
re-synced to this table at merge; the recommendation-policy layer there (REVIEW_RECOMMENDED_SC for
contrast) is orthogonal to these lanes and can stay.
"""
from __future__ import annotations

# ── Two axes (ADR 0023) ───────────────────────────────────────────────────────
# Every (format × criterion) pair answers TWO independent questions in customer-outcome
# language. This module authors the REMEDIATION axis directly (round-trip proven) and
# DERIVES the ASSESSMENT axis from it, so the two can never silently disagree.
#
#   Assessment — "Can ACP determine compliance?"
#       "auto"    🟢 ACP certifies PASS *and* FAIL from a deterministic/computable fact.
#       "review"  🟡 ACP can't certify a pass but detects evidence of a likely issue;
#                    it escalates with that evidence for a human to confirm.
#       "human"   🔴 ACP can't collect evidence at all (author intent / runtime behaviour).
#
#   Remediation — "If it fails, how is the fix produced?" (only relevant on FAIL)
#       "auto"     ⚡ deterministic fix, re-scan verified.
#       "assisted" 🤖 AI/OCR proposes a fix a human approves.
#       "human"    👤 genuine re-authoring; no tool can responsibly guess.

# Remediation lanes (the authored axis — unchanged vocabulary; frontend + round-trip proofs
# consume it verbatim).
AUTO = "auto"
ASSISTED = "assisted"
HUMAN = "human"
LANES = frozenset({AUTO, ASSISTED, HUMAN})

# Assessment lanes (the derived axis).
A_AUTO = "auto"
A_REVIEW = "review"
A_HUMAN = "human"
ASSESSMENT_LANES = frozenset({A_AUTO, A_REVIEW, A_HUMAN})

# format → { "X.Y.Z" WCAG SC : remediation lane }. Keyed identically to store.RULE_FORMATS'
# in-scope pairs; the contract test asserts this correspondence is exact. This is the AUTHORED,
# round-trip-proven table — the assessment axis is derived from it below.
REMEDIATION: dict[str, dict[str, str]] = {
    # Word — every in-scope criterion is actioned; only genuinely subjective/re-authoring
    # criteria stay human. auto set verified live on gen_demo_fixtures word-accessibility-demo.
    "docx": {
        "1.1.1": ASSISTED,   # image alt — vision proposal / human alt, never a silent guess
        "1.3.1": AUTO,       # pseudo-heading promotion, table header rows, single H1
        "1.3.2": ASSISTED,   # floating-text reading order → per-box "move it inline here" proposal (propose_reading_order)
        "1.3.3": ASSISTED,   # sensory rewrite (local text model)
        # Colour used as the sole carrier of meaning, and a shape outline too faint against its
        # own fill. Both detect today; both are HUMAN, not assisted, and that distinction is the
        # point: an assisted lane emits a PREFILLED value a reviewer confirms, and neither of
        # these has a value to prefill. The replacement for a colour-only cue is an editorial
        # choice about how the document communicates; recolouring an outline changes its visual
        # design. A tool guessing either would overwrite the author's intent with its own, and
        # the re-scan could not tell it had gone wrong — the finding would clear either way.
        #
        # What the lane DOES carry is the measurement, so a reviewer never repeats it: the 1.4.11
        # finding states the ratio it measured and the 3:1 it needed; the 1.4.1 finding states
        # how many links had their underline removed. Guidance with the numbers already in it is
        # the ceiling for both, and it is a real lane rather than an absence.
        "1.4.1": ASSISTED,   # restore the removed underline — exact card, human elects it
        "1.4.3": AUTO,       # low-contrast run recolour
        "1.4.5": ASSISTED,   # images-of-text — OCR the text back out for a human to paste
        "1.4.8": ASSISTED,   # justified text — exact one-click left-align card, human elects
        "1.4.9": ASSISTED,   # images-of-text (AAA, no exception) — same OCR proposer as 1.4.5
        "1.4.11": ASSISTED,  # the shade that reaches 3:1, measured — exact card, human elects
        # HUMAN, and unlike 1.4.1 and 1.4.11 above this one is not a conservative call that a
        # later proposer will overturn. Those two looked unprefillable and turned out to have an
        # exact remedy hiding in the detected SIGNAL — restore the underline, use this shade.
        # 2.1.2 has no such signal. Whether keyboard focus can move away from a control is
        # runtime behaviour, so ACP cannot know a trap exists, cannot name which control traps,
        # and cannot verify a fix if one were written. Anything prefilled here would be a guess
        # that the re-scan could not check.
        #
        # The lane is still worth having rather than an absence: the finding names every
        # interactive control in the document, so a reviewer knows exactly where to press Tab
        # instead of reading forty pages looking for something to try.
        "2.1.2": HUMAN,      # keyboard trap — runtime behaviour, not in the file
        "2.4.2": AUTO,       # document title (docProps/core.xml)
        "2.4.4": ASSISTED,   # link purpose — derived/AI-drafted link-text proposal (propose_link_texts)
        "2.4.6": AUTO,       # heading-skip closure after the 1.3.1 outline fix
        "2.4.9": ASSISTED,   # reused link text — same link-text proposer, per destination
        "2.4.10": ASSISTED,  # AI names the document's own sections; a human approves placement
        "3.1.1": AUTO,       # document language (docProps/core.xml)
        "3.1.2": ASSISTED,   # language-of-parts (langdetect proposal)
        "3.1.5": ASSISTED,      # reading level — re-writing prose
        "3.3.2": AUTO,       # form-field labels from adjacent text
        "4.1.2": AUTO,       # content-control accessible name — the SAME w:alias write that
                             # clears 3.3.2 above, borrowed deterministically from adjacent
                             # visible text by form_labels.adjacent_label. No model, no
                             # approval, and the real detector goes silent on the re-scan
                             # (measured, not assumed — tests/test_docx_412_auto_lane.py).
                             #
                             # This was ASSISTED, which understated a lane that already
                             # existed: the fixer ran, but was gated on 3.3.2's scope alone
                             # and credited only to 3.3.2, so 4.1.2 looked like it needed a
                             # human when the bytes had already been fixed.
                             #
                             # Honest-partial in exactly pdf 4.1.2's shape, and it earns the
                             # ⚡ the same way: a field with NO adjacent text to borrow is
                             # never named by guesswork — it stays a finding and routes to
                             # the per-field review card apply_field_name writes back on
                             # approval, the docx twin of refusing a generic /T. Note the
                             # ASSESSMENT axis deliberately does not follow to 🟢; the
                             # override below keeps it 🟡 because the detector reads content
                             # controls and nothing else.
    },
    # Excel — every structural/visual finding is actioned. Two human lanes, both because the
    # FORMAT cannot carry the answer rather than because nothing was built: reading level
    # (3.1.5, prose a person must rewrite) and language-of-parts (3.1.2, which SpreadsheetML
    # has no element to record). This comment used to read "fully actioned bar reading level",
    # which was true of the build and false of the format.
    "xlsx": {
        "1.1.1": ASSISTED,
        "1.3.1": AUTO,       # defined-table headerRowCount → 1
        "1.3.2": AUTO,       # hidden rows/columns holding data un-hidden
        "1.3.3": ASSISTED,
        "1.4.3": AUTO,       # low-contrast font clone to reach the AA luma-diff
        "1.4.5": ASSISTED,
        "1.4.6": AUTO,       # same contrast fix reaches the AAA threshold
        "1.4.9": ASSISTED,
        "2.4.2": AUTO,
        "2.4.4": ASSISTED,   # vague cell-hyperlink text → descriptive link-text proposal (propose_link_texts, xlsx)
        "2.4.6": ASSISTED,   # default sheet tabs / table columns → AI-named label proposal (propose_xlsx_labels)
        "3.1.1": AUTO,
        "3.1.2": HUMAN,      # language-of-parts — EXPLAIN-ONLY, and permanently so. The
                             # langdetect proposer is format-agnostic and does emit here, which
                             # is why this read ASSISTED; but SpreadsheetML has NOWHERE to put
                             # the answer. CT_RPrElt, the rich-text run properties element, has
                             # no language child — verified against the schema, not inferred —
                             # and neither does CT_Font at the cell level. So an approval could
                             # never be honoured, `apply_text_values` refuses xlsx for this mode
                             # outright, and a proposal nobody can write is not an assisted lane.
                             # Exactly the pdf 2.4.4 shape above: assessed, explained, and
                             # re-authored by a person. Document-level language (3.1.1) is
                             # unaffected — docProps/core.xml holds that one and stays AUTO.
        "3.1.5": ASSISTED,
    },
    # PowerPoint — slide-level deterministic fixes (title, contrast, reading order, language);
    # tables/keyboard/link/heading criteria have no pptx remediator, so they are human.
    "pptx": {
        "1.1.1": ASSISTED,
        "1.3.1": AUTO,       # multi-row tables get firstRow="1" (_pptx_mark_table_headers) — round-trip proven
        "1.4.2": ASSISTED,   # auto-starting audio — exact play-on-click card, human elects
        "1.3.2": AUTO,       # shapes reordered to visual top-to-bottom reading order
        "1.3.3": ASSISTED,
        "1.4.3": AUTO,       # low-contrast run recolour
        "1.4.5": ASSISTED,
        "1.4.6": AUTO,       # same recolour reaches the AAA threshold
        "1.4.9": ASSISTED,
        # 2.1.1 Keyboard is the ONE remaining human-only document lane, and it is correctly so —
        # not a coverage gap. A .pptx is a static document with no interactive/keyboard model to
        # remediate; keyboard operability is a property of the runtime that PRESENTS it (the slide
        # viewer / any embedded control), not of the file. There is nothing in the OOXML a
        # remediator could safely rewrite to make it "keyboard operable", so we detect and route
        # to a human rather than fabricate a fix (ADR 0016). docx/xlsx/pdf carry zero human-only
        # lanes; this is the single, intentional exception.
        "2.1.1": HUMAN,
        "2.4.2": AUTO,       # missing slide/document title
        "2.4.4": ASSISTED,   # link purpose — same link-text proposer as docx (a:hlinkClick)
        "2.4.6": ASSISTED,   # empty title placeholder — AI names the slide from its own content
        "2.4.9": ASSISTED,   # reused link text — link-text proposer, per destination
        "3.1.1": AUTO,       # presentation language (docProps/core.xml)
        "3.1.2": ASSISTED,
        "3.1.5": ASSISTED,
    },
    # PDF — only language/title/outline are safe to set deterministically. Contrast and structure
    # (re-tagging) need re-authoring; figure alt and reading order are AI proposals.
    "pdf": {
        "1.1.1": ASSISTED,   # tagged-figure alt — vision proposal
        "1.3.1": ASSISTED,   # tag structure — deterministic heading-map proposal, human confirms
        "1.3.2": ASSISTED,   # reading order — vision proposal for an untagged/scanned PDF
        "1.3.3": ASSISTED,
        "1.4.3": AUTO,       # text fill colours recoloured in content streams vs the resolved
                             # background (text-scoped; abstains where it can't resolve one)
        "1.4.5": ASSISTED,
        "1.4.6": AUTO,       # cleared incidentally by the 1.4.3 recolour (it targets 7:1 first)
        "1.4.9": ASSISTED,
        "2.4.1": AUTO,       # bookmark outline built from the document's headings
        "2.4.2": AUTO,       # /Title + ViewerPreferences DisplayDocTitle
        "2.4.4": HUMAN,      # raw-URL link text — EXPLAIN-ONLY. A label derived from the target
                             # is easy; writing it is not (the text-showing operators re-flow),
                             # and there is no PDF link write-back, so an approval could never
                             # be honoured. Assessed and routed to a human, never proposed.
        "2.4.6": ASSISTED,   # tagged PDF, no headings — heading map derived from the font hierarchy, human confirms
        "3.1.1": AUTO,       # catalog /Lang
        "3.1.2": ASSISTED,
        "3.1.5": ASSISTED,
        "4.1.2": AUTO,       # AcroForm accessible names — /TU copied from a meaningful /T by
                             # _fix_pdf_form_fields (mechanical, no model). Honest-partial like
                             # 1.4.3: a generic /T is refused, stays a finding, and routes to a
                             # review card that apply_pdf_field_name writes back on approval.
    },
    # HTML — the server-side remediator auto-fixes the broad structural/visual set (several
    # criteria clear incidentally, see module docstring). Media, target size, and non-text
    # contrast have no auto fix; alt text and reading-level are human; link-purpose, sensory,
    # and language-of-parts are proposals.
    "html": {
        "1.1.1": HUMAN,      # <img> alt — external image bytes, no OCR/vision proposer for HTML
        "1.2.1": HUMAN,      # audio transcript
        "1.2.2": HUMAN,      # video captions
        "1.2.3": HUMAN,      # video audio description
        "1.3.1": AUTO,       # unlabeled control → aria-label
        "1.3.2": HUMAN,      # CSS visual-reorder detected; the fix is a layout/source-order edit
        "1.3.3": ASSISTED,   # sensory rewrite (format-agnostic text proposer)
        "1.3.4": AUTO,       # orientation lock removed + responsive viewport
        "1.3.5": AUTO,       # input purpose → autocomplete
        "1.4.1": AUTO,       # colour-only link → underline
        "1.4.2": AUTO,       # autoplay removed
        "1.4.3": AUTO,       # low-contrast inline colour darkened
        "1.4.4": AUTO,       # zoom-blocking viewport restored
        "1.4.5": HUMAN,      # image-of-text detected; replacing it with real text is a human edit
        "1.4.6": AUTO,       # cleared incidentally by the 1.4.3 darken
        "1.4.10": AUTO,      # responsive viewport for reflow
        "1.4.11": HUMAN,     # non-text (border) contrast — no auto fix
        "1.4.12": AUTO,      # fixed line-height relaxed
        "2.4.1": AUTO,       # skip link + main landmark
        "2.4.2": AUTO,       # page title from <h1>
        "2.4.3": AUTO,       # positive tabindex reset
        "2.4.4": ASSISTED,   # vague link text → derived/AI-drafted proposal
        "2.4.6": AUTO,       # skipped heading level renumbered
        "2.4.7": AUTO,       # focus outline restored
        "2.4.9": HUMAN,      # link purpose (link only)
        "2.5.3": AUTO,       # accessible name aligned to visible label
        "2.5.8": HUMAN,      # target size — a layout decision
        "3.1.1": AUTO,       # <html lang>
        "3.1.2": ASSISTED,   # language-of-parts
        "3.1.4": AUTO,       # abbreviation expansion
        "3.1.5": ASSISTED,      # reading level
        "3.3.2": AUTO,       # cleared incidentally by the 1.3.1 labelling
        "4.1.2": AUTO,       # cleared incidentally by the 1.3.1 labelling
    },
}


# Stable format order for the API/UI. Matches store.RULE_FORMATS' formats.
FORMATS: tuple[str, ...] = ("html", "docx", "pptx", "xlsx", "pdf")


# ── Assessment axis, derived from remediation + audited overrides (ADR 0023) ───
# The honest rule: a criterion is 🟢 auto-assess when ACP can certify a PASS, not merely detect
# a FAIL. A deterministic remediator that clears the finding on re-scan proves that — so
# remediation "auto" ⟹ assessment "auto" (one direction) — but ONLY when the detector's coverage
# is the whole criterion. Where a deterministic remediator clears the one narrow signal its own
# detector emits, "clean on re-scan" proves that signal is absent, not that the criterion is met;
# the loop closes over a subset and the ⟹ over-claims. docx 2.4.6 below is exactly that case, and
# any new AUTO cell must be checked against it. The DEFAULT for a non-auto criterion
# is 🟡 review (ACP flags a likely issue for a human to confirm), because "not auto-fixable"
# strongly correlates with "not deterministically certifiable" (the fix would be deterministic
# if the check were). The reclassification audit (task #174, docs/adr/0023-reclassification-audit.md)
# round-trip-verified every non-auto cell against its detector and CONFIRMED the default for all
# but the exceptions below.
#
# ASSESSMENT_OVERRIDES carries those audited exceptions — in BOTH directions, because the two
# axes are genuinely independent:
#   • 🔴 human — ACP can't collect evidence (keyboard operability of a static deck: a runtime
#     property, not a file property; ADR 0016 — route to a human, never fabricate an assessment).
#   • 🟢 auto — deterministically ASSESSABLE even though the fix is not auto. docx 1.4.8 justified
#     text is an explicit `<w:jc w:val="both">` attribute (present = fail, absent = certifiable
#     pass), but the fix is an opt-in left-align a human elects (🤖), not a silent auto-fix. This
#     is the proof the axes don't collapse: 🟢 assess does NOT require ⚡ remediate.
#   • 🟡 review — auto-REMEDIABLE but not certifiable, the reverse exception. docx 2.4.6 is the
#     case: ⚡ auto is correct on the remediation axis (the heading-skip closure is deterministic
#     and round-trip proven), but the derivation must not read that as a certified pass.
# Control-gated 🟡 criteria (2.1.2/4.1.2 with no controls) are NOT listed here FOR THAT REASON —
# they resolve per-file to a grey ⚪ N/A when their detector finds nothing (a per-document
# outcome, not a lane). docx 4.1.2 does appear below, on unrelated grounds: its remediation lane
# is ⚡, so the derivation would otherwise make it certifiable. Being control-gated is why a cell
# may be absent from this list; it is not a bar to being present for a different reason.
ASSESSMENT_OVERRIDES: dict[tuple[str, str], str] = {
    ("pptx", "2.1.1"): A_HUMAN,   # keyboard operability of a static deck — nothing to assess
    ("docx", "1.4.8"): A_AUTO,    # justified-text detection is deterministic; fix is opt-in (🤖)
    # 2.4.6 asks whether a heading DESCRIBES its topic or purpose. The only docx detector,
    # office_structure.DOCX_HEADING_SKIP, decides a much narrower fact: whether heading LEVELS
    # step by one. A document can hold a flawless H1→H2→H3 outline whose headings read "Section
    # 1" / "Untitled" / "asdf" and scan clean — the derivation then certified a green PASS on
    # evidence that never bore on the criterion. Whether a heading describes its section is a
    # judgment no OOXML property settles, so 🟡 review is the honest ceiling here, matching
    # pdf/pptx/xlsx (all already review). The ⚡ auto REMEDIATION lane is untouched and correct.
    ("docx", "2.4.6"): A_REVIEW,  # level well-formedness ≠ descriptive headings — can't certify
    # html 2.4.6 is the same defect in the same shape, one detector over: scanner.HTML_HEADING_SKIP
    # judges heading LEVELS (h1 → h3), remediate._fix_heading_skip clamps every gap, and the clean
    # re-scan was read as certifying the criterion. A page whose outline is a perfect h1→h2→h3 but
    # whose headings read "Section 1" / "Untitled" / "asdf" scanned clean and resolved PASS; so did
    # a page starting at h3 with no h1 or h2, since the `prev_level > 0` guard never judges the
    # first heading. Nothing in the loop bears on whether a heading describes its topic, which is
    # what 2.4.6 asks — and no HTML property settles that. All five formats are now 🟡 review. The
    # ⚡ auto REMEDIATION lane is untouched and correct: the heading-skip closure is deterministic.
    ("html", "2.4.6"): A_REVIEW,  # level well-formedness ≠ descriptive headings — can't certify
    # pdf 4.1.2 is the ⚡-but-not-🟢 case in its purest form, and the reason the ⟹ carries the
    # "only when the detector covers the whole criterion" caveat above. The remediation lane is
    # genuinely ⚡ (a /TU copied from a meaningful /T is deterministic and re-scan proven), but
    # formats/pdf/detectors/name_role_value.py walks AcroForm terminal fields ONLY. The other
    # population 4.1.2 covers on a PDF — components expressed through the tagged-structure tree —
    # needs a /StructTreeRoot walker this codebase does not have, so a clean re-scan proves the
    # form fields are named, not that the criterion is met. The registry says the same thing on
    # its own axis (coverage=PARTIAL) and store._rule_outcome already resolves a clean PDF scan
    # to REVIEW; this override is what keeps the two from disagreeing. When a tag-tree detector
    # lands and coverage moves to FULL, delete this line.
    ("pdf", "4.1.2"): A_REVIEW,   # AcroForm-only detector — can't certify the whole criterion
    # docx 4.1.2 is the same shape and needed the same brake THE MOMENT its remediation lane
    # moved to ⚡. _assessment() derives 🟢 from AUTO, so flipping the lane without this line
    # would have silently started certifying the criterion — the false-PASS direction, and the
    # one ADR 0016 exists to prevent. The lane flip is sound (w:alias is written deterministically
    # and the detector goes silent), but a clean re-scan proves the CONTENT CONTROLS are named,
    # not that 4.1.2 is met: formats/docx/detectors/name_role_value.py reads w:sdt and nothing
    # else, and stays silent on ActiveX controls and embedded OLE objects whose name and role
    # live in code no static read can see. office_structure.office_control_review_checks keeps
    # emitting the REVIEW advisory for exactly those kinds, which is the other half of this.
    # The registry already says coverage=PARTIAL on its own axis; this keeps the two agreeing.
    # When a detector for opaque controls lands and coverage moves to FULL, delete this line.
    ("docx", "4.1.2"): A_REVIEW,  # content-control-only detector — can't certify the criterion
}


def _assessment(fmt: str, sc: str, remediation: str) -> str:
    """Assessment lane for a (format, sc) given its remediation lane. auto-remediation proves
    deterministic assessability (🟢); the audited override list carries both-direction exceptions
    (🔴 unassessable, 🟢 assessable-but-non-auto-fix); the honest default is 🟡 review."""
    override = ASSESSMENT_OVERRIDES.get((fmt, sc))
    if override is not None:
        return override
    return A_AUTO if remediation == AUTO else A_REVIEW


# The authoritative two-axis table, derived once at import. CAPABILITY[fmt][sc] =
# {"assessment": ..., "remediation": ...}. REMEDIATION stays the single source for the
# remediation axis (frontend + round-trip proofs read it verbatim via the projections below).
CAPABILITY: dict[str, dict[str, dict[str, str]]] = {
    fmt: {sc: {"assessment": _assessment(fmt, sc, rem), "remediation": rem}
          for sc, rem in table.items()}
    for fmt, table in REMEDIATION.items()
}


def remediation_table() -> dict[str, dict[str, str]]:
    """Single-value remediation projection {fmt: {sc: lane}} — the shape the frontend
    CAPABILITY_FALLBACK mirrors and the round-trip contract test proves."""
    return {fmt: dict(scs) for fmt, scs in REMEDIATION.items()}


def assessment_table() -> dict[str, dict[str, str]]:
    """Single-value assessment projection {fmt: {sc: 🟢/🟡/🔴 lane}}."""
    return {fmt: {sc: cell["assessment"] for sc, cell in scs.items()}
            for fmt, scs in CAPABILITY.items()}


def lane(fmt: str, sc: str) -> str | None:
    """The remediation lane for a (format, WCAG SC) pair, or None if the criterion is not
    in scope for that format. `sc` is a bare 'X.Y.Z' number."""
    return REMEDIATION.get(fmt, {}).get(sc)


def assessment_lane(fmt: str, sc: str) -> str | None:
    """The assessment lane (🟢 auto / 🟡 review / 🔴 human) for a pair, or None if out of scope."""
    cell = CAPABILITY.get(fmt, {}).get(sc)
    return cell["assessment"] if cell else None


# ── compatibility surface with the earlier sparse version (see module docstring) ──
# These let the /capability route and the frontend mirror consume the REMEDIATION axis
# unchanged. An out-of-scope pair still defaults to "human" — identical to the sparse version.
def mode_for(fmt: str | None, sc: str | None) -> str:
    """The remediation mode for one (format, criterion). Unknown/out-of-scope -> "human"."""
    return REMEDIATION.get(fmt or "", {}).get(sc or "", HUMAN)


def auto_scs(fmt: str | None) -> set[str]:
    """The set of SCs deterministically auto-fixable for this format."""
    return {sc for sc, ln in REMEDIATION.get(fmt or "", {}).items() if ln == AUTO}


def as_dict() -> dict[str, dict[str, str]]:
    """A JSON-serialisable deep copy of the remediation table (back-compat: this always
    returned the single-value remediation projection)."""
    return remediation_table()
