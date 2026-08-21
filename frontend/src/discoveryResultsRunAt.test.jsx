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

// The header now takes an `inventorySnapshot()` result, not a pre-formatted string: the module
// resolves the instant AND says which record it came from, so the component can show provenance
// without deciding a date format.
const SNAP = (absolute, extra = {}) => ({
  recorded: true, absolute, label: 'recorded when discovery finished', stale: false, ...extra,
})
// `recorded: false` is a real answer and must render as one — it means nobody persisted the
// instant, never that the inventory is current.
const NOT_RECORDED = { recorded: false, absolute: null, label: null, stale: false }

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
    const t = await mount({ scopeLine: 'SharePoint / OneDrive · 2 folders', runAt: SNAP('Aug 20, 2026, 4:04 PM PDT') })
    expect(t).toContain('SharePoint / OneDrive · 2 folders')
    expect(t).toContain('listed Aug 20, 2026, 4:04 PM PDT')
  })

  it('renders NO date at all when the run cannot be dated', async () => {
    const t = await mount({ scopeLine: 'SharePoint / OneDrive · 2 folders', runAt: NOT_RECORDED })
    expect(t).toContain('SharePoint / OneDrive · 2 folders')
    // Not "run", not a separator left dangling, and above all not a manufactured date.
    expect(t).not.toMatch(/\blisted\s/)
    expect(t).not.toContain('· ·')
    // Nothing that looks like a date reached the header — in EITHER shape. A mutation that filled
    // the gap with `new Date().toLocaleDateString()` produced "8/20/2026", which a month-name-only
    // pattern sails straight past, so the numeric form is pinned too.
    expect(t).not.toMatch(/\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+\d{4}/)
    expect(t).not.toMatch(/\b\d{1,2}\/\d{1,2}\/\d{2,4}\b/)
    expect(t).not.toMatch(/\b\d{4}-\d{2}-\d{2}/)
  })

  it('prints the stamp alone when there is no recorded scope', async () => {
    const t = await mount({ scopeLine: null, runAt: SNAP('Aug 20, 2026, 4:04 PM PDT') })
    expect(t).toContain('listed Aug 20, 2026, 4:04 PM PDT')
    // No leading separator with nothing before it.
    expect(t).not.toMatch(/·\s*listed Aug/)
  })

  it('renders neither when neither is known', async () => {
    const t = await mount({ scopeLine: null, runAt: NOT_RECORDED })
    expect(t).not.toMatch(/\blisted\s/)
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

  it('App resolves it through discoverRunTime, never from completed_at directly', () => {
    // THE BUG THIS REPLACES. `run.completed_at` is written at ASSESS finalize (ADR 0020), so it is
    // NULL on a discover-only run — the exact screen this line lives on — and afterwards dates the
    // assessment rather than the listing. resolveInventoryTime prefers the real run-level stamp,
    // falls back to the newest per-file stamp, and takes completed_at only last, labelled as the
    // upper bound it is.
    const app = read('App.jsx')
    expect(app).toMatch(/runAt=\{inventorySnapshot\(/)
    expect(app).not.toMatch(/runAt=\{fmtStamp\(/)
  })

  it('shows the stale-snapshot warning the resolver computes', async () => {
    const t = await mount({ scopeLine: null, runAt: SNAP('Aug 1, 2026, 9:00 AM PDT', { stale: true }) })
    expect(t).toContain('this snapshot is over a day old')
  })

  it('does not cry stale on a fresh snapshot', async () => {
    // Guards the case above from passing on a component that warns unconditionally.
    const t = await mount({ scopeLine: null, runAt: SNAP('Aug 20, 2026, 4:04 PM PDT') })
    expect(t).not.toContain('over a day old')
  })

  it('Discover forwards it rather than deriving its own', () => {
    const s = read('Discover.jsx')
    expect(s).toMatch(/runAt = null/)              // accepted as a prop
    expect(s).toMatch(/<DiscoveryResults[\s\S]{0,200}?runAt=\{runAt\}/)
  })
})


describe('how much of this estate can be assessed at all', () => {
  // The KPI that reframes an engagement. Discovery lists everything; only some of it carries an
  // accessibility test. On 12,408 files where 22 are Office or PDF, that one number is the story —
  // and it was previously visible only inside a funnel and a bar chart, never as a headline.
  const INV = (extra) => ({ discovered: 12408, ...extra })

  it('renders the count when discovery measured it', async () => {
    const t = await mount({ inventory: INV({ assessment_eligible: 22 }) })
    // Asserted against the rendered PAIR, not the number alone. textContent runs the tile's value
    // straight into its label ("22can be assessed"), and \b matches only a word/non-word
    // transition — 2 to c is word-to-word, so a \b22\b here fails on correct output. Matching the
    // pair is also the stronger claim: it pins that this count belongs to THIS label.
    expect(t).toMatch(/22\s*can be assessed/i)
  })

  it('accepts the older by_status shape', async () => {
    const t = await mount({ inventory: INV({ by_status: { assessable: 3400 } }) })
    expect(t).toMatch(/3,400\s*can be assessed/i)
  })

  it('renders NOTHING when nothing measured it — never a zero', async () => {
    // "0 can be assessed" asserts the estate contains nothing testable, which is a discovery
    // result nobody obtained. Absent is the honest answer.
    const t = await mount({ inventory: INV({}) })
    expect(t).not.toMatch(/can be assessed/i)
  })

  it('reads the same definition the bucket reconciliation uses', async () => {
    // Two derivations of "assessable" on one screen would let the header contradict the partition
    // directly beneath it — the four-denominator defect in a new place.
    const src = read('discoveryRecommendations.js')
    expect(src).toMatch(/import \{ assessmentEligible \} from '\.\/estateFunnel\.js'/)
    expect(src).toMatch(/assessable: assessmentEligible\(inventory\)/)
  })
})
