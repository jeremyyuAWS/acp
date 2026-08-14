# Remediate page redesign — spec (R4)

**Principle:** Turn Remediate into a focused **work queue**, not an architecture/status page.
The page currently mixes estate status, pipeline status, queue management, technical evidence,
and remediation authoring on one surface. Separate the *queue* from the *focused decision
surface* and it gets substantially calmer without hiding anything.

## What makes it feel busy (and the fix)

1. **Four competing navigation systems** — primary tabs (Overview…Monitor), scan metadata/time
   travel, the secondary Scan→Assess→Remediate→AI Work Inbox→Verify→Publish rail, and the
   per‑finding Detected→Human review→Written→Re‑scan→Certified rail. Keep the **primary tabs**;
   collapse the rest into **contextual status inside the Remediate page** (drop the ProgressRail
   as a persistent element).
2. **The top half repeats one message** — the `5` badge, the inbox `5`, "5 need your review",
   "Review 5 Remaining Issues", "0 of 5 reviewed", "5 critical findings open" all say the same
   thing. Collapse to **one dominant statement** + **one** progress indicator:
   > **5 findings need review across 2 documents** · ~15 min · `0 of 5 resolved`
3. **Organized around system terminology** — "AI Work Inbox" describes how the work was
   generated, not what the user must do. Rename → **Review queue** (or "Findings to resolve").
   Express AI as an *attribute of a finding*: `AI draft available` · `Guided fix` ·
   `Human authoring required`. (Some findings have no trustworthy AI draft.)
4. **The expanded finding consumes the page** — the accordion combines queue nav, doc metadata,
   workflow status, evidence, authoring and decision controls in one growing object; users lose
   their place. Use the **right‑drawer** pattern — but the drawer must **replace** detail, not
   duplicate it.

## Target layout

**Persistent page header** — title, one dominant summary, one progress bar, one primary action:
```
Accessibility remediation
5 findings need review across 2 documents            0 of 5 resolved
[████░░░░░░]                                          [Start review]
```
Compact filter row only: `Search · Severity · Criterion · Fix type · Document · Sort`.
Move scope‑counting behind an **Assessment scope** disclosure — the yellow counting banner must
not permanently occupy the work surface.

**Left — compact review queue.** Each row answers five questions without expanding:
Document · Problem (plain language) · Criterion (WCAG) · Fix path · Priority · ~time.
**No Approve/Reject on the collapsed row** (decisions lack context until evidence is inspected).
**Group by document by default** (fixes are written + verified per document); allow group‑by‑criterion.

**Right — focused remediation drawer** (40–45% width) with four fixed sections:
1. **Problem** — plain‑language explanation, criterion, severity, affected object.
2. **Evidence** — rendered page/object preview with the region highlighted; file metadata + rule
   details behind "Technical evidence".
3. **Proposed resolution** — show the actual mode explicitly: `Automatic fix available` ·
   `AI draft — review wording` · `Guided fix` · `Human authoring required`. When there's no
   trustworthy draft, give a text field + short authoring guidance, not an Approve button.
4. **Decision** — actions appropriate to the mode: **Apply fix** · **Save edited fix** ·
   **Mark resolved manually** · **Defer** · **Not applicable**. Replace ambiguous "Reject" with
   the specific action.

## The changes, in priority order
1. Accordion → **queue + right drawer** (the drawer replaces detail).
2. Remove duplicate `5` counters → **one dominant progress summary**.
3. Rename **AI Work Inbox → Review queue**; AI is a per‑finding attribute.
4. Remove Approve/Reject from collapsed rows.
5. Remediation‑**specific** decision actions (no generic Approve/Reject).
6. Counting banner → **Assessment scope** disclosure.
7. **Group by document** by default.
8. **Save and continue** as the primary action (guided sequence).
9. Technical rule data one level **below** the human‑readable problem.
10. Show verification (**Written→Re‑scan→Certified**) only **after** a fix is saved.

## Implementation notes (grounded in the current code)
- Current page: single `Remediate.jsx` (~1400 lines) — `ProgressRail`, hero with the duplicate
  counters (`Remediate.jsx` ~800‑870), and the inbox accordion where each row carries inline
  Approve/Reject (~635‑645) + an expanding `<EvidenceCard>` (~646).
- "AI Work Inbox" is a **product‑wide** term: `HitlBell.jsx` (top‑nav bell), `EvidenceCard.jsx`,
  and ~7 test files. Renaming is coordinated work, not just the section header.
- `ReviewDrawer.jsx` (97 lines, `{item, onClose, onAct, onDraft}`) is the base to grow the
  four‑section focused drawer on.
- ~30 review/inbox tests (`remediateInboxSearch`, `remediateCollapse`, `reviewInboxFilter`,
  `inboxPrefs`, `reviewCard`, `evidenceCard*` …) must stay green / be updated per change.

## Suggested phasing
- **Phase 1 (low‑risk clarity):** dedupe counters → one dominant summary; remove Approve/Reject
  from collapsed rows; Assessment‑scope disclosure; fix‑path shown as a row attribute.
- **Phase 2 (layout):** accordion → queue + right drawer; the four drawer sections; the
  AI‑Work‑Inbox → Review‑queue rename (coordinated across HitlBell/EvidenceCard/tests);
  group‑by‑document default; Save‑and‑continue guided sequence; remediation‑specific actions.
