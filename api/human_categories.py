"""The human-task view of the WCAG criteria — one source of truth.

A business analyst, paralegal, or ops person doing remediation does not think "is 1.3.1
compliant?" They think "what do I fix in Word?" This module is the single mapping from a
success criterion to the way a human actually encounters it: a plain category they can find
in their document (Images, Tables, Reading Order…) and a one-line human name for the problem.

It is deliberately the ONLY place this mapping lives. The certification report and the review
inbox both read from here, so a rename happens once and can never drift between the two — the
exact entropy that let `plain` names diverge between store.py and the frontend. The WCAG id
stays on every entry as metadata: an auditor doing a VPAT still wants "1.1.1 / PDF-UA 7.18",
so the standard is demoted to a technical detail, never deleted.

CATEGORY, not criterion, is the organizing idea — it mirrors how Microsoft Word's own
Accessibility Checker groups work, so "fix the Images section" means the same thing in our UI
and in the tool the reviewer verifies with.

Verify-in-Office paths (where to click to confirm a fix) are intentionally NOT here yet: the
exact Microsoft 365 menu strings differ Windows/Mac and must be checked against current docs
before they appear in a customer-facing certification report. They land in a follow-up, keyed
by category, without touching this mapping.
"""

# The human-facing buckets, in the order a report or inbox should present them: the things a
# reviewer fixes most often and most easily first, the rare/web-only ones last. `icon` is a
# plain emoji so a category reads at a glance without a design system.
CATEGORIES: dict[str, dict] = {
    "images":        {"label": "Images",              "icon": "🖼️", "order": 1},
    "tables":        {"label": "Tables",              "icon": "📊", "order": 2},
    "reading_order": {"label": "Reading Order",       "icon": "📖", "order": 3},
    "headings":      {"label": "Headings",            "icon": "📝", "order": 4},
    "language":      {"label": "Language",            "icon": "🌐", "order": 5},
    "hyperlinks":    {"label": "Hyperlinks",          "icon": "🔗", "order": 6},
    "contrast":      {"label": "Color & Contrast",    "icon": "🎨", "order": 7},
    "doc_props":     {"label": "Document Properties",  "icon": "📋", "order": 8},
    "forms":         {"label": "Forms",               "icon": "📄", "order": 9},
    "navigation":    {"label": "Navigation & Keyboard", "icon": "⌨️", "order": 10},
    "media":         {"label": "Audio & Video",       "icon": "🎬", "order": 11},
    "instructions":  {"label": "Instructions",        "icon": "🧭", "order": 12},
    "content":       {"label": "Readability",         "icon": "📚", "order": 13},
    "layout":        {"label": "Display & Layout",    "icon": "📐", "order": 14},
}

# SC id -> (category, human name). The human name says what a reviewer would SEE, in words they
# can act on, never the WCAG title. Every criterion in store.RULE_CATALOG must appear here; the
# contract test enforces it, so a new criterion cannot ship without a human home.
_MAP: dict[str, tuple[str, str]] = {
    "1.1.1":  ("images",        "Missing image description"),
    "1.2.1":  ("media",         "Audio or video without a transcript"),
    "1.2.2":  ("media",         "Video without captions"),
    "1.2.3":  ("media",         "Video without an audio description"),
    "1.3.1":  ("tables",        "Table headers not marked"),
    "1.3.2":  ("reading_order", "Reading order incorrect"),
    "1.3.3":  ("instructions",  "Directions depend on shape or position"),
    "1.3.4":  ("layout",        "Locked to one screen orientation"),
    "1.3.5":  ("forms",         "Form fields don't declare their purpose"),
    "1.4.1":  ("contrast",      "Meaning shown by color alone"),
    "1.4.2":  ("media",         "Media plays automatically"),
    "1.4.3":  ("contrast",      "Low text contrast"),
    "1.4.4":  ("layout",        "Text can't be enlarged"),
    "1.4.5":  ("images",        "Text embedded in an image"),
    "1.4.6":  ("contrast",      "Text below the enhanced contrast ratio"),
    "1.4.8":  ("layout",        "Body text set justified"),
    "1.4.9":  ("images",        "Text embedded in an image"),
    "1.4.10": ("layout",        "Content doesn't reflow on small screens"),
    "1.4.11": ("contrast",      "Buttons or icons with low contrast"),
    "1.4.12": ("layout",        "Text spacing can't be adjusted"),
    "2.1.1":  ("navigation",    "Can't be used with a keyboard"),
    "2.1.2":  ("navigation",    "Embedded control may trap keyboard focus"),
    "2.4.1":  ("navigation",    "No way to skip repeated navigation"),
    "2.4.2":  ("doc_props",     "Missing document title"),
    "2.4.3":  ("navigation",    "Illogical tab order"),
    "2.4.4":  ("hyperlinks",    "Link text is unclear"),
    "2.4.6":  ("headings",      "Unclear headings or labels"),
    "2.4.7":  ("navigation",    "No visible keyboard focus"),
    "2.4.9":  ("hyperlinks",    "Same link text for different destinations"),
    "2.4.10": ("headings",      "Long document has no section headings"),
    "2.5.3":  ("forms",         "Control name doesn't match its label"),
    "2.5.8":  ("layout",        "Touch targets too small"),
    "3.1.1":  ("language",      "Document language not set"),
    "3.1.2":  ("language",      "Mixed-language text not marked"),
    "3.1.4":  ("content",       "Unexplained abbreviations"),
    "3.1.5":  ("content",       "Reading level too high"),
    "3.3.2":  ("forms",         "Form fields without labels"),
    "4.1.2":  ("forms",         "Form fields missing names for assistive tech"),
}


def category_of(sc: str) -> str | None:
    """The category key for a success criterion, or None if it has no human home yet."""
    m = _MAP.get(sc)
    return m[0] if m else None


def human_name(sc: str) -> str | None:
    """The plain, act-on-it name for a criterion's problem — never the WCAG title."""
    m = _MAP.get(sc)
    return m[1] if m else None


def describe(sc: str) -> dict | None:
    """The full human view of a criterion: category (key + label + icon) and human name, with
    the WCAG id kept as the `wcag` field — demoted to metadata, present for the auditor."""
    m = _MAP.get(sc)
    if not m:
        return None
    cat_key, name = m
    cat = CATEGORIES[cat_key]
    return {"wcag": sc, "category": cat_key, "category_label": cat["label"],
            "icon": cat["icon"], "human_name": name, "order": cat["order"]}


def group_by_category(scs) -> list[dict]:
    """Roll a set of success criteria up into the human categories, in presentation order.

    Returns [{category, label, icon, criteria: [{wcag, human_name}, …]}, …] — the shape a
    report section or an inbox group renders directly. Criteria with no human mapping are
    dropped rather than shown under a wrong heading; the contract test guarantees a mapped
    criterion is never dropped for lack of an entry.
    """
    buckets: dict[str, list[dict]] = {}
    for sc in scs:
        m = _MAP.get(sc)
        if not m:
            continue
        buckets.setdefault(m[0], []).append({"wcag": sc, "human_name": m[1]})
    out = []
    for key in sorted(buckets, key=lambda k: CATEGORIES[k]["order"]):
        cat = CATEGORIES[key]
        out.append({"category": key, "label": cat["label"], "icon": cat["icon"],
                    "criteria": sorted(buckets[key], key=lambda c: c["wcag"])})
    return out
