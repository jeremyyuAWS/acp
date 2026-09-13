import { describe, expect, it, afterEach } from 'vitest'
import { act } from 'react'
import { createTestRoot, unmountAll } from './testRoots'
afterEach(unmountAll)
import { remediationEventLine, eventTone } from './remediationEventFeed'
import { Activity } from './RemediationOpsPanel'

describe('vision retry narration', () => {
  it('distinguishes recovered drafts from verified fixes', () => {
    const line = remediationEventLine({ kind: 'remediate.vision_retry_recovered', document: 'A.docx' })
    expect(line).toContain('still need verification')
    expect(eventTone('remediate.vision_retry_recovered')).toBe('neutral')
  })
  it('keeps exhausted descriptions in review', () => {
    expect(remediationEventLine({ kind: 'remediate.vision_retry_blocked', document: 'A.pdf' })).toContain('individual review')
    expect(eventTone('remediate.vision_retry_blocked')).toBe('attention')
  })
  it('explains spending uncertainty without calling it manual document work', () => {
    const line = remediationEventLine({ kind: 'remediate.vision_retry_blocked', document: 'A.docx',
      detail: { reason_code: 'vision_spending_reconciliation_required' } })
    expect(line).toContain('confirming previous AI usage')
    expect(line).not.toContain('individual review')
  })
  it('shows a yellow retry only when newly received', async () => {
    const event = { key: 'retry', documentKey: 'A', kind: 'remediate.vision_retry_pending',
      tone: 'attention', line: 'Image description queued to retry' }
    const { root, container } = createTestRoot()
    await act(async () => root.render(<Activity events={[]} />))
    await act(async () => root.render(<Activity events={[event]} />))
    expect(container.querySelector('.remops-activity-retry.remops-activity-fresh')).not.toBeNull()
    expect(container.textContent).toContain('Image description queued to retry')
  })
})
