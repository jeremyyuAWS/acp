import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import RemediationDocProgress from './RemediationDocProgress.jsx'

// R7 at the DOM level. The load-bearing assertion is the first one: a queue that has not arrived
// must not render as a document with nothing wrong with it.

afterEach(unmountAll)

const mount = async (props) => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(RemediationDocProgress, props)) })
  return container
}

const F = (over) => ({ id: over.id, file: 'Q3-plan.docx', rule_id: 'SC_1_3_1', ...over })

const QUEUE = [
  F({ id: 1, rule_id: 'SC_1_1_1', after: 'Bar chart of Q3 revenue' }), // to-review
  F({ id: 2 }),                                                        // authoring
  F({ id: 3, status: 'recheck' }),                                     // written
  F({ id: 4, status: 'verified' }),                                    // confirmed
  F({ id: 5, status: 'blocked' }),                                     // blocked
  F({ id: 6, file: 'other.pdf', status: 'verified' }),                 // another document
]

describe('RemediationDocProgress — absent is not zero', () => {
  it('a queue that has not loaded says so and renders no counts', async () => {
    const c = await mount({ queue: null, file: 'Q3-plan.docx' })
    expect(c.querySelector('.docprog-unloaded')).toBeTruthy()
    expect(c.textContent).toMatch(/hasn’t loaded yet/)
    // No stage rows, no bar, no reconciliation line — nothing a reader could mistake for a count.
    expect(c.querySelectorAll('.docprog-stage').length).toBe(0)
    expect(c.querySelector('.docprog-bar')).toBeNull()
    expect(c.querySelector('.docprog-reconcile')).toBeNull()
    expect(c.querySelector('.docprog-headline')).toBeNull()
    // Not one digit outside the document's own name — no "0", no "0 of 0", no percentage.
    const body = c.querySelector('p').textContent
    expect(body).not.toMatch(/\d/)
  })

  it('an empty queue is a real measured zero and says something different', async () => {
    const c = await mount({ queue: [], file: 'Q3-plan.docx' })
    expect(c.querySelector('.docprog-none')).toBeTruthy()
    expect(c.textContent).toMatch(/No remediation findings were recorded/)
    expect(c.querySelector('.docprog-unloaded')).toBeNull()
  })
})

describe('RemediationDocProgress — the pipeline', () => {
  it('reports one document’s findings, not the whole queue', async () => {
    const c = await mount({ queue: QUEUE, file: 'Q3-plan.docx' })
    expect(c.textContent).toContain('Q3-plan.docx')
    expect(c.querySelector('.docprog-headline').textContent).toBe('1 of 5 findings through the pipeline')
  })

  it('renders every stage with its count, including the empty ones', async () => {
    const c = await mount({ queue: QUEUE, file: 'Q3-plan.docx' })
    const rows = [...c.querySelectorAll('.docprog-stage')].map((r) => r.textContent)
    expect(rows.length).toBe(6)
    expect(rows[0]).toMatch(/Needs your review.*1$/)
    expect(rows[1]).toMatch(/Needs hand authoring.*1$/)
    expect(rows[2]).toMatch(/Fix written, not confirmed.*1$/)
    expect(rows[3]).toMatch(/Confirmed by re-scan.*1$/)
    expect(rows[4]).toMatch(/Settled without a fix.*0$/)
    expect(rows[5]).toMatch(/Blocked.*1$/)
  })

  it('marks where the document is being held, once', async () => {
    const c = await mount({ queue: QUEUE, file: 'Q3-plan.docx' })
    const current = c.querySelectorAll('.docprog-stage.current')
    expect(current.length).toBe(1)
    expect(current[0].textContent).toMatch(/Needs your review/)
    expect(current[0].textContent).toMatch(/where it is now/)
  })

  it('says what is left, split by who it is waiting on', async () => {
    const c = await mount({ queue: QUEUE, file: 'Q3-plan.docx' })
    expect(c.querySelector('.docprog-remaining').textContent)
      .toBe('2 need you · 1 awaiting the re-scan · 1 blocked')
  })

  it('prints the partition the counts must satisfy', async () => {
    const c = await mount({ queue: QUEUE, file: 'Q3-plan.docx' })
    expect(c.querySelector('.docprog-reconcile').textContent).toBe('1 + 1 + 1 + 1 + 0 + 1 = 5 findings')
  })

  it('labels the time figure as an estimate rather than a measurement', async () => {
    const c = await mount({ queue: QUEUE, file: 'Q3-plan.docx' })
    expect(c.querySelector('.docprog-effort').textContent)
      .toMatch(/an estimate from the kind of work left, not a measured time/)
  })
})

describe('RemediationDocProgress — the terminal states read differently', () => {
  it('a document whose fixes all cleared says exactly that', async () => {
    const c = await mount({
      queue: [F({ id: 1, status: 'verified' }), F({ id: 2, status: 'verified' })],
      file: 'Q3-plan.docx',
    })
    expect(c.querySelector('.docprog-headline').textContent)
      .toBe('All 2 findings on this document are confirmed by re-scan.')
    expect(c.querySelector('.docprog-remaining')).toBeNull()
    expect(c.querySelectorAll('.docprog-stage.current').length).toBe(0)
    // The whole bar is the confirmed segment; nothing settled.
    expect(c.querySelector('.docprog-bar-confirmed').style.width).toBe('100%')
    expect(c.querySelector('.docprog-bar-settled').style.width).toBe('0%')
  })

  it('a document that finished with NO fix written does not read as fixed', async () => {
    // Every finding rejected. It is through the pipeline, and nothing was remediated. The headline
    // must name the split, and the bar must not be a solid block of success.
    const c = await mount({
      queue: [F({ id: 1 }), F({ id: 2 })],
      file: 'Q3-plan.docx',
      decisions: { 1: { state: 'rejected' }, 2: { state: 'rejected' } },
    })
    const t = c.querySelector('.docprog-headline').textContent
    expect(t).toBe('All 2 findings on this document are through the pipeline — 0 confirmed by re-scan, 2 settled without a fix.')
    expect(c.querySelector('.docprog-bar-confirmed').style.width).toBe('0%')
    expect(c.querySelector('.docprog-bar-settled').style.width).toBe('100%')
    expect(c.querySelector('.docprog-bar').getAttribute('aria-label'))
      .toBe('0 of 2 findings confirmed by re-scan, 2 settled without a fix')
  })

  it('a document where everything is blocked is NOT reported as finished', async () => {
    const c = await mount({
      queue: [F({ id: 1, status: 'blocked' }), F({ id: 2, status: 'blocked' })],
      file: 'Q3-plan.docx',
    })
    const t = c.querySelector('.docprog-headline').textContent
    expect(t).toMatch(/All 2 findings on this document are blocked/)
    expect(t).not.toMatch(/through the pipeline/)
  })

  it('a document whose only remaining work is blocked still says so', async () => {
    const c = await mount({
      queue: [F({ id: 1, status: 'verified' }), F({ id: 2, status: 'blocked' })],
      file: 'Q3-plan.docx',
    })
    expect(c.querySelector('.docprog-headline').textContent).toBe('1 of 2 findings through the pipeline')
    expect(c.querySelector('.docprog-remaining').textContent).toBe('1 blocked')
  })

  it('settled-without-a-fix is never rendered as a confirmed fix', async () => {
    const c = await mount({
      queue: [F({ id: 1 }), F({ id: 2 })],
      file: 'Q3-plan.docx',
      decisions: { 1: { state: 'rejected' }, 2: { state: 'not_applicable' } },
    })
    const rows = [...c.querySelectorAll('.docprog-stage')].map((r) => r.textContent)
    expect(rows[3]).toMatch(/Confirmed by re-scan.*0$/)
    expect(rows[4]).toMatch(/Settled without a fix.*2$/)
  })
})

describe('RemediationDocProgress — nothing implies discovery opened the document', () => {
  it('has no discovery stage on the rail (ADR 0020 — Discover lists, it does not read)', async () => {
    const c = await mount({ queue: QUEUE, file: 'Q3-plan.docx' })
    expect(c.textContent).not.toMatch(/discover/i)
    expect(c.textContent).not.toMatch(/scanned the document|read the document/i)
  })
})
