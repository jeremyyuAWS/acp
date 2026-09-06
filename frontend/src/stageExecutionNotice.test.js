import { describe, expect, it } from 'vitest'
import { stageExecutionNotice } from './stageExecutionNotice.js'

describe('stageExecutionNotice', () => {
  it('explains an idempotent replay without claiming new work was queued', () => {
    expect(stageExecutionNotice('Assessment', { reused: true, requeued: 0 }))
      .toBe('Reconnected to the existing Assessment run — equivalent work was already accepted, so nothing was queued twice.')
  })

  it('gives a revived failed execution precedence over generic reuse', () => {
    expect(stageExecutionNotice('Remediation', { reused: false, requeued: 2 }))
      .toBe('Retrying 2 failed items in the existing Remediation run — no duplicate run was created.')
  })

  it('stays quiet for a genuinely new execution', () => {
    expect(stageExecutionNotice('Assessment', { reused: false, requeued: 0 })).toBe('')
  })
})
