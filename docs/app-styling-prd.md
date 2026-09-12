# ACP app-wide styling PRD

Status: design specification. Shared typography and control alignment is authorized and in progress; completion of every legacy panel is not implied.

## Objective
Make Sources, Discover, Assess, Remediate, and Release feel like one product. Users should recognize the same fonts, controls, file tables, status meanings, and action hierarchy throughout the workflow.

## Typography
Use the existing `--font-ui` system sans stack for headings, body copy, filenames, breadcrumbs, controls, and status tags. Use shared role tokens rather than local typeface overrides.

| Role | Size | Weight | Line height |
|---|---:|---:|---:|
| Page title | 22px | 650 | 1.3 |
| Component title | 18px | 650 | 1.35 |
| Body, buttons | 14px | 400; buttons 600 | 1.5 |
| Filenames, breadcrumbs | 13px | 400 | 1.5 |
| Table headers, metadata | 12px | 500; metadata 400 | 1.5 |
| Metadata, timestamps, tags | 12px | 400; tags 500 | 1.5 |
| KPI counts | 28px | 700 | 1.1 |

Use `--font-mono` for technical identifiers, code, hashes, and the expanded Live Activity sub-bullets specifically requested by the owner (13px). Keep delivery-status tags in the UI sans font even within those sub-bullets. KPI counts use tabular numerals so updates do not shift adjacent content. Filename text must not switch font when data arrives, a tab changes, or polling reconnects.

## Shared controls and surfaces
Use a 4px spacing scale: 4, 8, 12, 16, 24, 32. Cards have white opaque surfaces, a subtle border, a 12px radius, and 20–24px padding. Component groups use a consistent 16–24px vertical gap.

Buttons use one standard 40px height, 14px type, 600 weight, and the shared 9px radius. Primary actions use the existing plum color; secondary actions use an outlined surface. One primary action per action group. Loading retains the button width; disabled controls show a nearby reason when the next step is blocked.

Subtabs share height, font, spacing, and selected underline across Remediate and Release. Native controls inherit the UI font. Breadcrumb segments use 13px sans text with consistent separators and an obvious current folder.

## Clickable filters and status tags
A filter is one button with label and count on one surface: no badge nested inside another pill. Filters use a consistent 36px height, 13px text, 12px horizontal padding, and full pill radius. Keep category colors; show selection with an inset border and semibold label, and preserve a separate visible keyboard focus state. Hover explanations are also accessible by keyboard. Counts update without moving labels or changing control height.

A status tag is informational and must not look like an action. Use a 6px radius, 12px sans text, a light tinted background, and a subtle border. Separate “Source delivery unavailable” from the saved-copy message as an amber status tag; saving in ACP must not appear to mean SharePoint delivery succeeded.

The Auto-apply AI fixes control is a real labeled switch. On uses green plus visible “On”; Off uses neutral plus “Off.” Pending saves have a busy state. Color never carries the state alone.

## Tables, scroll, and search
Share the same file-table typography, header layout, row padding, and action alignment in Assess and Remediate. Headers use the UI font and an opaque sticky background. Keep deliberate column widths, wrap long filenames safely, and prevent headers from changing shape during updates.

Use a bounded vertical scroll container for long file lists and horizontal scrolling only when columns cannot fit. Keep search and format/category filters above the table. Filtering shows the visible count and an easy reset. Preserve the current scroll position, search, selection, and expanded state during confirmed live updates.

## Live Activity and KPI tiles
Live Activity uses a 15px sans headline, 12px timestamp, and 13px monospace expanded sub-bullets. Keep icons and timestamps aligned across success, failure, and retry cards. Delivery tags retain their sans font and remain readable on every card background.

Use compact Assess-style KPI tiles for file coverage, document status, findings, and publication: near-white surfaces, subtle borders, 9px radius, 14–16px padding, and 28px counts. Use semantic accents rather than large saturated backgrounds. Each domain states its scope. Fixed Before values, current counts, and signed deltas have a consistent hierarchy. Connection gaps retain confirmed values; unknown values show an em dash rather than zero. Reduced motion disables count and pulse animation. Animations must not change tile dimensions or replay on refresh.

## Release batch default
Default to all unpublished eligible saved copies as one batch. Show a compact batch summary and “Publish batch (N)” action. “Choose specific files” reveals individual controls. Exclude already delivered files, and distinguish blockers from unresolved findings that the selected publishing policy permits. Never imply approved changes are applied before corrected bytes are actually saved.

## Acceptance
- Representative screens in every main workflow tab use the typography and spacing roles above.
- File names, filters, breadcrumbs, and controls match across Assess, Remediate, and Release.
- No nested bordered filter pills, clipped selection rings, or unexplained browser-font controls.
- Delivery availability remains separate from saved-copy and verification status.
- Long names, 200% zoom, narrow screens, keyboard navigation, and reduced motion remain usable.
- Loading, polling, reconnecting, and KPI updates preserve table geometry and control state.
- Visual and DOM regression checks cover shared controls, representative file tables, Live Activity, and Release batch selection.

## Rollout
First establish shared tokens and reusable controls. Then align file tables, filters, and breadcrumbs. Finally align activity cards, KPI surfaces, and legacy panels. Preserve workflow behavior and validate each phase; the PRD is broader than the styling fixes already merged in PR #1999.


## Queue drawers and optional inspection
Clicking a file, document, finding, or publication KPI opens a right-side drawer instead of scrolling to the bottom table. Show exact queue membership, searchable filenames, status tags, blocked reasons, and per-file finding counts where relevant. Finding and publication queues stay bound to their immutable execution. Missing membership evidence shows unavailable, never a different batch. Support Escape, focus trapping and restoration, narrow-screen layout, and reduced motion. Opening a drawer does not change table filters.

Automatically applied change records are optional to browse. They do not require Defer, Not applicable, or an individual approval click. They count as recorded review tasks, not verified accessibility fixes. Preserve historical decisions honestly. Remaining issues and real pending proposals retain their actual states.

Known assessment failures remain visible as Blocked files with the recorded reason and unavailable finding counts. Corruption, timeout, and access failures must not be conflated. Do not offer remediation until readable assessment evidence exists. Unknown ledger telemetry alone is not a blocker diagnosis.

Release omits the remediation Needs attention tile and duplicate counter; users manage that work in Remediate. Actual publication failures remain in Release as Delivery issues.
