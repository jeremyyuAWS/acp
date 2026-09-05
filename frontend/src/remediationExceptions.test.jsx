import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import {
  eligibleFiles, groupSummary, outcomeDetails, outcomeMessage, reconcileSelection, visibleItems,
  VISIBLE_PER_GROUP,
} from './remediationExceptions.js'

// Region E — actionable exceptions (PRD §6E, §11).
//
// The two failure modes these guard are opposites, and both were real elsewhere in this panel:
//
//   * a group action that touches more than the user could see and evaluate — "Retry all" over a
//     collapsed list, or over rows a live update added after they ticked the boxes;
//   * an action reported as a success when part of it was refused.
//
// Everything about eligibility is the SERVER's answer, read off the row. So the component tests
// below assert what the browser DOES with that answer, never that it recomputes it — a second
// implementation in the browser would eventually offer a button the server refuses.

const api = vi.hoisted(() => ({
  retryDelivery: vi.fn(), retryDocuments: vi.fn(),
  cancel: vi.fn(), pause: vi.fn(), resume: vi.fn(),
}))
vi.mock('./api.js', () => ({
  getRemediationExceptions: vi.fn(() => Promise.resolve({ groups: [], controls: [] })),
  retryRemediationDelivery: api.retryDelivery,
  retryRemediationDocuments: api.retryDocuments,
  cancelRemediationRun: api.cancel,
  pauseRemediationRun: api.pause,
  resumeRemediationRun: api.resume,
}))

const { default: RemediationExceptions } = await import('./RemediationExceptions.jsx')

afterEach(() => { unmountAll(); vi.clearAllMocks() })

let container, root
beforeEach(() => {
  ({ container, root } = createTestRoot())
  api.retryDelivery.mockResolvedValue({
    requested: 1, started: 1, refused: 0, failed: 0, duplicate: 0, complete_success: true,
    summary: '1 delivery started', results: [{ file: 'a.docx', outcome: 'started' }],
  })
  api.pause.mockResolvedValue({ paused: true, held: 5, in_flight: 3 })
})

const render = async (props) => {
  await act(async () => { root.render(createElement(RemediationExceptions, props)) })
}
const el = (testid) => container.querySelector(`[data-testid="${testid}"]`)
const click = async (node) => {
  await act(async () => { node.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
}
// A real click: jsdom flips `checked` itself and React derives the change from the click, which
// is what a keyboard Space does too. Setting `.checked` by hand and firing 'change' does not
// reach a React controlled input.
const check = async (node) => {
  await act(async () => { node.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
}

const item = (file, over = {}) => ({
  file, group: 'delivery_failure', action_enabled: true, action_reason: null, action_code: null,
  review_items: 0, destination: { provider: 'sharepoint', label: 'Contracts' }, ...over,
})

const deliveryGroup = (items) => ({
  key: 'delivery_failure', label: 'Delivery failures',
  summary: 'The corrected copy exists and was verified; writing it to the source provider did not succeed.',
  action: 'retry_delivery', action_label: 'Retry delivery only', capability: 'remediate.run',
  reapplies_fixes: false, documents: items.length,
  actionable: items.filter((i) => i.action_enabled).length, items,
})

const view = (groups, controls = []) => ({ run_id: 'scan-1', groups, controls })


// ── the projection, without a DOM ─────────────────────────────────────────────

describe('what a group action would touch', () => {
  it('is scoped to what is on screen, so a collapsed list cannot be acted on unseen', () => {
    const many = Array.from({ length: 9 }, (_, i) => item(`doc-${i}.docx`))
    const group = deliveryGroup(many)
    expect(visibleItems(group)).toHaveLength(VISIBLE_PER_GROUP)
    expect(eligibleFiles(group)).toHaveLength(VISIBLE_PER_GROUP)
    expect(eligibleFiles(group, { expanded: true })).toHaveLength(9)
  })

  it('never includes a document the server refused', () => {
    const group = deliveryGroup([
      item('ok.docx'),
      item('stale.docx', { action_enabled: false, action_code: 'artifact_stale' }),
    ])
    expect(eligibleFiles(group)).toEqual(['ok.docx'])
  })

  it('narrows to the selection once the user makes one', () => {
    const group = deliveryGroup([item('a.docx'), item('b.docx'), item('c.docx')])
    expect(eligibleFiles(group, { selected: new Set(['b.docx']) })).toEqual(['b.docx'])
  })

  it('keeps a selection across a live update, minus what is no longer actionable', () => {
    const before = new Set(['a.docx', 'b.docx'])
    const after = reconcileSelection(before, [deliveryGroup([
      item('a.docx'),
      item('b.docx', { action_enabled: false, action_code: 'already_delivered' }),
    ])])
    expect([...after]).toEqual(['a.docx'])
  })

  it('summarises a group by how much of it can actually be retried', () => {
    expect(groupSummary(deliveryGroup([item('a.docx'), item('b.docx')]))).toBe('2 documents')
    expect(groupSummary(deliveryGroup([
      item('a.docx'), item('b.docx', { action_enabled: false }),
    ]))).toBe('2 documents · 1 can be retried')
  })
})

describe('reporting an action', () => {
  it('never reads as total success when part of the group did not run', () => {
    const result = { complete_success: false, summary: '2 delivery operations started · 1 refused',
                     results: [{ file: 'a', outcome: 'started' },
                               { file: 'c', outcome: 'refused', message: 'Stale.' }] }
    expect(outcomeMessage(result)).toContain('Review the details below')
    expect(outcomeDetails(result).map((r) => r.file)).toEqual(['c'])
  })

  it('lists no per-document detail when every document started', () => {
    expect(outcomeDetails({ complete_success: true, results: [{ file: 'a', outcome: 'started' }] }))
      .toEqual([])
  })
})


// ── the rendered region ───────────────────────────────────────────────────────

describe('the exceptions region', () => {
  it('says which retry re-applies fixes and which does not', async () => {
    await render({ view: view([deliveryGroup([item('a.docx')])]), runId: 'scan-1' })
    expect(container.textContent).toContain('No fix is re-applied')
    expect(container.textContent).not.toContain('applies approved fixes again')
  })

  it('shows the refusal beside the document it is about, not somewhere else', async () => {
    await render({ view: view([deliveryGroup([
      item('stale.docx', { action_enabled: false, action_code: 'artifact_stale',
                           action_reason: 'The source document changed after this corrected copy was produced.' }),
    ])]), runId: 'scan-1' })
    expect(el('remops-x-reason-stale.docx').textContent)
      .toContain('The source document changed')
    expect(el('remops-x-check-stale.docx').disabled).toBe(true)
    expect(el('remops-x-action-delivery_failure').disabled).toBe(true)
  })

  it('sends only the documents it offered to send', async () => {
    await render({ view: view([deliveryGroup([
      item('a.docx'), item('b.docx'),
      item('stale.docx', { action_enabled: false, action_reason: 'Stale.' }),
    ])]), runId: 'scan-1' })
    await click(el('remops-x-action-delivery_failure'))
    expect(api.retryDelivery).toHaveBeenCalledWith('scan-1', ['a.docx', 'b.docx'])
  })

  it('sends only the ticked documents once a selection exists', async () => {
    await render({ view: view([deliveryGroup([item('a.docx'), item('b.docx')])]),
                   runId: 'scan-1' })
    await check(el('remops-x-check-b.docx'))
    expect(el('remops-x-action-delivery_failure').textContent).toContain('1 selected')
    await click(el('remops-x-action-delivery_failure'))
    expect(api.retryDelivery).toHaveBeenCalledWith('scan-1', ['b.docx'])
  })

  it('widens the action only when the user expands the group', async () => {
    const many = Array.from({ length: 7 }, (_, i) => item(`doc-${i}.docx`))
    await render({ view: view([deliveryGroup(many)]), runId: 'scan-1' })
    expect(el('remops-x-action-delivery_failure').textContent).toContain('(5)')
    await click(el('remops-x-expand-delivery_failure'))
    expect(el('remops-x-action-delivery_failure').textContent).toContain('(7)')
    await click(el('remops-x-action-delivery_failure'))
    expect(api.retryDelivery.mock.calls[0][1]).toHaveLength(7)
  })

  it('reports each outcome of a partial failure rather than one verdict', async () => {
    api.retryDelivery.mockResolvedValue({
      requested: 3, started: 1, refused: 1, failed: 1, duplicate: 0, complete_success: false,
      summary: '1 delivery started · 1 refused · 1 could not be started',
      results: [{ file: 'a.docx', outcome: 'started' },
                { file: 'b.docx', outcome: 'refused', message: 'The source document changed.' },
                { file: 'c.docx', outcome: 'failed', message: 'enqueue failed' }],
    })
    const announced = []
    await render({ view: view([deliveryGroup([item('a.docx'), item('b.docx'), item('c.docx')])]),
                   runId: 'scan-1', onAnnounce: (text) => announced.push(text) })
    await click(el('remops-x-action-delivery_failure'))
    const outcomes = el('remops-x-outcomes-delivery_failure').textContent
    expect(outcomes).toContain('b.docx')
    expect(outcomes).toContain('Refused')
    expect(outcomes).toContain('c.docx')
    expect(outcomes).toContain('Could not start')
    expect(outcomes).not.toContain('a.docx')     // a success needs no explanation
    expect(announced.at(-1)).toContain('Review the details below')
  })

  it('announces through the panel rather than opening a live region of its own', async () => {
    await render({ view: view([deliveryGroup([item('a.docx')])]), runId: 'scan-1',
                   onAnnounce: () => {} })
    expect(container.querySelectorAll('[aria-live]')).toHaveLength(0)
  })

  it('states what a control can and cannot reach before it is pressed', async () => {
    const announced = []
    await render({ view: view([], [
      { action: 'pause', label: 'Pause run', available: true, reason: null,
        scope: 'Holds work that has not been claimed. Attempts already in flight run to completion.',
        holds: 5, in_flight: 3 },
      { action: 'resume', label: 'Resume run', available: false, reason: 'This run is not paused.',
        scope: 'Releases the held work back to the queue.' },
    ]), runId: 'scan-1', onAnnounce: (t) => announced.push(t) })
    expect(container.textContent).toContain('Attempts already in flight run to completion')
    expect(el('remops-x-control-resume')).toBeNull()    // unavailable controls are not offered
    const button = el('remops-x-control-pause')
    expect(button.getAttribute('aria-describedby')).toBe('remops-control-scope-pause')
    await click(button)
    expect(api.pause).toHaveBeenCalledWith('scan-1')
    expect(announced.at(-1)).toBe('Run paused. 5 documents held, 3 still finishing.')
  })

  it('keeps its place, and its ticks, when a live update arrives', async () => {
    const groups = [deliveryGroup([item('a.docx'), item('b.docx')])]
    await render({ view: view(groups), runId: 'scan-1' })
    await check(el('remops-x-check-a.docx'))
    const focused = el('remops-x-check-a.docx')
    focused.focus()
    // The same run, one document further along: b has been delivered and is no longer actionable.
    await render({ view: view([deliveryGroup([
      item('a.docx'), item('b.docx', { action_enabled: false, action_reason: 'Already delivered.' }),
    ])]), runId: 'scan-1' })
    expect(el('remops-x-check-a.docx').checked).toBe(true)
    expect(document.activeElement).toBe(el('remops-x-check-a.docx'))
  })

  it('drops a tick the server has stopped offering, rather than retrying it anyway', async () => {
    await render({ view: view([deliveryGroup([item('a.docx'), item('b.docx')])]),
                   runId: 'scan-1' })
    await check(el('remops-x-check-b.docx'))
    await render({ view: view([deliveryGroup([
      item('a.docx'), item('b.docx', { action_enabled: false, action_reason: 'Already delivered.' }),
    ])]), runId: 'scan-1' })
    await click(el('remops-x-action-delivery_failure'))
    expect(api.retryDelivery).toHaveBeenCalledWith('scan-1', ['a.docx'])
  })

  it('keeps the last confirmed list when a refresh fails, rather than reporting a clean run',
    async () => {
      await render({ view: view([deliveryGroup([item('a.docx')])]), error: true, runId: 'scan-1' })
      expect(container.textContent).toContain('last it confirmed')
      expect(container.textContent).toContain('a.docx')
    })

  it('says a clean run is clean, and offers nothing to press', async () => {
    await render({ view: view([]), runId: 'scan-1' })
    expect(container.textContent).toContain('Nothing needs a decision or a retry')
    expect(container.querySelectorAll('button')).toHaveLength(0)
  })

  it('is fully operable from the keyboard — every control is a real button or checkbox',
    async () => {
      await render({ view: view([deliveryGroup(
        Array.from({ length: 7 }, (_, i) => item(`doc-${i}.docx`)))],
      [{ action: 'cancel', label: 'Stop run', available: true, reason: null, scope: 'Stops...' }]),
      runId: 'scan-1' })
      const interactive = [...container.querySelectorAll('button, input, a, [tabindex]')]
      expect(interactive.length).toBeGreaterThan(0)
      for (const node of interactive) {
        expect(['BUTTON', 'INPUT'].includes(node.tagName)).toBe(true)
        expect(node.getAttribute('tabindex')).not.toBe('-1')
      }
      expect(el('remops-x-expand-delivery_failure').getAttribute('aria-expanded')).toBe('false')
    })

  it('names every state in words, so nothing depends on colour alone', async () => {
    api.retryDelivery.mockResolvedValue({
      requested: 2, started: 1, refused: 1, failed: 0, duplicate: 0, complete_success: false,
      summary: '1 delivery started · 1 refused',
      results: [{ file: 'a.docx', outcome: 'started' },
                { file: 'b.docx', outcome: 'refused', message: 'Stale.' }],
    })
    await render({ view: view([deliveryGroup([item('a.docx'), item('b.docx')])]),
                   runId: 'scan-1' })
    await click(el('remops-x-action-delivery_failure'))
    expect(el('remops-x-outcomes-delivery_failure').textContent).toContain('Refused')
  })
})
