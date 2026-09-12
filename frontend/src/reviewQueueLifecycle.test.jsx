import { act, useState } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import RemediationInbox from './RemediationInbox.jsx'
import ReviewQueueTabs from './ReviewQueueTabs.jsx'
import { matchesWorkflow } from './remediationInboxModel.js'

afterEach(() => { unmountAll(); vi.useRealTimers() })
const rows = [
  { id: 1, file: 'one.docx', title: 'Image alt text', hasProposal: true, after: 'A parking sign', rule_id: '1.1.1' },
  { id: 2, file: 'two.docx', title: 'Another image', hasProposal: true, after: 'A garden', rule_id: '1.1.1' },
]
const click = async element => act(async () => element.click())
it('moves approval out of Needs review, advances selection, and keeps it out of Completed until verified', async () => {
  const { root, container } = createTestRoot()
  function Workspace() {
    const [decisions, setDecisions] = useState({})
    return <RemediationInbox queue={rows} decisions={decisions} initialSort="document" onDecide={async (row, decision) => setDecisions(d => ({ ...d, [row.id]: decision }))} />
  }
  await act(async () => root.render(<Workspace />))
  await click([...container.querySelectorAll('button')].find(b => b.textContent.includes('Apply this fix')))
  const tabs = () => [...container.querySelectorAll('.review-queue-tabs button')]
  expect(tabs()[0].querySelector('strong').textContent).toBe('1')
  expect(tabs()[1].querySelector('strong').textContent).toBe('1')
  expect(tabs()[2].querySelector('strong').textContent).toBe('0')
  expect(container.querySelector('.rinbox-row[aria-current="true"]')?.textContent).toContain('Another image')
  await click(tabs()[1])
  expect(container.querySelector('.rinbox-queuepane').textContent).toContain('one.docx')
})

it('flashes signed deltas only on updates, and clears them across scans', async () => {
  vi.useFakeTimers()
  const { root, container } = createTestRoot()
  const show = async (queue, scanId = 'a') => act(async () => root.render(<ReviewQueueTabs queue={queue} decisions={{}} scanId={scanId} value="review" onChange={() => {}} />))
  await show(rows)
  expect(container.querySelector('.review-queue-delta')).toBeNull()
  await show([{ ...rows[0], status: 'approved' }, rows[1]])
  expect(container.querySelector('.review-queue-delta.positive').textContent).toBe('−1')
  await show([{ ...rows[0], status: 'verified' }, rows[1]])
  expect(container.querySelector('button:last-child .review-queue-delta').textContent).toBe('+1')
  await show(rows, 'b')
  expect(container.querySelector('.review-queue-delta')).toBeNull()
})

it('returns failed applications to Needs review even if a prior write was recorded', () => {
  const row = { ...rows[0], applied: true, status: 'apply_failed' }
  expect(matchesWorkflow(row, 'review')).toBe(true)
  expect(matchesWorkflow(row, 'completed')).toBe(false)
  expect(matchesWorkflow(row, 'awaiting-validation')).toBe(false)
})

it('places one compact queue control after document progress and above both review panels', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(<RemediationInbox queue={rows} decisions={{}} onDecide={async () => true} />))
  const pills = container.querySelector('.review-queue-tabs')
  const progress = container.querySelector('.rem-wsprog')
  const panels = container.querySelector('.rinbox')
  expect(container.querySelectorAll('.review-queue-tabs')).toHaveLength(1)
  expect(progress.nextElementSibling).toBe(pills)
  expect(pills.nextElementSibling).toBe(panels)
  expect(container.querySelector('.rinbox-queuepane .review-queue-tabs')).toBeNull()
  expect(container.querySelector('.rinbox-workspace .review-queue-tabs')).toBeNull()
  const buttons = [...pills.querySelectorAll('button')]
  expect(buttons.map(button => button.querySelector('strong').textContent)).toEqual(['2', '0', '0'])
  expect(buttons[0].getAttribute('aria-pressed')).toBe('true')
  await click(buttons[1])
  expect(buttons[1].getAttribute('aria-pressed')).toBe('true')
  expect(buttons[0].getAttribute('aria-pressed')).toBe('false')
  expect(container.querySelectorAll('.rinbox-row')).toHaveLength(0)
  buttons[1].focus()
  expect(document.activeElement).toBe(buttons[1])
  await click(buttons[0])
  expect(container.querySelectorAll('.rinbox-row')).toHaveLength(2)
})
