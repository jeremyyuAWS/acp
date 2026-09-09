import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

// W5 — Publish surfaces the set-level certification status and offers a one-action graduation
// from conditional → full without a re-scan. Verified at the DOM level (per the repo's rule that
// worktree changes are proven in vitest, not the shared-checkout preview server).

const publishAllFiles = vi.fn(() => Promise.resolve({ published: [] }))
const listHitlQueue = vi.fn(() => Promise.resolve([]))
const getReleaseStatus = vi.fn(() => Promise.resolve({ release_id: null }))
const getSourceStatus = vi.fn(() => Promise.resolve({ files: [], stale_count: 0 }))
const previewReleaseDestination = vi.fn(() => Promise.resolve({ can_release: true, folder_name: 'Delivery', documents: [] }))
const getSettings = vi.fn(() => Promise.resolve({ drive_mirror_enabled: false, drive_mirror_folder: 'Remediated' }))
const putMyReleaseTemplates = vi.fn((templates) => Promise.resolve({ release_templates: templates }))
vi.mock('./api.js', () => ({
  getReleaseAiProvenance: vi.fn(() => Promise.resolve({ calls: [] })),
  openReport: vi.fn(), publishFile: vi.fn(() => Promise.resolve({})),
  publishAllFiles: (...a) => publishAllFiles(...a),
  getReleaseStatus: (...args) => getReleaseStatus(...args),
  listReleaseHistory: vi.fn(() => Promise.resolve({ releases: [] })),
  getReleaseManifest: vi.fn(() => Promise.resolve({ manifest: {} })),
  listHitlQueue: (...args) => listHitlQueue(...args),
  getSettings: (...a) => getSettings(...a),
  putMyReleaseTemplates: (...a) => putMyReleaseTemplates(...a),
  getSourceStatus: (...args) => getSourceStatus(...args),
  rescoreFile: vi.fn(() => Promise.resolve({})),
  previewReleaseDestination: (...args) => previewReleaseDestination(...args),
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

afterEach(async () => { await unmountAll(); vi.clearAllMocks(); getReleaseStatus.mockResolvedValue({ release_id: null }); getSourceStatus.mockResolvedValue({ files: [], stale_count: 0 }); publishAllFiles.mockResolvedValue({ published: [] }); listHitlQueue.mockResolvedValue([]) })
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


Element.prototype.scrollIntoView = vi.fn()
const button = (c, text) => [...c.querySelectorAll('button')].find((b) => b.textContent === text && !b.closest('[hidden]'))
const click = async (node) => { expect(node).toBeTruthy(); await act(async () => node.click()); await flush() }
const row = (c, name) => c.querySelector(`[aria-label="Select ${name}"]`).closest('.release-selection__row')
const review = async (c) => { await click(button(c, 'Choose delivery')); await click(button(c, 'Review release')); }

describe('Release clarity and execution boundaries', () => {
  it('shows unknown, uncorrected and review-blocked files beside ready copies', async () => {
    listHitlQueue.mockResolvedValue([{ file: 'review.pdf' }])
    const c = await mount({ run, files: [verified('ready.pdf'), { file: 'unknown.pdf' }, verified('uncorrected.pdf', { remediated_at: null }), held('review.pdf')] })
    expect(row(c, 'ready.pdf').textContent).toContain('awaiting Release')
    expect(row(c, 'unknown.pdf').textContent).toContain('Readiness unknown')
    expect(row(c, 'uncorrected.pdf').textContent).toContain('No verified corrected copy')
    expect(row(c, 'review.pdf').textContent).toContain('1 review items pending')
    for (const name of ['unknown.pdf', 'uncorrected.pdf', 'review.pdf']) expect(c.querySelector(`[aria-label="Select ${name}"]`).disabled).toBe(true)
    expect(publishAllFiles).not.toHaveBeenCalled()
  })

  it('does not call uploaded certification a delivery or hide an unknown file from the scope', async () => {
    const c = await mount({ run, files: [verified('a.pdf'), { file: 'unknown.pdf' }], certified: [{ file: 'a.pdf' }] })
    expect(c.querySelector('[aria-label="Delivery receipt"]')).toBeNull()
    expect(c.querySelector('[aria-label="Release complete"]')).toBeNull()
    expect(row(c, 'a.pdf').textContent).toContain('awaiting Release')
  })

  it('restores a durable partial receipt and retries only failed files through fresh review', async () => {
    getReleaseStatus.mockResolvedValue({ release_id: 'receipt-1', roots: [{ folder_id: 'd', folder_name: 'Delivery', folder_url: 'https://example.test/delivery' }], documents: [
      { file: 'a.pdf', status: 'published', published_at: '2026-08-02T00:00:00Z', released_document_url: 'https://example.test/a' },
      { file: 'b.pdf', status: 'failed', explanation: 'Destination permission denied' },
    ] })
    const c = await mount({ run, files: [verified('a.pdf'), verified('b.pdf')] })
    const receipt = c.querySelector('[aria-label="Delivery receipt"]')
    expect(receipt.textContent).toContain('Partial delivery receipt')
    expect(receipt.textContent).toContain('1 delivered · 1 failed')
    expect(receipt.textContent).toContain('receipt-1')
    expect(row(c, 'a.pdf').textContent).toContain('Delivered')
    expect(row(c, 'b.pdf').textContent).toContain('Destination permission denied')
    await click(button(c, 'Review and retry failed (1)'))
    expect(publishAllFiles).not.toHaveBeenCalled()
    expect(c.querySelector('#release-delivery-step')).toBeTruthy()
    await click(button(c, 'Review release'))
    expect(previewReleaseDestination.mock.calls.at(-1)[1]).toEqual(['b.pdf'])
    expect(c.querySelector('.release-plan__actions').textContent).toContain('1 selected · 1 awaiting Release')
    await click(button(c, 'Publish 1 copy'))
    expect(publishAllFiles).not.toHaveBeenCalled()
    publishAllFiles.mockResolvedValue({ release_id: 'receipt-1', published: [{ file: 'b.pdf', status: 'published', published_at: '2026-08-03T00:00:00Z' }] })
    await click(button(c, 'Publish 1'))
    expect(publishAllFiles.mock.calls.at(-1)[1]).toEqual(['b.pdf'])
  })

  it('keeps a newer corrected copy out of Delivered despite an old receipt', async () => {
    getReleaseStatus.mockResolvedValue({ release_id: 'old', documents: [{ file: 'a.pdf', status: 'published', published_at: '2026-08-01' }] })
    const c = await mount({ run, files: [verified('a.pdf', { remediated_at: '2026-08-02', published_at: '2026-08-01' })] })
    expect(row(c, 'a.pdf').textContent).toContain('awaiting Release')
    expect(c.querySelector('[aria-label="Release complete"]')).toBeNull()
    expect(c.querySelector('[aria-label="Delivery receipt"]').textContent).toContain('0 delivered')
  })

  it('never infers success from an empty publish response', async () => {
    const onPublish = vi.fn()
    const c = await mount({ run, files: [verified('a.pdf')], onPublish })
    await review(c); await click(button(c, 'Publish 1 copy')); await click(button(c, 'Publish 1'))
    expect(onPublish).not.toHaveBeenCalled()
    expect(row(c, 'a.pdf').textContent).toContain('awaiting Release')
    expect(c.textContent).toContain('Delivery has not been confirmed')
  })

  it('keeps hidden selections explicit and preserves clear selection after freshness refresh', async () => {
    getSourceStatus.mockResolvedValue({ files: [{ file: 'b.pdf', state: 'stale' }], stale_count: 1 })
    const c = await mount({ run, files: [verified('a.pdf'), verified('b.pdf')] })
    const status = c.querySelectorAll('.release-selection__toolbar select')[1]
    await act(async () => { status.value = 'attention'; status.dispatchEvent(new Event('change', { bubbles: true })) })
    expect(c.textContent).toContain('1 outside these filters')
    expect(c.querySelector('[aria-label="Select b.pdf"]').disabled).toBe(true)
  })

  it('traps confirmation focus, supports Escape, and restores the invoking control', async () => {
    const c = await mount({ run, files: [verified('a.pdf')] })
    await review(c)
    const trigger = button(c, 'Publish 1 copy'); trigger.focus(); await click(trigger)
    await act(async () => new Promise((resolve) => setTimeout(resolve, 30)))
    const cancel = button(c, 'Cancel'); const submit = button(c, 'Publish 1')
    expect(document.activeElement).toBe(cancel)
    await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true })))
    expect(document.activeElement).toBe(submit)
    await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true })))
    expect(document.activeElement).toBe(cancel)
    await act(async () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
    await act(async () => new Promise((resolve) => setTimeout(resolve, 30)))
    expect(c.querySelector('[role="dialog"]')).toBeNull()
    expect(document.activeElement).toBe(trigger)
    expect(publishAllFiles).not.toHaveBeenCalled()
  })

  it('opens file details with focus and returns it on Escape; honors reduced motion', async () => {
    window.matchMedia = vi.fn(() => ({ matches: true }))
    Element.prototype.scrollIntoView = vi.fn()
    const c = await mount({ run, files: [verified('a.pdf')] })
    const details = row(c, 'a.pdf').querySelector('.release-selection__details')
    await click(details)
    expect(document.activeElement).toBe(c.querySelector('aside'))
    await act(async () => document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
    expect(document.activeElement).toBe(details)
    expect(c.querySelector('aside').hidden).toBe(true)
    await click(button(c, 'Start a release'))
    await act(async () => new Promise((resolve) => setTimeout(resolve, 30)))
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ behavior: 'auto', block: 'start' })
  })

  it('retains removed summaries deliberately hidden and cannot mount the direct graduate control', async () => {
    const c = await mount({ run, files: [verified('a.pdf', { published_at: '2026-08-01' })] })
    expect(c.querySelector('[data-retired="release-accounting"]').hidden).toBe(true)
    expect(c.querySelector('[data-retired="release-audit-summary"]').hidden).toBe(true)
    const { readFileSync } = await import('node:fs')
    const source = readFileSync('src/Publish.jsx', 'utf8')
    expect(source).toContain('const graduate = async')
    expect(source).not.toMatch(/onClick=\{graduate\}/)
  })
})
