import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { beforeEach, describe, expect, it, vi } from 'vitest'
vi.mock('./api.js', () => ({
  getAiCosts: vi.fn(() => Promise.resolve({ today: { calls: 5, cost_usd: .0123, by_surface: [{ key: 'assessment_second_opinion', calls: 3 }] } })),
  getAiProvidersHealth: vi.fn(() => Promise.resolve({ providers: { huggingface: { errors: 1 } } })),
}))
import LiveOpsAiSummary from './LiveOpsAiSummary.jsx'

describe('Live Ops AI wiring', () => {
  let host
  beforeEach(() => { host = document.createElement('div'); document.body.appendChild(host) })
  it('renders measured second-opinion activity, cost, and provider health', async () => {
    await act(async () => { createRoot(host).render(<LiveOpsAiSummary />); await Promise.resolve() })
    expect(host.textContent).toContain('5 calls')
    expect(host.textContent).toContain('3 calls')
    expect(host.textContent).toContain('$0.0123')
    expect(host.textContent).toContain('1 errors / 24h')
  })
})
