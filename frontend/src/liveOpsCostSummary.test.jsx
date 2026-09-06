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

  it('separates the three data feeds and preserves measured capacity without a rate card', async () => {
    const root = await render({ configured: true, measured_at: new Date().toISOString(),
      rate_source: null, estimated_hourly_usd: null, estimated_daily_usd: null,
      setup: {
        capacity: { configured: true, available: true, reason: null },
        rate_card: { configured: false, reason: 'No operations-approved rate card is configured' },
        billing_actuals: { configured: false, reason: 'Azure Cost Management is not connected' },
      },
      services: [{ app: 'acp-remediate', replicas: 5, allocated_vcpu: 10,
        allocated_memory_gib: 20, estimated_hourly_usd: null,
        unavailable_reason: 'No rate card is configured for this worker service' }],
      billing: { configured: false, freshness_label: 'Azure billing feed not configured',
        delay_note: 'Azure Cost Management actuals can lag by about four hours.' },
    })
    expect(host.textContent).toContain('Worker capacityConnected')
    expect(host.textContent).toContain('Rate cardNot configured')
    expect(host.textContent).toContain('Billing actualsNot configured')
    expect(host.textContent).toContain('2 inputs missing')
    expect(host.textContent).toContain('10 vCPU · 20 GiB allocated')
    expect(host.textContent).toContain('Estimate unavailable')
    expect(host.textContent).toContain('lag by about four hours')
    act(() => root.unmount())
  })

  it('does not call a configured but unreadable Azure capacity feed connected', async () => {
    const root = await render({ configured: true, measured_at: new Date().toISOString(),
      rate_source: 'Approved rates', estimated_hourly_usd: null, estimated_daily_usd: null,
      setup: {
        capacity: { configured: true, available: false, reason: 'Capacity could not be read for: acp-assess' },
        rate_card: { configured: true }, billing_actuals: { configured: false },
      }, services: [], billing: { configured: false, freshness_label: 'Not connected' } })
    expect(host.textContent).toContain('Worker capacityUnavailable')
    expect(host.textContent).toContain('Capacity could not be read for: acp-assess')
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
