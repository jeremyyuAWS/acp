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

  it('differs from the frontend/ copy in exactly one way: the criteria it offers', () => {
    // This was a byte-identity check — two SPAs, one component — and it held until v2 deliberately
    // narrowed the grid to the 17 tracked criteria while frontend/ stayed the backup of the
    // shipped app. Byte-identity is the wrong guard for a fork, but the property it protected is
    // still worth having: any OTHER divergence should be a decision someone made, not a patch
    // that landed in one tree and not the other.
    //
    // So compare code lines and pin the divergence in BOTH directions. An unrelated fix applied to
    // one SPA shows up here as an unexpected line, exactly as it did before. Comments are excluded
    // — the v2 rationale lives in them and is expected to differ.
    const code = (s) => s.split('\n').map((l) => l.trim())
      .filter((l) => l && !l.startsWith('//'))
    const v2 = code(read('ScanScope.jsx'))
    const v1 = code(readFileSync(join(HERE, '..', '..', 'frontend', 'src', 'ScanScope.jsx'), 'utf8'))
    // Multiset difference, then sorted. Sorted because a line that appears in both files a
    // different NUMBER of times (`)}` does) leaves its unmatched copy at whichever position the
    // matching happened to consume last — an ordering that carries no meaning and would fail on a
    // reformat. The set of differing lines is the claim; where they sit is not.
    const only = (a, b) => {
      const rest = [...b]
      return a.filter((l) => {
        const i = rest.indexOf(l)
        if (i === -1) return true
        rest.splice(i, 1)
        return false
      }).sort()
    }

    expect(only(v1, v2), 'frontend/ has code v2 dropped').toEqual([
      'const total = SCOPE_UNIVERSE.reduce((n, r) => n + r.formats.length, 0)',
      '{SCOPE_UNIVERSE.map((row) => (',
    ])
    expect(only(v2, v1), 'v2 has code frontend/ does not').toEqual([
      ')}',
      '.filter(([sc, fmts]) => fmts.size && !OFFERED.some((r) => r.sc === sc))',
      '.map(([sc]) => sc)',
      '.sort()',
      "<> · <b title={`Not shown: ${hidden.join(', ')}`}>{hidden.length} outside the tracked list</b></>",
      'const OFFERED = SCOPE_UNIVERSE.filter((r) => TRACKED_17.has(r.sc))',
      'const hidden = Object.entries(sel)',
      'const total = OFFERED.reduce((n, r) => n + r.formats.length, 0)',
      "import { TRACKED_17 } from './ruleDetails.js'",
      '{OFFERED.map((row) => (',
      '{hidden.length > 0 && (',
    ])
  })

  it('keeps the divergence one-directional — frontend/ stays the backup, unnarrowed', () => {
    // The v1 SPA is the working backup of what is deployed today. Narrowing it too would make the
    // fork invisible and remove the thing being backed up.
    const v1 = readFileSync(join(HERE, '..', '..', 'frontend', 'src', 'ScanScope.jsx'), 'utf8')
    expect(v1).not.toContain('TRACKED_17')
  })
})
