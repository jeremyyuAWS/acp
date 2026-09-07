import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import LiveHeartbeatBars, { heartbeatBuckets } from './LiveHeartbeatBars.jsx'

describe('rolling assessment heartbeat bars', () => {
  it('buckets successful updates into the last twelve five-second windows', () => {
    const now = 100_000
    expect(heartbeatBuckets([now - 59_000, now - 4_000, now - 3_000], now))
      .toEqual([1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2])
  })

  it('renders twelve vertical bars with an accessible heartbeat count', () => {
    const now = Date.now()
    const html = renderToStaticMarkup(<LiveHeartbeatBars measuredAt={now} />)
    expect(html).toContain('Last 60 seconds: 1 successful live update')
    expect(html.match(/<i /g)).toHaveLength(12)
    expect(html).toContain('data-stage="assess"')
    expect(html).not.toContain('polyline')
  })

  it.each(['discover', 'assess', 'remediate', 'release'])('marks the %s stage for its palette', (stage) => {
    const html = renderToStaticMarkup(<LiveHeartbeatBars measuredAt={Date.now()} stage={stage} />)
    expect(html).toContain(`data-stage="${stage}"`)
  })

  it('drops updates outside the rolling minute', () => {
    const now = 100_000
    expect(heartbeatBuckets([now - 61_000, now - 1_000], now).reduce((a, b) => a + b, 0)).toBe(1)
  })
})
