import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { renderToStaticMarkup } from 'react-dom/server'
import { createTestRoot, unmountAll } from './testRoots.js'
import Overview from './Overview.jsx'

afterEach(unmountAll)

const here = dirname(fileURLToPath(import.meta.url))
const { default: AssessmentReconciliation } = await import('./AssessmentReconciliation.jsx')

// 12,408 discovered; 8,336 in an assessable format; xlsx (1,300) not selected by this run.
const INV = {
  discovered: 12408,
  assessment_eligible: 8336,
  truncated: false,
  by_format: { pdf: 3600, image: 3000, docx: 2900, xlsx: 1300, other: 1072, pptx: 536 },
  by_status: { assessable: 8336, metadata_only: 3000, unsupported: 1072, excluded: 0 },
}
const SCAN_SCOPE = { '1.1.1': ['docx', 'pdf', 'pptx'], '1.3.1': ['docx', 'pdf', 'pptx'] }

// A run whose file rows add up: 6,646 assessed + 47 unreadable, with 343 held back by lifecycle
// review and 1,300 dropped for their document type.
const doc = (i, over) => ({ file: `f${i}.docx`, score: 88, issues: [], ...over })
const rows = (assessed, unreadable) => [
  ...Array.from({ length: assessed }, (_, i) => doc(i)),
  ...Array.from({ length: unreadable }, (_, i) => doc(1000 + i, { status: 'error', score: null })),
]
const RUN = {
  id: 's1', files: 6693, certifiable: 6000, error: 47, avg_score: 88,
  scan_scope: SCAN_SCOPE,
  scope: {
    kind: 'drive', kept: 6693, truncated: false,
    skipped_out_of_scope: 1300,
    lifecycle_eligible_excluded: 343,
    lifecycle_overridden: 9,
    inventory: INV,
  },
}

let container, root
beforeEach(() => { ;({ container, root } = createTestRoot()) })
const render = async (props) => { await act(async () => { root.render(createElement(AssessmentReconciliation, props)) }) }
const text = () => container.textContent.replace(/\s+/g, ' ')

describe('the reconciliation renders every bucket and its arithmetic', () => {
  it('prints the addition and the discovered total it reaches', async () => {
    await render({ run: RUN, files: rows(6646, 47) })
    // The whole point: a reader can add these up on screen.
    expect(text()).toContain('6,646 + 343 + 1,300 + 4,072 + 47')
    expect(text()).toContain('12,408')
    expect(text()).toContain('account for all 12,408 discovered files')
  })

  it('names all five buckets', async () => {
    await render({ run: RUN, files: rows(6646, 47) })
    const t = text()
    for (const label of ['Assessed', 'Not eligible — lifecycle', 'Not eligible — type',
                         'Not eligible — no test exists', 'Not eligible — access or error']) {
      expect(t).toContain(label)
    }
  })

  it('shows every percentage with its denominator', async () => {
    await render({ run: RUN, files: rows(6646, 47) })
    // "53.6%" alone is an unexplained number; "53.6% of 12,408" is a claim a reader can check.
    const t = text()
    const percents = t.match(/\d+\.\d%/g) || []
    expect(percents.length).toBeGreaterThan(0)
    for (const p of percents) expect(t).toContain(`${p} of 12,408`)
  })

  it('says so — loudly, in a live region — when the rows do not reach the discovered total', async () => {
    // 500 eligible files this run never got to. Nothing may swell to absorb them.
    await render({ run: RUN, files: rows(6646 - 500, 47) })
    const t = text()
    expect(t).toContain('11,908 of 12,408 discovered files')
    expect(t).toContain('500 files are in no row above')
    expect(container.querySelector('[role="status"]')).not.toBe(null)
    expect(t).not.toContain('account for all 12,408')
  })

  it('says so when the rows OVERLAP and count files twice', async () => {
    const over = { ...RUN, scope: { ...RUN.scope, lifecycle_eligible_excluded: 543 } }
    await render({ run: over, files: rows(6646, 47) })
    expect(text()).toContain('200 MORE than the 12,408 files discovered')
    expect(text()).toContain('counted twice')
  })

  it('renders an unrecorded bucket as “not recorded”, never as 0', async () => {
    const noLifecycle = { ...RUN, scope: { ...RUN.scope, lifecycle_eligible_excluded: undefined, lifecycle_overridden: undefined } }
    await render({ run: noLifecycle, files: rows(6646, 47) })
    const t = text()
    expect(t).toContain('not recorded')
    // The lifecycle bucket must not appear in the equation at all — not even as "+ 0".
    expect(t).toContain('6,646 + 1,300 + 4,072 + 47')
    expect(t).toContain('One bucket was not recorded by this scan')
    expect(t).toContain('Not eligible — lifecycle')
  })

  it('describes the lifecycle bucket as a recommendation, never as an archive or a deletion', async () => {
    await render({ run: RUN, files: rows(6646, 47) })
    const t = text()
    expect(t).toContain('archive-or-delete recommendation awaiting a decision')
    expect(t).toContain('no file was moved or deleted')
    expect(t).not.toMatch(/\b343 (files )?(were )?(archived|deleted)\b/i)
  })

  it('reports overrides beside the lifecycle row, not as a sixth bucket', async () => {
    await render({ run: RUN, files: rows(6646, 47) })
    expect(text()).toContain('9 overridden and assessed')
    // Still five rows in the addition.
    expect(text()).toContain('6,646 + 343 + 1,300 + 4,072 + 47')
  })

  it('marks the counts a floor when the listing was truncated', async () => {
    const capped = { ...RUN, scope: { ...RUN.scope, inventory: { ...INV, truncated: true } } }
    await render({ run: capped, files: rows(6646, 47) })
    expect(text()).toContain('discovered total is a floor')
  })

  it('renders nothing at all without an inventory to partition', async () => {
    await render({ run: { id: 's2', scope: {} }, files: [] })
    expect(container.textContent).toBe('')
  })

  it('does not claim conformance — “assessed” is scoped to the criteria that ran', async () => {
    await render({ run: RUN, files: rows(6646, 47) })
    expect(text()).toContain('not that the file conforms to WCAG 2.1 AA')
  })
})

describe('Overview mounts the reconciliation', () => {
  const screen = (run, files) =>
    renderToStaticMarkup(createElement(Overview, {
      run, files, trend: [], trendDates: [], onGo: () => {}, scanList: [], onPickScan: () => {},
      me: { email: 'auditor@example.com' },
    })).replace(/<[^>]+>/g, ' ').replace(/&#x27;/g, "'").replace(/&amp;/g, '&').replace(/\s+/g, ' ')

  it('renders the panel and its arithmetic on the estate dashboard', () => {
    const html = screen(RUN, rows(6646, 47))
    expect(html).toContain('What was assessed, and what was not')
    expect(html).toContain('6,646 + 343 + 1,300 + 4,072 + 47')
  })

  it('leaves the dashboard alone when the scan carries no inventory', () => {
    const html = screen({ id: 's3', files: 3, certifiable: 1, scope: { kind: 'local' } }, rows(3, 0))
    expect(html).not.toContain('What was assessed, and what was not')
  })
})

// ── Source-level pins for what the DOM cannot show ────────────────────────────────────────────
describe('the wiring is where it says it is', () => {
  const overview = readFileSync(join(here, 'Overview.jsx'), 'utf8')
  const panel = readFileSync(join(here, 'AssessmentReconciliation.jsx'), 'utf8')

  it('Overview imports and renders the panel from the run’s own data', () => {
    expect(overview).toMatch(/import AssessmentReconciliation from '\.\/AssessmentReconciliation\.jsx'/)
    expect(overview).toMatch(/<AssessmentReconciliation run=\{run\} files=\{files\} \/>/)
  })

  it('the panel derives nothing itself — the model is the pure module', () => {
    // Every count comes from estateFunnel/reconciliationInputs. A number computed in JSX is a
    // number no unit test can reach.
    expect(panel).toMatch(/import \{ reconcileBuckets, bucketEquation \} from '\.\/estateFunnel\.js'/)
    expect(panel).toMatch(/import \{ reconciliationInputs \} from '\.\/reconciliationInputs\.js'/)
  })

  it('a share is never formatted without its denominator', () => {
    // One helper builds every percentage on this panel, and it always appends "of <discovered>".
    expect(panel).toMatch(/const share = \(row, discovered\) =>[\s\S]*?% of \$\{nf\.format\(discovered\)\}/)
  })
})
