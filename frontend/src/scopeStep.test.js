import { describe, it, expect } from 'vitest'
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// The scope grid's PLACEMENT is the v2 change, not the grid itself — that ported unmodified from
// frontend/, where it sits behind Platform settings → Scan scope. What is new here is that it
// runs BEFORE discovery, which is the order the decision actually happens in.
//
// Source-level for the same reason as v2Simplification.test.js: this asserts where a component
// sits in a tree, and a mount that silently rendered neither Discover's header nor the panel
// would pass a "the panel is absent from Settings" check while failing the user completely.
// scanScope.test.jsx already covers the component's BEHAVIOUR at the DOM level; this covers
// only the wiring that behaviour test cannot see.

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')

describe('v2: scan scope is a pre-discovery step', () => {
  it('ships the grid and its behaviour tests in v2', () => {
    expect(existsSync(join(HERE, 'ScanScope.jsx'))).toBe(true)
    expect(existsSync(join(HERE, 'scanScope.test.jsx'))).toBe(true)
  })

  // SUPERSEDED 2026-08-20. The three cases here pinned ScanScope's PLACEMENT on the Discover tab
  // — imported there, above the estate bar, open before an estate exists. That placement was the
  // v2 change when this file was written, and the product has since moved past it.
  //
  // Discover asks ONE question: WHERE to inventory. Which document types and which WCAG criteria
  // are Assess's question, and AssessSetup owns both there now. Keeping the picker on Discover
  // asked the same thing twice with two answers — and asked it at a stage where it does not
  // apply, since discovery is metadata-only (ADR 0020) and lists every file whatever the criteria
  // say. #532 began removing that conflation and #549 fixed the wizard hint; this was the last
  // of it, still live on the tab itself.
  //
  // What replaces them below is not a loosening. The removal is pinned in both directions, and
  // the two guards that were never about placement — no second editor in Settings, and the grid
  // stays generated — are kept exactly as they were.

  it('no longer asks the assess question on the discovery tab', () => {
    // COMMENTS STRIPPED FIRST. The comment explaining the removal necessarily quotes the copy
    // being removed, so a whole-file ban matches its own protected explanation and fails on
    // correct code — testing the vocabulary instead of the claim. The claim is about what the
    // component RENDERS, so the assertions run against the source with comments removed.
    const d = read('Discover.jsx')
      .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')     // JSX comments
      .replace(/\/\*[\s\S]*?\*\//g, '')           // block comments
      .replace(/^\s*\/\/.*$/gm, '')                // line comments
    expect(d).not.toMatch(/<ScanScope\s*\/>/)
    expect(d).not.toContain("import ScanScope from './ScanScope.jsx'")
    // The copy went with it. "before you scan" was the part that actively misled: it invited a
    // criterion choice to be read as narrowing what discovery would list.
    expect(d).not.toContain('criteria and file types, before you scan')
    expect(d).not.toContain('1 · Choose what to assess')
    // The stripper must not be what makes this pass — if it ate the whole file, every negative
    // assertion above would hold vacuously.
    expect(d).toContain('export default function Discover')
    expect(d.length).toBeGreaterThan(2000)
  })

  it('the org-scope picker (ScanScope) is not in Settings', () => {
    // MyScanScope (per-user override) is intentionally in Settings as the My Scope tab (R7).
    // ScanScope (org-level default picker) must stay out — two editors for the org default is
    // how an operator reads a stale value in one place after saving in the other.
    expect(read('Settings.jsx')).not.toContain("import ScanScope from './ScanScope.jsx'")
    expect(read('Settings.jsx')).not.toMatch(/<ScanScope\s*\/>/)
  })

  it('records that ScanScope.jsx is now mounted nowhere', () => {
    // Deliberately asserted rather than left implicit. The component is orphaned: no screen
    // renders it. That is a real state, and an unmounted component is exactly the thing that
    // reads as shipped on a status list while rendering for nobody — so it is written down here
    // instead of being discovered again in six weeks.
    //
    // Deleting it is a SEPARATE decision from removing the panel and has not been taken. When it
    // is, this case goes with the file.
    const mounts = ['Discover.jsx', 'Overview.jsx', 'Settings.jsx', 'App.jsx', 'ScanSetup.jsx']
      .filter((f) => existsSync(join(HERE, f)))
      .filter((f) => /<ScanScope\s*\/>/.test(read(f)))
    expect(mounts).toEqual([])
  })

  it('keeps the grid derived — v2 imports the generated module, never a literal', () => {
    const s = read('ScanScope.jsx')
    expect(s).toContain("from './scopePresets.js'")
    // If someone inlines the universe to "avoid the import", the codegen guard stops applying
    // and the panel can drift from the backend silently — the failure the generator exists for.
    expect(s).not.toMatch(/const\s+SCOPE_UNIVERSE\s*=/)
  })

  // REMOVED 2026-08-19 — the two cross-tree comparisons that lived here.
  //
  // They guarded the fork: one pinned the exact divergence between frontend/'s ScanScope and
  // v2's in both directions, so "an unrelated fix applied to one SPA shows up here as an
  // unexpected line"; the other kept frontend/ unnarrowed, as the working backup of the
  // deployed app.
  //
  // Both properties are now unreachable rather than unimportant: the v2 redesign replaced
  // frontend/ in place, so there is one tree and no second copy for a patch to miss. Deleting
  // them is not a loosening — with the fork gone, they compared a file to itself and passed
  // vacuously, which is a worse guard than none. The four cases above still assert the real
  // wiring (the grid ships, renders inside Discover and not Settings, sits above the estate
  // bar, opens before an estate exists).
})
