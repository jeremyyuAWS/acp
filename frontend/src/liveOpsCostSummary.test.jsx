import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createRoot } from 'react-dom/client'
import { act } from 'react'
import LiveOpsCostSummary, { money } from './LiveOpsCostSummary.jsx'

const getLiveOpsCosts = vi.fn()
vi.mock('./api.js', () => ({ getLiveOpsCosts: (...args) => getLiveOpsCosts(...args) }))

let host
beforeEach(() => { host = document.createElement('div'); document.body.appendChild(host) })
afterEach(() => { host.remove(); vi.clearAllMocks() })

async function render(value) {
  getLiveOpsCosts.mockResolvedValue(value)
  const root = createRoot(host)
  await act(async () => { root.render(<LiveOpsCostSummary />); await Promise.resolve() })
  return root
}

describe('Live Operations cost transparency', () => {
  it('renders estimates with provenance and keeps billing actuals distinct', async () => {
    const root = await render({ measured_at: new Date().toISOString(), rate_source: 'Contract rates',
      estimate_label: 'Estimated from configured capacity', estimated_hourly_usd: .96,
      estimated_daily_usd: 23.04, services: [{ app: 'acp-assess', replicas: 2, estimated_hourly_usd: .48 }],
      billing: { freshness_label: 'Azure billing feed not configured' } })
    expect(host.textContent).toContain('$0.9600')
    expect(host.textContent).toContain('$23.04')
    expect(host.textContent).toContain('Contract rates')
    expect(host.textContent).toContain('Azure billing feed not configured')
    expect(host.textContent).toContain('They are not invoices')
    act(() => root.unmount())
  })

  it('does not turn missing inputs into zero dollars', async () => {
    const root = await render({ measured_at: null, rate_source: null, estimated_hourly_usd: null,
      estimated_daily_usd: null, services: [], billing: { freshness_label: 'Azure billing feed not configured' } })
    expect(host.textContent).toContain('Not reported')
    expect(host.textContent).not.toContain('$0.00')
    act(() => root.unmount())
  })

  it('formats a genuine zero differently from missing data', () => {
    expect(money(0)).toBe('$0.00')
    expect(money(null)).toBe('Not reported')
  })
})
