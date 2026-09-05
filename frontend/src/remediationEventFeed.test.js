import { describe, expect, it } from 'vitest'
import { addRemediationEvent, eventTone, remediationEventLine,
         MAX_VISIBLE_REMEDIATION_EVENTS } from './remediationEventFeed.js'

describe('remediation lifecycle event narration', () => {
  it('maps every durable remediation event without exposing arbitrary detail', () => {
    const cases = [
      ['remediate.accepted', { documents: 12 }, /accepted for 12 documents/],
      ['remediate.fix_applied', { file: 'a.docx', fixes: 2 }, /2 approved fixes applied to a.docx/],
      ['remediate.verified', { file: 'a.docx', fixes: 2 }, /independently verified/],
      ['remediate.verification_failed', { file: 'a.docx', fixes: 1 }, /did not pass re-scan/],
      ['remediate.delivered', { file: 'a.docx' }, /saved to the source provider/],
      ['remediate.delivery_failed', { file: 'a.docx' }, /retained in ACP/],
      ['remediate.review_requested', { file: 'a.docx', criterion: '1.1.1' }, /WCAG 1.1.1/],
      ['remediate.document_completed', { file: 'a.docx' }, /remediation finished/],
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
  })
})
