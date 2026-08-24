import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

// Discover asks ONE question: WHERE to inventory.
//
// Which document types and which WCAG criteria apply is ASSESS's question, and AssessSetup owns it
// there. Discovery is metadata-only (ADR 0020) — it lists every file whatever the criteria say — so
// a criterion picker on this tab never changed what got listed. It only invited the reader to
// believe it did.
//
// That conflation came off in three passes. #532 stripped the format and criterion pickers from the
// scan wizard; #549 fixed the wizard hint that still said "assess"; today the two remaining scope
// panels went from the tab itself:
//
//   ScanScope    the org-level criteria picker ("1 · Choose what to assess")
//   MyScanScope  the per-user twin that widened those criteria for one reviewer's own scans
//
// Both components are KEPT and mounted nowhere, per the standing rule in CLAUDE.md: a UI removal
// deletes the mount, not the code, so restoring either is one commit. This file is the other half
// of that rule — an orphan nobody writes down reads as shipped on every status list, which is the
// failure this codebase hit repeatedly on 2026-08-20.

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

// Comments stripped: a comment explaining a removal necessarily names what it removed, and a
// whole-file ban then matches its own protected explanation.
const code = (f) => read(f)
  .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')

describe('Discover no longer asks which criteria to assess against', () => {
  it('mounts neither scope panel', () => {
    const d = code('Discover.jsx')
    expect(d).not.toMatch(/<ScanScope\s*\/>/)
    expect(d).not.toMatch(/<MyScanScope\s*\/>/)
    expect(d).not.toMatch(/import ScanScope from/)
    expect(d).not.toMatch(/import MyScanScope from/)
    // The stripper must not be what makes this pass.
    expect(d).toContain('export default function Discover')
    expect(d.length).toBeGreaterThan(2000)
  })

  it('and neither panel’s copy survives', () => {
    const d = code('Discover.jsx')
    expect(d).not.toContain('My scan scope')
    expect(d).not.toContain('assess more than the org default')
    expect(d).not.toContain('Choose what to assess')
  })

  it('while Assess still owns the question', () => {
    // Removing it from Discover is only correct because the question is answered elsewhere. If
    // AssessSetup ever stops carrying it, this becomes a capability deletion rather than a move.
    expect(code('App.jsx')).toMatch(/<AssessSetup\b/)
  })
})

describe('both components are kept, and recorded as retired', () => {
  it('ScanScope.jsx still exists and is mounted nowhere', () => {
    expect(existsSync(join(here, 'ScanScope.jsx')), 'kept so restoring is one commit').toBe(true)
    const screens = ['App.jsx', 'Discover.jsx', 'Overview.jsx', 'Settings.jsx', 'ScanSetup.jsx']
      .filter((f) => existsSync(join(here, f)))
      .filter((f) => /<ScanScope\s*[/>]/.test(code(f)))
    expect(screens, 'if ScanScope is mounted again, delete this case').toEqual([])
  })

  it('MyScanScope.jsx still exists (R7: now mounted as My Scope tab in Settings)', () => {
    expect(existsSync(join(here, 'MyScanScope.jsx')), 'kept so restoring is one commit').toBe(true)
  })

  it('the org-scope picker (ScanScope) is not duplicated into Settings', () => {
    // MyScanScope (per-user override) is intentionally in Settings as the My Scope tab (R7).
    // ScanScope (org-level default picker) must stay out — two editors for the org default is
    // how an operator reads a stale value in one place after saving in the other.
    expect(read('Settings.jsx')).not.toContain("import ScanScope from './ScanScope.jsx'")
    expect(read('Settings.jsx')).not.toMatch(/<ScanScope\s*\/>/)
  })
})
