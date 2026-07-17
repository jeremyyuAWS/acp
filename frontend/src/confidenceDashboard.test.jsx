import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react-dom/test-utils'

// ADR 0026 Epic 5 — Confidence Dashboard: process confidence, never a model %. Pins: every tile
// is a real ratio shown WITH its counts, the unresolved line is derived from real buckets, and the
// component degrades to nothing when the status is unavailable.
const getScanStatus = vi.fn()
vi.mock('./api.js', () => ({ getScanStatus: (...a) => getScanStatus(...a) }))
const { default: ConfidenceDashboard } = await import('./ConfidenceDashboard.jsx')

let container
const mount = async () => {
  container = document.createElement('div'); document.body.appendChild(container)
  const root = createRoot(container)
  await act(async () => { root.render(createElement(ConfidenceDashboard, { scanId: 's1' })) })
  for (let k = 0; k < 4; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}
const BASE = {
  available: true, scope: 'scan', documents: 12, in_scope: 240,
  coverage: { evaluable: 210, total: 240 }, resolved: 190,
  automatically_verified: 180, human_verified: 10, needs_review: 14, needs_remediation: 6,
  not_automatically_assessable: 30, not_applicable: 0, unapplied_approved: 0,
  est_review_secs: 630, state: 'needs_remediation', cta: 'Start Remediation',
}
beforeEach(() => { getScanStatus.mockReset() })

describe('ConfidenceDashboard (process confidence, ADR 0026 Epic 5)', () => {
  it('every percentage is a real ratio shown with its counts', async () => {
    getScanStatus.mockResolvedValue(BASE)
    await mount()
    expect(container.textContent).toContain('88%')            // 210/240 coverage
    expect(container.textContent).toContain('210 of 240 criteria · 12 documents')
    expect(container.textContent).toContain('75%')            // 180/240 auto verified
    expect(container.textContent).toContain('180 of 240')
    expect(container.textContent).toContain('Needs Review')
  })

  it('the unresolved line derives from the real buckets', async () => {
    getScanStatus.mockResolvedValue(BASE)
    await mount()
    expect(container.textContent).toContain('20 unresolved — 14 need review · 6 need remediation')
  })

  it('a clean scan says so affirmatively', async () => {
    getScanStatus.mockResolvedValue({ ...BASE, needs_review: 0, needs_remediation: 0,
      automatically_verified: 210, state: 'ready_for_certification' })
    await mount()
    expect(container.textContent).toContain('No unresolved criteria')
  })

  it('degrades to nothing when unavailable', async () => {
    getScanStatus.mockResolvedValue({ available: false })
    await mount()
    expect(container.querySelector('.confdash')).toBeNull()
  })
})
