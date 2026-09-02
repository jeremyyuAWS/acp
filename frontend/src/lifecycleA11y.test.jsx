/**
 * The lifecycle control plane, exercised the way somebody without a mouse or a monitor uses it.
 *
 * PRD §15.11 makes this an acceptance criterion of the FIRST increment — "keyboard and
 * screen-reader tests cover the summary, ledger, filters, and two-panel review" — and §12 lists
 * what that means. lifecycleControlPlane.test.jsx already covers what these panels SAY, via
 * renderToStaticMarkup and string matching. That cannot see any of this: a string match cannot
 * tell a <button> from a <div onClick>, cannot watch aria-expanded change, and cannot notice
 * that the only thing distinguishing two rows is their colour.
 *
 * So this file mounts them in a real DOM instead, and asserts the four things a string match
 * structurally cannot:
 *
 *   1. colour is never the only carrier of meaning (1.4.1), and the colours used still clear
 *      AA (1.4.3) — measured with ACP's OWN detector, remediationEvidence.contrastRatio, which
 *      is the function it certifies customer documents with;
 *   2. the decorative bar has an equivalent table (§12), and is hidden from assistive tech
 *      rather than read out as nine anonymous spans;
 *   3. every control is natively operable — a real <button>, not a div wearing an onClick,
 *      which is the defect that passes every visual review and every string assertion;
 *   4. run state is announced politely and ONCE, not per file (§12).
 *
 * Deliberately NOT asserted: prefers-reduced-motion (§12). These four components animate
 * nothing, so a test for it would pass by describing an absence and would keep passing if the
 * requirement were violated in the component that will actually need it — the Lifecycle Activity
 * Feed of §7.3, which is not built yet. A test that cannot fail is not coverage.
 */
import { describe, it, expect, afterEach, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import { contrastRatio } from './remediationEvidence.js'
import LifecycleEstateSummary from './LifecycleEstateSummary.jsx'
import LifecycleRuleLedger from './LifecycleRuleLedger.jsx'
import LifecycleEvidencePanel from './LifecycleEvidencePanel.jsx'
import DispositionReviewWorkspace from './DispositionReviewWorkspace.jsx'

vi.mock('./api.js', () => ({
  getLifecycleFiles: vi.fn(async () => ({ rows: [
    { file: 'old.docx', lifecycle_status: 'Archive Candidate', lifecycle_reason: 'older than the cutoff' },
    { file: 'new.docx', lifecycle_status: 'Active', lifecycle_reason: '' },
  ] })),
  // Added when the review panel started loading a history alongside the detail: a mock that
  // omits a function the component now calls fails as an unhandled rejection, not as a
  // readable assertion, so the mock has to track the module's real surface.
  getLifecycleFileHistory: vi.fn(async () => ({ events: [] })),
  getLifecycleFileDetail: vi.fn(async (_scan, file) => ({
    file, path: `/estate/${file}`, lifecycle_status: 'Archive Candidate',
    lifecycle_reason: 'older than the cutoff', lifecycle_rule_id: 'retention',
    evaluations: [{ evaluation_id: 'e1', policy_id: 'retention', policy_version: 2,
      result: 'matched', evidence: { conditions: [{ field: 'modified_age_days',
        observed_value: 730, op: 'gte', value: 365, reason: '730 is at least 365' }] } }],
  })),
}))

afterEach(unmountAll)

const CARD = '#ffffff'          // styles.css --card, the surface these panels are drawn on

const SUMMARY = {
  total: 10, reconciled_total: 10, assessment_excluded: 3,
  counts: { active: 5, already_archived: 1, archive_candidate: 2, delete_candidate: 0,
    deleted: 0, exempt: 1, reactivated: 0, unevaluable: 1, failed: 0 },
}

const RULES = [{
  policy_id: 'retention', policy_version: 3, name: 'Legacy files', priority: 1,
  evaluated: 20, matched: 5, skipped: 4, unevaluable: 2, conflicts: 1,
  proposed_action: 'archive', evaluated_at: '2026-09-01T00:00:00Z',
}]

async function mount(Component, props = {}) {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(Component, props)) })
  return container
}

const text = (el) => (el.textContent || '').replace(/\s+/g, ' ').trim()

/** jsdom reports an inline colour as "rgb(r, g, b)"; ACP's detector takes hex. */
const toHex = (value) => {
  const m = /^rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(value || '')
  if (m) return '#' + m.slice(1, 4).map((n) => Number(n).toString(16).padStart(2, '0')).join('')
  return (value || '').trim().toLowerCase()
}

// ── 1. colour is never the only signal ───────────────────────────────────────

describe('disposition colour never carries meaning alone', () => {
  it('labels every segment in text, so the breakdown survives greyscale', async () => {
    const c = await mount(LifecycleEstateSummary, { summary: SUMMARY })
    // Every disposition in the model, spelled out. If a future edit drops a label and keeps the
    // swatch, this is what notices — 1.4.1 is the criterion ACP itself reports on.
    for (const label of ['Active', 'Already archived', 'Archive candidate', 'Delete candidate',
                         'Moved to source trash', 'Exempt / legal hold', 'Reactivated',
                         'Unevaluable / conflict', 'Source action failed']) {
      expect(text(c), `"${label}" has no text label — colour is its only carrier`).toContain(label)
    }
  })

  it('hides the decorative swatches from assistive tech', async () => {
    const c = await mount(LifecycleEstateSummary, { summary: SUMMARY })
    // The ● glyphs duplicate the adjacent text label. Left exposed they read as a row of
    // meaningless bullets between every count.
    const dots = [...c.querySelectorAll('span')].filter((s) => text(s) === '●')
    // Counted first, because the loop below is vacuous if the glyph ever changes: a test that
    // examines nothing reports the same green as one that examined everything.
    expect(dots.length, 'no swatches found — this assertion would pass by examining nothing')
      .toBe(9)
    for (const dot of dots) {
      expect(dot.getAttribute('aria-hidden'), 'a decorative swatch is exposed to screen readers')
        .toBe('true')
    }
  })

  it('clears AA at every colour it actually draws, measured with ACP\'s own detector', async () => {
    // Read off the RENDERED swatches, never from a list copied into this file. The first draft
    // asserted nine hex literals and passed while the component drew something else entirely —
    // caught by mutating a colour and watching this stay green, which is the whole argument for
    // bite-checking a test that passes the moment you write it.
    //
    // contrastRatio is not a palette helper: it is the function ACP runs against customer
    // documents for 1.4.3. The product failing its own criterion in its own UI is the specific
    // embarrassment ownContrast.test.js exists to prevent, and these nine arrived after it.
    const c = await mount(LifecycleEstateSummary, { summary: SUMMARY })
    const swatches = [...c.querySelectorAll('span')].filter((s) => text(s) === '●')
    expect(swatches.length, 'no swatches rendered — nothing was measured').toBe(9)
    for (const swatch of swatches) {
      const hex = toHex(swatch.style.color)
      expect(hex, `could not read a colour from "${swatch.style.color}"`).toMatch(/^#[0-9a-f]{6}$/)
      const ratio = contrastRatio(hex, CARD)
      expect(ratio, `${hex} renders at ${ratio.toFixed(2)}:1 on ${CARD} — below AA's 4.5:1`)
        .toBeGreaterThanOrEqual(4.5)
    }
  })
})

// ── 2. the chart has an equivalent table ─────────────────────────────────────

describe('the estate bar is not the only way to read the estate', () => {
  it('carries an equivalent table with a caption and every count', async () => {
    const c = await mount(LifecycleEstateSummary, { summary: SUMMARY })
    const table = c.querySelector('table')
    expect(table, 'the disposition bar has no equivalent table (§12)').toBeTruthy()
    expect(table.querySelector('caption'), 'the equivalent table has no caption').toBeTruthy()
    // The numbers themselves, not just the labels — a table of labels with no values is not an
    // equivalent of a bar chart.
    expect(text(table)).toContain('5')
    expect(text(table)).toContain('2')
  })

  it('states reconciliation politely rather than as an alert', async () => {
    const c = await mount(LifecycleEstateSummary, { summary: SUMMARY })
    const live = c.querySelector('[role="status"]')
    expect(live, 'the reconciliation total is not in a live region').toBeTruthy()
    expect(live.getAttribute('role'), 'reconciliation interrupts the user as an alert').toBe('status')
    expect(text(live)).toContain('10 of 10')
  })
})

// ── 3. every control is natively keyboard-operable ───────────────────────────

describe('the filters and the ledger work without a mouse', () => {
  it('makes each count a real button, not a div wearing an onClick', async () => {
    const picked = []
    const c = await mount(LifecycleEstateSummary, { summary: SUMMARY, onSelect: (s) => picked.push(s) })
    const buttons = [...c.querySelectorAll('button')]
    const five = buttons.find((b) => text(b) === '5')
    expect(five, 'the Active count is not a button — it cannot be reached by keyboard').toBeTruthy()
    expect(five.tagName).toBe('BUTTON')
    expect(five.getAttribute('tabindex'), 'a control was removed from the tab order').not.toBe('-1')
    await act(async () => { five.click() })
    expect(picked, 'activating a count filtered nothing').toEqual(['Active'])
  })

  it('gives the ledger real column headers', async () => {
    const c = await mount(LifecycleRuleLedger, { rules: RULES })
    const heads = [...c.querySelectorAll('th')].map(text)
    // Without <th>, every count is an anonymous cell: a screen reader reads "20, 5, 4, 2, 1"
    // with nothing saying which is which.
    for (const col of ['Rule', 'Evaluated', 'Matched', 'Skipped', 'Unevaluable', 'Conflicts']) {
      expect(heads, `the ledger has no "${col}" header`).toContain(col)
    }
  })

  it('announces the rule expander state through aria-expanded, and toggles it', async () => {
    const c = await mount(LifecycleRuleLedger, { rules: RULES })
    const expander = [...c.querySelectorAll('button')].find((b) => text(b) === 'Legacy files')
    expect(expander, 'the rule name is not an expander control').toBeTruthy()
    expect(expander.getAttribute('aria-expanded')).toBe('false')
    await act(async () => { expander.click() })
    expect(expander.getAttribute('aria-expanded'), 'expanding the rule did not update aria-expanded')
      .toBe('true')
    expect(text(c), 'the expanded detail omits the immutable policy version').toContain('version 3')
    await act(async () => { expander.click() })
    expect(expander.getAttribute('aria-expanded')).toBe('false')
  })

  it('routes a matched count to the review queue from the keyboard too', async () => {
    const picked = []
    const c = await mount(LifecycleRuleLedger, { rules: RULES, onSelect: (p) => picked.push(p) })
    const matched = [...c.querySelectorAll('button')].find((b) => text(b) === '5')
    expect(matched.tagName).toBe('BUTTON')
    await act(async () => { matched.click() })
    expect(picked).toEqual(['retention'])
  })
})

// ── 4. the two-panel review ──────────────────────────────────────────────────

describe('the two-panel review is navigable and states its selection non-visually', () => {
  it('exposes selection through aria-pressed rather than styling alone', async () => {
    const c = await mount(DispositionReviewWorkspace, { scanId: 'scan-1' })
    await act(async () => {})                                  // let the mocked fetch settle
    const rows = [...c.querySelectorAll('button')].filter((b) => text(b).includes('.docx'))
    expect(rows.length, 'the queue rendered no rows').toBe(2)
    expect(rows[0].tagName).toBe('BUTTON')
    expect(rows.every((b) => b.getAttribute('aria-pressed') !== null),
      'queue rows do not report their selected state to assistive tech').toBe(true)
    expect(rows[0].getAttribute('aria-pressed')).toBe('false')

    await act(async () => { rows[0].click() })
    await act(async () => {})
    const after = [...c.querySelectorAll('button')].filter((b) => text(b).includes('.docx'))
    expect(after[0].getAttribute('aria-pressed'),
      'selecting a file changed only its appearance').toBe('true')
  })

  it('announces the queue size once, not once per file', async () => {
    const c = await mount(DispositionReviewWorkspace, { scanId: 'scan-1' })
    await act(async () => {})
    const live = [...c.querySelectorAll('[role="status"], [aria-live]')]
    // §12: "Status updates use a polite live region and do not announce every file." A live
    // region per row turns a 6,000-file queue into 6,000 announcements.
    expect(live.length, 'more than one live region in the queue — this will announce per file')
      .toBe(1)
    expect(text(live[0])).toContain('2 files in this view')
  })

  it('gives the detail panel its own labelled landmark, so it is reachable independently', async () => {
    const c = await mount(DispositionReviewWorkspace, { scanId: 'scan-1' })
    await act(async () => {})
    const rows = [...c.querySelectorAll('button')].filter((b) => text(b).includes('.docx'))
    await act(async () => { rows[0].click() })
    await act(async () => {})
    const panel = c.querySelector('section[aria-labelledby="lifecycle-evidence-heading"]')
    expect(panel, 'the evidence panel is not a labelled region a screen reader can jump to')
      .toBeTruthy()
    expect(c.querySelector('#lifecycle-evidence-heading'), 'its label points at nothing').toBeTruthy()
  })

  it('reads the evidence as text, not as chips alone', async () => {
    // §12: "Rule expressions are readable as text, not only visual chips." The actual value and
    // the threshold both have to be in the accessible name, or the panel says a rule matched
    // without saying what it observed.
    const c = await mount(LifecycleEvidencePanel, { file: {
      file: 'old.docx', lifecycle_status: 'Archive Candidate', lifecycle_rule_id: 'retention',
      lifecycle_reason: 'older than the cutoff',
      evaluations: [{ evaluation_id: 'e1', policy_id: 'retention', policy_version: 2,
        result: 'matched', evidence: { conditions: [{ field: 'modified_age_days',
          observed_value: 730, op: 'gte', value: 365, reason: '730 is at least 365' }] } }],
    } })
    const t = text(c)
    expect(t).toContain('modified_age_days')
    expect(t).toContain('actual 730')
    expect(t).toContain('required gte 365')
    expect(t, 'the panel does not name the policy version it decided on').toContain('version 2')
  })

  it('says what to do when nothing is selected, rather than rendering an empty box', async () => {
    const c = await mount(LifecycleEvidencePanel, {})
    expect(text(c)).toContain('Select a file')
  })
})
