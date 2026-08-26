/**
 * GET /scans/{scanId}/discover/stream (api/routes/scans.py, #840) — read manually via
 * fetch()+ReadableStream rather than the browser's native EventSource, which cannot send the
 * Authorization bearer header every other call in api.js uses. See openDiscoverStream's own
 * comment for why a URL-embedded token was rejected instead.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
// api.js short-circuits to canned data whenever SIM is on, and SIM defaults ON under vitest.
// These tests are about the REAL fetch path, so turn it off for this module only.
vi.mock('./sim.js', async (importOriginal) => ({ ...(await importOriginal()), SIM: false }))

const { parseSSEFrames, openDiscoverStream, setGoogleToken } = await import('./api.js')

afterEach(() => { vi.unstubAllGlobals() })

describe('parseSSEFrames — pure parsing', () => {
  it('parses a single complete frame', () => {
    const { frames, rest } = parseSSEFrames('data: {"phase":"listing"}\n\n')
    expect(frames).toEqual([{ event: 'message', data: '{"phase":"listing"}' }])
    expect(rest).toBe('')
  })

  it('recognises an event: line', () => {
    const { frames } = parseSSEFrames('event: done\ndata: {"done": true}\n\n')
    expect(frames).toEqual([{ event: 'done', data: '{"done": true}' }])
  })

  it('parses multiple frames in one buffer', () => {
    const buf = 'data: {"a":1}\n\ndata: {"a":2}\n\n'
    const { frames, rest } = parseSSEFrames(buf)
    expect(frames.map((f) => f.data)).toEqual(['{"a":1}', '{"a":2}'])
    expect(rest).toBe('')
  })

  it('leaves a partial (not yet blank-line-terminated) frame in rest', () => {
    const { frames, rest } = parseSSEFrames('data: {"a":1}\n\ndata: {"a":2')
    expect(frames.map((f) => f.data)).toEqual(['{"a":1}'])
    expect(rest).toBe('data: {"a":2')
  })

  it('completes a frame split across two chunks once the rest arrives', () => {
    const first = parseSSEFrames('data: {"a":2')
    expect(first.frames).toEqual([])
    const second = parseSSEFrames(first.rest + '}\n\n')
    expect(second.frames).toEqual([{ event: 'message', data: '{"a":2}' }])
  })

  it('ignores a frame with no data: line at all', () => {
    const { frames } = parseSSEFrames(': keepalive comment\n\n')
    expect(frames).toEqual([])
  })
})

/** Encodes a series of text chunks into a real ReadableStream, the same shape res.body is. */
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

describe('openDiscoverStream — end to end over a fake fetch', () => {
  it('delivers one onMessage per data: frame, in order', async () => {
    setGoogleToken('token')
    const body = streamOf(['data: {"phase":"listing","files_found":10}\n\n',
                            'data: {"phase":"listing","files_found":20}\n\n'])
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, body })))

    const seen = []
    let done = false
    openDiscoverStream('s1', { onMessage: (s) => seen.push(s), onDone: () => { done = true } })

    await vi.waitFor(() => expect(done).toBe(true))
    expect(seen).toEqual([{ phase: 'listing', files_found: 10 }, { phase: 'listing', files_found: 20 }])
  })

  it('calls onDone on the server\'s terminal "done" frame and stops reading', async () => {
    setGoogleToken('token')
    const body = streamOf(['data: {"phase":"lifecycle"}\n\n', 'event: done\ndata: {"done": true}\n\n',
                            'data: {"phase":"should not arrive"}\n\n'])
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, body })))

    const seen = []
    let done = false
    openDiscoverStream('s2', { onMessage: (s) => seen.push(s), onDone: () => { done = true } })

    await vi.waitFor(() => expect(done).toBe(true))
    expect(seen).toEqual([{ phase: 'lifecycle' }])   // the post-done frame never arrives
  })

  it('calls onError on the server\'s terminal "error" frame', async () => {
    setGoogleToken('token')
    const body = streamOf(['event: error\ndata: {"error": "no active job for this scan"}\n\n'])
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, body })))

    let errored = false
    openDiscoverStream('s3', { onError: () => { errored = true } })
    await vi.waitFor(() => expect(errored).toBe(true))
  })

  it('calls onError when the HTTP response itself is not ok (e.g. 404 from the ownership check)', async () => {
    setGoogleToken('token')
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 404, body: null })))

    let errored = false
    openDiscoverStream('s4', { onError: () => { errored = true } })
    await vi.waitFor(() => expect(errored).toBe(true))
  })

  it('close() aborts the underlying fetch — a caller that navigates away stops the connection', async () => {
    setGoogleToken('token')
    let capturedSignal = null
    vi.stubGlobal('fetch', vi.fn((url, opts) => {
      capturedSignal = opts.signal
      return new Promise(() => {}) // never resolves — same shape a real still-open connection has
    }))

    const stream = openDiscoverStream('s5', {})
    await vi.waitFor(() => expect(capturedSignal).not.toBeNull())
    expect(capturedSignal.aborted).toBe(false)
    stream.close()
    expect(capturedSignal.aborted).toBe(true)
  })

  it('sends the same Authorization header every other authenticated call uses', async () => {
    setGoogleToken('tok-abc')
    let capturedHeaders = null
    vi.stubGlobal('fetch', vi.fn(async (url, opts) => {
      capturedHeaders = opts.headers
      return { ok: true, body: streamOf(['event: done\ndata: {"done": true}\n\n']) }
    }))
    let done = false
    openDiscoverStream('s6', { onDone: () => { done = true } })
    await vi.waitFor(() => expect(done).toBe(true))
    expect(capturedHeaders.Authorization).toBe('Bearer tok-abc')
  })
})
