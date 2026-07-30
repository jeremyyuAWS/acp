import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// ADR 0026 — the Accessibility Status hero. Pins: decision-first headline + coverage/status split,
// the six-bucket segmented bar, the labeled estimate, the Why? affordance, the one dynamic CTA, and
// the honesty rules (no fabricated %, "Automatically Verified" not "Certified", degrade on unavailable).

// Unmount every root this file mounts — see testRoots.js.
afterEach(unmountAll)

const getFileStatus = vi.fn()
const getScanStatus = vi.fn()
vi.mock('./api.js', () => ({
  getFileStatus: (...a) => getFileStatus(...a),
  getScanStatus: (...a) => getScanStatus(...a),
}))

const { default: AccessibilityStatus } = await import('./AccessibilityStatus.jsx')

let container, root
const mount = async (onAction) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(AccessibilityStatus, { scanId: 's1', file: 'f.pdf', onAction })) })
}
const settle = async (n = 5) => { for (let k = 0; k < n; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }
const click = async (el) => { await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) }) }
const text = () => container.textContent

const READY_AFTER = {
  available: true, in_scope: 20, coverage: { evaluable: 18, total: 20 }, resolved: 16,
  automatically_verified: 16, human_verified: 0, needs_review: 2, needs_remediation: 0,
  not_automatically_assessable: 2, not_applicable: 0, unapplied_approved: 0,
  est_review_secs: 120, state: 'ready_after_review', cta: 'Review Findings',
}

beforeEach(() => { getFileStatus.mockReset(); getScanStatus.mockReset() })

describe('AccessibilityStatus (ADR 0026 hero)', () => {
  it('leads with the decision, shows coverage separately, resolved count, and the estimate', async () => {
    getFileStatus.mockResolvedValue(READY_AFTER)
    await mount(); await settle()
    expect(getFileStatus).toHaveBeenCalledWith('s1', 'f.pdf')
    expect(text()).toContain('Ready after 2 reviews')      // decision first
    expect(text()).toContain('Assessment Coverage')        // coverage kept separate from status
    expect(text()).toContain('18 / 20')
    expect(text()).toContain('16 of 20 criteria resolved')
    expect(text()).toContain('Est. review ~2 min')         // labeled estimate, not precision
  })

  it('renders the six-bucket segmented bar with plain labels (Auto Verified, not Certified)', async () => {
    getFileStatus.mockResolvedValue(READY_AFTER)
    await mount(); await settle()
    expect(container.querySelectorAll('.acstatus-seg').length).toBeGreaterThanOrEqual(2)
    expect(text()).toContain('Auto Verified')
    expect(text()).toContain('Needs Review')
    expect(text()).not.toContain('Certified')              // an automated pass is never "Certified"
    expect(text()).not.toContain('%')                      // no fabricated percentage anywhere
  })

  it('Why? expands the honest explanation and never claims work was skipped', async () => {
    getFileStatus.mockResolvedValue(READY_AFTER)
    await mount(); await settle()
    await click(container.querySelector('.acstatus-why-btn')); await settle()
    expect(text()).toContain('Nothing has been skipped')
    expect(text().toLowerCase()).toContain('human judgement')
  })

  it('the one CTA is state-matched and fires onAction with the state', async () => {
    const onAction = vi.fn()
    getFileStatus.mockResolvedValue(READY_AFTER)
    await mount(onAction); await settle()
    const cta = container.querySelector('.acstatus-cta')
    expect(cta.textContent).toBe('Review Findings')
    await click(cta)
    expect(onAction).toHaveBeenCalledWith('ready_after_review')
  })

  it('a clean doc reads "Ready for certification" with the no-gaps trust sentence', async () => {
    getFileStatus.mockResolvedValue({
      available: true, in_scope: 20, coverage: { evaluable: 20, total: 20 }, resolved: 20,
      automatically_verified: 20, human_verified: 0, needs_review: 0, needs_remediation: 0,
      not_automatically_assessable: 0, not_applicable: 0, unapplied_approved: 0,
      est_review_secs: 0, state: 'ready_for_certification', cta: 'Generate Report',
    })
    await mount(); await settle()
    expect(text()).toContain('Ready for certification')
    expect(text()).toContain('No unresolved assessment gaps')
    expect(container.querySelector('.acstatus-cta').textContent).toBe('Generate Report')
  })

  it('degrades to nothing when the status is unavailable', async () => {
    getFileStatus.mockResolvedValue({ available: false })
    await mount(); await settle()
    expect(container.querySelector('.acstatus')).toBeNull()
  })
})

// ── scope unification (ADR 0026 PR 3): omit `file` → the SAME card renders the scan roll-up ──
describe('scan scope (one component, every scope)', () => {
  const SCAN = {
    ...READY_AFTER,
    scope: 'scan', documents: 12, in_scope: 240, coverage: { evaluable: 210, total: 240 },
    resolved: 190, automatically_verified: 180, human_verified: 10, needs_review: 14,
    needs_remediation: 6, not_automatically_assessable: 30,
    est_review_secs: 630, state: 'needs_remediation', cta: 'Start Remediation',
  }

  const mountScan = async () => {
    ;({ container, root } = createTestRoot())
    await act(async () => { root.render(createElement(AccessibilityStatus, { scanId: 's1' })) })
  }

  it('omitting file calls getScanStatus and shows the documents count', async () => {
    getScanStatus.mockResolvedValue(SCAN)
    await mountScan(); await settle()
    expect(getScanStatus).toHaveBeenCalledWith('s1')
    expect(getFileStatus).not.toHaveBeenCalled()
    expect(text()).toContain('190 of 240 criteria resolved across 12 documents')
    expect(text()).toContain('6 issues need remediation')     // state re-derived over the totals
    expect(container.querySelector('[role="status"]').getAttribute('aria-label')).toContain('scan')
  })

  it('the per-file mount keeps its per-document aria label', async () => {
    getFileStatus.mockResolvedValue(READY_AFTER)
    await mount(); await settle()
    expect(container.querySelector('[role="status"]').getAttribute('aria-label')).toContain('document')
  })
})
