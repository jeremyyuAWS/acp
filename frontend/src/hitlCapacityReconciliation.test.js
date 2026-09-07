import { describe, expect, it, vi } from 'vitest'
import { hitlFailureCopy, reconcileHitlPutFailure } from './Remediate.jsx'

const ITEM = { id: 'review-42', file: 'policy.docx' }
const busy = () => Object.assign(new Error('The database is at capacity.'), {
  code: 'DB_CAPACITY_BUSY', changes: 'unknown', requestId: 'request-7',
})

describe('an uncertain HITL decision response', () => {
  it('accepts the decision when the durable row has the requested status', async () => {
    const read = vi.fn().mockResolvedValue([
      { id: 'other', status: 'pending' },
      { id: ITEM.id, status: 'approved' },
    ])

    await expect(reconcileHitlPutFailure(ITEM.id, 'approved', busy(), read))
      .resolves.toMatchObject({ outcome: 'saved', row: { status: 'approved' } })
    expect(read).toHaveBeenCalledOnce()
  })

  it('rolls back only when the durable row proves the requested status did not land', async () => {
    await expect(reconcileHitlPutFailure(
      ITEM.id, 'approved', busy(), () => Promise.resolve([{ ...ITEM, status: 'pending' }]),
    )).resolves.toMatchObject({ outcome: 'not_saved', row: { status: 'pending' } })
  })

  it('keeps the outcome unknown when the authoritative read cannot settle it', async () => {
    await expect(reconcileHitlPutFailure(ITEM.id, 'approved', busy(), () => Promise.resolve([])))
      .resolves.toMatchObject({ outcome: 'unknown' })
    await expect(reconcileHitlPutFailure(ITEM.id, 'approved', busy(), () => Promise.reject(new Error('busy'))))
      .resolves.toMatchObject({ outcome: 'unknown' })
  })

  it('does not spend a reconciliation read on an ordinary refused write', async () => {
    const read = vi.fn()
    const refused = Object.assign(new Error('invalid decision'), { status: 422, changes: 'none' })

    await expect(reconcileHitlPutFailure(ITEM.id, 'approved', refused, read))
      .resolves.toEqual({ outcome: 'not_saved', error: refused })
    expect(read).not.toHaveBeenCalled()
  })

  it('never calls an unknown database outcome “NOT saved” or invites a blind retry', () => {
    const uncertain = hitlFailureCopy(ITEM, 'approved', busy(), 'unknown')
    expect(uncertain).toContain('could not confirm whether')
    expect(uncertain).toContain('refresh the queue before trying again')
    expect(uncertain).not.toContain('NOT saved')
    expect(uncertain).not.toContain('back in the queue — try again')

    const certain = hitlFailureCopy(ITEM, 'approved', new Error('rejected'), 'not_saved')
    expect(certain).toContain('NOT saved')
    expect(certain).toContain('back in the queue — try again')
  })
})
