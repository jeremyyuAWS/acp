/**
 * The queue may not claim anything it has not read.
 *
 * THE DEFECT, at QueuePanel.jsx before this change:
 *
 *     const [q, setQ] = useState(null)
 *     const stats   = q?.stats || {}                    // {} before any response
 *     const shown   = order.filter((s) => stats[s])     // []
 *     const workers = q?.workers ?? 0                   // 0
 *     …
 *     {shown.length === 0 && !err && <span>queue empty — nothing in flight</span>}
 *     <span style={{ fontSize: 22, fontWeight: 700 }}>{workers}</span>
 *
 * On first mount, before a single response has arrived: **"queue empty" and a bold "0" workers**,
 * with +/- controls beside the zero. Two confident factual claims that no successful read had
 * established — and they render identically whether the request is in flight, slow, or has been
 * failing for a minute, so an operator cannot tell "nothing is queued" from "I cannot see the
 * queue".
 *
 * `null` was doing double duty as "not asked yet" and "nothing there". These tests pin the four
 * states that replaces, and the rule that only two of them may make a positive claim.
 */
import { describe, it, expect } from 'vitest'
import {
  FEED_STATES, deriveFeedState, hasConfirmedData, needsFreshnessLabel,
  ageLabel, statusLine, topologyIsKnown,
} from './queueFreshness.js'

const OK = { stats: { queued: 3 }, workers: 2, runtime_mode: 'distributed' }
const FRESH = { fetchedAt: Date.now(), ageMs: 1200, stale: false }
const OLD = { fetchedAt: Date.now() - 240000, ageMs: 240000, stale: true }

describe('the state before anything has been read', () => {
  it('is loading, not "nothing there"', () => {
    // THE regression. Before the fix this case was indistinguishable from a confirmed empty
    // queue, because both produced zero rows to render.
    expect(deriveFeedState({ data: null, meta: null, error: null })).toBe('loading')
  })

  it('permits no claim about the queue', () => {
    expect(hasConfirmedData(deriveFeedState({ data: null }))).toBe(false)
  })

  it('says what it is doing rather than what the queue contains', () => {
    const line = statusLine('loading')
    expect(line).toMatch(/checking/i)
    expect(line).not.toMatch(/empty|0|zero/i)
  })

  it('treats undefined the same as null — a missing payload is not an empty one', () => {
    expect(deriveFeedState({ data: undefined })).toBe('loading')
  })
})

describe('a confirmed read', () => {
  it('is current when fresh', () => {
    expect(deriveFeedState({ data: OK, meta: FRESH, error: null })).toBe('current')
  })

  it('may claim the queue is empty — this is the only state that earns it', () => {
    expect(hasConfirmedData(deriveFeedState({ data: { stats: {} }, meta: FRESH }))).toBe(true)
  })

  it('needs no freshness label while it is current', () => {
    expect(needsFreshnessLabel(deriveFeedState({ data: OK, meta: FRESH }))).toBe(false)
  })
})

describe('failure with something cached — the case worth distinguishing', () => {
  it('is stale, not unavailable: the counts are real, they are simply old', () => {
    expect(deriveFeedState({ data: OK, meta: OLD, error: new Error('500') })).toBe('stale')
  })

  it('keeps the last-known counts showable', () => {
    expect(hasConfirmedData(deriveFeedState({ data: OK, meta: OLD, error: new Error('503') })))
      .toBe(true)
  })

  it('requires the age to be shown beside them', () => {
    expect(needsFreshnessLabel(deriveFeedState({ data: OK, meta: OLD, error: new Error('500') })))
      .toBe(true)
  })

  it('says how old, so a four-minute-old number is never read as live', () => {
    expect(statusLine('stale', { ageMs: 240000 })).toMatch(/4m ago/)
  })

  it('goes stale on age alone, with no error at all', () => {
    // A poll that simply stopped arriving — a hidden tab, a paused feed — is not a failure, but
    // the number on screen is still old and must say so.
    expect(deriveFeedState({ data: OK, meta: OLD, error: null })).toBe('stale')
  })
})

describe('failure with nothing cached', () => {
  it('is unavailable — there is no honest count to show', () => {
    expect(deriveFeedState({ data: null, meta: null, error: new Error('503') }))
      .toBe('unavailable')
  })

  it('permits no claim', () => {
    expect(hasConfirmedData('unavailable')).toBe(false)
  })

  it('says it could not read, not that the queue is empty', () => {
    const line = statusLine('unavailable')
    expect(line).toMatch(/unavailable|could not/i)
    expect(line).not.toMatch(/empty/i)
  })
})

describe('the specific failures asked for', () => {
  // 500 and 503 differ only in the message; what matters is whether anything was cached first.
  it.each([['500'], ['503']])('a %s before any success is unavailable, never empty', (code) => {
    const st = deriveFeedState({ data: null, error: new Error(code) })
    expect(st).toBe('unavailable')
    expect(hasConfirmedData(st)).toBe(false)
  })

  it.each([['500'], ['503']])('a %s after a success keeps the last-known data', (code) => {
    expect(deriveFeedState({ data: OK, meta: OLD, error: new Error(code) })).toBe('stale')
  })

  it('a delayed first response stays loading throughout — never a momentary "empty"', () => {
    // The slow-response case: the panel is mounted, polling, and nothing has come back. Every
    // intermediate observation must be `loading`.
    for (const ageMs of [0, 500, 2000, 10000, 60000]) {
      expect(deriveFeedState({ data: null, meta: { fetchedAt: null, ageMs, stale: true } }))
        .toBe('loading')
    }
  })

  it('returning to a tab shows the cached counts as stale, not as fresh', () => {
    // jobsFeed pauses on document.hidden and keeps the cache with its timestamp. On return the
    // data is real but old — which is exactly `stale`, and must carry its age.
    const st = deriveFeedState({ data: OK, meta: OLD, error: null })
    expect(st).toBe('stale')
    expect(needsFreshnessLabel(st)).toBe(true)
    expect(statusLine(st, { ageMs: OLD.ageMs })).toMatch(/ago/)
  })
})

describe('worker controls and topology', () => {
  it('are withheld when runtime_mode is absent — unknown is not zero', () => {
    expect(topologyIsKnown({ stats: {}, workers: 0 })).toBe(false)
  })

  it('are withheld before any response', () => {
    expect(topologyIsKnown(null)).toBe(false)
  })

  it('are permitted once the topology is actually stated', () => {
    expect(topologyIsKnown({ runtime_mode: 'distributed' })).toBe(true)
    expect(topologyIsKnown({ runtime_mode: 'in_process' })).toBe(true)
  })

  it('treats an empty runtime_mode as unknown rather than as a mode', () => {
    expect(topologyIsKnown({ runtime_mode: '' })).toBe(false)
  })
})

describe('ageLabel', () => {
  it('returns null with no timestamp, so nothing renders rather than a fabricated zero', () => {
    expect(ageLabel(null)).toBeNull()
    expect(ageLabel(undefined)).toBeNull()
    expect(ageLabel(NaN)).toBeNull()
    expect(ageLabel(-5)).toBeNull()
  })

  it('is coarse on purpose — a per-second tick invites reading it as live', () => {
    expect(ageLabel(1000)).toBe('just now')
    expect(ageLabel(20000)).toBe('20s ago')
    expect(ageLabel(180000)).toBe('3m ago')
    expect(ageLabel(7200000)).toBe('2h ago')
  })
})

describe('the state set', () => {
  it('is exhaustive — every state some input produces is declared', () => {
    const produced = new Set([
      deriveFeedState({ data: null }),
      deriveFeedState({ data: null, error: new Error('x') }),
      deriveFeedState({ data: OK, meta: FRESH }),
      deriveFeedState({ data: OK, meta: OLD }),
    ])
    expect([...produced].sort()).toEqual([...FEED_STATES].sort())
  })

  it('lets exactly two states make a claim', () => {
    expect(FEED_STATES.filter(hasConfirmedData)).toEqual(['current', 'stale'])
  })
})
