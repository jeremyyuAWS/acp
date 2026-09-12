import { describe, expect, it } from 'vitest'
import { addRemediationEvent, eventTone, remediationEventLine,
         MAX_VISIBLE_REMEDIATION_EVENTS, activityGroups } from './remediationEventFeed.js'

describe('remediation lifecycle event narration', () => {
  it('maps every durable remediation event without exposing arbitrary detail', () => {
    const cases = [
      ['remediate.accepted', { documents: 12 }, /accepted for 12 documents/],
      ['remediate.fix_applied', { file: 'a.docx', fixes: 2 }, /2 recorded changes applied to a.docx/],
      ['remediate.verified', { file: 'a.docx', fixes: 2 }, /independently verified/],
      ['remediate.verification_failed', { file: 'a.docx', fixes: 1 }, /did not pass re-scan/],
      ['remediate.delivered', { file: 'a.docx' }, /saved to the source provider/],
      ['remediate.delivery_failed', { file: 'a.docx' }, /retained in ACP/],
      ['remediate.review_requested', { file: 'a.docx', criterion: '1.1.1' }, /WCAG 1.1.1/],
      ['remediate.document_completed', { file: 'a.docx' }, /remediation finished/],
      ['scan.interrupted', {}, /worker stopped without reporting/],
      ['scan.retrying', {}, /processing attempt failed and was scheduled to retry/],
    ]
    for (const [kind, detail, expected] of cases) {
      expect(remediationEventLine({ kind, detail })).toMatch(expected)
    }
    expect(remediationEventLine({ kind: 'unknown', detail: { secret: 'never render me' } })).toBe(null)
  })

  it('deduplicates by durable event id and retains only the newest ten', () => {
    let rows = []
    for (let id = 1; id <= 12; id += 1) {
      rows = addRemediationEvent(rows, {
        kind: 'remediate.document_completed', detail: { file: `${id}.docx` },
      }, id)
    }
    expect(rows).toHaveLength(MAX_VISIBLE_REMEDIATION_EVENTS)
    expect(rows[0].id).toBe('12')
    expect(rows.at(-1).id).toBe('3')
    expect(addRemediationEvent(rows, {
      kind: 'remediate.document_completed', detail: { file: 'duplicate.docx' },
    }, 12)).toBe(rows)
  })

  it('uses attention and error tones only for actionable events', () => {
    expect(eventTone('remediate.review_requested')).toBe('attention')
    expect(eventTone('remediate.delivery_failed')).toBe('error')
    expect(eventTone('remediate.verified')).toBe('success')
    expect(eventTone('remediate.fix_applied')).toBe('neutral')
    expect(eventTone('scan.interrupted')).toBe('attention')
    expect(eventTone('scan.retrying')).toBe('attention')
  })
})

describe('clear grouped activity', () => {
  it('suppresses zero recorded-change events without claiming automatic fixes failed', () => {
    const prior = []
    expect(addRemediationEvent(prior, { kind: 'remediate.fix_applied', detail: { fixes: 0 } }, 1)).toBe(prior)
  })
  it('distinguishes saved-only outcomes from provider failures and never renders raw errors', () => {
    const event = { kind: 'remediate.delivery_failed', detail: { file: 'a.docx', delivery_status: 'saved_in_acp', reason: 'delivery_disabled', error: 'secret' } }
    expect(remediationEventLine(event)).toContain('source delivery is disabled')
    expect(remediationEventLine(event)).not.toContain('secret')
    expect(eventTone(event.kind, event.detail)).toBe('neutral')
    expect(remediationEventLine({ ...event, detail: { file: 'a.docx', reason: 'write_permission_required' } })).toContain('write permission required')
    expect(remediationEventLine({ ...event, detail: { file: 'a.docx', delivery_status: 'saved_in_acp', reason: 'source_delivery_unavailable' } })).toContain('source delivery is unavailable')
  })
  it('groups documents by opaque reference and surfaces exceptions before completion', () => {
    const rows = [
      { key: '3', documentKey: 'opaque', tone: 'success', line: 'Finished' },
      { key: '2', documentKey: 'opaque', tone: 'error', line: 'Delivery failed' },
      { key: '1', documentKey: 'other', tone: 'neutral', line: 'Applying' },
    ]
    const groups = activityGroups(rows)
    expect(groups).toHaveLength(2)
    expect(groups[0].lead.line).toBe('Delivery failed')
    expect(groups[0].rows).toHaveLength(2)
  })
})

it('does not prioritize an old delivery failure after a confirmed delivery', () => {
  const groups = activityGroups([
    { key: '2', documentKey: 'one', kind: 'remediate.delivered', tone: 'success' },
    { key: '1', documentKey: 'one', kind: 'remediate.delivery_failed', tone: 'error' },
  ])
  expect(groups[0].lead.key).toBe('2')
})
