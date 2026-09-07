import { act, createElement } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createTestRoot } from './testRoots.js'
import LiveHeartbeatBars, { heartbeatBuckets, HEARTBEAT_INTERVAL_MS,
  retainedHeartbeatHistory } from './LiveHeartbeatBars.jsx'

const here = dirname(fileURLToPath(import.meta.url))

describe('rolling assessment heartbeat bars', () => {
  it('buckets successful updates into the last twelve five-second windows', () => {
    const now = 100_000
    expect(heartbeatBuckets([now - 59_000, now - 4_000, now - 3_000], now))
      .toEqual([1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2])
  })

  it('renders twelve fixed history bars without a line overlay or noisy live region', () => {
    const now = Date.now()
    const html = renderToStaticMarkup(<LiveHeartbeatBars measuredAt={now} showText />)
    expect(html).toContain('Live · refreshed now')
    expect(html).toContain('totals are from the canonical snapshot')
    expect(html.match(/<i /g)).toHaveLength(12)
    expect(html).toContain('data-stage="assess"')
    expect(html).not.toContain('polyline')
    expect(html).not.toContain('aria-live')
    expect(html).not.toContain('role="status"')
  })

  it.each(['discover', 'assess', 'remediate', 'release'])('marks the %s stage for its palette', (stage) => {
    const html = renderToStaticMarkup(<LiveHeartbeatBars measuredAt={Date.now()} stage={stage} />)
    expect(html).toContain(`data-stage="${stage}"`)
  })

  it('locks the strip dimensions and maps the approved stage colors', () => {
    const css = readFileSync(join(here, 'live-heartbeat-bars.css'), 'utf8')
    expect(css).toMatch(/width:57px;height:18px;flex:0 0 57px/)
    expect(css).toMatch(/data-stage="discover"[^}]*#1f5fa8/)
    expect(css).toMatch(/data-stage="assess"[^}]*#397521/)
    expect(css).toMatch(/data-stage="remediate"[^}]*#8a5a00/)
    expect(css).toMatch(/data-stage="release"[^}]*#6f4a78/)
    expect(css).toMatch(/prefers-reduced-motion:reduce[^}]*transition:none/)
  })

  it('drops updates outside the rolling minute', () => {
    const now = 100_000
    expect(heartbeatBuckets([now - 61_000, now - 1_000], now).reduce((a, b) => a + b, 0)).toBe(1)
  })

  it('always retains exactly twelve five-second positions', () => {
    const now = 100_000
    expect(retainedHeartbeatHistory([now - 1000], now)).toHaveLength(12)
    expect(HEARTBEAT_INTERVAL_MS).toBe(5000)
  })

  it('shifts once per five-second interval and freezes a terminal strip', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-07T01:02:03Z'))
    const { container, root } = createTestRoot()
    await act(async () => { root.render(createElement(LiveHeartbeatBars, {
      measuredAt: Date.now(), historyKey: 'timer-test', showText: true,
    })) })
    const before = container.innerHTML
    await act(async () => { vi.advanceTimersByTime(4999) })
    expect(container.innerHTML).toBe(before)
    await act(async () => { vi.advanceTimersByTime(1) })
    expect(container.textContent).toContain('refreshed 5s ago')

    await act(async () => { root.render(createElement(LiveHeartbeatBars, {
      measuredAt: Date.now() - 5000, historyKey: 'timer-test', terminal: true, showText: true,
    })) })
    const frozen = container.innerHTML
    await act(async () => { vi.advanceTimersByTime(15_000) })
    expect(container.innerHTML).toBe(frozen)
    await act(async () => { root.unmount() })
    vi.useRealTimers()
  })
})
