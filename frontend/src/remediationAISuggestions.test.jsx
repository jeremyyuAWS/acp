import { act, createElement } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import Suggestions from './RemediationAISuggestions.jsx'
import { getRemediationAIDetails } from './api.js'

vi.mock('./api.js', () => ({ getRemediationAIDetails: vi.fn() }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(unmountAll)
beforeEach(() => vi.resetAllMocks())

const row = { id: 'r1', file: 'report.docx', origin: 'ai', rule_id: '1.1.1', plain_name: 'Describe the image' }
const item = { id: 'review-1', scan_id: 's1', file: row.file, rule_id: row.rule_id, status: 'pending', proposals: [{ before: 'old description', proposed_value: '<img src=x onerror="alert(1)">', source: 'AI vision model', model_call_id: 'c1', locator: 'slide 2' }] }
const call = { id: 'c1', scan_id: 's1', file: row.file, model: 'recorded-model-v2', provider: 'anthropic', cost_usd: '0.012', ts: '2026-09-08', surface: 'vision_alt' }
async function render(props = {}) {
  const result = createTestRoot()
  await act(async () => result.root.render(createElement(Suggestions, { runId: 's1', scopeFiles: [row.file], rows: [row], ...props })))
  return result
}

it('shows stored original/output as inert text with exact call attribution, not configured attribution', async () => {
  getRemediationAIDetails.mockResolvedValue({ items: [item, { ...item, id: 'foreign', scan_id: 's2', file: 'private.docx' }], calls: [call], callsAvailable: true })
  const { container } = await render({ providers: { text: { model: 'planned-model', provider: 'openai' } } })
  expect(container.textContent).toContain('old description')
  expect(container.textContent).toContain(item.proposals[0].proposed_value)
  expect(container.querySelector('img')).toBeNull()
  expect(container.textContent).toContain('anthropic · recorded-model-v2')
  expect(container.textContent).toContain('Configured models — not completed calls')
  expect(container.textContent).toContain('Earlier AI attempts, previous drafts and separate AI reviewer results are unavailable')
  expect(container.textContent).toContain('$0.012000 USD')
  expect(container.textContent).toContain('not a per-finding total')
  expect(container.textContent).not.toContain('private.docx')
  expect(getRemediationAIDetails).toHaveBeenCalledExactlyOnceWith('s1')
})

it('never assigns nearby or cross-file/cross-scan calls to a suggestion', async () => {
  getRemediationAIDetails.mockResolvedValue({ items: [item], calls: [{ ...call, id: 'nearby' }, { ...call, file: 'wrong.docx' }, { ...call, scan_id: 's2' }], callsAvailable: true })
  const { container } = await render()
  expect(container.textContent).toContain('Model details unavailable')
  expect(container.textContent).not.toContain('recorded-model-v2')
  expect(container.textContent).not.toContain('$0.012000')
})

it('keeps actual saved content when the call ledger fails and does not invent earlier drafts', async () => {
  getRemediationAIDetails.mockResolvedValue({ items: [{ ...item, status: 'rejected', superseded: true }], calls: [], callsAvailable: false })
  const { container } = await render()
  expect(container.textContent).toContain('Model call details could not be loaded')
  expect(container.textContent).toContain(item.proposals[0].proposed_value)
  expect(container.textContent).toContain('Historical item — no longer current')
})

it('distinguishes unavailable stored content from a not-yet-generated draft', async () => {
  getRemediationAIDetails.mockResolvedValue({ items: [], calls: [], callsAvailable: true })
  const { container, root } = await render()
  expect(container.textContent).toContain('No suggestion generated yet')
  await act(async () => root.render(createElement(Suggestions, { runId: 's1', scopeFiles: [row.file], rows: [{ ...row, has_proposal: true }] })))
  expect(container.textContent).toContain('Generated content unavailable')
  expect(container.textContent).not.toContain('No suggestion generated yet')
})

it('does not treat request failures or simulation as an empty successful history', async () => {
  getRemediationAIDetails.mockRejectedValue(new Error('offline'))
  const first = await render()
  expect(first.container.querySelector('[role=alert]').textContent).toContain('could not be loaded')
  expect(first.container.textContent).not.toContain('No suggestion generated yet')
  getRemediationAIDetails.mockResolvedValue({ items: [], calls: [], callsAvailable: false, available: false })
  const second = await render()
  expect(second.container.textContent).toContain('unavailable in this environment')
  expect(second.container.textContent).not.toContain('No suggestion generated yet')
})

it('shows all scan files for omitted scope but none for an explicit empty scope', async () => {
  getRemediationAIDetails.mockResolvedValue({ items: [item], calls: [call], callsAvailable: true })
  const { root, container } = await render({ scopeFiles: undefined })
  expect(container.textContent).toContain('old description')
  await act(async () => root.render(createElement(Suggestions, { runId: 's1', scopeFiles: [], rows: [row] })))
  expect(container.textContent).not.toContain('old description')
  expect(container.textContent).toContain('No saved AI suggestions')
})

it('restricts chart details to matching file and criterion while the toolbar shows all saved AI suggestions', async () => {
  const other = { ...item, id: 'other-rule', rule_id: '2.4.4', proposals: [{ source: 'AI text model', proposed_value: 'Another criterion draft' }] }
  getRemediationAIDetails.mockResolvedValue({ items: [item, other], calls: [call], callsAvailable: true })
  const { root, container } = await render({ filterToRows: true })
  expect(container.textContent).toContain('matching the chart findings')
  expect(container.textContent).toContain('old description')
  expect(container.textContent).not.toContain('Another criterion draft')
  await act(async () => root.render(createElement(Suggestions, { runId: 's1', scopeFiles: [row.file], rows: [row], filterToRows: false })))
  expect(container.textContent).toContain('Another criterion draft')
  expect(container.textContent).toContain('for the selected files')
})

it('keeps malformed proposal records unavailable instead of crashing or fabricating content', async () => {
  getRemediationAIDetails.mockResolvedValue({ items: [null, { ...item, proposals: 'corrupt' }], calls: [null], callsAvailable: true })
  const { container } = await render()
  expect(container.textContent).toContain('Generated content unavailable for this review item')
  expect(container.textContent).not.toContain('old description')
})

it('drops stale responses after switching selection and never loads without an assessment', async () => {
  let completeOld
  getRemediationAIDetails.mockImplementationOnce(() => new Promise(resolve => { completeOld = resolve }))
    .mockResolvedValue({ items: [], calls: [], callsAvailable: true })
  const { root, container } = await render()
  await act(async () => root.render(createElement(Suggestions, { runId: 's2', scopeFiles: ['new.docx'], rows: [] })))
  await act(async () => completeOld({ items: [item], calls: [call], callsAvailable: true }))
  expect(container.textContent).not.toContain('old description')
  getRemediationAIDetails.mockClear()
  await act(async () => root.render(createElement(Suggestions, { scopeFiles: [row.file], rows: [row] })))
  expect(getRemediationAIDetails).not.toHaveBeenCalled()
  expect(container.textContent).toContain('Choose an assessment')
})

it('shows an exact finding timeline with proposal version, model, review and validation details', async () => {
  const detailed = {
    ...item,
    status: 'approved',
    review_events: [{ id: 'review-1', action: 'approve', created_at: '2026-09-08T12:01:00Z' }],
    validation_events: [{ id: 'check-1', outcome: 'verified_cleared', detail: 'Re-scan passed', created_at: '2026-09-08T12:02:00Z' }],
    proposals: [{ ...item.proposals[0], snapshot_id: 'snapshot-1', version_verified: true, created_at: '2026-09-08T12:00:00Z', human_reviews: [{ id: 'review-1', action: 'approve' }], validation_events: [{ id: 'check-1', outcome: 'verified_cleared' }] }],
  }
  getRemediationAIDetails.mockResolvedValue({ items: [detailed], calls: [call], callsAvailable: true })
  const { container } = await render()
  expect(container.textContent).toContain('Current decision: Approved')
  expect(container.textContent).toContain('Proposal version 1')
  expect(container.textContent).toContain('Exact proposal version verified')
  expect(container.textContent).toContain('anthropic · recorded-model-v2')
  expect(container.textContent).toContain('Saved version: snapshot-1')
  expect(container.textContent).toContain('Review: approve')
  expect(container.textContent).toContain('Check: verified cleared')
})

it('states when exact finding steps are unavailable instead of inferring model history', async () => {
  getRemediationAIDetails.mockResolvedValue({ items: [{ ...item, proposals: [] }], calls: [], callsAvailable: false })
  const { container } = await render()
  expect(container.textContent).toContain('Exact AI steps are unavailable for this finding')
  expect(container.textContent).toContain('Generated content unavailable for this review item')
  expect(container.textContent).not.toContain('recorded-model-v2')
})
