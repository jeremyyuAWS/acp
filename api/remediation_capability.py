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
  * html clears several criteria *incidentally*: darkening low-contrast text (1.4.3) also clears
    the AAA contrast finding (1.4.6); labelling a bare control (1.3.1) also clears 3.3.2 and 4.1.2.
    Those are marked "auto" because the re-scan proves they clear, not because a fixer is named
    after them.
  * pdf can only set language/title/outline deterministically; contrast and structure (re-tagging)
    have no safe automated fix, so they are human. Figure alt and reading order are AI proposals.

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

AUTO = "auto"
ASSISTED = "assisted"
HUMAN = "human"
LANES = frozenset({AUTO, ASSISTED, HUMAN})

# format → { "X.Y.Z" WCAG SC : lane }. Keyed identically to store.RULE_FORMATS' in-scope pairs;
# the contract test asserts this correspondence is exact.
CAPABILITY: dict[str, dict[str, str]] = {
    # Word — every in-scope criterion is actioned; only genuinely subjective/re-authoring
    # criteria stay human. auto set verified live on gen_demo_fixtures word-accessibility-demo.
    "docx": {
        "1.1.1": ASSISTED,   # image alt — vision proposal / human alt, never a silent guess
        "1.3.1": AUTO,       # pseudo-heading promotion, table header rows, single H1
        "1.3.3": ASSISTED,   # sensory rewrite (local text model)
        "1.4.3": AUTO,       # low-contrast run recolour
        "1.4.5": ASSISTED,   # images-of-text — OCR the text back out for a human to paste
        "1.4.8": HUMAN,      # justified body text — no deterministic fix (does NOT clear on re-scan)
        "1.4.9": ASSISTED,   # images-of-text (AAA, no exception) — same OCR proposer as 1.4.5
        "2.4.2": AUTO,       # document title (docProps/core.xml)
        "2.4.4": HUMAN,      # link purpose — no Office link-text proposer wired; routed to review
        "2.4.6": AUTO,       # heading-skip closure after the 1.3.1 outline fix
        "2.4.9": HUMAN,      # link purpose (link only) — routed to review
        "2.4.10": HUMAN,     # section headings — an authoring decision
        "3.1.1": AUTO,       # document language (docProps/core.xml)
        "3.1.2": ASSISTED,   # language-of-parts (langdetect proposal)
        "3.1.5": HUMAN,      # reading level — re-writing prose
        "3.3.2": AUTO,       # form-field labels from adjacent text
    },
    # Excel — fully actioned bar reading level; no human lane for any structural/visual finding.
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
        "3.1.1": AUTO,
        "3.1.2": ASSISTED,
        "3.1.5": HUMAN,
    },
    # PowerPoint — slide-level deterministic fixes (title, contrast, reading order, language);
    # tables/keyboard/link/heading criteria have no pptx remediator, so they are human.
    "pptx": {
        "1.1.1": ASSISTED,
        "1.3.1": HUMAN,      # slide table structure — no pptx structural remediator
        "1.3.2": AUTO,       # shapes reordered to visual top-to-bottom reading order
        "1.3.3": ASSISTED,
        "1.4.3": AUTO,       # low-contrast run recolour
        "1.4.5": ASSISTED,
        "1.4.6": AUTO,       # same recolour reaches the AAA threshold
        "1.4.9": ASSISTED,
        "2.1.1": HUMAN,      # keyboard operability — an authoring/runtime concern
        "2.4.2": AUTO,       # missing slide/document title
        "2.4.4": HUMAN,
        "2.4.6": HUMAN,      # empty title placeholder guidance — routed to review
        "2.4.9": HUMAN,
        "3.1.1": AUTO,       # presentation language (docProps/core.xml)
        "3.1.2": ASSISTED,
        "3.1.5": HUMAN,
    },
    # PDF — only language/title/outline are safe to set deterministically. Contrast and structure
    # (re-tagging) need re-authoring; figure alt and reading order are AI proposals.
    "pdf": {
        "1.1.1": ASSISTED,   # tagged-figure alt — vision proposal
        "1.3.1": HUMAN,      # tag structure — re-tagging, no safe automated fix
        "1.3.2": ASSISTED,   # reading order — vision proposal for an untagged/scanned PDF
        "1.3.3": ASSISTED,
        "1.4.3": HUMAN,      # contrast — no PDF recolour fixer
        "1.4.5": ASSISTED,
        "1.4.6": HUMAN,
        "1.4.9": ASSISTED,
        "2.4.1": AUTO,       # bookmark outline built from the document's headings
        "2.4.2": AUTO,       # /Title + ViewerPreferences DisplayDocTitle
        "3.1.1": AUTO,       # catalog /Lang
        "3.1.2": ASSISTED,
        "3.1.5": HUMAN,
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
        "1.3.3": ASSISTED,   # sensory rewrite (format-agnostic text proposer)
        "1.3.4": AUTO,       # orientation lock removed + responsive viewport
        "1.3.5": AUTO,       # input purpose → autocomplete
        "1.4.1": AUTO,       # colour-only link → underline
        "1.4.2": AUTO,       # autoplay removed
        "1.4.3": AUTO,       # low-contrast inline colour darkened
        "1.4.4": AUTO,       # zoom-blocking viewport restored
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
        "3.1.5": HUMAN,      # reading level
        "3.3.2": AUTO,       # cleared incidentally by the 1.3.1 labelling
        "4.1.2": AUTO,       # cleared incidentally by the 1.3.1 labelling
    },
}


# Stable format order for the API/UI. Matches store.RULE_FORMATS' formats.
FORMATS: tuple[str, ...] = ("html", "docx", "pptx", "xlsx", "pdf")


def lane(fmt: str, sc: str) -> str | None:
    """The remediation lane for a (format, WCAG SC) pair, or None if the criterion is not
    in scope for that format. `sc` is a bare 'X.Y.Z' number."""
    return CAPABILITY.get(fmt, {}).get(sc)


# ── compatibility surface with the earlier sparse version (see module docstring) ──
# These let the /capability route and the frontend mirror consume this table unchanged.
# Because the table is dense, an in-scope "human" criterion is returned explicitly; an
# out-of-scope pair still defaults to "human" — identical behaviour to the sparse version.
def mode_for(fmt: str | None, sc: str | None) -> str:
    """The automation mode for one (format, criterion). Unknown/out-of-scope -> "human"."""
    return CAPABILITY.get(fmt or "", {}).get(sc or "", HUMAN)


def auto_scs(fmt: str | None) -> set[str]:
    """The set of SCs deterministically auto-fixable for this format."""
    return {sc for sc, ln in CAPABILITY.get(fmt or "", {}).items() if ln == AUTO}


def as_dict() -> dict[str, dict[str, str]]:
    """A JSON-serialisable deep copy of the table (so a caller can't mutate the module state)."""
    return {fmt: dict(scs) for fmt, scs in CAPABILITY.items()}
