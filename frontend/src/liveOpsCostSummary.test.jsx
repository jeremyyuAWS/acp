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

describe('Azure billing actuals', () => {
  // `billing.configured` was hardcoded False and no Cost Management call existed, so this panel
  // could only ever show a rate-card estimate. These pin how a real invoice figure is presented:
  // as a measurement of a stale window, never as a live cost, and never blended with the estimate.
  const withBilling = (billing) => ({
    measured_at: new Date().toISOString(), rate_source: 'East US 2 Consumption',
    estimate_label: 'Estimated from configured capacity', estimated_hourly_usd: 0.96,
    estimated_daily_usd: 23.04, services: [], billing,
  })

  it('shows month-to-date spend with when it was read, and the four-hour caveat', async () => {
    await render(withBilling({
      configured: true, actual_month_to_date_usd: 418.62, forecast_month_usd: 910.4,
      currency: 'USD', updated_at: new Date().toISOString(),
      freshness_label: 'Azure billing data last updated',
      refresh_note: 'Azure Cost Management refreshes roughly every four hours; month-to-date is a measurement, not a live figure.',
      unavailable_reason: null, forecast_unavailable_reason: null,
    }))
    expect(host.textContent).toContain('$418.62')
    expect(host.textContent).toContain('$910.40')
    expect(host.textContent).toContain('Azure billing data last updated')
    expect(host.textContent).toContain('four hours')
    // Never presented as live, whatever else the panel says.
    expect(host.textContent.toLowerCase()).not.toContain('live cost')
  })

  it('keeps the estimate and the invoice as separate numbers', async () => {
    // They are different kinds of number: one is what Azure billed, the other what this capacity
    // would cost at a rate card ACP was told. Summing or blending them would make both wrong.
    await render(withBilling({
      configured: true, actual_month_to_date_usd: 100, forecast_month_usd: null,
      currency: 'USD', updated_at: new Date().toISOString(),
      freshness_label: 'Azure billing data last updated', unavailable_reason: null,
      forecast_unavailable_reason: 'no_data',
    }))
    expect(host.textContent).toContain('$0.9600')
    expect(host.textContent).toContain('$100.00')
    expect(host.textContent).toContain('AZURE BILLING ACTUALS')
    expect(host.textContent).toContain('Forecast not returned')
  })

  it('names a non-dollar currency instead of relabelling it', async () => {
    await render(withBilling({
      configured: true, actual_month_to_date_usd: 55.5, forecast_month_usd: null,
      currency: 'EUR', updated_at: new Date().toISOString(),
      freshness_label: 'Azure billing data last updated', unavailable_reason: null,
    }))
    expect(host.textContent).toContain('EUR')
  })

  it('says which role is missing rather than just "not reported"', async () => {
    // An operator told only "unavailable" grants the wrong role: Cost Management Reader is a
    // different assignment from the Monitoring Reader the metrics path needs.
    await render(withBilling({
      configured: false, actual_month_to_date_usd: null, forecast_month_usd: null,
      currency: null, updated_at: null,
      freshness_label: 'Azure billing actuals unavailable: Cost Management Reader role needed',
      unavailable_reason: 'permission', forecast_unavailable_reason: 'permission',
    }))
    expect(host.textContent).toContain('Cost Management Reader role needed')
    // And no dollar figure is invented in its place.
    expect(host.textContent).not.toContain('$0.00')
  })

  it('renders against a backend that predates the billing block', async () => {
    // Mid-rollout the API can be older than the bundle; the tile falls back to its label rather
    // than throwing on a missing key.
    await render(withBilling(undefined))
    expect(host.textContent).toContain('AZURE BILLING ACTUALS')
    expect(host.textContent).toContain('Not reported')
  })
})

// On 2026-09-07 the panel read "Billing actuals — Not configured" beside a tile saying "Cost
// Management is throttling". The feed was fully configured; Azure was asking the app to wait.
describe('A throttled billing feed is temporary, not unconfigured', () => {
  const base = () => ({ configured: true, measured_at: new Date().toISOString(),
    rate_source: 'East US 2 Consumption list price', estimated_hourly_usd: 3.5496, estimated_daily_usd: 85.19,
    services: [], billing: { configured: false, delay_note: 'lag by about four hours',
      freshness_label: 'Azure billing actuals unavailable: Cost Management is throttling' } })
  const setup = (billing_actuals) => ({
    capacity: { configured: true, available: true, reason: null },
    rate_card: { configured: true, reason: null },
    billing_actuals,
  })

  it('says Temporarily unavailable and when it will retry', async () => {
    const root = await render({ ...base(), setup: setup({ configured: false, state: 'throttled',
      reason: 'Azure billing actuals unavailable: Cost Management is throttling',
      retry_at: new Date(Date.now() + 15 * 60000).toISOString() }) })
    expect(host.textContent).toContain('Billing actualsTemporarily unavailable')
    expect(host.textContent).not.toContain('Billing actualsNot configured')
    expect(host.textContent).toContain('retrying at')
    act(() => root.unmount())
  })

  it('falls back to the hour when Azure gave no retry time', async () => {
    const root = await render({ ...base(), setup: setup({ configured: false, state: 'throttled',
      reason: 'Azure billing actuals unavailable: Cost Management is throttling', retry_at: null }) })
    expect(host.textContent).toContain('retrying within the hour')
    act(() => root.unmount())
  })

  it('a refusal is Unavailable, and still counts as a missing input', async () => {
    const root = await render({ ...base(), estimated_hourly_usd: null, estimated_daily_usd: null,
      setup: setup({ configured: false, state: 'unavailable',
        reason: 'Azure billing actuals unavailable: Cost Management Reader role needed' }) })
    expect(host.textContent).toContain('Billing actualsUnavailable')
    expect(host.textContent).toContain('1 input missing')
    act(() => root.unmount())
  })

  it('a backend that predates `state` still reads as it always did', async () => {
    const root = await render({ ...base(), setup: setup({ configured: false, reason: 'Azure Cost Management is not connected' }) })
    expect(host.textContent).toContain('Billing actualsNot configured')
    act(() => root.unmount())
  })
})
