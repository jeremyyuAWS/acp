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

  it('renders inside Discover, not Settings', () => {
    const d = read('Discover.jsx')
    expect(d).toContain("import ScanScope from './ScanScope.jsx'")
    expect(d).toMatch(/<ScanScope\s*\/>/)
    // Deliberately NOT also in Settings: two editors of one setting is how an operator ends up
    // reading a stale value in one place after saving in the other. Front and centre means
    // moved, not duplicated.
    expect(read('Settings.jsx')).not.toContain('ScanScope')
  })

  it('sits above the estate bar, so the choice precedes the scan', () => {
    const d = read('Discover.jsx')
    const scope = d.indexOf('<ScanScope')
    const estate = d.indexOf('className="estatebar"')
    expect(scope).toBeGreaterThan(-1)
    expect(estate).toBeGreaterThan(-1)
    expect(scope, 'the scope step must render before the scan controls').toBeLessThan(estate)
  })

  it('is open before an estate exists and collapsed after', () => {
    // The whole point of "pre-discovery": open when the choice is free, collapsed once results
    // are on screen, because narrowing afterwards leaves the scope disagreeing with the numbers
    // beside it. A hard-coded `open` would nag forever; no `open` would hide it exactly when it
    // matters most.
    expect(read('Discover.jsx')).toMatch(/<details[^>]*open=\{files\.length === 0\}/)
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
