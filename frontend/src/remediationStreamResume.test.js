import { describe, it, expect } from 'vitest'
import { parseSSEFrames } from './api.js'

// The client half of ADR 0051. `parseSSEFrames` discarded `id:` until now, which meant no client
// could resume even once the server offered to — the mechanism was half-absent on the wire and
// entirely absent in the browser.

describe('the SSE parser carries the resume cursor', () => {
  it('reads id: alongside event: and data:', () => {
    const { frames } = parseSSEFrames(
      'id: 7\nevent: remediation-event\ndata: {"kind":"remediate.verified"}\n\n')
    expect(frames).toHaveLength(1)
    expect(frames[0].id).toBe('7')
    expect(frames[0].event).toBe('remediation-event')
    expect(JSON.parse(frames[0].data).kind).toBe('remediate.verified')
  })

  it('leaves id null on a frame that has none, rather than inventing one', () => {
    // The snapshot frame carries no id and must not appear to. A cursor advanced by a frame the
    // server never numbered would be a cursor pointing at nothing.
    const { frames } = parseSSEFrames('data: {"in_flight":3}\n\n')
    expect(frames[0].id).toBe(null)
    expect(frames[0].event).toBe('message')
  })

  it('keeps ids attached to the right frames when several arrive in one chunk', () => {
    const { frames, rest } = parseSSEFrames(
      'id: 1\nevent: remediation-event\ndata: {"seq":1}\n\n' +
      'id: 2\nevent: remediation-event\ndata: {"seq":2}\n\n' +
      'data: {"in_flight":0}\n\n' +
      'id: 3\nevent: remediation-event\ndata: {"seq"')
    expect(frames.map((f) => f.id)).toEqual(['1', '2', null])
    // The trailing partial frame is held back, not guessed at — advancing a cursor to 3 here
    // would claim the client rendered an event it has not finished receiving.
    expect(rest.startsWith('id: 3')).toBe(true)
  })

  it('does not mistake a data payload containing "id:" for a frame id', () => {
    const { frames } = parseSSEFrames(
      'event: remediation-event\ndata: {"detail":"id: 99"}\n\n')
    expect(frames[0].id).toBe(null)
  })

  it('still parses an ordinary heartbeat-separated stream unchanged', () => {
    const { frames } = parseSSEFrames(': keep-alive\n\ndata: {"ok":true}\n\n')
    expect(frames).toHaveLength(1)
    expect(JSON.parse(frames[0].data).ok).toBe(true)
  })
})
