import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import {
  laneOf, LANES, tabOf, tabCounts, isResolved, effortSecOf, TABS,
} from './remediationInboxModel.js'

const { default: RemediationInbox } = await import('./RemediationInbox.jsx')

afterEach(unmountAll)

// ── W2 · the rejected-fix handoff lane (pure model) ────────────────────────────────────────────
describe('W2 — a rejected AI fix has a destination (handoff lane)', () => {
  const rejected = { id: 9, file: 'brief.docx', title: 'DOCX · Image needs alt text', rejectedFix: true }

  it('routes a rejected AI fix to the amber handoff lane, not blocked/manual', () => {
    expect(laneOf(rejected)).toBe(LANES.handoff)
    expect(LANES.handoff.label).toMatch(/needs manual handling/i)
  })
  it('handoff is a visible follow-up tab, not "resolved"', () => {
    expect(TABS).toContain('needs-attention')
    expect(tabOf(rejected)).toBe('needs-attention')
    // It is NOT resolved — the whole point is that a person still has to do the work.
    expect(isResolved(rejected)).toBe(false)
  })
  it('counts handoff findings under needs-attention', () => {
    const counts = tabCounts([rejected, { id: 1, autoApplied: true }])
    expect(counts['needs-attention']).toBe(1)
    expect(counts['auto-fixed']).toBe(1)
  })
  it('estimates handoff effort at the manual (slow) cost', () => {
    expect(effortSecOf(rejected)).toBe(120)
  })
})

// ── component harness ──────────────────────────────────────────────────────────────────────────
let container, root
beforeEach(() => { ;({ container, root } = createTestRoot()) })
const render = async (props) => { await act(async () => { root.render(createElement(RemediationInbox, { initialSort: 'document', ...props })) }) }
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const btnByText = (t) => [...container.querySelectorAll('button')].find((b) => b.textContent.includes(t))
const detailHeading = () => container.querySelector('h3')?.textContent

// ── W2 · the handoff item in the detail pane ───────────────────────────────────────────────────
describe('W2 — rejected fix appears in the inbox as manual-handling work', () => {
  const QUEUE = [
    { id: 9, file: 'brief.docx', title: 'DOCX · Image needs alt text', rule_id: '1.1.1', rejectedFix: true },
  ]
  it('shows the needs-manual-handling treatment, not an approve button', async () => {
    await render({ queue: QUEUE, decisions: {} })
    // A rejected AI fix needs hand-editing, so it lives in the Manual fixes tab (not Needs review).
    await click(btnByText('Complete manual work'))
    expect(detailHeading()).toBe('Image needs alt text')
    expect(container.textContent).toContain('Needs manual handling')   // eyebrow + lane label
    expect(container.textContent).toContain('Fix this in Word')          // guided manual steps (docx → Word)
    expect(btnByText('Defer')).toBeTruthy()                              // set aside for later (state: assigned)
    expect(btnByText('Approve fix')).toBeFalsy()
  })
  it('acting on it clears it via onDecide(assigned)', async () => {
    const calls = []
    await render({ queue: QUEUE, decisions: {}, onDecide: (f, d) => calls.push([f.id, d.state]) })
    await click(btnByText('Complete manual work'))
    await click(btnByText('Defer'))
    expect(calls).toEqual([[9, 'assigned']])
  })
})

// ── W8 · apply-to-all-matching ───────────────────────────────────────────────────────────────
describe('W8 — apply a decision to every matching finding in the same cluster', () => {
  // Three "missing alt text" (1.1.1) findings across three files, all in the actionable apply lane.
  // The batch's scope is the selected finding's CLUSTER (criterion + lane). Format is deliberately
  // NOT part of that key — it was tried and reverted at the owner's direction, because keying on it
  // split the large single-criterion runs clustering exists to collapse. So the .pdf finding IS in
  // reach here, and the compensating control is disclosure: the banner names the formats the
  // decision covers.
  const QUEUE = [
    { id: 1, file: 'a.docx', title: 'DOCX · Image needs alt text', rule_id: '1.1.1', hasProposal: true, after: 'alt A' },
    { id: 2, file: 'b.docx', title: 'DOCX · Image needs alt text', rule_id: 'SC_1_1_1', hasProposal: true, after: 'alt B' },
    // Same criterion, different format — joins the batch, and the banner says so.
    { id: 3, file: 'c.pdf', title: 'PDF · Image needs alt text', rule_id: 'WCAG 1.1.1', hasProposal: true, after: 'alt C' },
    // A different rule — must never be swept into the 1.1.1 batch.
    { id: 4, file: 'd.docx', title: 'DOCX · Document has no title', rule_id: '2.4.2', hasProposal: true, after: 'A title' },
  ]

  it('offers a batch action naming the matching count', async () => {
    await render({ queue: QUEUE, decisions: {} })
    expect(detailHeading()).toBe('Image needs alt text')
    // TWO other findings are in reach: id2 (.docx) and id3 (.pdf). id4 is a different criterion and
    // is not. The copy names the criterion, the formats and the document count, so the reviewer knows
    // exactly what a batch press would reach — including that it crosses a format boundary.
    expect(container.textContent).toContain('You are looking at one of 3 findings that share this issue')
    expect(container.textContent).toContain('WCAG 1.1.1 in DOCX and PDF files')
    expect(container.textContent).toContain('covers more than one document format')
    const optIn = container.querySelector('input[type=checkbox]')
    expect(optIn).toBeTruthy()
    expect(optIn.parentElement.textContent).toContain('Apply this decision to 2 matching WCAG 1.1.1 findings')
  })

  it('applies the decision to its cluster only — every format of that rule, and no other rule', async () => {
    const calls = []
    await render({ queue: QUEUE, decisions: {}, onDecide: (f, d) => calls.push([f.id, d.state]) })
    await click(container.querySelector('input[type=checkbox]'))
    await click(btnByText('Approve & next'))
    // ids 1,2,3 (every 1.1.1 in the actionable lane, both formats) approved. id4 is a different
    // criterion, so it is not in the cluster and is not touched.
    expect(calls.map((c) => c[0]).sort()).toEqual([1, 2, 3])
    expect(calls.every((c) => c[1] === 'accepted')).toBe(true)
  })

  it('does not offer a batch action for a lone finding or a manual one', async () => {
    // Only the 2.4.2 finding + a manual finding: no siblings to batch.
    await render({ queue: [QUEUE[3], { id: 5, file: 'e.pdf', title: 'PDF · Scanned page, no text', rule_id: '1.1.1' }], decisions: {} })
    // 2.4.2 is selected first (document sort → d.docx before e.pdf); it has no 2.4.2 sibling.
    expect(detailHeading()).toBe('Document has no title')
    expect(container.textContent).not.toContain('share this issue')
  })
})
