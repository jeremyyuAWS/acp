/**
 * P1.1 — Walk v2 on a cleared browser.
 *
 * The backlog item names three specific invariants that must hold when localStorage contains
 * nothing (fresh browser / private tab / explicitly cleared):
 *
 *   1. .docx is ticked on by default — the operator never has to enable it explicitly.
 *   2. Discover is filtered by the same config — excluded types do not appear in the inventory.
 *   3. Assess / Remediate / Overview count the SAME population — one filter, applied once.
 *
 * "Everything verified so far has been static (bundle contents, minified strings, traffic
 * weights). localStorage must be cleared first or the old config masks the change."
 *
 * These tests run against functions and source text, not against a mounted App, for the same
 * reason scanBehaviourDefaults.test.js does: mounting the whole provider tree to read one
 * initial useState value buries the signal in infrastructure noise.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const HERE = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(HERE, f), 'utf8')

import { loadFileTypeConfig, visibleForFileTypes } from './FileTypeConfig.jsx'

// Snapshot and restore localStorage so tests do not bleed into each other.
let _ls
beforeEach(() => { _ls = { ...localStorage }; localStorage.clear() })
afterEach(() => { localStorage.clear(); Object.entries(_ls).forEach(([k, v]) => localStorage.setItem(k, v)) })


// ── 1. .docx ticked by default ───────────────────────────────────────────────────────────────

describe('.docx is on by default from a cleared browser', () => {
  it('returns docx: true when localStorage holds nothing', () => {
    // The LS_KEY ('mova_filetypes') is absent — no stored overrides.
    expect(localStorage.getItem('mova_filetypes')).toBeNull()
    const cfg = loadFileTypeConfig()
    expect(cfg.docx).toBe(true)
  })

  it('returns true for every known type, not just docx', () => {
    // Every format in KNOWN defaults on so a fresh install has no invisible blind spots.
    const cfg = loadFileTypeConfig()
    for (const ext of ['pdf', 'docx', 'pptx', 'xlsx', 'html', 'video', 'audio']) {
      expect(cfg[ext], `${ext} should default to true from empty localStorage`).toBe(true)
    }
  })

  it('still respects an explicit false stored in localStorage', () => {
    // The default is not sticky — an operator who unticked pdf gets pdf off.
    localStorage.setItem('mova_filetypes', JSON.stringify({ pdf: false }))
    const cfg = loadFileTypeConfig()
    expect(cfg.pdf).toBe(false)
    // …but docx is unaffected by someone else's preference for pdf.
    expect(cfg.docx).toBe(true)
  })

  it('recovers gracefully from a corrupt stored value', () => {
    // JSON.parse failure in localStorage must not crash the app — loadConfig() catches it.
    localStorage.setItem('mova_filetypes', 'not-json')
    const cfg = loadFileTypeConfig()
    expect(cfg.docx).toBe(true)
  })
})


// ── 2. Discover filters by the same config ───────────────────────────────────────────────────

describe('Discover uses the same filter as every other tab', () => {
  const appSrc = read('App.jsx')

  it('App applies visibleForFileTypes once, from the shared module', () => {
    // The filter used to live inside Discover as an inline files.filter(), so Assess, Remediate
    // and Overview got the unfiltered list. App.jsx now owns the one filtered `files` memo.
    expect(appSrc).toMatch(/import \{[^}]*\bvisibleForFileTypes\b[^}]*\} from '\.\/FileTypeConfig\.jsx'/)
    expect(appSrc).toMatch(/visibleForFileTypes\(allFiles, fileTypeConfig\)/)
  })

  it('App exposes exactly one `files` binding from that filter', () => {
    // Two parallel filtered lists would let any tab quietly see a different population.
    const matches = [...appSrc.matchAll(/\bvisibleForFileTypes\b/g)]
    expect(matches.length).toBe(2) // import + one call-site
  })

  it('the filter config is initialised from loadFileTypeConfig — the localStorage-backed source', () => {
    expect(appSrc).toMatch(/import \{[^}]*\bloadFileTypeConfig\b[^}]*\} from '\.\/FileTypeConfig\.jsx'/)
    expect(appSrc).toMatch(/useState\(loadFileTypeConfig\)/)
  })

  it('a type set false disappears from the filtered list', () => {
    const files = [
      { file: 'report.docx', type: 'docx' },
      { file: 'slide.pptx', type: 'pptx' },
      { file: 'data.pdf', type: 'pdf' },
    ]
    const cfg = { ...loadFileTypeConfig(), pptx: false }
    const visible = visibleForFileTypes(files, cfg)
    expect(visible.map((f) => f.type).sort()).toEqual(['docx', 'pdf'])
  })

  it('from a cleared browser, the default config shows all three types', () => {
    // On a fresh install the operator sees the full estate — nothing hidden by an absent preference.
    const files = [
      { file: 'report.docx', type: 'docx' },
      { file: 'slide.pptx', type: 'pptx' },
      { file: 'data.pdf', type: 'pdf' },
    ]
    const cfg = loadFileTypeConfig()   // empty localStorage → all DEFAULTS true
    expect(visibleForFileTypes(files, cfg)).toHaveLength(3)
  })
})


// ── 3. Assess / Remediate / Overview count the same population ───────────────────────────────

describe('Assess, Remediate, and Overview all read from the one filtered list', () => {
  const appSrc = read('App.jsx')

  it('every tab receives the same `files` prop, not allFiles', () => {
    // Check that allFiles is never passed directly as a tab prop. The filtered binding `files`
    // is what every panel downstream sees.
    //
    // App renders something like <TabPanel files={files} ...>. A tab receiving `allFiles`
    // directly would bypass the filter and count a different population.
    expect(appSrc).not.toMatch(/\bAssessRunner\b[^/\n]*\ballFiles\b/)
    expect(appSrc).not.toMatch(/\bRemediate\b[^/\n]*\ballFiles\b/)
    expect(appSrc).not.toMatch(/\bOverview\b[^/\n]*\ballFiles\b/)
  })

  it('coreStats (Assess) and remediableCount (Remediate) are imported from separate modules', () => {
    // Their formulas differ by design (coreStats counts criteria; remediableCount counts files
    // with a fix route). The point is that they both operate on the same `files` array — neither
    // adds its own secondary filter on top.
    const assessSrc = read('AssessRunner.jsx')
    const simSrc = read('sim.js')
    expect(assessSrc).toMatch(/import \{[^}]*\bcoreStats\b[^}]*\} from '\.\/coreStats\.js'/)
    expect(simSrc).toMatch(/export (const|function) remediableCount/)
  })

  it('coreStats is not re-implemented by Remediate or Overview', () => {
    // Two independent formulas would disagree whenever the scope or the capability table changed,
    // because neither would know the other existed. coreStats.test.js pins it against AssessRunner.
    for (const f of ['Remediate.jsx', 'Overview.jsx']) {
      const src = read(f)
      expect(src, `${f} re-implements coreStats instead of importing it`)
        .not.toMatch(/function coreStats\b/)
      expect(src, `${f} re-implements coreStats as an arrow instead of importing it`)
        .not.toMatch(/const coreStats\s*=\s*\(/)
    }
  })
})
