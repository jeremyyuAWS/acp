import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// W5 — Publish surfaces the set-level certification status and offers a one-action graduation
// from conditional → full without a re-scan. Verified at the DOM level (per the repo's rule that
// worktree changes are proven in vitest, not the shared-checkout preview server).

const publishAllFiles = vi.fn(() => Promise.resolve({ published: [] }))
vi.mock('./api.js', () => ({
  openReport: vi.fn(), publishFile: vi.fn(() => Promise.resolve({})),
  publishAllFiles: (...a) => publishAllFiles(...a),
  getReleaseStatus: vi.fn(() => Promise.resolve({ release_id: null })),
  listHitlQueue: vi.fn(() => Promise.resolve([])),
  getSettings: vi.fn(() => Promise.resolve({ drive_mirror_enabled: false, drive_mirror_folder: 'Remediated' })),
  getSourceStatus: vi.fn(() => Promise.resolve({ files: [], stale_count: 0 })),
  rescoreFile: vi.fn(() => Promise.resolve({})),
}))
// Keep the heavy children out of the mount — this test is about the Publish graduation surface.
vi.mock('./FileDrawer.jsx', () => ({ default: () => null }))
vi.mock('./ScopeBanner.jsx', () => ({ default: () => null }))
vi.mock('./SearchFilterBar.jsx', () => ({
  default: () => null,
  useSearchFilter: () => ({ active: false, clear: () => {} }),
  matchesFilters: () => () => true,
}))
vi.mock('./remediableScope.js', () => ({ documentSelection: () => ({}), documentScopeSentence: () => '' }))

const { default: Publish } = await import('./Publish.jsx')

afterEach(unmountAll)
const flush = async () => { for (let k = 0; k < 5; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) }) }
const mount = async (props) => {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(Publish, props)) })
  await flush()
  return container
}
const verified = (file, over = {}) => ({ file, compliant: true, score: 100, department: 'D', sourceName: 'S', ...over })
const held = (file, over = {}) => ({ file, compliant: false, score: 40, issues: [{ wcag: 'SC_1_1_1' }], department: 'D', sourceName: 'S', ...over })
const run = { id: 'scan1', files: 3, certifiable: 2 }

describe('Publish — W5 conditional-to-full graduation', () => {
  it('shows CONDITIONAL status when a document was released while another is held', async () => {
    // a.pdf released (persisted published_at), b.pdf still held.
    const files = [verified('a.pdf', { published_at: '2026-08-01T00:00:00Z' }), held('b.pdf')]
    const c = await mount({ run, files, certified: [], onPublish: vi.fn() })
    expect(c.textContent).toMatch(/Conditionally released/i)
    expect(c.textContent).toMatch(/no whole-estate re-scan required/i)
    // Held-only: nothing to graduate yet, so no release-remediated button.
    expect([...c.querySelectorAll('button')].some((b) => /Graduate to full/i.test(b.textContent))).toBe(false)
  })

  it('offers GRADUATE once every held document is remediated, and releases them without a re-scan', async () => {
    // a.pdf released; b.pdf was held but is now compliant (remediated) and unreleased.
    const onPublish = vi.fn()
    const files = [verified('a.pdf', { published_at: '2026-08-01T00:00:00Z' }), verified('b.pdf')]
    const c = await mount({ run, files, certified: [], onPublish })
    const gradBtn = [...c.querySelectorAll('button')].find((b) => /Graduate to full certification/i.test(b.textContent))
    expect(gradBtn).toBeTruthy()
    expect(c.textContent).toMatch(/Ready to graduate to full certification/i)

    await act(async () => { gradBtn.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    await flush()
    // graduation releases exactly the formerly-held, now-verified document — via the ordinary
    // publish path, no rescoreFile / re-scan involved.
    expect(publishAllFiles).toHaveBeenCalledWith('scan1', ['b.pdf'])
    expect(onPublish).toHaveBeenCalledWith('b.pdf')
  })

  it('reports FULL once the graduation completes (all in-scope documents released)', async () => {
    const files = [verified('a.pdf', { published_at: '2026-08-01T00:00:00Z' }), verified('b.pdf')]
    const c = await mount({ run, files, certified: [], onPublish: vi.fn() })
    const gradBtn = [...c.querySelectorAll('button')].find((b) => /Graduate to full certification/i.test(b.textContent))
    await act(async () => { gradBtn.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    await flush()
    expect(c.textContent).toMatch(/Fully certified/i)
  })

  it('shows no graduation surface before any release has started', async () => {
    const files = [verified('a.pdf'), held('b.pdf')]
    const c = await mount({ run, files, certified: [], onPublish: vi.fn() })
    expect(c.textContent).not.toMatch(/Conditionally released/i)
    expect(c.textContent).not.toMatch(/Ready to graduate/i)
  })
})
