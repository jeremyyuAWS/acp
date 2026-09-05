import { describe, it, expect, vi, afterEach } from 'vitest'
// api.js short-circuits to canned data whenever SIM is on, and SIM defaults ON under vitest.
// These tests are about the REAL fetch path, so turn it off for this module only.
vi.mock('./sim.js', async (importOriginal) => ({ ...(await importOriginal()), SIM: false }))

const { openRemediationStream, setGoogleToken } = await import('./api.js')

afterEach(() => { vi.unstubAllGlobals() })

function streamOf(chunks) {
  const enc = new TextEncoder()
  let i = 0
  return new ReadableStream({
    pull(controller) {
      if (i < chunks.length) { controller.enqueue(enc.encode(chunks[i++])); return }
      controller.close()
    },
  })
}

// The client half of ADR 0051's reconnect contract. The header is sent EXPLICITLY because nothing
// sends it for us: `Last-Event-ID` is automatic only for native EventSource, which this codebase
// cannot use (it cannot carry the bearer token).

describe('openRemediationStream resume', () => {
  it('sends the cursor as a request header, not a query parameter', async () => {
    setGoogleToken('tok')
    let url = null, sentHeaders = null
    vi.stubGlobal('fetch', vi.fn(async (u, opts) => {
      url = u; sentHeaders = opts.headers
      return { ok: true, body: streamOf(['event: done\ndata: {"done":true}\n\n']) }
    }))
    let done = false
    openRemediationStream('s1', { lastEventId: 42, onDone: () => { done = true } })
    await vi.waitFor(() => expect(done).toBe(true))
    expect(sentHeaders['Last-Event-ID']).toBe('42')
    // A request URL reaches proxy access logs and browser history; that is why the bearer token
    // is a header here too, and the cursor follows the same rule.
    expect(url).not.toContain('42')
    expect(sentHeaders.Authorization).toBe('Bearer tok')
  })

  it('omits the header entirely on a first connection', async () => {
    setGoogleToken('tok')
    let sentHeaders = null
    vi.stubGlobal('fetch', vi.fn(async (u, opts) => {
      sentHeaders = opts.headers
      return { ok: true, body: streamOf(['event: done\ndata: {"done":true}\n\n']) }
    }))
    let done = false
    openRemediationStream('s2', { onDone: () => { done = true } })
    await vi.waitFor(() => expect(done).toBe(true))
    // Not "" and not "null" — either would be a cursor the server has to parse and reject.
    expect('Last-Event-ID' in sentHeaders).toBe(false)
  })

  it('routes event frames to onEvent with their id, and snapshots to onMessage', async () => {
    setGoogleToken('tok')
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, body: streamOf([
      'id: 3\nevent: remediation-event\ndata: {"kind":"remediate.fix_applied"}\n\n',
      'id: 4\nevent: remediation-event\ndata: {"kind":"remediate.verified"}\n\n',
      'data: {"in_flight":2}\n\n',
      'event: done\ndata: {"done":true}\n\n',
    ]) })))
    const events = [], snapshots = []
    let done = false
    openRemediationStream('s3', {
      onEvent: (e, id) => events.push([e.kind, id]),
      onMessage: (s) => snapshots.push(s),
      onDone: () => { done = true },
    })
    await vi.waitFor(() => expect(done).toBe(true))
    expect(events).toEqual([['remediate.fix_applied', '3'], ['remediate.verified', '4']])
    expect(snapshots).toEqual([{ in_flight: 2 }])
  })

  it('fires onReconcile — and delivers no events — when the server declines to replay', async () => {
    setGoogleToken('tok')
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, body: streamOf([
      'event: reconciliation-required\ndata: {"reason":"cursor_ahead_of_log"}\n\n',
      'data: {"in_flight":0}\n\n',
      'event: done\ndata: {"done":true}\n\n',
    ]) })))
    const events = []
    let reason = null, done = false
    openRemediationStream('s4', {
      onEvent: (e, id) => events.push(id),
      onReconcile: (d) => { reason = d.reason },
      onDone: () => { done = true },
    })
    await vi.waitFor(() => expect(done).toBe(true))
    expect(reason).toBe('cursor_ahead_of_log')
    expect(events).toEqual([])
  })

  it('a caller that passes neither handler behaves exactly as before resume existed', async () => {
    // The rollout-safety property, from the client side: the shipped progress bar passes only
    // onMessage/onDone/onError, and event frames must not reach it as snapshots.
    setGoogleToken('tok')
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, body: streamOf([
      'id: 9\nevent: remediation-event\ndata: {"kind":"remediate.delivered"}\n\n',
      'data: {"in_flight":1}\n\n',
      'event: done\ndata: {"done":true}\n\n',
    ]) })))
    const snapshots = []
    let done = false
    openRemediationStream('s5', { onMessage: (s) => snapshots.push(s), onDone: () => { done = true } })
    await vi.waitFor(() => expect(done).toBe(true))
    expect(snapshots).toEqual([{ in_flight: 1 }])
  })
})
