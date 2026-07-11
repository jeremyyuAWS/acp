"""The capability table — the single source of truth for HOW each (document format, WCAG
criterion) is actioned, so the product's "100% actioned" claim is provable and drift-proof.

Three lanes:
  * "auto"     — a deterministic remediator clears it on re-scan, no human touch.
  * "assisted" — an AI/OCR proposer emits a prefilled value a human approves in one click
                 (NEVER auto-applied — a cleared re-scan proves the finding stopped firing,
                 not that a machine-authored value is correct).
  * "human"    — routed with guidance; re-authoring / a human decision is required.

`store.RULE_FORMATS` says WHICH formats a criterion applies to; this says HOW it's actioned.
Every in-scope (format, criterion) pair has exactly one lane here, and the contract test
(tests/test_remediation_capability.py) PROVES each lane against the real remediators — an
"auto" entry that doesn't actually clear on re-scan, or an "assisted" entry with no proposer,
fails the build. So this file cannot silently drift out of sync with what the code really does.

The docx/xlsx lanes are grounded in an observed scan→remediate→re-scan of the demo fixtures
(the SCs that cleared are "auto"; the rest are "assisted" where a proposer exists, else
"human"). pdf/pptx follow the same rule from their remediators. When unsure, a criterion is
"human" — under-claiming is safe for a compliance product; over-claiming is not.
"""
from __future__ import annotations

AUTO = "auto"
ASSISTED = "assisted"
HUMAN = "human"
LANES = frozenset({AUTO, ASSISTED, HUMAN})

# format → { WCAG SC : lane }. Keep in sync with store.RULE_FORMATS (the contract test enforces
# it both ways: no missing entry, no orphan).
CAPABILITY: dict[str, dict[str, str]] = {
    "docx": {
        "1.1.1": ASSISTED,   # image alt — vision proposal
        "1.3.1": AUTO,       # table headers + pseudo-heading promotion
        "1.3.3": ASSISTED,   # sensory rewrite proposal
        "1.4.3": AUTO,       # contrast recolor
        "1.4.5": ASSISTED,   # images-of-text OCR proposal
        "1.4.8": HUMAN,      # justified text — flagged, re-author (did not clear on re-scan)
        "1.4.9": HUMAN,      # images of text (AAA) — detect only
        "2.4.2": AUTO,       # document title
        "2.4.4": HUMAN,      # link purpose (in context)
        "2.4.6": AUTO,       # heading outline / skip
        "2.4.9": HUMAN,      # link purpose (link only)
        "2.4.10": HUMAN,     # section headings — re-author
        "3.1.1": AUTO,       # document language
        "3.1.2": ASSISTED,   # language of parts proposal
        "3.1.5": HUMAN,      # reading level — plain-language re-author
        "3.3.2": AUTO,       # form-field labels
    },
    "xlsx": {
        "1.1.1": ASSISTED,
        "1.3.1": AUTO,       # table headers
        "1.3.2": AUTO,       # hidden rows/cols with data
        "1.3.3": ASSISTED,
        "1.4.3": AUTO,       # contrast (min)
        "1.4.5": ASSISTED,
        "1.4.6": AUTO,       # contrast (enhanced)
        "1.4.9": HUMAN,
        "2.4.2": AUTO,
        "3.1.1": AUTO,
        "3.1.2": ASSISTED,
        "3.1.5": HUMAN,
    },
    "pdf": {
        "1.1.1": ASSISTED,   # tagged-figure vision alt; untagged routes to human
        "1.3.1": HUMAN,      # tagging an untagged PDF — structural, re-author
        "1.3.2": ASSISTED,   # reading-order vision proposal (untagged)
        "1.3.3": ASSISTED,
        "1.4.3": HUMAN,      # content-stream recolor is impractical — detect only
        "1.4.5": ASSISTED,
        "1.4.6": HUMAN,
        "1.4.9": HUMAN,
        "2.4.1": AUTO,       # bookmark outline built from headings
        "2.4.2": AUTO,       # title + display-doc-title
        "3.1.1": AUTO,       # /Lang
        "3.1.2": ASSISTED,
        "3.1.5": HUMAN,
    },
    "pptx": {
        "1.1.1": ASSISTED,
        "1.3.1": AUTO,       # table headers (partner engine)
        "1.3.2": AUTO,       # slide reading order
        "1.3.3": ASSISTED,
        "1.4.3": AUTO,       # contrast (min)
        "1.4.5": ASSISTED,
        "1.4.6": AUTO,       # contrast (enhanced)
        "1.4.9": HUMAN,
        "2.1.1": HUMAN,      # auto-advance / animation timing — re-author
        "2.4.2": AUTO,       # slide title
        "2.4.4": HUMAN,
        "2.4.6": AUTO,       # empty title placeholder → filled
        "2.4.9": HUMAN,
        "3.1.1": AUTO,
        "3.1.2": ASSISTED,
        "3.1.5": HUMAN,
    },
    "html": {
        # html has its own deterministic rule modules (frontend/src/rules); coarse lanes here
        # so the contract test's completeness check has an entry per in-scope criterion. html
        # remediation is validated by its own suite, not re-proved here.
        "1.1.1": ASSISTED, "1.2.1": HUMAN, "1.2.2": HUMAN, "1.2.3": HUMAN,
        "1.3.1": AUTO, "1.3.3": ASSISTED, "1.3.4": AUTO, "1.3.5": AUTO,
        "1.4.1": HUMAN, "1.4.2": AUTO, "1.4.3": AUTO, "1.4.4": AUTO, "1.4.6": AUTO,
        "1.4.10": AUTO, "1.4.11": HUMAN, "1.4.12": AUTO, "2.4.1": AUTO, "2.4.2": AUTO,
        "2.4.3": HUMAN, "2.4.4": HUMAN, "2.4.6": AUTO, "2.4.7": HUMAN, "2.4.9": HUMAN,
        "2.5.3": HUMAN, "2.5.8": AUTO, "3.1.1": AUTO, "3.1.2": ASSISTED, "3.1.4": HUMAN,
        "3.1.5": HUMAN, "3.3.2": AUTO, "4.1.2": HUMAN,
    },
}


def lane(fmt: str, sc: str) -> str | None:
    """The remediation lane for (format, criterion), or None if the criterion isn't in scope
    for that format."""
    return CAPABILITY.get(fmt, {}).get(sc)


def actioned_summary(fmt: str) -> dict[str, int]:
    """{auto, assisted, human, total} for a format — the honest breakdown behind a
    "100% actioned" statement (every in-scope criterion lands in exactly one lane)."""
    lanes = CAPABILITY.get(fmt, {})
    out = {AUTO: 0, ASSISTED: 0, HUMAN: 0}
    for v in lanes.values():
        out[v] = out.get(v, 0) + 1
    out["total"] = len(lanes)
    return out
