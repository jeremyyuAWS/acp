import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// W5 — Publish surfaces the set-level certification status and offers a one-action graduation
// from conditional → full without a re-scan. Verified at the DOM level (per the repo's rule that
// worktree changes are proven in vitest, not the shared-checkout preview server).

const publishAllFiles = vi.fn(() => Promise.resolve({ published: [] }))
const listHitlQueue = vi.fn(() => Promise.resolve([]))
const getSettings = vi.fn(() => Promise.resolve({ drive_mirror_enabled: false, drive_mirror_folder: 'Remediated' }))
const putMyReleaseTemplates = vi.fn((templates) => Promise.resolve({ release_templates: templates }))
vi.mock('./api.js', () => ({
  openReport: vi.fn(), publishFile: vi.fn(() => Promise.resolve({})),
  publishAllFiles: (...a) => publishAllFiles(...a),
  getReleaseStatus: vi.fn(() => Promise.resolve({ release_id: null })),
  listReleaseHistory: vi.fn(() => Promise.resolve({ releases: [] })),
  getReleaseManifest: vi.fn(() => Promise.resolve({ manifest: {} })),
  listHitlQueue: (...args) => listHitlQueue(...args),
  getSettings: (...a) => getSettings(...a),
  putMyReleaseTemplates: (...a) => putMyReleaseTemplates(...a),
  getSourceStatus: vi.fn(() => Promise.resolve({ files: [], stale_count: 0 })),
  rescoreFile: vi.fn(() => Promise.resolve({})),
  previewReleaseDestination: vi.fn(() => Promise.resolve({ can_release: true, documents: [] })),
  downloadReleasePackage: vi.fn(() => Promise.resolve()),
}))
// Keep the heavy children out of the mount — this test is about the Publish graduation surface.
vi.mock('./FileDrawer.jsx', () => ({ default: () => null }))
vi.mock('./ScopeBanner.jsx', () => ({ default: () => null }))
vi.mock('./SearchFilterBar.jsx', () => ({
  default: () => null,
  useSearchFilter: () => ({ active: false, clear: () => {} }),
  matchesFilters: () => () => true,
}))
vi.mock('./remediableScope.js', () => ({
  documentSelection: () => ({}),
  documentScopeSentence: () => '',
  documentsInSelection: (files) => files || [],
}))

const { default: Publish } = await import('./Publish.jsx')

afterEach(async () => { await unmountAll(); vi.clearAllMocks(); listHitlQueue.mockResolvedValue([]) })
const flush = async () => { for (let k = 0; k < 5; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }
const mount = async (props) => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(Publish, props)) })
  await flush()
  return container
}
const verified = (file, over = {}) => ({ file, compliant: true, remediated_at: '2026-07-31T00:00:00Z', score: 100, department: 'D', sourceName: 'S', ...over })
const held = (file, over = {}) => ({ file, compliant: false, score: 40, issues: [{ wcag: 'SC_1_1_1' }], department: 'D', sourceName: 'S', ...over })
const run = { id: 'scan1', files: 3, certifiable: 2 }

describe('Publish — W5 conditional-to-full graduation', () => {
  it('links blocked documents directly to the Review workspace', async () => {
    listHitlQueue.mockResolvedValue([{ file: 'b.pdf' }])
    const c = await mount({ run, files: [held('b.pdf')], certified: [] })
    expect(c.textContent).toContain('Review 1 file')
    expect([...c.querySelectorAll('a')].map(a => a.getAttribute('href'))).toContain('?tab=remediate&mode=review')
    expect(c.textContent).toContain('Approved changes must be applied and verified')
  })

  it('loads and applies a saved delivery template in the guided workspace', async () => {
    getSettings.mockResolvedValueOnce({ release_templates: [{ name: 'Finance ZIP', method: 'download', preserve_hierarchy: false }] })
    const c = await mount({ run: { ...run, source: 'drive' }, files: [verified('a.pdf')], certified: [], onPublish: vi.fn() })
    await act(async () => [...c.querySelectorAll('button')].find((b) => b.textContent === 'Choose delivery').click())
    const disclosure = [...c.querySelectorAll('summary')].find((s) => /Saved delivery templates/.test(s.textContent))
    disclosure.parentElement.open = true
    await act(async () => [...disclosure.parentElement.querySelectorAll('button')].find((b) => b.textContent === 'Apply').click())
    expect(c.querySelector('input[name="delivery-method"][value="download"]').checked).toBe(true)
    expect(c.textContent).toMatch(/Finance ZIP delivery template applied/)
  })

  it('shows the three real delivery destinations in the guided workspace', async () => {
    const c = await mount({ run, files: [verified('a.pdf')], certified: [], onPublish: vi.fn() })
    const choose = [...c.querySelectorAll('button')].find((b) => b.textContent === 'Choose delivery')
    await act(async () => { choose.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(c.textContent).toMatch(/Where should the corrected files go\?/)
    expect(c.textContent).toMatch(/Publish to connected source/i)
    expect(c.textContent).toMatch(/Download to this device/)
    expect(c.textContent).toMatch(/Keep in ACP for later/)
    expect(c.querySelectorAll('input[name="delivery-method"]')).toHaveLength(3)
  })

  it('shows CONDITIONAL status when a document was released while another is held', async () => {
    // a.pdf released (persisted published_at), b.pdf still held.
    const files = [verified('a.pdf', { published_at: '2026-08-01T00:00:00Z' }), held('b.pdf')]
    const c = await mount({ run, files, certified: [], onPublish: vi.fn() })
    expect(c.textContent).toMatch(/Conditionally released/i)
    expect(c.textContent).toMatch(/no whole-estate re-scan required/i)
    // Held-only: nothing to graduate yet, so no release-remediated button.
    expect([...c.querySelectorAll('button')].some((b) => /Graduate to full/i.test(b.textContent))).toBe(false)
  })

  it('routes remaining verified documents through delivery review without publishing', async () => {
    // a.pdf released; b.pdf was held but is now compliant (remediated) and unreleased.
    const onPublish = vi.fn()
    const files = [verified('a.pdf', { published_at: '2026-08-01T00:00:00Z' }), verified('b.pdf')]
    const c = await mount({ run, files, certified: [], onPublish })
    const gradBtn = [...c.querySelectorAll('button')].find((b) => /Review delivery for/i.test(b.textContent))
    expect(gradBtn).toBeTruthy()
    expect(c.textContent).toMatch(/Ready to release remaining documents/i)

    await act(async () => { gradBtn.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    await flush()
    // The shortcut only selects the remaining file; delivery review must precede publishing.
    expect(publishAllFiles).not.toHaveBeenCalled()
    expect(onPublish).not.toHaveBeenCalled()
    expect(c.querySelector('#release-delivery-step')).toBeTruthy()
    expect(c.textContent).toContain('1 selected · 2 in scope')
  })

  it('reports completed delivery without claiming overall certification', async () => {
    const files = [verified('a.pdf', { published_at: '2026-08-01T00:00:00Z' })]
    const c = await mount({ run, files, certified: [], onPublish: vi.fn() })
    expect(c.textContent).toContain('Release complete')
    expect(c.textContent).not.toMatch(/fully certified/i)
  })

  it('shows no graduation surface before any release has started', async () => {
    const files = [verified('a.pdf'), held('b.pdf')]
    const c = await mount({ run, files, certified: [], onPublish: vi.fn() })
    expect(c.textContent).not.toMatch(/Conditionally released/i)
    expect(c.textContent).not.toMatch(/Ready to graduate/i)
  })
})
