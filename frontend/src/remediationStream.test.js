import { describe, it, expect, vi, afterEach } from 'vitest'

vi.mock('./sim.js', async (importOriginal) => ({ ...(await importOriginal()), SIM: false }))
const { openRemediationStream, setGoogleToken } = await import('./api.js')

afterEach(() => vi.unstubAllGlobals())

function streamOf(chunks) {
  const enc = new TextEncoder()
  let i = 0
  return new ReadableStream({
    pull(controller) {
      if (i < chunks.length) controller.enqueue(enc.encode(chunks[i++]))
      else controller.close()
    },
  })
}

describe('openRemediationStream', () => {
  it('delivers progress and closes on the terminal frame using authenticated fetch', async () => {
    setGoogleToken('token')
    const body = streamOf([
      'data: {"in_flight":4,"failed":0}\n\n',
      'data: {"in_flight":2,"failed":0,"activity":{"text":"Applying title fix"}}\n\n',
      'event: done\ndata: {"done":true}\n\n',
    ])
    const fetchMock = vi.fn(async () => ({ ok: true, body }))
    vi.stubGlobal('fetch', fetchMock)
    const seen = []
    let done = false

    openRemediationStream('scan 1', { onMessage: (v) => seen.push(v), onDone: () => { done = true } })
    await vi.waitFor(() => expect(done).toBe(true))

    expect(seen.map((v) => v.in_flight)).toEqual([4, 2])
    expect(fetchMock.mock.calls[0][0]).toContain('/scans/scan%201/remediation/stream')
    expect(fetchMock.mock.calls[0][1].headers.Authorization).toBe('Bearer token')
  })

  it('reports a refused stream so the caller can fall back to polling', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, body: null })))
    let failed = false
    openRemediationStream('s2', { onError: () => { failed = true } })
    await vi.waitFor(() => expect(failed).toBe(true))
  })
})
