/**
 * I.2 — The production approval gate silently failed because of a race condition.
 *
 * Root cause: Remediate.jsx dispatches `acp:hitl-changed` BEFORE it calls updateHitlItem.
 * The reload triggered by that event calls listHitlQueue (GET), which completes faster than
 * the approval PUT. The GET returns the item as still-pending and setQueue puts it back, so
 * clicking Approve appears to do nothing.
 *
 * Fix (api.js): updateHitlItem registers the item in _pendingActs synchronously — before the
 * fetch even starts — so that the listHitlQueue .then() callback, which runs after the GET
 * resolves, finds the item in _pendingActs and filters it out. The entry is cleared when the
 * PUT settles so a network-error undo correctly re-surfaces the item.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// Each test gets a fresh module so _pendingActs starts empty.
beforeEach(() => { vi.resetModules(); vi.stubEnv('VITE_SIM', 'false') })
afterEach(() => { vi.unstubAllEnvs(); vi.restoreAllMocks() })

const ITEM   = { id: 'item-42', status: 'pending', scan_id: 's1', file: 'f.docx', rule_id: '1.1.1' }
const OTHER  = { id: 'item-99', status: 'pending', scan_id: 's1', file: 'g.docx', rule_id: '2.4.4' }

// Stub fetch to:
//   GET  /hitl/queue?... → resolves immediately with the two items above
//   PUT  /hitl/queue/... → resolves after a microtask delay (simulates GET winning the race)
function stubFetch({ putError = false } = {}) {
  let resolvePut
  const putDone = new Promise((res, rej) => {
    resolvePut = putError ? (e) => rej(e || new Error('server error')) : () => res({ id: ITEM.id, status: 'approved' })
  })

  vi.stubGlobal('fetch', vi.fn((url, opts) => {
    const method = opts?.method ?? 'GET'
    if (method === 'GET') {
      // GET resolves immediately — simulates it winning the race vs. the PUT
      return Promise.resolve({
        ok: true, status: 200,
        json: () => Promise.resolve([ITEM, OTHER]),
      })
    }
    // PUT: caller controls when it resolves so we can verify intermediate state
    return putDone.then(
      (body) => ({ ok: true, status: 200, json: () => Promise.resolve(body) }),
    )
  }))

  return { resolvePut }
}

describe('I.2 — listHitlQueue suppresses items whose PUT is still in flight', () => {
  it('sends request identity and the exact row version the reviewer saw', async () => {
    const { resolvePut } = stubFetch()
    const { updateHitlItem } = await import('./api.js')
    const pending = updateHitlItem(ITEM.id, 'approved', null, 'Accessible chart', {
      requestId: 'decision-request-42', expectedVersion: 7,
    })
    const [, opts] = fetch.mock.calls.find(([, options]) => options?.method === 'PUT')
    expect(JSON.parse(opts.body)).toMatchObject({
      request_id: 'decision-request-42', expected_version: 7,
    })
    resolvePut()
    await pending
  })

  it('sends the exact model-call identifier with the reviewer decision', async () => {
    const { resolvePut } = stubFetch()
    const { updateHitlItem } = await import('./api.js')
    const pending = updateHitlItem(ITEM.id, 'approved', null, 'Accessible chart', {
      modelCallId: 'call-exact-42',
    })
    const [, opts] = fetch.mock.calls.find(([, options]) => options?.method === 'PUT')
    expect(JSON.parse(opts.body).model_call_id).toBe('call-exact-42')
    resolvePut()
    await pending
  })

  it('sends positional model-call identifiers for a multi-instance card', async () => {
    const { resolvePut } = stubFetch()
    const { updateHitlItem } = await import('./api.js')
    const pending = updateHitlItem(ITEM.id, 'approved', null, null, {
      modelCallIds: ['vision-1', null, 'vision-3'],
    })
    const [, opts] = fetch.mock.calls.find(([, options]) => options?.method === 'PUT')
    expect(JSON.parse(opts.body).model_call_ids).toEqual(['vision-1', null, 'vision-3'])
    resolvePut()
    await pending
  })

  it('filters out the acted-on item while the PUT is unresolved', async () => {
    stubFetch()
    const { listHitlQueue, updateHitlItem } = await import('./api.js')

    // Fire update (starts PUT but does NOT await it)
    updateHitlItem(ITEM.id, 'approved')

    // Immediately call listHitlQueue — this is what the acp:hitl-changed reload does.
    // The GET resolves with both items, but the PUT is still in flight.
    const items = await listHitlQueue('s1', 'pending')

    // The acted-on item must not resurface; the other item is unaffected.
    expect(items.map((x) => x.id)).toEqual([OTHER.id])
  })

  it('un-suppresses the item after the PUT resolves successfully', async () => {
    const { resolvePut } = stubFetch()
    const { listHitlQueue, updateHitlItem } = await import('./api.js')

    const putPromise = updateHitlItem(ITEM.id, 'approved')
    resolvePut()
    await putPromise   // PUT settled

    // A subsequent listHitlQueue call no longer filters the item.
    // (In production the server now answers 'approved' so the item won't come back
    // via a pending-status filter — but the suppression itself must be lifted.)
    const items = await listHitlQueue('s1', 'pending')
    expect(items.map((x) => x.id)).toContain(ITEM.id)
  })

  it('un-suppresses the item after the PUT fails so the undo works', async () => {
    const { resolvePut } = stubFetch({ putError: true })
    const { listHitlQueue, updateHitlItem } = await import('./api.js')

    const putPromise = updateHitlItem(ITEM.id, 'approved').catch(() => {})
    resolvePut()
    await putPromise   // PUT failed

    // Suppression must be cleared so Remediate.jsx's undoAct can re-add the item and the
    // next reload will include it.
    const items = await listHitlQueue('s1', 'pending')
    expect(items.map((x) => x.id)).toContain(ITEM.id)
  })

  it('does not suppress items that were never actioned', async () => {
    stubFetch()
    const { listHitlQueue } = await import('./api.js')

    const items = await listHitlQueue('s1', 'pending')
    expect(items.map((x) => x.id)).toEqual([ITEM.id, OTHER.id])
  })
})
