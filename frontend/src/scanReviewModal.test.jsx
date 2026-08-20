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
// The wizard's folder step reads the connection's saved locations, so the mock needs those too.
// A PARTIAL mock of a module a component imports from does not fail at import — it fails at the
// first call, inside a useEffect, and surfaces as an unrelated assertion.
vi.mock('./api.js', () => ({
  getSettings: vi.fn(async () => ({ scan_scope: '' })),
  updateSettings: vi.fn(async () => ({ scan_scope: '' })),
  getScanLocations: vi.fn(async () => ({ locations: {} })),
  setScanLocations: vi.fn(async () => ({ ok: true })),
  listFolders: vi.fn(async () => ({ folders: [] })),
  listSpFolders: vi.fn(async () => ({ drive_id: 'd', folders: [] })),
  // The review step names how many lifecycle rules will run during the discovery.
  listDispositionPolicies: vi.fn(async () => []),
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
const startBtn = (c) => [...dialog(c).querySelectorAll('button')].find((b) => /Start discovery/.test(b.textContent))
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

  it('names the source it is about to scan', async () => {
    // Asserted on the DIALOG, not on `.scanmodal-sec`: the titled "Sources included" section is
    // gone (a heading, a rule and a dot spent on one fact, above the decision the user came for)
    // and the fact moved into the header line. The guarantee — the source is named, accurately —
    // is unchanged, which is why this test stays rather than being deleted with the section.
    const drive = await mount({ source: 'drive', ...BEHAVIOR })
    expect(dialog(drive).textContent).toMatch(/Google Drive/)
    // 'all' has no single source, so it is named for the connected provider (accurate labeling —
    // no longer "everything that isn't SharePoint is Google Drive").
    const all = await mount({ source: 'all', hasDrive: true, ...BEHAVIOR })
    expect(dialog(all).textContent).toMatch(/Google Drive/)
    const sp = await mount({ source: 'sharepoint', ...BEHAVIOR })
    expect(dialog(sp).textContent).toMatch(/SharePoint \/ OneDrive/)
  })

  it('notes a selected folder when one is passed', async () => {
    const c = await mount({ source: 'drive', folder: 'folder-123', ...BEHAVIOR })
    expect(dialog(c).textContent).toMatch(/selected folder/)
  })

  it('shows an honest estimate line for the chosen source', async () => {
    const c = await mount({ source: 'drive', estCount: 50, ...BEHAVIOR })
    expect(dialog(c).querySelector('.scanmodal-est').textContent).toMatch(/~50 documents in Google Drive/)
  })
})

describe('ScanReviewModal — the engine switches are not on this surface', () => {
  // PII scan, Durable scan, Skip Remediated/ and Incremental scan used to sit in front of every
  // user before they could start a basic scan. They are platform behaviour, not per-run decisions
  // a compliance officer should be asked to make: the wrong combination is slow, expensive, or
  // silently narrowing, and none is answerable without knowing how the scanner works.
  //
  // Inverted rather than deleted, because "removed" is a claim that decays. The likeliest way this
  // regresses is somebody restoring them behind an "Advanced" reveal — which is still surface, and
  // Skip Remediated/ is exactly the one nobody should toggle casually.
  it('renders none of the four, even when every setter is wired', async () => {
    const c = await mount({ source: 'all', ...BEHAVIOR })
    const d = dialog(c)
    expect(d.textContent).not.toMatch(/Scan behavior/)
    for (const label of ['PII scan', 'Durable scan', 'Skip Remediated/', 'Incremental scan']) {
      expect([...d.querySelectorAll('[role="switch"]')].some((sw) => (sw.getAttribute('aria-label') || '').includes(label)),
        `behaviour toggle "${label}" is back on the scan modal`).toBe(false)
    }
  })

  it('does not hide them behind an Advanced reveal either', async () => {
    const c = await mount({ source: 'all', ...BEHAVIOR })
    const d = dialog(c)
    expect(d.textContent).not.toMatch(/Advanced/i)
    expect([...d.querySelectorAll('[role="switch"]')].length).toBe(0)
  })

  it('still accepts the props, so callers keep working', async () => {
    // The props are deliberately still in the signature: App passes them, and removing them from
    // both sides at once would make this change bigger than it needs to be.
    const c = await mount({ source: 'drive', estCount: 3, ...BEHAVIOR })
    // This has now lost two proxies in a row — first the "Formats & WCAG criteria" heading (#509),
    // then the Continue control, both of which were only ever standing in for "the modal rendered
    // with these props". Assert the thing itself: the wizard's own primary action is on screen.
    expect(dialog(c).textContent).toMatch(/documents in/)
    expect(startBtn(c), 'the wizard did not mount, so the props were not accepted after all')
      .toBeTruthy()
  })
})

describe('ScanReviewModal — confirm / cancel', () => {
  it('mounts the wizard and runs onConfirm on Start discovery', async () => {
    // One screen (PRD DISC-01) — Start is right there. The guarantee is unchanged: confirming in
    // the wizard reaches the modal's onConfirm.
    const onConfirm = vi.fn()
    const c = await mount({ source: 'drive', estCount: 5, onConfirm })
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
