/**
 * The shared, app-level scan-scope REVIEW modal — the universal gate every scan opens first.
 *
 * It was lifted out of Integrations.jsx (where only the Sources tab reached it) so Discover,
 * Overview, single-file and the Drive/SharePoint browse panels all pass through the same review.
 * This guards its contract directly: the sources-included label, the honest estimate line, the
 * four behavior toggles (only when their setters are wired), the ~1.5×-wider dialog, and that the
 * wizard's Start scan / Cancel resolve to onConfirm / onCancel.
 *
 * DOM-level, not browser-level: this repo's preview server runs vite rooted at the SHARED checkout
 * whatever worktree you are in (CLAUDE.md), so a browser check would exercise code without this.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

// The wizard nested inside reads getSettings/updateSettings.
vi.mock('./api.js', () => ({
  getSettings: vi.fn(async () => ({ scan_scope: '' })),
  updateSettings: vi.fn(async () => ({ scan_scope: '' })),
}))

const { default: ScanReviewModal, scanSourceLabel } = await import('./ScanReviewModal.jsx')

const BEHAVIOR = {
  deepScan: true, setDeepScan: vi.fn(),
  queuedScan: false, setQueuedScan: vi.fn(),
  excludeRemediated: true, setExcludeRemediated: vi.fn(),
  incremental: true, setIncremental: vi.fn(),
}

async function mount(props = {}) {
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(ScanReviewModal, { onConfirm: vi.fn(), onCancel: vi.fn(), ...props })) })
  await act(async () => { await Promise.resolve() })
  return container
}
const click = async (el) => { await act(async () => { el.click() }); await act(async () => { await Promise.resolve() }) }
const dialog = (c) => c.querySelector('[role="dialog"]')
const startBtn = (c) => [...dialog(c).querySelectorAll('button')].find((b) => /Start scan/.test(b.textContent))
const cancelBtn = (c) => [...dialog(c).querySelectorAll('button')].find((b) => b.textContent.trim() === 'Cancel')

describe('scanSourceLabel — accurate per source, not "everything is Google Drive"', () => {
  it('maps each concrete source to its own friendly name', () => {
    expect(scanSourceLabel('local')).toBe('sample corpus')
    expect(scanSourceLabel('sharepoint')).toBe('SharePoint / OneDrive')
    expect(scanSourceLabel('drive')).toBe('Google Drive')
  })

  it("derives 'all' from whichever provider is connected", () => {
    expect(scanSourceLabel('all', { hasDrive: true })).toBe('Google Drive')
    expect(scanSourceLabel('all', { hasSP: true })).toBe('SharePoint / OneDrive')
    // Drive wins when both are present (the app's primary), and with nothing known it stays neutral.
    expect(scanSourceLabel('all', { hasDrive: true, hasSP: true })).toBe('Google Drive')
    expect(scanSourceLabel('all')).toBe('connected source')
    expect(scanSourceLabel('unknown-source')).toBe('connected source')
  })
})

describe('ScanReviewModal — honest estimate line', () => {
  it('suppresses the count for 0 / null / missing (never renders "~0 documents")', async () => {
    for (const estCount of [0, null, undefined]) {
      const c = await mount({ source: 'drive', estCount, ...BEHAVIOR })
      const est = dialog(c).querySelector('.scanmodal-est').textContent
      expect(est, `estCount=${estCount} leaked a ~0 line`).not.toMatch(/~0/)
      expect(est).toMatch(/determined when the scan starts/)
    }
  })

  it('shows the count only for a real positive estimate', async () => {
    const c = await mount({ source: 'drive', estCount: 42, ...BEHAVIOR })
    expect(dialog(c).querySelector('.scanmodal-est').textContent).toMatch(/~42 documents in Google Drive/)
  })
})

describe('ScanReviewModal — chrome and labels', () => {
  it('renders a real dialog labeled "New scan", ~1.5× wider than the old modal', async () => {
    const c = await mount({ source: 'drive', ...BEHAVIOR })
    const d = dialog(c)
    expect(d).toBeTruthy()
    expect(d.getAttribute('aria-modal')).toBe('true')
    expect(d.getAttribute('aria-label')).toBe('New scan')
    // The wider inner panel (min(940px, 100%), up from 620px) is asserted at the source level in
    // scanScopeWizard.test.jsx — jsdom's CSS parser drops the unsupported min() from the DOM style,
    // so it cannot be read back off the rendered node here.
  })

  it('shows a friendly "Sources included" label per source', async () => {
    const drive = await mount({ source: 'drive', ...BEHAVIOR })
    expect(drive.querySelector('.scanmodal-sec').textContent).toMatch(/Google Drive/)
    // 'all' has no single source, so it is named for the connected provider (accurate labeling —
    // no longer "everything that isn't SharePoint is Google Drive").
    const all = await mount({ source: 'all', hasDrive: true, ...BEHAVIOR })
    expect(all.querySelector('.scanmodal-sec').textContent).toMatch(/Google Drive/)
    const sp = await mount({ source: 'sharepoint', ...BEHAVIOR })
    expect(sp.querySelector('.scanmodal-sec').textContent).toMatch(/SharePoint \/ OneDrive/)
  })

  it('notes a selected folder when one is passed', async () => {
    const c = await mount({ source: 'drive', folder: 'folder-123', ...BEHAVIOR })
    expect(c.querySelector('.scanmodal-sec').textContent).toMatch(/selected folder/)
  })

  it('shows an honest estimate line for the chosen source', async () => {
    const c = await mount({ source: 'drive', estCount: 50, ...BEHAVIOR })
    expect(dialog(c).querySelector('.scanmodal-est').textContent).toMatch(/~50 documents in Google Drive/)
  })
})

describe('ScanReviewModal — scan behavior toggles', () => {
  it('carries the four behavior toggles when their setters are wired', async () => {
    const c = await mount({ source: 'all', ...BEHAVIOR })
    const d = dialog(c)
    expect(d.textContent).toMatch(/Scan behavior/)
    for (const label of ['PII scan', 'Durable scan', 'Skip Remediated/', 'Incremental scan']) {
      expect([...d.querySelectorAll('[role="switch"]')].some((s) => (s.getAttribute('aria-label') || '').includes(label)),
        `missing behavior toggle "${label}"`).toBe(true)
    }
  })

  it('omits the Scan behavior section entirely when no setters are wired (browse panels)', async () => {
    const c = await mount({ source: 'drive', estCount: 3 })   // no toggle setters
    expect(dialog(c).textContent).not.toMatch(/Scan behavior/)
    expect([...dialog(c).querySelectorAll('[role="switch"]')].length).toBe(0)
    // The wizard is still there — scope review always shows.
    expect(dialog(c).textContent).toMatch(/Formats & WCAG criteria/)
  })

  it('flips a toggle through its setter', async () => {
    const setDeepScan = vi.fn()
    const c = await mount({ source: 'all', ...BEHAVIOR, setDeepScan })
    const pii = [...dialog(c).querySelectorAll('[role="switch"]')].find((s) => (s.getAttribute('aria-label') || '').includes('PII scan'))
    await click(pii)
    expect(setDeepScan).toHaveBeenCalled()
  })
})

describe('ScanReviewModal — confirm / cancel', () => {
  it('mounts the wizard and runs onConfirm on Start scan', async () => {
    const onConfirm = vi.fn()
    const c = await mount({ source: 'drive', estCount: 5, onConfirm })
    expect(dialog(c).textContent).toMatch(/Formats & WCAG criteria/)
    const start = startBtn(c)
    expect(start).toBeTruthy()
    await click(start)
    expect(onConfirm).toHaveBeenCalled()
  })

  it('runs onCancel — not onConfirm — on the wizard Cancel', async () => {
    const onConfirm = vi.fn(); const onCancel = vi.fn()
    const c = await mount({ source: 'drive', onConfirm, onCancel })
    await click(cancelBtn(c))
    expect(onCancel).toHaveBeenCalled()
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('runs onCancel on the × close button', async () => {
    const onCancel = vi.fn()
    const c = await mount({ source: 'drive', onCancel })
    await click(dialog(c).querySelector('button[aria-label="Close"]'))
    expect(onCancel).toHaveBeenCalled()
  })

  it('runs onCancel when the backdrop is clicked', async () => {
    const onCancel = vi.fn()
    const c = await mount({ source: 'drive', onCancel })
    await click(dialog(c))   // the backdrop is the role=dialog element itself
    expect(onCancel).toHaveBeenCalled()
  })
})
