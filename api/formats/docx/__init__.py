"""DOCX format package — capability declarations and the (rule × format) registrations.

Everything this package knows about Word accessibility is declared here, in one readable block.
Adding a criterion to docx is a `register()` call plus a detector module; it is not an edit to a
shared dispatch table, a scope frozenset, and a catalog JSON that must be kept in agreement.
"""
from __future__ import annotations

from assessment import Confidence, Coverage
from capabilities import Capability
from rule_registry import register

from formats.docx.detectors import (language_parts, link_purpose, name_role_value,
                                    no_keyboard_trap, nontext_contrast, use_of_color)

# ── 4.1.2 Name, Role, Value ───────────────────────────────────────────────────────────
# PARTIAL, not FULL: sound over interactive content controls, silent on ActiveX, embedded OLE
# objects and anything else a Word form can hold. PARTIAL, not HEURISTIC: within that subset the
# technique is exact — w:alias is present and non-empty, or it is not, read straight from the
# control's properties. There is no guessing and no false-positive class.
#
# HIGH confidence follows from that exactness; it is not a claim about breadth. Same reasoning
# as the PDF registration next door, and deliberately the same shape: narrow but certain.
#
# WHAT THIS FIXES. docx 4.1.2 entered RULE_FORMATS in #144 when the w:alias check and its
# write-back applier landed, so a FAILING document reported FAIL correctly. But a CLEAN one fell
# through to NOT_EVALUATED — "we did not look" — for work that had in fact been done, because
# RULE_FORMATS cannot express that a detector reaches part of a criterion. That is the exact gap
# the registry was built for, and the exact wrong answer PDF 4.1.2 gave before it was migrated.
# With coverage declared, a clean file now reads REVIEW: we checked what our technique reaches,
# a human confirms the rest.
#
# It does NOT become a certified pass, and should not. Certifying 4.1.2 means asserting every
# interactive component exposes a name and a role, which no static read can claim for an
# arbitrary ActiveX or OLE control. When a detector for those lands, this coverage moves to FULL
# and clean scans start certifying — with no change to this file or to the outcome gate.
register(
    rule="4.1.2",
    fmt="docx",
    detector=name_role_value.detect,
    requires={Capability.FORMS},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=("interactive content controls are checked exactly for a Title (w:alias), the "
            "attribute Word exposes to assistive technology as the accessible name; ActiveX "
            "controls, embedded OLE objects and other form content are not examined, which "
            "would need reading each control's own implementation"),
)


# ── 1.4.1 Use of Color ────────────────────────────────────────────────────────────────
# The detector has shipped since ADR 0023 Phase 1b and its findings already reach users through
# `checks_for`. What was missing was this declaration — so a document with no colour-only link
# resolved to NOT_EVALUATED, "we did not look", for a check that had in fact run. Exactly the
# gap docx 4.1.2 had before #144, and the one the registry exists to close.
#
# PARTIAL, and the reason names the boundary precisely: one high-precision structural signal is
# read (a hyperlink whose underline is explicitly removed), and every other way a document can
# use colour as the sole carrier of meaning — a red row in a table, a green tick glyph, a chart
# keyed only by hue — is not examined. Claiming FULL here would assert we had looked at all of
# them.
#
# HIGH confidence, because within that signal the read is exact: the underline is explicitly
# removed or it is not. Narrow but certain, the same shape as the 4.1.2 registration above.
#
# It does NOT become a pass, and should not. Whether a NON-COLOUR cue also distinguishes the
# link is a human judgement about the rendered page, which no read of the XML can settle.
register(
    rule="1.4.1",
    fmt="docx",
    detector=use_of_color.detect,
    # LINKS + FONTS, deliberately not COLOR. Capabilities are about the SUBSTRATE the rule gets
    # to look at, and this detector never resolves a colour pair: it reads whether a hyperlink's
    # underline was explicitly removed, which is font styling on a link. Declaring COLOR would
    # claim an inspection it does not perform.
    requires={Capability.LINKS, Capability.FONTS},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=("hyperlinks are checked exactly for an explicitly removed underline, which leaves "
            "colour as the only thing setting a link apart from body text; colour used as the "
            "sole carrier of meaning anywhere else — shaded table rows, coloured glyphs, "
            "chart series keyed by hue — is not examined"),
)

# ── 1.4.11 Non-text Contrast ──────────────────────────────────────────────────────────
# Same story as 1.4.1 above: shipped detector, findings already surfaced, pair undeclared, so a
# clean file read NOT_EVALUATED for work that had been done.
#
# PARTIAL because the technique reaches shapes with a SOLID outline on a SOLID fill, measured
# structurally. Gradients, images behind a shape, theme-colour indirection, and every non-shape
# non-text element a criterion of this breadth covers (focus indicators, icon glyphs, control
# borders) are outside it.
#
# HIGH confidence within that: the ratio is computed from the two resolved colours by the same
# WCAG formula used for text contrast, not estimated.
#
# It does NOT become a pass. Whether a faint outline MATTERS depends on whether the shape
# conveys information or is decoration — a question about intent, which the file does not record.
register(
    rule="1.4.11",
    fmt="docx",
    detector=nontext_contrast.detect,
    # COLOR, and only COLOR: this one really does resolve a foreground/background pair — the
    # shape's outline against its own fill — and computes a ratio from it.
    requires={Capability.COLOR},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=("shapes with a solid outline on a solid fill are measured exactly, by the same "
            "WCAG contrast formula used for text; gradient or image fills, theme-colour "
            "indirection, and non-shape non-text elements such as focus indicators and control "
            "borders are not examined"),
)


# ── 2.1.2 No Keyboard Trap ────────────────────────────────────────────────────────────
# The last Core-17 criterion with no .docx declaration, and the one where the limit is a fact
# about DOCUMENTS rather than about ACP. Whether focus can move away from a control is runtime
# behaviour — it depends on the control's own implementation and on Word's handling — and no
# static read settles it. Better parsing would not help; the answer is not in the file.
#
# So the detector answers what it can (does this document embed interactive controls, and which)
# and hands the list to a reviewer. That is a real contribution: a 40-page consent pack with two
# content controls tells a reviewer exactly where to press Tab, instead of leaving them to read
# the whole document looking for something to try.
#
# PARTIAL because of that boundary, and the reason says so plainly. HIGH confidence within it:
# the control inventory is read straight from the package, not inferred.
#
# It CANNOT become a pass, and this is the clearest case of that in the whole registry. A clean
# document here means "no controls, so nothing to trap" — the criterion never arises rather than
# being satisfied — and _rule_outcome resolves that to NOT_EVALUATED, which is the honest answer.
# Unlike 1.1.1 or 2.4.6, no future detector moves this to FULL: the evidence does not exist
# statically, and the ceiling is a property of the format, not of the effort spent.
register(
    rule="2.1.2",
    fmt="docx",
    detector=no_keyboard_trap.detect,
    requires={Capability.FORMS},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=("the document is read for embedded interactive controls and each one is named for a "
            "reviewer to try with a keyboard; whether focus can actually move away from a "
            "control is runtime behaviour that depends on the control's own implementation and "
            "is not examined, because it is not recorded in the file"),
)


# ── 2.4.4 Link Purpose (In Context) ────────────────────────────────────────────────────
# Migrated from store.RULE_FORMATS + _certify to the coverage gate (ADR 0031's consolidation).
# The pair was never in doubt — a vague link fails, a clean file reviews — but it reached that
# verdict through the legacy path while 4.1.2/1.4.1/1.4.11/2.1.2 above reach the SAME verdict
# through the registry. Two mechanisms agreeing by coincidence is the "disagreeing tables" hazard
# the registry exists to end (ADR 0023); this makes docx 2.4.4's REVIEW structural.
#
# PARTIAL because the technique judges whether link text is a generic filler phrase or a raw URL,
# and not whether otherwise-fine text describes THIS destination — a link "Annual Report" pointing
# at the wrong year passes this check and fails the criterion. That accuracy-to-target judgement is
# the unexamined remainder, and it is a content question, so this never becomes a certified pass.
# HIGH confidence within the subset: the vague-text predicate is exact, shared with the remediator
# so an approved rewrite is credited by re-scan.
register(
    rule="2.4.4",
    fmt="docx",
    detector=link_purpose.detect,
    requires={Capability.LINKS},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=("hyperlink display text is checked exactly for generic filler ('click here', a bare "
            "URL); whether otherwise-descriptive text actually names THIS destination — a link "
            "reading 'Annual Report' that points at the wrong document — is a content judgement "
            "not examined, because the target's meaning is not recorded in the file"),
)


# ── 3.1.2 Language of Parts ────────────────────────────────────────────────────────────
# Migrated from store.RULE_FORMATS + _certify to the coverage gate, same as 2.4.4 above and for
# the same reason (ADR 0031). Verdict unchanged: an unmarked foreign passage fails, a clean file
# reviews; only the mechanism moves.
#
# PARTIAL because the technique needs a passage of at least textchecks._MIN_SEG_WORDS (12) words
# in a language other than the document's own before langdetect is trusted to call it, so a
# shorter foreign phrase or a single borrowed word is under the floor and unflagged. And "which
# language a passage IS" is a statistical detection, not a certainty. A clean result means "no
# unmarked foreign passage long enough for us to be sure" — a real check over a strict subset,
# which is why it reviews rather than certifies. HIGH confidence within the floor: the language
# comparison is deterministic given langdetect's answer, and the applier writes the same w:lang
# the detector reads, so an approved mark is credited by re-scan.
register(
    rule="3.1.2",
    fmt="docx",
    detector=language_parts.detect,
    requires={Capability.TEXT},
    coverage=Coverage.PARTIAL,
    confidence=Confidence.HIGH,
    reason=("passages of at least 12 words in a language other than the document's own are "
            "flagged when they carry no w:lang mark; a shorter foreign phrase or a single "
            "borrowed word is under the length floor langdetect needs to be trusted, and is not "
            "flagged"),
)
