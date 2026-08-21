import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import AssessFileFindings from './AssessFileFindings.jsx'
import { documentRows } from './assessMetrics.js'
import { CAPABILITY_FALLBACK, ASSESSMENT_FALLBACK } from './capability.js'

// The last two components from the approved boards, and a sweep so there is never a third.
//
// An audit found exactly two that shipped and rendered for nobody: AssessFileFindings (board
// assess-05, from #546) and DiscoverInventoryExport (from #562). That is the same failure this
// codebase hit three times in one evening — a component merges, its own tests pass, the suite is
// green, and nothing mounts it. It was reported as "wired" twice before anyone checked.
//
// The sweep at the bottom is the part that matters. Pinning these two by name fixes today; a rule
// that every redesign component is reachable fixes the next one nobody has written yet.

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')
const code = (f) => read(f)
  .replace(/\{\/\*[\s\S]*?\*\/\}/g, '')
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/^\s*\/\/.*$/gm, '')

const cap = CAPABILITY_FALLBACK
const assessment = ASSESSMENT_FALLBACK

const FILES = [
  {
    file: 'policies/handbook.docx', name: 'handbook.docx', status: 'done', score: 62,
    issues: [
      { sc: '1.1.1', severity: 'CRITICAL', message: 'Image has no alt text' },
      { sc: '1.3.1', severity: 'SERIOUS', message: 'Headings skip a level' },
    ],
  },
]

describe('the per-file findings view is reachable', () => {
  it('App mounts AssessFileFindings', () => {
    const s = code('App.jsx')
    expect(s).toMatch(/import AssessFileFindings from '\.\/AssessFileFindings\.jsx'/)
    expect(s).toMatch(/<AssessFileFindings\b/)
  })

  it('the worklist hands it the ROW, not a re-looked-up file', () => {
    // documentRows ordered the list by what needs a person first. Passing the row means the view
    // renders that same derivation; re-deriving here could disagree with the list it was opened
    // from about which document matters most.
    const s = code('App.jsx')
    expect(s).toMatch(/onOpenFile=\{\(row\) => setAssessFile\(row\)\}/)
    expect(s).toMatch(/<AssessFileFindings row=\{assessFile\}/)
  })

  it('it takes over the results rather than stacking on them', () => {
    // It carries its own Back and next-document controls, which only make sense for a view that
    // owns the screen — the same arrangement RunDetails already uses.
    const s = code('App.jsx')
    expect(s).toMatch(/&& !runDetails && !assessFile && <><AssessSummary/)
  })

  it('and App no longer imports the drawer it replaced', () => {
    // FileDrawer is not deleted — Overview still mounts it. But an import nothing renders is the
    // kind of dead reference that makes the next reader think this screen still uses it.
    expect(code('App.jsx')).not.toMatch(/import FileDrawer from/)
  })

  it('renders real content for a real row, not an empty frame', () => {
    // The mount tests cannot see this: the component returns null when it cannot derive findings,
    // so a shape mismatch would render blank with every test still green.
    const [row] = documentRows(FILES, { cap, assessment })
    const html = renderToStaticMarkup(createElement(AssessFileFindings, { row, cap, assessment }))
    const text = html.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim()
    expect(text.length).toBeGreaterThan(40)
    expect(text).toMatch(/1\.1\.1|1\.3\.1/)      // grouped BY CRITERION, which is the whole board
  })

  it('renders nothing for a document that was never opened', () => {
    // A document Assess never opened has NO findings, not zero findings. "0 findings · 0
    // auto-fixable" over a file ACP could not read is the most misleading thing this screen could
    // print, and the component's own comment says so.
    const [row] = documentRows([{ file: 'a.docx', name: 'a.docx', status: 'error' }], { cap, assessment })
    const html = renderToStaticMarkup(createElement(AssessFileFindings, { row, cap, assessment }))
    expect(html).toBe('')
  })
})

describe('the inventory export is reachable', () => {
  it('Discover mounts DiscoverInventoryExport', () => {
    const s = code('Discover.jsx')
    expect(s).toMatch(/import DiscoverInventoryExport from '\.\/DiscoverInventoryExport\.jsx'/)
    expect(s).toMatch(/<DiscoverInventoryExport\b/)
  })

  it('it is given the scan and the inventory it exports', () => {
    expect(code('Discover.jsx')).toMatch(/<DiscoverInventoryExport scanId=\{scanId\}[\s\S]{0,160}?inventory=/)
  })
})

describe('no redesign component ships unreachable', () => {
  // THE GENERAL RULE. Naming today's two fixes today; this catches the next one.
  //
  // Every component below was written for the approved boards and merged as a standalone module.
  // For each, SOME screen must render it. The list is explicit rather than globbed because a glob
  // would sweep in shared widgets, per-item children and anything a test file happens to define —
  // and a check that quietly matches nothing is worse than no check.
  const BOARD_COMPONENTS = [
    'AssessSetup', 'AssessSummary', 'AssessWorklist', 'AssessFileFindings',
    'DiscoveryResults', 'DiscoverInventoryExport', 'DiscoveryCompleteness', 'AssessmentReconciliation',
    'AssertionScope', 'NextStep', 'RunDetails',
    'RemediationWork', 'RemediationApprovals', 'ManualWork', 'RemediationVerify',
    'DeliveryPanel', 'CloseoutPanel', 'FixOutcomes', 'RemediationDocProgress', 'DocumentAudit',
  ]

  const screens = readdirSync(here).filter((f) => f.endsWith('.jsx') && !f.includes('.test.'))

  for (const name of BOARD_COMPONENTS) {
    it(`${name} is rendered by some screen`, () => {
      const mounted = screens.filter((f) => f !== `${name}.jsx`
        && new RegExp(`<${name}[\\s/>]`).test(code(f)))
      expect(mounted.length, `${name}.jsx exists but nothing renders it`).toBeGreaterThan(0)
    })
  }

  it('and the sweep is actually looking at files', () => {
    // Guards the whole block from passing vacuously if the directory read or the comment stripper
    // ever returns nothing.
    expect(screens.length).toBeGreaterThan(30)
    expect(code('App.jsx').length).toBeGreaterThan(5000)
  })
})
