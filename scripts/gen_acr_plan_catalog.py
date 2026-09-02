#!/usr/bin/env python3
"""Generate config/acr-manual-test-plans.json — the guided manual test plans (PRD §14).

WHAT THIS CATALOG IS, AND WHAT IT IS NOT
-----------------------------------------
It is **DERIVED from the WCAG 2.2 Recommendation**, not transcribed from PRD §14. The PRD names
"20 plans" but does not enumerate them anywhere in this repository, and inventing a list while
claiming it is §14's would be a fabricated citation in a compliance feature — precisely the class
of thing PRD §19 forbids. So every plan here cites the normative requirement of the criteria it
covers, `_meta.derivation` says on its face that it is derived, and swapping in the real §14 list
later is a change to this file, not to any code that reads it.

The derivation yields **21 plans**, not 20. The count is what the grouping produced; bending a
group to reach a number this repo cannot verify would be fake precision.

WHY EVERY ONE OF THE 55 CRITERIA GETS A PLAN
---------------------------------------------
Measured, not assumed: axe-core 4.12.1 publishes rules for **23** of the 55 criteria in this
catalog. **32 have no axe rule at all** — more than half the standard an ACR must report on is
entirely outside what the automated tool speaks to. (Measured by walking `axe.getRules()` metadata
and decoding `wcag<major><minor><criterion>` tags, the same decoding `api/acr_axe.py` uses.)

But the 23 do not get a pass either. Every row `acr_axe` emits declares `Coverage.PARTIAL`, and
`assessment.CAN_CERTIFY_PASS` is `{Coverage.FULL}` (ADR 0031) — a rule tests a technique, not a
whole success criterion. So automation cannot finish ANY criterion, and every applicable criterion
needs a human. That is PRD §4.3 stated as data rather than as a paragraph.

`axe_rule_criteria` records the 23 per plan, so a tester can see where automation already gave
them a partial answer and where it gave them nothing whatsoever. It is context, never a reason to
skip a step.

USAGE
    python scripts/gen_acr_plan_catalog.py           # write the JSON
    python scripts/gen_acr_plan_catalog.py --check   # verify the committed JSON is current
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WCAG_CATALOG = ROOT / "config" / "wcag-2.2-aa.json"
OUT = ROOT / "config" / "acr-manual-test-plans.json"

# Criteria axe-core 4.12.1 publishes at least one rule for. Measured from axe.getRules(), not
# recalled. Recorded so a plan can tell a tester "automation gave you a partial answer here"
# versus "automation said nothing at all" — see the module docstring for why neither is a pass.
AXE_RULE_CRITERIA = frozenset({
    "1.1.1", "1.2.1", "1.2.2", "1.3.1", "1.3.4", "1.3.5", "1.4.1", "1.4.2", "1.4.3", "1.4.4",
    "1.4.12", "2.1.1", "2.2.1", "2.2.2", "2.4.1", "2.4.2", "2.4.4", "2.5.3", "2.5.8", "3.1.1",
    "3.1.2", "3.3.2", "4.1.2",
})
AXE_VERSION_MEASURED = "4.12.1"

# Tester metadata a plan REQUIRES before it can be called complete (PRD §12, §4.5).
#
# Every name here MUST be a field of acr_model.Evidence, and `build()` asserts it. That is the
# whole point: a completed run produces an Evidence row, and the run's metadata IS that row's
# metadata. A `needs` vocabulary of its own — "viewport", "input_method", "os" — would be a second
# list that the durable record cannot store, so the plan would demand something the evidence then
# silently drops. Device and viewport specifics belong in the `environment` text, and the plan
# steps say what to put there.
#
# Split per-plan rather than applied globally because demanding a screen-reader name for a
# viewport-resize test trains people to type "n/a", which is worse than an empty field — the same
# reasoning the metadata form uses for advisory fields.
EVIDENCE_METADATA_FIELDS = frozenset({
    "tester", "tested_at", "product_version", "build_id", "environment", "workflow", "browser",
    "assistive_tech", "tool_name", "tool_version", "rule_id", "tested_url", "method", "notes",
})

# Plans driven through an assistive technology: the AT must be named and versioned in the record,
# because a result is not portable between screen readers or between browser+SR pairings.
NEEDS_AT = ("browser", "assistive_tech", "environment")
# Everything else: the browser and the environment it ran in.
NEEDS_BROWSER = ("browser", "environment")
NEEDS_VIEWPORT = NEEDS_BROWSER
NEEDS_POINTER = NEEDS_BROWSER

PLANS: list[dict] = [
    {
        "plan_id": "keyboard-operability",
        "title": "Keyboard operability sweep",
        "criteria": ["2.1.1", "2.1.2", "2.1.4"],
        "why_manual": (
            "axe can see that a control is focusable; it cannot operate it. Whether every "
            "function is REACHABLE and USABLE by keyboard, and whether focus can always be moved "
            "away again, is only established by a person driving the interface."
        ),
        "needs": NEEDS_BROWSER,
        "preconditions": [
            "Unplug or ignore the mouse for the whole session. Reaching for it invalidates the run.",
            "Start from the application's entry screen, signed in as an ordinary user.",
        ],
        "steps": [
            {"action": "Tab forward through the entire screen, then Shift+Tab back to the start.",
             "expect": "Every interactive control is reachable in both directions, and focus never "
                       "enters a component it cannot leave by Tab, Shift+Tab or Escape (2.1.2)."},
            {"action": "Operate each control from the keyboard — Enter/Space on buttons, arrows in "
                       "menus, listboxes, tabs and sliders.",
             "expect": "Every function available by pointer is available from the keyboard (2.1.1)."},
            {"action": "Open every dialog, menu and popover, then dismiss each with Escape.",
             "expect": "Focus returns to the control that opened it, and no dialog traps focus."},
            {"action": "Press each single-character key (letters, digits, punctuation) with no "
                       "modifier while focus is on the page body rather than a text field.",
             "expect": "Either nothing happens, or any single-key shortcut can be turned off, "
                       "remapped, or is active only while a component has focus (2.1.4)."},
        ],
    },
    {
        "plan_id": "focus-visibility-and-order",
        "title": "Focus visibility, order and obscuring",
        "criteria": ["2.4.3", "2.4.7", "2.4.11"],
        "why_manual": (
            "axe-core has NO rule for any of these three. Whether a focus indicator is actually "
            "visible, whether the order preserves meaning, and whether a sticky header hides the "
            "focused control are all visual judgements about a rendered page."
        ),
        "needs": NEEDS_BROWSER,
        "preconditions": [
            "Use a real browser at default zoom. jsdom has no layout engine and cannot answer any "
            "of this.",
        ],
        "steps": [
            {"action": "Tab through the screen watching only the focus indicator.",
             "expect": "The focused control is visibly indicated at every step, with no point where "
                       "focus is invisible (2.4.7)."},
            {"action": "Compare the tab order against the visual reading order of the screen.",
             "expect": "Focus moves in an order that preserves meaning and operability (2.4.3)."},
            {"action": "Scroll so a sticky header, footer or floating panel overlaps content, then "
                       "Tab to controls beneath it.",
             "expect": "No focused control is entirely hidden by author-created content (2.4.11)."},
            {"action": "Open each modal and Tab through it.",
             "expect": "Focus is placed in the dialog on open and confined to it while it is open."},
        ],
    },
    {
        "plan_id": "screen-reader-structure",
        "title": "Screen reader: page structure and relationships",
        "criteria": ["1.3.1", "1.3.2", "2.4.1", "2.4.6"],
        "why_manual": (
            "axe checks that heading and landmark MARKUP is well formed. It cannot judge whether "
            "the structure conveyed matches the structure a sighted user perceives, whether the "
            "reading sequence preserves meaning, or whether a heading actually describes its "
            "section."
        ),
        "needs": NEEDS_AT,
        "preconditions": [
            "Use a screen reader you can name and version — NVDA, JAWS or VoiceOver.",
            "Record the exact browser + screen reader pairing; results are not portable between them.",
        ],
        "steps": [
            {"action": "List the headings with the screen reader's heading list.",
             "expect": "Headings describe their sections and nest without skipping a level (2.4.6)."},
            {"action": "List the landmarks and regions.",
             "expect": "Each region is identified, and a mechanism exists to skip repeated blocks "
                       "of content (2.4.1)."},
            {"action": "Read the screen top to bottom in browse mode.",
             "expect": "The reading sequence conveys the same meaning as the visual order (1.3.2)."},
            {"action": "Enter each table and each form group and read its relationships.",
             "expect": "Header cells, groups and labels are programmatically associated with what "
                       "they describe (1.3.1)."},
        ],
    },
    {
        "plan_id": "screen-reader-controls",
        "title": "Screen reader: name, role and value of every control",
        # 1.3.1 appears here AND in screen-reader-structure, and that is not a duplication to tidy
        # away. Info and Relationships spans both: the structure plan covers headings, landmarks
        # and table relationships, while step 3 below tests LABEL-to-field association, which is
        # the same criterion reached by a different technique. A criterion finished by only one of
        # the two would be a criterion nobody had fully evaluated.
        "criteria": ["4.1.2", "2.5.3", "3.3.2", "1.3.1"],
        "why_manual": (
            "axe can detect a control with NO accessible name. It cannot tell whether the name is "
            "the right one, whether it contains the visible label text, or whether an instruction "
            "is sufficient to complete the field."
        ),
        "needs": NEEDS_AT,
        "preconditions": ["Have the visible screen in front of you while listening."],
        "steps": [
            {"action": "Move to every control and compare what is announced with what is displayed.",
             "expect": "Name, role and current value are announced, and the announced name contains "
                       "the visible label text (4.1.2, 2.5.3)."},
            {"action": "Change the state of every toggle, checkbox, expandable and tab.",
             "expect": "The new state is announced without needing to re-read the page."},
            {"action": "Enter each form field cold, without reading the screen first.",
             "expect": "The label and any required format instruction are announced, and are enough "
                       "to complete the field correctly (3.3.2)."},
        ],
    },
    {
        "plan_id": "status-messages",
        "title": "Status messages announced without focus movement",
        "criteria": ["4.1.3"],
        "why_manual": (
            "axe has NO rule for 4.1.3. Whether a status message is actually announced, and "
            "announced without stealing focus, can only be heard."
        ),
        "needs": NEEDS_AT,
        "preconditions": ["Screen reader running with default verbosity."],
        "steps": [
            {"action": "Trigger each success, error, progress and result-count message without "
                       "moving focus to it.",
             "expect": "Each is announced by the screen reader (4.1.3)."},
            {"action": "Watch where focus is while each message appears.",
             "expect": "Focus is not moved to the message; the user's place is preserved."},
            {"action": "Trigger a long-running operation.",
             "expect": "Progress and completion are announced, not only shown."},
        ],
    },
    {
        "plan_id": "text-alternatives",
        "title": "Text alternatives convey equivalent purpose",
        "criteria": ["1.1.1"],
        "why_manual": (
            "axe detects a MISSING alt attribute. Whether the alternative conveys the same purpose "
            "as the image — and whether a decorative image is correctly hidden rather than "
            "described — is a judgement about meaning that no tool makes."
        ),
        "needs": NEEDS_AT,
        "preconditions": ["Inventory every non-text element: images, icons, charts, canvases, "
                          "media thumbnails, CSS background images that carry meaning."],
        "steps": [
            {"action": "For each informative image, read its alternative with the image hidden.",
             "expect": "The alternative serves the same purpose as the image (1.1.1)."},
            {"action": "For each decorative image, check how it is exposed.",
             "expect": "It is hidden from assistive technology rather than given a description."},
            {"action": "For each chart or data visualisation, look for the equivalent.",
             "expect": "The information is available in text or a table, not only as a picture."},
            {"action": "For each icon-only control, listen to its announced name.",
             "expect": "The name describes the ACTION, not the glyph."},
        ],
    },
    {
        "plan_id": "prerecorded-media",
        "title": "Prerecorded audio and video alternatives",
        "criteria": ["1.2.1", "1.2.2", "1.2.3", "1.2.5"],
        "why_manual": (
            "This is the criterion group where automation is most dangerously misleading. A page "
            "with no <video> makes axe report `inapplicable`, which says NOTHING about whether the "
            "product captions its videos — see api/acr_axe.py. Only an inventory of the product's "
            "actual media answers it."
        ),
        "needs": NEEDS_BROWSER,
        "preconditions": [
            "Build an inventory of EVERY prerecorded audio and video asset the product presents, "
            "including onboarding, help, marketing and embedded third-party media.",
            "If the inventory is genuinely empty, that is a Not Applicable decision with an "
            "explanation — not a pass, and not a skipped plan.",
        ],
        "steps": [
            {"action": "For each audio-only and video-only asset, look for the alternative.",
             "expect": "An equivalent text alternative is available, or an audio track for "
                       "video-only content (1.2.1)."},
            {"action": "Play each video with sound and read the captions.",
             "expect": "Captions are present, synchronised, and include speaker identification and "
                       "meaningful non-speech audio (1.2.2)."},
            {"action": "Watch each video with the screen off, listening only.",
             "expect": "An audio description or a full text alternative conveys the visual "
                       "information (1.2.3, 1.2.5)."},
        ],
    },
    {
        "plan_id": "live-media",
        "title": "Live media captions",
        "criteria": ["1.2.4"],
        "why_manual": "Live content cannot be tested from a static page at all.",
        "needs": NEEDS_BROWSER,
        "preconditions": [
            "Identify any live audio the product streams — webinars, live support, broadcast.",
            "If there is none, that is a Not Applicable decision with an explanation.",
        ],
        "steps": [
            {"action": "Join a live session and enable captions.",
             "expect": "Real-time captions are available for live audio content (1.2.4)."},
            {"action": "Follow the captions for several minutes against the spoken audio.",
             "expect": "Captions keep pace and are accurate enough to follow the content."},
        ],
    },
    {
        "plan_id": "colour-and-sensory-cues",
        "title": "Colour and sensory characteristics are never the only cue",
        "criteria": ["1.3.3", "1.4.1"],
        "why_manual": (
            "axe cannot tell whether colour is the ONLY means of conveying something. That "
            "requires understanding what the interface is trying to communicate."
        ),
        "needs": NEEDS_BROWSER,
        "preconditions": ["Have a greyscale filter available (OS display filter or browser devtools)."],
        "steps": [
            {"action": "View every screen in greyscale.",
             "expect": "Every distinction still readable — status, validity, required-ness, "
                       "selection, chart series — is conveyed by more than colour (1.4.1)."},
            {"action": "Read every instruction in the interface.",
             "expect": "No instruction depends solely on shape, size, position, orientation or "
                       "sound — 'the button on the right', 'the round icon' (1.3.3)."},
            {"action": "Check links within blocks of text.",
             "expect": "Links are distinguishable from surrounding text without relying on colour."},
        ],
    },
    {
        "plan_id": "contrast",
        "title": "Text and non-text contrast, measured",
        "criteria": ["1.4.3", "1.4.11"],
        "why_manual": (
            "axe DOES check text contrast, and reports `incomplete` — not a pass — whenever it "
            "cannot resolve a background: over an image, a gradient, or a partially transparent "
            "layer. Those are exactly the cases a person must measure. 1.4.11 has no axe rule."
        ),
        "needs": NEEDS_BROWSER,
        "preconditions": [
            "Use a contrast measurement tool that samples rendered pixels.",
            "Test in BOTH light and dark themes. A fix in one can break the other.",
        ],
        "steps": [
            {"action": "Measure every case axe reported as `incomplete`.",
             "expect": "Text meets 4.5:1, or 3:1 for large text (1.4.3)."},
            {"action": "Measure text over images, gradients and translucent overlays.",
             "expect": "The ratio holds against the actual rendered background, at every scroll "
                       "position where the text moves over different pixels."},
            {"action": "Measure UI component boundaries, focus indicators, icons carrying meaning, "
                       "and chart elements.",
             "expect": "Non-text elements needed to understand or operate the interface meet 3:1 "
                       "(1.4.11)."},
        ],
    },
    {
        "plan_id": "resize-reflow-and-spacing",
        "title": "Zoom, reflow, text spacing and orientation",
        "criteria": ["1.3.4", "1.4.4", "1.4.10", "1.4.12"],
        "why_manual": (
            "Every one of these is about what happens to a RENDERED layout under manipulation. "
            "1.4.10, 1.4.13 and the reflow behaviour have no axe rule; jsdom cannot answer any of "
            "them because it has no layout engine."
        ),
        "needs": NEEDS_VIEWPORT,
        "preconditions": ["Record the exact viewport size and zoom level for each observation."],
        "steps": [
            {"action": "Zoom text to 200% without zooming the page.",
             "expect": "All content and functionality remain available with no loss (1.4.4)."},
            {"action": "Set the viewport to 320 CSS pixels wide (or 400% zoom at 1280px).",
             "expect": "Content reflows into one column with no two-dimensional scrolling, except "
                       "for content that genuinely requires it such as a data table (1.4.10)."},
            {"action": "Apply the 1.4.12 text-spacing overrides — line height 1.5×, paragraph "
                       "spacing 2×, letter spacing 0.12em, word spacing 0.16em.",
             "expect": "No content is clipped, overlapped or lost (1.4.12)."},
            {"action": "Rotate a tablet or phone between portrait and landscape.",
             "expect": "The interface works in both unless a specific orientation is essential "
                       "(1.3.4)."},
        ],
    },
    {
        "plan_id": "images-of-text",
        "title": "Images of text",
        "criteria": ["1.4.5"],
        "why_manual": "No axe rule. Recognising that a picture contains text requires looking at it.",
        "needs": NEEDS_BROWSER,
        "preconditions": ["Inventory images that render words: banners, diagrams, screenshots, logos."],
        "steps": [
            {"action": "For each image containing text, ask whether real text could achieve the "
                       "same presentation.",
             "expect": "Text is used rather than an image of text, except for logotypes and cases "
                       "where a particular presentation is essential (1.4.5)."},
            {"action": "Zoom each such image to 200%.",
             "expect": "Any text that remains as an image stays legible when magnified."},
        ],
    },
    {
        "plan_id": "hover-and-focus-content",
        "title": "Content revealed on hover or focus",
        "criteria": ["1.4.13"],
        "why_manual": (
            "No axe rule. Dismissible, hoverable and persistent are behaviours over time; they can "
            "only be observed by interacting."
        ),
        "needs": NEEDS_POINTER,
        "preconditions": ["Inventory every tooltip, popover and hover card."],
        "steps": [
            {"action": "Trigger each on hover, then press Escape.",
             "expect": "It can be dismissed without moving the pointer or focus (dismissible)."},
            {"action": "Move the pointer from the trigger onto the revealed content.",
             "expect": "The content stays visible while the pointer is over it (hoverable)."},
            {"action": "Leave the pointer on the trigger and wait.",
             "expect": "The content remains until dismissed, focus moves away, or it stops being "
                       "valid — it does not disappear on a timer (persistent)."},
            {"action": "Repeat the whole plan using only the keyboard.",
             "expect": "The same three behaviours hold when the content is revealed by focus."},
        ],
    },
    {
        "plan_id": "auto-starting-content",
        "title": "Content that starts, moves or flashes on its own",
        "criteria": ["1.4.2", "2.2.2", "2.3.1"],
        "why_manual": (
            "These share one test session: find everything that begins without the user asking, "
            "then verify it can be stopped. 2.3.1 has no axe rule, and a flash rate cannot be "
            "judged from markup."
        ),
        "needs": NEEDS_BROWSER,
        "preconditions": ["Inventory anything that autoplays, animates, scrolls, blinks or "
                          "auto-updates, including carousels, toasts and live-updating counts."],
        "steps": [
            {"action": "Load each screen and listen for audio that starts on its own.",
             "expect": "Any audio playing longer than 3 seconds can be paused, stopped, or its "
                       "volume controlled independently of the system volume (1.4.2)."},
            {"action": "Watch each moving, blinking, scrolling or auto-updating element for more "
                       "than 5 seconds.",
             "expect": "A mechanism exists to pause, stop or hide it, unless it is essential "
                       "(2.2.2)."},
            {"action": "Observe anything that flashes.",
             "expect": "Nothing flashes more than three times per second, or it stays below the "
                       "general and red flash thresholds (2.3.1)."},
        ],
    },
    {
        "plan_id": "time-limits",
        "title": "Time limits are adjustable",
        "criteria": ["2.2.1"],
        "why_manual": (
            "axe can see a meta refresh. It cannot see a session timeout, an idle logout, or a "
            "form that expires server-side — which is where a real application's time limits live."
        ),
        "needs": NEEDS_BROWSER,
        "preconditions": ["Identify every time limit: session expiry, idle logout, auto-save "
                          "windows, one-time codes, rate limits that discard work."],
        "steps": [
            {"action": "Let a session reach its idle limit while a form is partly filled.",
             "expect": "The user is warned with at least 20 seconds to extend, and can extend with "
                       "a simple action (2.2.1)."},
            {"action": "Extend the limit when prompted.",
             "expect": "The limit extends at least ten times, and entered data survives."},
            {"action": "Check whether the limit can be turned off or lengthened to ten times the "
                       "default in settings.",
             "expect": "One of turn-off, adjust, or extend is available — or the limit is essential "
                       "and documented as such."},
        ],
    },
    {
        "plan_id": "pointer-touch-and-targets",
        "title": "Pointer gestures, cancellation, motion and target size",
        "criteria": ["2.5.1", "2.5.2", "2.5.4", "2.5.7", "2.5.8"],
        "why_manual": (
            "Four of these five have no axe rule. Gestures, drag operations and device motion are "
            "input behaviours; only 2.5.8 target size is partly measurable from geometry."
        ),
        "needs": NEEDS_POINTER,
        "preconditions": ["Use a real touch device for the gesture and motion steps.",
                          "Inventory every drag, swipe, pinch and multi-point interaction."],
        "steps": [
            {"action": "For each path-based or multipoint gesture, look for a single-pointer "
                       "alternative.",
             "expect": "A single-tap, click or keyboard alternative exists unless the gesture is "
                       "essential (2.5.1)."},
            {"action": "Press down on a control, move the pointer away, and release.",
             "expect": "The action does not fire on down-event, and can be aborted or undone "
                       "(2.5.2)."},
            {"action": "For each drag operation, attempt the same result without dragging.",
             "expect": "A single-pointer alternative exists unless dragging is essential (2.5.7)."},
            {"action": "Shake, tilt or move the device where motion triggers anything.",
             "expect": "The function is also available through the interface, and motion actuation "
                       "can be disabled (2.5.4)."},
            {"action": "Measure the smallest interactive targets, including inline links in "
                       "toolbars and icon buttons.",
             "expect": "Targets are at least 24×24 CSS pixels, or spaced so a 24px circle does not "
                       "overlap another target, or meet a listed exception (2.5.8)."},
        ],
    },
    {
        "plan_id": "page-identity-and-navigation",
        "title": "Page titles, link purpose and multiple ways",
        "criteria": ["2.4.2", "2.4.4", "2.4.5"],
        "why_manual": (
            "axe checks that a <title> EXISTS and that a link has SOME text. Whether the title "
            "describes the page, and whether the link text describes where it goes, are judgements "
            "about words. 2.4.5 has no axe rule."
        ),
        "needs": NEEDS_BROWSER,
        "preconditions": ["Work from a list of every distinct view in the product."],
        "steps": [
            {"action": "Read each view's browser tab title.",
             "expect": "It describes the topic or purpose of that view and distinguishes it from "
                       "the others (2.4.2)."},
            {"action": "Read every link's text out of context, then in context.",
             "expect": "The purpose is determinable from the link text with its context (2.4.4)."},
            {"action": "Count the ways to reach each view.",
             "expect": "At least two independent ways exist — navigation, search, sitemap, "
                       "in-context link — unless the view is a step in a process (2.4.5)."},
        ],
    },
    {
        "plan_id": "language",
        "title": "Language of page and of parts",
        "criteria": ["3.1.1", "3.1.2"],
        "why_manual": (
            "axe checks that `lang` is PRESENT and well formed. Whether the declared language is "
            "the language actually used, and whether foreign-language passages are marked, needs "
            "someone who can read the content."
        ),
        "needs": NEEDS_AT,
        "preconditions": ["Include any localised builds in scope."],
        "steps": [
            {"action": "Compare each page's declared lang against the language of its content.",
             "expect": "The declared language is the one actually used (3.1.1)."},
            {"action": "Find passages in a different language from the page.",
             "expect": "Each is marked with its own lang, except proper names and technical terms "
                       "(3.1.2)."},
            {"action": "Listen to a mixed-language page with a screen reader.",
             "expect": "Pronunciation switches at the marked passages."},
        ],
    },
    {
        "plan_id": "predictability",
        "title": "Predictable behaviour and consistency across views",
        "criteria": ["3.2.1", "3.2.2", "3.2.3", "3.2.4", "3.2.6"],
        "why_manual": (
            "None of these five has an axe rule, and none is a property of a single page — they "
            "compare behaviour ACROSS views, which is a session a person runs."
        ),
        "needs": NEEDS_BROWSER,
        "preconditions": ["Visit at least three views that share navigation and repeated controls."],
        "steps": [
            {"action": "Tab onto every control without activating it.",
             "expect": "Receiving focus alone never changes context — no navigation, no submission, "
                       "no new window (3.2.1)."},
            {"action": "Change every input's value: type, select, check, toggle.",
             "expect": "Changing a setting alone never changes context without warning (3.2.2)."},
            {"action": "Compare navigation across views.",
             "expect": "Repeated navigation appears in the same relative order (3.2.3)."},
            {"action": "Compare repeated icons, controls and labels across views.",
             "expect": "Components with the same function are identified consistently (3.2.4)."},
            {"action": "Locate the help mechanism on each view that offers one.",
             "expect": "Help appears in the same relative order across views (3.2.6)."},
        ],
    },
    {
        "plan_id": "forms-errors-and-authentication",
        "title": "Errors, error prevention, redundant entry and authentication",
        "criteria": ["3.3.1", "3.3.3", "3.3.4", "3.3.7", "3.3.8"],
        "why_manual": (
            "Four of these five have no axe rule. Every one is about what happens AFTER the user "
            "acts — submitting bad data, correcting it, re-entering it, or proving who they are."
        ),
        "needs": NEEDS_AT,
        "preconditions": ["Identify forms that are legal, financial, or modify user-controlled data.",
                          "Have the sign-in flow available, including any second factor."],
        "steps": [
            {"action": "Submit each form with invalid and missing values.",
             "expect": "The field in error is identified in text, not by colour or position alone "
                       "(3.3.1), and is announced by the screen reader."},
            {"action": "Read each error message.",
             "expect": "It suggests how to correct the problem where the correction is known "
                       "(3.3.3)."},
            {"action": "Complete a legal, financial or data-modifying submission.",
             "expect": "It is reversible, checked for errors with a chance to correct, or confirmed "
                       "before finalising (3.3.4)."},
            {"action": "Work through a multi-step flow that asks for the same information twice.",
             "expect": "Previously entered information is auto-populated or selectable, unless "
                       "re-entry is essential (3.3.7)."},
            {"action": "Sign in, including any second factor.",
             "expect": "No step requires a cognitive function test such as remembering or "
                       "transcribing, or an alternative exists — and pasting into the password "
                       "and code fields works (3.3.8)."},
        ],
    },
    {
        "plan_id": "input-purpose",
        "title": "Identify input purpose",
        "criteria": ["1.3.5"],
        "why_manual": (
            "axe checks that an autocomplete token is VALID. Whether the right token was chosen "
            "for what the field collects — and whether a field collecting user information has one "
            "at all — is a judgement about the field's meaning."
        ),
        "needs": NEEDS_BROWSER,
        "preconditions": ["List every field that collects information ABOUT THE USER."],
        "steps": [
            {"action": "For each such field, inspect its autocomplete attribute.",
             "expect": "It carries the correct token from the HTML autofill list (1.3.5)."},
            {"action": "Use the browser's own autofill on the form.",
             "expect": "Values land in the fields they belong to."},
            {"action": "Check fields that do NOT collect user information.",
             "expect": "They are not given a token that misdescribes them."},
        ],
    },
]


def _wcag_criteria() -> list[str]:
    data = json.loads(WCAG_CATALOG.read_text(encoding="utf-8"))
    return [c["num"] for c in data["criteria"]]


def build() -> dict:
    """Assemble the catalog and validate it against the WCAG catalog it must cover."""
    all_criteria = _wcag_criteria()
    known = set(all_criteria)

    covered: dict[str, list[str]] = {}
    for plan in PLANS:
        for num in plan["criteria"]:
            if num not in known:
                raise SystemExit(f"plan {plan['plan_id']} names unknown criterion {num}")
            covered.setdefault(num, []).append(plan["plan_id"])

    missing = [n for n in all_criteria if n not in covered]
    if missing:
        raise SystemExit(
            "every applicable criterion needs a plan, because automation can finish none of them "
            f"(ADR 0031, PRD §4.3). Uncovered: {missing}")

    ids = [p["plan_id"] for p in PLANS]
    if len(ids) != len(set(ids)):
        raise SystemExit("duplicate plan_id")

    # A plan may only demand metadata the evidence record can actually carry. Without this a plan
    # could require a field that is dropped on the way to acr_evidence, so the run would look
    # reproducible and the durable record would not be.
    for plan in PLANS:
        unknown = sorted(set(plan["needs"]) - EVIDENCE_METADATA_FIELDS)
        if unknown:
            raise SystemExit(
                f"plan {plan['plan_id']} needs {unknown}, which acr_model.Evidence cannot store")

    plans_out = []
    for plan in PLANS:
        with_rules = sorted(c for c in plan["criteria"] if c in AXE_RULE_CRITERIA)
        plans_out.append({
            "plan_id": plan["plan_id"],
            "title": plan["title"],
            "criteria": list(plan["criteria"]),
            "why_manual": plan["why_manual"],
            "needs": list(plan["needs"]),
            "preconditions": list(plan["preconditions"]),
            "steps": [dict(s) for s in plan["steps"]],
            # Context for the tester: where automation already gave a PARTIAL answer, and where it
            # gave none at all. Never a reason to skip a step — see the module docstring.
            "axe_rule_criteria": with_rules,
            "criteria_with_no_axe_rule": sorted(set(plan["criteria"]) - AXE_RULE_CRITERIA),
        })

    body = {"plans": plans_out,
            "criterion_to_plans": {n: sorted(covered[n]) for n in all_criteria}}
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]

    return {
        "_meta": {
            "derived_from": "https://www.w3.org/TR/WCAG22/",
            "derivation": (
                "DERIVED from the WCAG 2.2 Recommendation, NOT transcribed from PRD §14. The PRD "
                "names 20 plans but does not enumerate them in this repository; presenting an "
                "invented list as §14's would be a fabricated citation in a compliance feature "
                "(PRD §19). Replace this file to adopt the real §14 catalog — no code reads the "
                "plan text."),
            "generator": "scripts/gen_acr_plan_catalog.py",
            "plan_count": len(plans_out),
            "criteria_covered": len(all_criteria),
            "axe_version_measured": AXE_VERSION_MEASURED,
            "criteria_with_any_axe_rule": len(AXE_RULE_CRITERIA),
            "criteria_with_no_axe_rule": len(known - AXE_RULE_CRITERIA),
            "why_every_criterion_has_a_plan": (
                "axe-core publishes rules for 23 of these 55 criteria; 32 have none at all. The 23 "
                "do not get a pass either: every acr_axe row declares Coverage.PARTIAL and "
                "CAN_CERTIFY_PASS is {FULL} (ADR 0031), so automation finishes no criterion and "
                "every applicable one needs a human."),
            "content_hash": digest,
        },
        **body,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="verify the committed JSON matches what this script generates")
    args = ap.parse_args()

    catalog = build()
    rendered = json.dumps(catalog, indent=2, ensure_ascii=False) + "\n"

    if args.check:
        if not OUT.exists():
            print(f"MISSING {OUT.relative_to(ROOT)} — run scripts/gen_acr_plan_catalog.py")
            return 1
        if OUT.read_text(encoding="utf-8") != rendered:
            print(f"STALE {OUT.relative_to(ROOT)} — run scripts/gen_acr_plan_catalog.py")
            return 1
        meta = catalog["_meta"]
        print(f"OK  {meta['plan_count']} plans covering all {meta['criteria_covered']} criteria "
              f"(hash {meta['content_hash']})")
        return 0

    OUT.write_text(rendered, encoding="utf-8")
    meta = catalog["_meta"]
    print(f"wrote {OUT.relative_to(ROOT)}: {meta['plan_count']} plans, "
          f"{meta['criteria_covered']} criteria, hash {meta['content_hash']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
