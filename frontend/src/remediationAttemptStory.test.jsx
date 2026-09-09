import { act, createElement } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import RemediationAttemptStory from './RemediationAttemptStory.jsx'
import { attemptStory, fallbackEvidence, attemptReason } from './remediationAttemptStoryModel.js'
import { getRunInsights } from './remediationRunInsightsClient.js'
vi.mock('./remediationRunInsightsClient.js', () => ({ getRunInsights: vi.fn() }))
vi.mock('./apiIdentity.js', () => ({ authEpoch: () => 1 }))
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const record = {
  scan_id: 'scan', batch_id: 'batch', coverage: 'complete',
  attempts: [
    { file: 'Report.docx', operation_id: 'op', attempt_id: 'a1', purpose: 'draft', provider: 'provider-one', model: 'recorded-first', status: 'empty_response', reason: 'empty_response', created_at: '2026-09-08T12:00:00Z', actual_cost_units: 12 },
    { file: 'Report.docx', operation_id: 'op', attempt_id: 'a2', purpose: 'fallback', provider: 'provider-two', model: 'recorded-fallback', status: 'drafted', output_sha256: 'digest', output_retention: 'full', result: { text: 'Saved generated text <script>not code</script>' }, actual_cost_units: 42 },
    { file: 'Other.pdf', operation_id: 'other', attempt_id: 'a3', purpose: 'draft', status: 'started' },
  ],
  proposals: [{ snapshot_id: 'p1', attempt_id: 'a2', file: 'Report.docx', rule_id: '1.1.1', proposal: { before: 'Original', proposed_value: 'Suggested' }, verification_reason: 'Exact version verification is unavailable.' }],
  review_receipts: [{ operation_id: 'op', proposal_sha256: 'digest', review: { verdict: 'revise', reason: 'Add source context', steps: [{ purpose: 'review', provider: 'review-provider', model: 'recorded-reviewer', reason: 'Needs detail' }] } }],
  pagination: { offset: 0, limit: 100, has_more: true },
}
beforeEach(() => { vi.clearAllMocks(); getRunInsights.mockResolvedValue(record) })
afterEach(unmountAll)
async function mount(props = {}) {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(RemediationAttemptStory, { scanId: 'scan', batchId: 'batch', defaultOpen: true, ...props })))
  return { root, container }
}
const buttons = (container, name) => [...container.querySelectorAll('button')].find(button => button.textContent === name)

describe('Follow an attempt', () => {
  it('is lazy while collapsed and only reads saved records when opened', async () => {
    const { container } = await mount({ defaultOpen: false })
    expect(getRunInsights).not.toHaveBeenCalled()
    await act(async () => { const details = container.querySelector('details'); details.open = true; details.dispatchEvent(new Event('toggle')) })
    expect(getRunInsights).toHaveBeenCalledWith('scan', 'batch', expect.any(AbortSignal), 0)
  })

  it('selects a file and renders actual models, output, review reason, costs and next action', async () => {
    const { container } = await mount({ reviewHref: '/?tab=remediate&mode=review' })
    const select = container.querySelector('select')
    await act(async () => { select.value = 'Report.docx'; select.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(container.textContent).toContain('provider-two · recorded-fallback')
    expect(container.textContent).toContain('$0.000042 USD')
    expect(container.textContent).toContain('Add source context')
    expect(container.textContent).toContain('Why this fallback was requested is not recorded')
    expect(container.querySelector('a').getAttribute('href')).toBe('/?tab=remediate&mode=review')
    expect(container.querySelector('script')).toBeNull()
    expect([...container.querySelectorAll('.attempt-story-output,.attempt-story-proposal')].every(detail => !detail.open)).toBe(true)
    expect(container.textContent).toContain('Exact version verification is unavailable.')
  })

  it('reports related human and validation evidence without claiming this version was verified', async () => {
    getRunInsights.mockResolvedValue({ ...record, proposals: [{ ...record.proposals[0], human_reviews: [{ id: 1, action: 'approve' }], validation_events: [{ id: 2, outcome: 'passed', detail: 'Related recorded check' }] }] })
    const { container } = await mount()
    const select = container.querySelector('select')
    await act(async () => { select.value = 'Report.docx'; select.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(container.textContent).toContain('Related human decisions already exist')
    expect(container.textContent).toContain('Related recorded check')
    expect(container.textContent).toContain('do not prove verification of this exact proposal version')
  })

  it('paginates bounded server records and says sequences may cross page boundaries', async () => {
    const { container } = await mount()
    expect(container.textContent).toContain('sequence can continue on another page')
    getRunInsights.mockResolvedValue({ ...record, attempts: [], proposals: [], pagination: { offset: 100, limit: 100, has_more: false } })
    await act(async () => buttons(container, 'Next records').click())
    expect(getRunInsights).toHaveBeenLastCalledWith('scan', 'batch', expect.any(AbortSignal), 100)
    expect(container.textContent).toContain('Record page 2')
    expect(container.textContent).not.toContain('recorded-fallback')
    expect(buttons(container, 'Next records').disabled).toBe(true)
  })

  it('does not tell a completed run to keep waiting for an unretained final response', () => {
    expect(attemptStory(record, 'Other.pdf', { live: false }).groups[0].next).toContain('No final response was retained')
    expect(attemptStory(record, 'Other.pdf', { live: true }).groups[0].next).toContain('Wait for the recorded response')
  })

  it('does not join unrelated attempts by same file, timestamp, or model', () => {
    const data = { ...record, attempts: [...record.attempts, { ...record.attempts[1], attempt_id: 'a4', operation_id: 'unrelated', output_sha256: 'different' }] }
    const story = attemptStory(data, 'Report.docx')
    expect(story.groups).toHaveLength(2)
    expect(story.groups[1].receipts).toEqual([])
    expect(story.groups[1].proposals).toEqual([])
    const changedReceipt = { ...record, review_receipts: [{ ...record.review_receipts[0], proposal_sha256: 'different' }] }
    expect(attemptStory(changedReceipt, 'Report.docx').groups[0].receipts).toEqual([])
  })

  it('keeps missing operation IDs separate and unmatched proposal snapshots unattributed', () => {
    const data = { ...record, attempts: record.attempts.map(attempt => ({ ...attempt, operation_id: null })), proposals: [...record.proposals, { file: 'Report.docx', snapshot_id: 'unlinked', attempt_id: 'missing' }] }
    const story = attemptStory(data, 'Report.docx')
    expect(story.groups).toHaveLength(2)
    expect(story.groups.every(group => !group.receipts.length)).toBe(true)
    expect(story.unlinkedProposals.map(proposal => proposal.snapshot_id)).toEqual(['unlinked'])
  })

  it('follows review attempt IDs only when linked by an exact output review receipt', () => {
    const review = { file: 'Report.docx', operation_id: 'review-op', attempt_id: 'review-a', purpose: 'review' }
    const data = { ...record, attempts: [...record.attempts, review], review_receipts: [{ ...record.review_receipts[0], review: { steps: [{ attempt_id: 'review-a' }] } }] }
    expect(attemptStory(data, 'Report.docx').groups[0].reviewAttempts).toEqual([review])
  })
})

it('previews only an exactly linked proposal and keeps long before/after evidence collapsed', async () => {
  const longBefore = 'before '.repeat(100)
  const longAfter = 'after '.repeat(100)
  getRunInsights.mockResolvedValue({ ...record, proposals: [{ ...record.proposals[0], proposal: { before: longBefore, proposed_value: longAfter }, version_verified: true, validation_events: [{ outcome: 'passed' }] }, { snapshot_id: 'unlinked', file: 'Report.docx', attempt_id: 'different', proposal: { before: 'Other source', proposed_value: 'Other proposal' } }] })
  const { container } = await mount()
  const select = container.querySelector('select')
  await act(async () => { select.value = 'Report.docx'; select.dispatchEvent(new Event('change', { bubbles: true })) })
  const preview = container.querySelector('.attempt-story-preview')
  const compact = preview.querySelector('.attempt-story-comparison')
  expect(compact.textContent).not.toContain(longBefore)
  expect(compact.textContent).not.toContain('Other source')
  expect(preview.querySelector('.attempt-story-proposal').open).toBe(false)
  expect(preview.querySelector('.attempt-story-proposal').textContent).toContain(longBefore)
  expect(preview.querySelector('.attempt-story-proposal').textContent).toContain(longAfter)
  expect(preview.textContent).toContain('Exact-version checks: unavailable')
  expect(preview.textContent).toContain('Proposal only · not verified')
})

it('selects saved proposal versions without mixing their original excerpts', async () => {
  getRunInsights.mockResolvedValue({ ...record, proposals: [record.proposals[0], { ...record.proposals[0], snapshot_id: 'p2', proposal: { before: 'Second original', proposed_value: 'Second proposed' } }] })
  const { container } = await mount()
  const file = container.querySelector('select')
  await act(async () => { file.value = 'Report.docx'; file.dispatchEvent(new Event('change', { bubbles: true })) })
  const select = container.querySelector('.attempt-story-version select')
  await act(async () => { select.value = 'p2'; select.dispatchEvent(new Event('change', { bubbles: true })) })
  expect(container.querySelector('.attempt-story-preview').textContent).toContain('Second original')
  expect(container.querySelector('.attempt-story-preview').textContent).toContain('Second proposed')
})

it('compares AI review verdicts only when both exact saved output fingerprints differ and match', () => {
  const first = { ...record.attempts[0], output_sha256: 'first-hash' }
  const fallback = record.attempts[1]
  const data = { ...record, attempts: [first, fallback], review_receipts: [
    { operation_id: 'op', proposal_sha256: 'first-hash', review: { verdict: 'revise' } },
    { operation_id: 'op', proposal_sha256: 'digest', review: { verdict: 'accept' } },
  ] }
  const group = attemptStory(data, 'Report.docx').groups[0]
  expect(fallbackEvidence(group, fallback).comparable).toBe(true)
  const missing = { ...group, receipts: group.receipts.slice(1) }
  expect(fallbackEvidence(missing, fallback).comparable).toBe(false)
  expect(fallbackEvidence({ ...group, operationId: null }, fallback).previous).toBeNull()
  expect(fallbackEvidence({ ...group, receipts: [{ ...group.receipts[0], operation_id: 'wrong' }] }, fallback).comparable).toBe(false)
})

it('calls a predecessor result context rather than an invented fallback trigger or improvement', async () => {
  const { container } = await mount()
  const file = container.querySelector('select')
  await act(async () => { file.value = 'Report.docx'; file.dispatchEvent(new Event('change', { bubbles: true })) })
  const evidence = container.querySelector('.attempt-story-fallback')
  expect(evidence.textContent).toContain('Earlier recorded result: No response content')
  expect(evidence.textContent).toContain('context, not a recorded fallback decision')
  expect(evidence.textContent).toContain('Improvement: Not measured')
  expect(evidence.textContent).toContain('Review of this fallback: AI review requested changes')
})

it('explains recorded stopping reasons without claiming the next model ran', () => {
  expect(attemptReason('budget_admission_denied')).toBe('The remaining budget could not cover another request.')
  expect(attemptReason('provider_usage_unknown')).toContain('charge is uncertain')
  expect(attemptReason('provider_refused')).toContain('no further model was tried')
  expect(attemptReason('unrecognized_reason')).toBe('unrecognized reason')
})
