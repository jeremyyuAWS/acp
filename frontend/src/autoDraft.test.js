// The auto-draft gate must never let the AI Work Inbox stampede the model: no matter how many
// undrafted cards fire on sight, at most MAX_CONCURRENT vision calls run at once, and a call that
// throws still frees its slot.
import { describe, it, expect } from 'vitest'
import { runAutoDraft, _gateState, _MAX_CONCURRENT } from './autoDraft.js'

const deferred = () => { let resolve; const p = new Promise((r) => { resolve = r }); return { p, resolve } }

describe('auto-draft gate — bounded concurrency', () => {
  it('never runs more than MAX_CONCURRENT thunks at once', async () => {
    const gates = Array.from({ length: 6 }, deferred)
    let running = 0
    let peak = 0
    const runs = gates.map((g) => runAutoDraft(async () => {
      running += 1; peak = Math.max(peak, running)
      await g.p
      running -= 1
    }))
    // let the gate admit its first batch
    await Promise.resolve(); await Promise.resolve()
    expect(_gateState().active).toBe(_MAX_CONCURRENT)
    expect(peak).toBeLessThanOrEqual(_MAX_CONCURRENT)
    // drain: releasing one admits the next, peak still capped
    for (const g of gates) { g.resolve(); await Promise.resolve(); await Promise.resolve() }
    await Promise.all(runs)
    expect(peak).toBe(_MAX_CONCURRENT)
    expect(_gateState()).toEqual({ active: 0, queued: 0 })
  })

  it('frees the slot when a thunk throws', async () => {
    await expect(runAutoDraft(async () => { throw new Error('vision down') })).rejects.toThrow('vision down')
    // a subsequent call still gets a slot — the pool was not permanently shrunk
    const ok = await runAutoDraft(async () => 'drafted')
    expect(ok).toBe('drafted')
    expect(_gateState()).toEqual({ active: 0, queued: 0 })
  })
})
