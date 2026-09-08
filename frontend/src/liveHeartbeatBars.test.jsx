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

describe('rolling canonical snapshot refresh bars', () => {
  it('buckets successful updates into the last four fifteen-second windows', () => {
    const now = 100_000
    expect(heartbeatBuckets([now - 59_000, now - 4_000, now - 3_000], now))
      .toEqual([1, 0, 0, 2])
  })

  it('renders four fixed refresh slots without a line overlay or noisy live region', () => {
    const now = Date.now()
    const html = renderToStaticMarkup(<LiveHeartbeatBars measuredAt={now} showText />)
    expect(html).toContain('Live · refreshed now')
    expect(html).toContain('Four slots represent fifteen seconds each')
    expect(html).toContain('canonical snapshot refresh')
    expect(html.match(/<i /g)).toHaveLength(4)
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
    expect(css).toMatch(/width:44px;height:18px;flex:0 0 44px/)
    expect(css).toMatch(/width:8px;flex:0 0 8px;height:18px/)
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

  it('always retains exactly four fifteen-second positions', () => {
    const now = 100_000
    expect(retainedHeartbeatHistory([now - 1000], now)).toHaveLength(4)
    expect(HEARTBEAT_INTERVAL_MS).toBe(15_000)
  })

  it('shifts once per fifteen-second interval and freezes a terminal strip', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-09-07T01:02:03Z'))
    const { container, root } = createTestRoot()
    await act(async () => { root.render(createElement(LiveHeartbeatBars, {
      measuredAt: Date.now(), historyKey: 'timer-test', showText: true,
    })) })
    const before = container.innerHTML
    await act(async () => { vi.advanceTimersByTime(14_999) })
    expect(container.innerHTML).toBe(before)
    await act(async () => { vi.advanceTimersByTime(1) })
    expect(container.textContent).toContain('refreshed 15s ago')

    await act(async () => { root.render(createElement(LiveHeartbeatBars, {
      measuredAt: Date.now() - 15_000, historyKey: 'timer-test', terminal: true, showText: true,
    })) })
    const frozen = container.innerHTML
    await act(async () => { vi.advanceTimersByTime(15_000) })
    expect(container.innerHTML).toBe(frozen)
    await act(async () => { root.unmount() })
    vi.useRealTimers()
  })
})
