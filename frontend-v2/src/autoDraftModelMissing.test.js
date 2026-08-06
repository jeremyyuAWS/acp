import { describe, it, expect, beforeEach, vi } from 'vitest'
import { runAutoDraft, resetAutoDraftBreaker, _gateState, _breakerTripped } from './autoDraft.js'

// A missing model is a property of the DEPLOYMENT, not of a card.
//
// A reachable Ollama that never pulled the model 503s every draft identically. Opening a
// 40-finding inbox therefore used to discover the same missing model 40 times — 40 requests, and
// the reviewer told nothing until each card's own attempt returned. These pin the breaker that
// ends that, and — just as important — pin what must NOT trip it: a model that IS pulled and
// merely failed has to stay retryable per card, or one timeout stops the whole inbox drafting.

const missing = () => Object.assign(new Error(
  "AI suggestion unavailable — model not pulled: Ollama is running but the text model " +
  "'llama3.2' is not present. Run: ollama pull llama3.2"), { aiModelNotPulled: true })

beforeEach(() => resetAutoDraftBreaker())

describe('autoDraft — the missing-model breaker', () => {
  it('trips on the first missing-model failure and spares every later call a request', async () => {
    const fn = vi.fn().mockRejectedValue(missing())
    await expect(runAutoDraft(fn)).rejects.toThrow(/model not pulled/)
    expect(fn).toHaveBeenCalledTimes(1)

    const later = vi.fn()
    for (let i = 0; i < 39; i++) {
      await expect(runAutoDraft(later)).rejects.toThrow(/model not pulled/)
    }
    expect(later).not.toHaveBeenCalled()          // 39 cards, zero requests
    expect(_breakerTripped()).toBe(true)
  })

  it('replays the SAME error, so a spared card can still show the reason and the pull', async () => {
    await expect(runAutoDraft(() => Promise.reject(missing()))).rejects.toThrow()
    const e = await runAutoDraft(vi.fn()).catch((x) => x)
    expect(e.aiModelNotPulled).toBe(true)
    expect(e.message).toMatch(/ollama pull llama3\.2/)
    expect(e.message).toMatch(/llama3\.2/)
  })

  it('does NOT trip on an ordinary draft failure — the next card may well succeed', async () => {
    const boom = vi.fn().mockRejectedValue(new Error('read ETIMEDOUT'))
    await expect(runAutoDraft(boom)).rejects.toThrow(/ETIMEDOUT/)
    const next = vi.fn().mockResolvedValue('a drafted value')
    await expect(runAutoDraft(next)).resolves.toBe('a drafted value')
    expect(next).toHaveBeenCalledTimes(1)
    expect(_breakerTripped()).toBe(false)
  })

  it('a short-circuit takes no slot, so the pool is never shrunk by doomed calls', async () => {
    await expect(runAutoDraft(() => Promise.reject(missing()))).rejects.toThrow()
    await expect(runAutoDraft(vi.fn())).rejects.toThrow()
    expect(_gateState()).toMatchObject({ active: 0, queued: 0 })
  })

  it('re-checks after waiting for a slot, so a QUEUED draft is spared too', async () => {
    // Fill both slots with drafts that fail on the missing model, and queue a third behind them.
    // A breaker checked only on entry would let the queued one fire — it entered while closed.
    let releaseA, releaseB
    const a = vi.fn(() => new Promise((_, rej) => { releaseA = () => rej(missing()) }))
    const b = vi.fn(() => new Promise((_, rej) => { releaseB = () => rej(missing()) }))
    const queued = vi.fn().mockResolvedValue('should never run')

    const pa = runAutoDraft(a).catch(() => 'a')
    const pb = runAutoDraft(b).catch(() => 'b')
    await Promise.resolve()
    const pq = runAutoDraft(queued).catch((e) => e)

    releaseA(); releaseB()
    await pa; await pb
    const got = await pq
    expect(queued).not.toHaveBeenCalled()
    expect(got.aiModelNotPulled).toBe(true)
  })

  it('re-arms on demand, so a reviewer who just pulled the model can prove it', async () => {
    await expect(runAutoDraft(() => Promise.reject(missing()))).rejects.toThrow()
    resetAutoDraftBreaker()
    const back = vi.fn().mockResolvedValue('drafted now')
    await expect(runAutoDraft(back)).resolves.toBe('drafted now')
    expect(back).toHaveBeenCalledTimes(1)
  })
})
