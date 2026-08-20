import { describe, it, expect, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createTestRoot, unmountAll } from './testRoots.js'

// WHEN the inventory was taken, on the results header (approved board 5).
//
// The header carried the source and folder count and stopped. The missing half decides whether
// the numbers below are worth acting on: this estate gets re-scanned, and an undated inventory is
// indistinguishable from a current one. Same class as a count with no denominator — every number
// is true and the reader's conclusion is not.
//
// The case this file exists for is the ABSENT one. A results header that invented today's date
// for a run it cannot date would be worse than one that gives no date at all, because it would
// be confidently wrong in the direction that says "this is fresh".

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const here = dirname(fileURLToPath(import.meta.url))
const read = (f) => readFileSync(join(here, f), 'utf8')

const { default: DiscoveryResults } = await import('./DiscoveryResults.jsx')

const FILES = [
  { file: 'a.docx', name: 'a.docx', status: 'done' },
  { file: 'b.pdf', name: 'b.pdf', status: 'done' },
]

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => {
    root.render(createElement(DiscoveryResults, { files: FILES, ...props }))
  })
  return container.textContent
}

afterEach(() => unmountAll())

describe('Discovery results header states when the inventory was taken', () => {
  it('prints the run stamp beside the scope', async () => {
    const t = await mount({ scopeLine: 'SharePoint / OneDrive · 2 folders', runAt: 'Aug 20, 2026, 4:04 PM PDT' })
    expect(t).toContain('SharePoint / OneDrive · 2 folders')
    expect(t).toContain('run Aug 20, 2026, 4:04 PM PDT')
  })

  it('renders NO date at all when the run cannot be dated', async () => {
    const t = await mount({ scopeLine: 'SharePoint / OneDrive · 2 folders', runAt: null })
    expect(t).toContain('SharePoint / OneDrive · 2 folders')
    // Not "run", not a separator left dangling, and above all not a manufactured date.
    expect(t).not.toMatch(/\brun\s/)
    expect(t).not.toContain('· ·')
    // Nothing that looks like a date reached the header — in EITHER shape. A mutation that filled
    // the gap with `new Date().toLocaleDateString()` produced "8/20/2026", which a month-name-only
    // pattern sails straight past, so the numeric form is pinned too.
    expect(t).not.toMatch(/\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}/)
    expect(t).not.toMatch(/\b\d{1,2}\/\d{1,2}\/\d{2,4}\b/)
    expect(t).not.toMatch(/\b\d{4}-\d{2}-\d{2}/)
  })

  it('prints the stamp alone when there is no recorded scope', async () => {
    const t = await mount({ scopeLine: null, runAt: 'Aug 20, 2026, 4:04 PM PDT' })
    expect(t).toContain('run Aug 20, 2026, 4:04 PM PDT')
    // No leading separator with nothing before it.
    expect(t).not.toMatch(/·\s*run Aug/)
  })

  it('renders neither when neither is known', async () => {
    const t = await mount({ scopeLine: null, runAt: null })
    expect(t).not.toMatch(/\brun\s/)
    expect(t).toContain('DISCOVERY RESULTS')      // the screen itself still renders
  })
})

describe('the stamp is formatted by the caller, in the app-wide format', () => {
  it('DiscoveryResults owns no date format', () => {
    const s = read('DiscoveryResults.jsx')
    // A component that starts formatting dates is how a product ends up with one stamp format per
    // screen. It prints the string it is given.
    //
    // DATE APIs only. `toLocaleString` is deliberately not banned here: this file calls it a dozen
    // times to format NUMBERS (n.toLocaleString(), rec.sum.toLocaleString()), and a ban that wide
    // fails on correct code while saying nothing about dates — testing the vocabulary instead of
    // the claim.
    expect(s).not.toMatch(/toLocaleDateString|toLocaleTimeString|new Date\(/)
    expect(s).not.toMatch(/Intl\.DateTimeFormat/)
  })

  it('App formats it with fmtStamp, the same helper the run header uses', () => {
    expect(read('App.jsx')).toMatch(/runAt=\{fmtStamp\(run\?\.completed_at\)\}/)
  })

  it('Discover forwards it rather than deriving its own', () => {
    const s = read('Discover.jsx')
    expect(s).toMatch(/runAt = null/)              // accepted as a prop
    expect(s).toMatch(/<DiscoveryResults[\s\S]{0,200}?runAt=\{runAt\}/)
  })
})
