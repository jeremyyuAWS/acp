import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

const { default: CloseoutPanel } = await import('./CloseoutPanel.jsx')

afterEach(unmountAll)

let container, root
beforeEach(() => { ({ container, root } = createTestRoot()) })

const render = async (props) => { await act(async () => { root.render(createElement(CloseoutPanel, props)) }) }
const el = (testid) => container.querySelector(`[data-testid="${testid}"]`)
const text = (testid) => el(testid)?.textContent || ''
const click = async (b) => { await act(async () => { b.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }

const cleared = (file) => ({ file, remediated_at: 't', rescan: 'ran', cleared: ['1.1.1'], kept: [] })
const failing = (file) => ({ file, remediated_at: 't', rescan: 'ran', cleared: ['1.1.1'], kept: ['1.4.3'] })
const unverified = (file) => ({ file, remediated_at: 't', rescan: 'unavailable', cleared: ['1.1.1'], kept: [] })

describe('CloseoutPanel — re-verification', () => {
  it('counts cleared, still-failing and unverified as three separate numbers', async () => {
    await render({ docs: [cleared('a.docx'), cleared('b.docx'), failing('c.pdf'), unverified('d.pptx')] })
    expect(text('count-cleared')).toMatch(/2\s*verified cleared/)
    expect(text('count-still-failing')).toMatch(/1\s*still failing/)
    expect(text('count-unverified')).toMatch(/1\s*not verified/)
  })

  it('shows an unverified document as an absence of evidence, not a pass or a failure', async () => {
    await render({ docs: [unverified('d.pptx')] })
    const note = text('closeout-unverified-note')
    expect(note).toMatch(/could not be re-scanned/i)
    expect(note).toMatch(/not a failure and it is not a pass/i)
    expect(note).toMatch(/must not be released/i)
    // And it is not counted as cleared anywhere on the panel.
    expect(text('count-cleared')).toMatch(/0\s*verified cleared/)
  })

  it('says nothing about unverified documents when there are none', async () => {
    await render({ docs: [cleared('a.docx')] })
    expect(el('closeout-unverified-note')).toBeNull()
  })

  it('renders an unread review queue as unread, not as zero awaiting review', async () => {
    await render({ docs: [cleared('a.docx')] })
    expect(text('count-pending-review')).toMatch(/review queue not read/i)
    expect(text('count-pending-review')).not.toMatch(/0\s*awaiting/)
  })

  it('renders a real zero when the queue was actually read and was empty', async () => {
    await render({ docs: [{ ...cleared('a.docx'), pendingReview: 0 }] })
    expect(text('count-pending-review')).toMatch(/0\s*awaiting review/)
    expect(text('count-pending-review')).not.toMatch(/not read/i)
  })

  it('gives every document its own evidence line', async () => {
    await render({ docs: [cleared('a.docx'), failing('c.pdf'), unverified('d.pptx')] })
    const rows = [...container.querySelectorAll('[data-testid="closeout-doc-row"]')]
    expect(rows).toHaveLength(3)
    expect(rows.find((r) => r.textContent.includes('a.docx')).textContent).toMatch(/no longer fails/)
    expect(rows.find((r) => r.textContent.includes('c.pdf')).textContent).toMatch(/still fails/)
    expect(rows.find((r) => r.textContent.includes('d.pptx')).textContent).toMatch(/nothing here is verified/i)
  })
})

describe('CloseoutPanel — the compliance record', () => {
  it('names what a later reader will find, and why a fix that did not take is not in it', async () => {
    await render({ docs: [cleared('a.docx')] })
    expect(text('record-verified')).toMatch(/credited only if it actually stopped failing/i)
  })

  it('records the fixes that did not take under their audit action', async () => {
    await render({ docs: [failing('c.pdf')] })
    expect(text('record-unverified-log')).toContain('remediate.unverified')
  })

  it('records a missing re-scan as its own entry rather than omitting it', async () => {
    await render({ docs: [unverified('d.pptx')] })
    expect(el('record-no-evidence')).not.toBeNull()
    expect(text('record-no-evidence')).toMatch(/no verification either way/i)
  })

  it('does not print a review-routing entry when the queue was never read', async () => {
    await render({ docs: [cleared('a.docx')] })
    expect(el('record-review')).toBeNull()
    await render({ docs: [{ ...cleared('a.docx'), pendingReview: 2 }] })
    expect(el('record-review')).not.toBeNull()
  })

  it('shows no record section for a run with nothing in it', async () => {
    await render({ docs: [] })
    expect(el('closeout-record')).toBeNull()
  })
})

describe('CloseoutPanel — the handoff', () => {
  it('offers exactly one next step, not a row of equal buttons', async () => {
    await render({ docs: [cleared('a.docx'), failing('c.pdf'), unverified('d.pptx')], onReverify: () => {}, onRemediate: () => {}, onPublish: () => {} })
    expect(el('closeout-next').querySelectorAll('button')).toHaveLength(1)
  })

  it('sends the operator to re-check first when evidence is missing', async () => {
    const onReverify = vi.fn()
    await render({ docs: [cleared('a.docx'), failing('c.pdf'), unverified('d.pptx')], onReverify })
    expect(text('closeout-next-label')).toMatch(/Re-check 1 document/)
    await click(el('closeout-next').querySelector('button'))
    expect(onReverify).toHaveBeenCalledTimes(1)
    expect(onReverify.mock.calls[0][0].unverified).toBe(1)
  })

  it('offers release only when the loop is closed', async () => {
    const onPublish = vi.fn()
    await render({ docs: [{ ...cleared('a.docx'), pendingReview: 0 }], onPublish })
    expect(text('closeout-next-label')).toMatch(/Release 1 verified document/)
    await click(el('closeout-next').querySelector('button'))
    expect(onPublish).toHaveBeenCalledTimes(1)
  })

  it('renders no dead button when the host wired no handler for the step', async () => {
    await render({ docs: [unverified('d.pptx')] })
    expect(text('closeout-next-label')).toMatch(/Re-check/)
    expect(el('closeout-next').querySelector('button')).toBeNull()
  })

  // ADR 0020 — a re-check reads the file, so it is an Assess step. The screen that invites one
  // states the boundary rather than leaving it to be inferred from the tab it happens to be on.
  it('states that a re-check is Assess, and that Discover never opens a file', async () => {
    await render({ docs: [unverified('d.pptx')], onReverify: () => {} })
    expect(text('closeout-assess-note')).toMatch(/Assess step/i)
    expect(text('closeout-assess-note')).toMatch(/never opens a file/i)
  })

  it('does not imply discovery reads or scans anything, anywhere on the panel', async () => {
    await render({ docs: [cleared('a.docx'), failing('c.pdf'), unverified('d.pptx'), { ...cleared('e.docx'), pendingReview: 2 }], onReverify: () => {} })
    const all = el('closeout-panel').textContent
    expect(all).not.toMatch(/discover\w*\s+(?:re-?)?(?:scans?|reads?|opens?|analyses?|analyzes?)/i)
    expect(all).not.toMatch(/(?:re-?)?(?:scan|read|open|analyse|analyze)\w*\s+(?:in|during|at)\s+discover/i)
  })

  it('says there is nothing to hand off for an untouched run', async () => {
    await render({ docs: [{ file: 'x.docx' }] })
    expect(text('closeout-next-label')).toMatch(/Nothing to hand off yet/)
  })
})
