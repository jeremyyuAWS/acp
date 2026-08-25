"""PDF format package — capability declarations and the (rule × format) registrations.

Everything this package knows about PDF accessibility is declared here, in one readable block.
Adding a criterion to PDF is a `register()` call plus a detector module; it is not an edit to
a shared dispatch table, a scope frozenset, and a catalog JSON that must be kept in agreement.
"""
from __future__ import annotations

from assessment import Confidence, Coverage
from capabilities import Capability
from rule_registry import register

from formats.pdf.detectors import (focus_order, input_purpose, label_in_name, link_purpose,
                                   name_role_value, nontext_contrast, text_spacing, use_of_color)

# ── 4.1.2 Name, Role, Value ───────────────────────────────────────────────────────────
# PARTIAL, not FULL: sound over AcroForm fields, silent on tagged-structure components.
# PARTIAL, not HEURISTIC: within that subset the technique is exact — /TU, /FT and /V are
# read straight from the field dictionary, so there is no guessing and no false-positive class.
# HIGH confidence follows from that exactness; it is not a claim about breadth.
register(
    rule="4.1.2",
    fmt="pdf",
    detector=name_role_value.detect,
    requires={Capability.FORMS},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=("interactive AcroForm fields are checked exactly (/TU name, /FT role, /V value); "
            "components expressed through the tagged-structure tree are not examined"),
)

# ── 2.4.3 Focus Order ─────────────────────────────────────────────────────────────────
# PARTIAL (upgraded from HEURISTIC): when both an AcroForm and a /StructTreeRoot are present,
# widget annotations are collected in both field-tree order (= tab order) and OBJR structure
# order (= reading order) and compared directly. Any inversion in the matched set is a finding.
# This is exact within the matched set — not a proxy — hence PARTIAL rather than HEURISTIC.
# Remaining limitations: /R (row) and /C (column) /Tabs layouts are legitimate for some forms
# and cannot be distinguished from /S errors statically; non-widget interactive elements and
# untagged PDFs (no StructTreeRoot) fall back to the legacy /Tabs = /S heuristic check.
# MEDIUM confidence is kept: the fallback heuristic still runs for untagged documents, so the
# overall detection is not uniformly sound. The structure-tree comparison path alone would be
# HIGH, but paired with the fallback the blended estimate is MEDIUM.
register(
    rule="2.4.3",
    fmt="pdf",
    detector=focus_order.detect,
    requires={Capability.FORMS},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.MEDIUM,
    reason=("when /StructTreeRoot is present, widget object-number lists from the AcroForm field "
            "tree and the structure-tree OBJR references are compared directly — any inversion "
            "is a finding; untagged PDFs without a structure tree fall back to checking that "
            "pages with widgets declare /Tabs = /S"),
)

# ── 1.3.5 Identify Input Purpose ─────────────────────────────────────────────────────
# HEURISTIC: PDF AcroForm fields carry /T (partial name) and /TU (tooltip) but no autocomplete-
# equivalent attribute — the PDF specification defines no mechanism to declare input purpose in
# the sense WCAG 1.3.5 requires. The detector pattern-matches /T and /TU against the WCAG
# personal-data vocabulary (name, email, phone, address, birth date, etc.) and flags fields that
# appear to collect personal user information. Within the matched set the finding is sound
# (the format genuinely cannot declare purpose), but the vocabulary match is approximate —
# false positives and false negatives are both possible — so coverage stays HEURISTIC.
# LOW confidence: the heuristic fires on field-name similarity alone; it cannot rule out that
# a matched field is organisational (a company address) rather than personal.
register(
    rule="1.3.5",
    fmt="pdf",
    detector=input_purpose.detect,
    requires={Capability.FORMS},
    coverage=Coverage.HEURISTIC,
    confidence=Confidence.LOW,
    reason=("AcroForm fields whose /T name or /TU tooltip matches the WCAG personal-data "
            "vocabulary (name, email, phone, address, etc.) are flagged — PDF provides no "
            "autocomplete-equivalent mechanism, so those fields cannot declare input purpose "
            "programmatically; the vocabulary match is approximate and some organisational "
            "forms will produce false positives"),
)

# ── 1.4.1 Use of Color ────────────────────────────────────────────────────────────────
# Hyperlinks whose only distinguishing cue from surrounding text is colour — no underline or
# other non-colour marker is present. PARTIAL: the detector reads annotation link objects and
# inline link text for underline presence; other ways colour can be the sole carrier of meaning
# in a PDF (colour-keyed legends, status indicators, chart series) are outside scope. HIGH
# confidence within that: the underline check is a direct structural read of each link object.
# No write-back exists for PDF link styling, so the remediation lane is human.
register(
    rule="1.4.1",
    fmt="pdf",
    detector=use_of_color.detect,
    requires={Capability.LINKS},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=("annotation links and inline link text are checked for the presence of an underline "
            "or other non-colour distinguishing cue; colour used as the sole carrier of meaning "
            "elsewhere — colour-keyed legends, chart series, status indicators — is not examined"),
)

# ── 1.4.11 Non-text Contrast ──────────────────────────────────────────────────────────
# Non-text elements (shapes, borders) whose contrast ratio against their background falls below
# 3:1. PARTIAL: the detector samples solid-colour fills on a capped number of pages and measures
# the ratio using the WCAG formula; gradient fills, bitmap images, and most icon glyphs are
# outside scope. MEDIUM confidence: the measurement is exact within scope, but whether a low-
# contrast element conveys meaning or is decorative is a judgement not made by the detector.
register(
    rule="1.4.11",
    fmt="pdf",
    detector=nontext_contrast.detect,
    requires={Capability.COLOR},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.MEDIUM,
    reason=("solid-colour non-text elements are measured with the WCAG contrast formula on sampled "
            "pages; gradient fills, bitmap images and most icon glyphs are not examined, and "
            "whether a low-contrast element conveys meaning is left to a human"),
)

# ── 2.4.4 Link Purpose (In Context) ──────────────────────────────────────────────────
# PARTIAL, not FULL: two complementary checks run (P-21):
#   (a) raw-URL label — the annotation's /URI appears verbatim in the page text.
#   (b) vague-phrase label — text cropped from the annotation bounding box matches the same
#       _VAGUE_LINK_TEXT predicate used for docx/pptx/xlsx ("click here", "here", etc.).
# What cannot be checked is whether otherwise-descriptive text actually names the correct
# destination — "Annual Report" pointing at the wrong year passes both checks. So a clean
# scan means no raw-URL or generic-phrase label was found, not that every link is meaningful.
# Both checks are exact (no heuristic), so confidence remains HIGH.
register(
    rule="2.4.4",
    fmt="pdf",
    detector=link_purpose.detect,
    requires={Capability.LINKS},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=("raw-URL labels (URI appears verbatim in page text) and generic filler phrases "
            "('click here', 'here', etc. — cropped from the annotation bounding box) are both "
            "detected; whether otherwise-descriptive text names the correct destination is a "
            "content judgement not examinable from the file"),
)

# ── 1.4.12 Text Spacing ───────────────────────────────────────────────────────────────
# Pages whose line pitch is tight enough that the WCAG 1.4.12 line-height override (1.5× the
# font size) would clip text. The pitch is measured from page content streams; whether clipping
# actually occurs at the override setting is a rendered outcome not recorded in the file. PARTIAL
# because only sampled pages are examined; HIGH confidence within scope because the pitch is a
# direct measurement, not an estimate.
register(
    rule="1.4.12",
    fmt="pdf",
    detector=text_spacing.detect,
    requires={Capability.FONTS},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=("line pitch is measured from page content streams and compared to the 1.5× font-size "
            "threshold; whether text actually clips when the override is applied is a rendered "
            "outcome not recorded in the file, and only sampled pages are examined"),
)

# ── 2.5.3 Label in Name ───────────────────────────────────────────────────────────────
# PARTIAL (not FULL): push buttons are the only AcroForm field type that carries both its
# visible text label (/MK /CA caption) and its accessible name (/TU, or /T as fallback) in the
# same field object. For every other field type (text, checkbox, radio) the visible label is a
# separate text object drawn on the page and not programmatically linked to the field — so a
# comparison requires rendering and is outside scope. HIGH confidence within the push-button
# subset: the caption-in-name check is a direct string comparison, not an estimate.
register(
    rule="2.5.3",
    fmt="pdf",
    detector=label_in_name.detect,
    requires={Capability.FORMS},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=("push buttons are checked for WCAG 2.5.3: the visible caption (/MK /CA) must appear "
            "inside the accessible name (/TU, or /T when /TU is absent); other field types "
            "(text, checkbox, radio) display their labels as separate text objects not linked to "
            "the field object and cannot be compared without rendering"),
)
