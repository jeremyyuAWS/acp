# Scan-scope wizard — design spec

Source: Jeremy, 2026-08-13. This replaces the dense `ScanScope` grid (which "feels like an admin
configuration grid, not a confident 'start scan' decision") with a short scan-launch wizard that
has optional expert controls. Captured here so the phased build has one reference.

## Core behavior (the rules)

1. **Confirm scope before EVERY scan**, via a pop-up prefilled with the last-used scope.
2. **Require confirmation, not reconfiguration** — the user shouldn't re-tick 17×4 every time.
3. Scope becomes an **immutable part of that scan's configuration**: save a frozen
   `scan_scope_snapshot` with the scan.
4. **Downstream inherits it**: Discover, Assess, Remediate, reporting, and exports all use the
   scan's frozen scope.
5. **Never recompute history**: later global-setting changes must not alter past scan results.
   Offer "Change scope and rescan" instead.
6. Unsupported (criterion×format) pairs are **excluded from the denominator**, clearly labeled
   **Not evaluated**, never counted as passes. (Already true in the engine today.)
7. Show a compact **scope chip** when entering Assess/Remediate: `Core 17 · DOCX/PDF · 29 checks`.
8. Disable formats absent from the uploaded batch (`No XLSX files detected`); if nothing uploaded
   yet, allow all format selection.
9. Show practical impact before starting: `12 files · 57 checks · approximately 4–6 minutes`.

## Popup structure (wizard)

```
┌─ Configure scan scope ───────────────────────────────── × ─┐
│ This scope will be used throughout Discover, Assess and     │
│ Remediate.                                                  │
│                                                             │
│ SCAN PROFILE                                                │
│ [✓ Core 17 — Recommended] [Saved scope] [Custom] [Everything]│
│                                                             │
│ FILE FORMATS                                                │
│ [✓ DOCX] [✓ XLSX] [✓ PPTX] [✓ PDF]      Select all · Clear  │
│                                                             │
│ 17 criteria · 4 formats · 57 supported checks               │
│ 4 unsupported combinations will not be evaluated            │
│                                                             │
│ ▸ Customize criteria and combinations   (reveals matrix)    │
│                                                             │
│ Remember these selections for my next scan        [toggle]  │
│                                                             │
│                       [Cancel]   [Start scan →]             │
└─────────────────────────────────────────────────────────────┘
```

- **Scan profile**: Core 17 (recommended) · Saved scope · Custom · Everything supported.
- **File formats**: four large selectable cards (DOCX 15, XLSX 13, PPTX 17, PDF 14 supported
  criteria — counts derived from the capability registry, not hardcoded), with Select all / Clear all.
- **Summary line**: `<profile> · <n> formats · <n> supported checks` + `<n> unsupported combinations
  will not be evaluated`.
- **Customize criteria and combinations**: collapsed; reveals the detailed matrix for experts.

## Matrix (only when expanded) — improvements

- Sticky header row and criterion column.
- Group criteria by WCAG principle: Perceivable / Operable / Understandable / Robust, with
  group-level All / None.
- Column-level checkboxes in each format header (DOCX/XLSX/PPTX/PDF).
- Replace each row's `none` button with a single row checkbox / compact **Select row**.
- Unsupported cells: muted, **Not supported** on hover (not a dash that reads as "off").
- Visually distinguish: Selected / Available-but-excluded / Unsupported.
- Search + filters: Selected only · Level A/AA · Supported by all selected formats ·
  Deterministic / assisted / human-review.
- The current `all` / `none` controls read as status values, not actions — replace them.

## Wording

Top paragraph → **"Choose what this scan should evaluate. The same scope will be used for
assessment, remediation, reporting, and export."** Scoring caveat behind an info icon:
"Unsupported combinations are reported as 'Not evaluated' and are never counted as passes."

Renames:
- `No restriction` → **Everything supported**
- `Restrict to pairs selected below` → **Custom scope**
- `Load "acp-core-17"` → **Core 17**
- `Load "engagement-14"` → **Engagement 14**
- `Save scope` → **Save as reusable scope**
- `57 of 61 pairs selected` → **57 supported checks selected**

## Phasing (build order)

- **Phase 1 (frontend, vitest-verifiable):** the wizard modal — profile picker, format cards,
  summary line, wording renames, "Customize" reveal wrapping the *existing* grid, "Remember"
  toggle, required before scan (gates the Integrations "Scan all sources"). Keep the collapsed
  panel on the tab.
- **Phase 2 (frontend):** the matrix redesign (sticky, principle-grouping, column/row/group
  controls, cell states, search/filters).
- **Phase 3 (backend, needs a runnable suite):** frozen `scan_scope_snapshot` per scan; downstream
  (Discover/Assess/Remediate/report/export) reads the frozen scope; scope chip in Assess/Remediate;
  "Change scope and rescan"; impact estimate (files · checks · time); format-present gating.
- **Phase 4:** "Saved scope" named configs (save/load beyond the two presets).
