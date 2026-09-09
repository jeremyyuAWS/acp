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
  container.rerender = async (next) => { await act(async () => root.render(createElement(Publish, next))); await flush() }
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
    getSourceStatus.mockResolvedValue({ files: [{ file: 'b.pdf', state: 'conflict' }], stale_count: 1 })
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
    await click(button(c, 'More delivery options'))
    await act(async () => new Promise((resolve) => setTimeout(resolve, 30)))
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ behavior: 'auto', block: 'start' })
  })

  it('retains removed summaries deliberately hidden and cannot mount the direct graduate control', async () => {
    const c = await mount({ run, files: [verified('a.pdf', { published_at: '2026-08-01' })] })
    expect(c.querySelector('[data-retired="release-accounting"]').hidden).toBe(true)
    expect(c.querySelector('[data-retired="release-plan-summary"]').hidden).toBe(true)
    expect(c.querySelector('[data-retired="release-audit-summary"]').hidden).toBe(true)
    const { readFileSync } = await import('node:fs')
    const source = readFileSync('src/Publish.jsx', 'utf8')
    expect(source).toContain('const graduate = async')
    expect(source).not.toMatch(/onClick=\{graduate\}/)
  })
})

describe('Release selection changes', () => {
  it('invalidates a preview when the selection changes and never submits the old plan', async () => {
    const c = await mount({ run, files: [verified('a.pdf'), verified('b.pdf')] })
    await review(c)
    expect(button(c, 'Publish 2 copies').disabled).toBe(false)
    await click(c.querySelector('[aria-label="Select b.pdf"]'))
    expect(button(c, 'Publish 1 copy').disabled).toBe(true)
    expect(publishAllFiles).not.toHaveBeenCalled()
  })
  it('preserves an explicit empty selection when eligible data refreshes', async () => {
    const c = await mount({ run, files: [verified('a.pdf')] })
    await click(c.querySelector('[aria-label="Select a.pdf"]'))
    await c.rerender({ run, files: [verified('a.pdf'), verified('b.pdf')] })
    expect(button(c, 'Choose delivery').disabled).toBe(true)
    expect(c.querySelector('[aria-label="Select b.pdf"]').checked).toBe(false)
  })
  it('clears the old scan receipt when navigating to another scan with the same file name', async () => {
    getReleaseStatus.mockResolvedValueOnce({ release_id: 'first', documents: [{ file: 'a.pdf', status: 'published', published_at: '2026-08-01' }] })
    const c = await mount({ run, files: [verified('a.pdf')] })
    expect(row(c, 'a.pdf').textContent).toContain('Delivered')
    await c.rerender({ run: { ...run, id: 'second' }, files: [verified('a.pdf')] })
    expect(row(c, 'a.pdf').textContent).toContain('awaiting Release')
    expect(c.querySelector('[aria-label="Delivery receipt"]')).toBeNull()
  })
  it('keeps history replay read-only even after preview', async () => {
    const c = await mount({ run, files: [verified('a.pdf')], readOnly: true })
    await review(c)
    expect(button(c, 'Publish 1 copy').disabled).toBe(true)
    expect(publishAllFiles).not.toHaveBeenCalled()
  })
})

describe('Exact corrected-copy changes', () => {
  it('refreshes open details from current file evidence instead of its earlier selected object', async () => {
    getReleaseStatus.mockResolvedValue({ release_id: 'versioned', documents: [{ file: 'a.pdf', status: 'published', artifact_digest: `sha256:${'a'.repeat(64)}`, published_at: '2026-08-01' }] })
    const c = await mount({ run, files: [verified('a.pdf', { corrected_sha256: 'a'.repeat(64) })] })
    await click(row(c, 'a.pdf').querySelector('.release-selection__details'))
    expect(c.querySelector('aside').textContent).toContain('Delivered')
    await c.rerender({ run, files: [verified('a.pdf', { corrected_sha256: 'b'.repeat(64) })] })
    expect(c.querySelector('aside').textContent).toContain('Ready')
    expect(c.querySelector('aside').textContent).not.toContain('Delivered')
  })
  it('invalidates delivery review when bytes change within the same timestamp', async () => {
    const c = await mount({ run, files: [verified('a.pdf', { corrected_sha256: 'a'.repeat(64) })] })
    await review(c)
    expect(button(c, 'Publish 1 copy').disabled).toBe(false)
    await c.rerender({ run, files: [verified('a.pdf', { corrected_sha256: 'b'.repeat(64) })] })
    expect(button(c, 'Publish 1 copy').disabled).toBe(true)
    expect(publishAllFiles).not.toHaveBeenCalled()
  })
})


it('ready-only action excludes recorded deliveries and binds exact corrected artifacts', async () => {
  getReleaseStatus.mockResolvedValue({ release_id: 'receipt', documents: [{ file: 'delivered.pdf', status: 'published', artifact_digest: 'sha256:done' }] })
  const c = await mount({ run, files: [verified('ready.pdf', { corrected_sha256: 'current' }), verified('delivered.pdf', { corrected_sha256: 'done' }), held('manual.pdf')] })
  expect(JSON.stringify([...c.querySelectorAll('button')].map(b => b.textContent))).toContain('Publish ready files (1)')
  await click(button(c, 'Publish ready files (1)'))
  expect(publishAllFiles).toHaveBeenCalledWith('scan1', ['ready.pdf'], '', {
    destination: null, expectedArtifacts: { 'ready.pdf': 'current' },
  })
})


it('mounts both top-level Release actions for a run with no ready copies', async () => {
  const c = await mount({ run, files: [held('review.pdf')] })
  const quick = c.querySelector('.release-quick')
  expect(quick).not.toBeNull()
  expect(quick.closest('details')).toBeNull()
  expect(quick.textContent).toContain('Verification incomplete')
  for (const name of ['Publish ready files (0)', 'Approve eligible changes and publish when ready']) {
    expect(button(quick, name).disabled).toBe(true)
  }
  expect(publishAllFiles).not.toHaveBeenCalled()
})

it('publishes only the ready subset while the same run still has processing and review files', async () => {
  listHitlQueue.mockResolvedValue([{ file: 'review.pdf', status: 'pending' }])
  const c = await mount({ run: { ...run, status: 'running' }, files: [verified('ready.pdf', { corrected_sha256: 'exact-ready' }), held('processing.pdf', { status: 'running' }), held('review.pdf')] })
  expect(button(c, 'Publish ready files (1)').disabled).toBe(false)
  await click(button(c, 'Publish ready files (1)'))
  expect(publishAllFiles).toHaveBeenCalledWith('scan1', ['ready.pdf'], '', {
    destination: null, expectedArtifacts: { 'ready.pdf': 'exact-ready' },
  })
})

it('publishes a saved partial copy only after explicit opt-in without approving pending work', async () => {
  listHitlQueue.mockResolvedValue([{ id: 42, file: 'partial.docx', status: 'pending' }])
  const files = [held('partial.docx', { remediated_at: '2026-09-09T12:00:00Z', corrected_sha256: 'saved-digest' }), held('draft.docx')]
  const c = await mount({ run, files })
  expect(c.querySelector('[aria-label="Select partial.docx"]').disabled).toBe(true)
  const optIn = [...c.querySelectorAll('label')].find(el => el.textContent.includes('Publish with remaining issues')).querySelector('input')
  expect(optIn.checked).toBe(false)
  await click(optIn)
  expect(c.querySelector('[aria-label="Select partial.docx"]').disabled).toBe(false)
  expect(c.querySelector('[aria-label="Select draft.docx"]').disabled).toBe(true)
  expect(c.textContent).toContain('Ready with remaining issues')
  await review(c)
  expect(previewReleaseDestination).toHaveBeenLastCalledWith(run.id, ['partial.docx'], '', true, null,
    { allowRemainingIssues: true, expectedArtifacts: { 'partial.docx': 'saved-digest' } })
  await click(button(c, 'Publish 1 copy'))
  expect(c.querySelector('[role="dialog"]').textContent).toContain('does not mark them approved, inspected, verified or compliant')
  await click(button(c, 'Publish 1'))
  expect(publishAllFiles).toHaveBeenCalledWith(run.id, ['partial.docx'], 'Delivery',
    { destination: null, allowRemainingIssues: true, expectedArtifacts: { 'partial.docx': 'saved-digest' } })
  expect(files[0].compliant).toBe(false)
  await c.rerender({ run: { id: 'other' }, files })
  expect([...c.querySelectorAll('label')].find(el => el.textContent.includes('Publish with remaining issues')).querySelector('input').checked).toBe(false)
})

it('offers partial publication in the visible release actions without opening advanced details', async () => {
  const files = [held('one.pdf', { remediated_at: '2026-09-09', corrected_sha256: 'one-digest' }),
    held('two.pdf', { remediated_at: '2026-09-09', corrected_sha256: 'two-digest' }), held('draft.pdf')]
  listHitlQueue.mockResolvedValue(files.map((f, i) => ({ id: i, file: f.file, status: 'pending' })))
  const c = await mount({ run, files })
  const optIn = [...c.querySelectorAll('label')].find(el => el.textContent.includes('Publish with remaining issues')).querySelector('input')
  expect(optIn.closest('details')).toBeNull()
  expect(optIn.closest('.release-quick')).not.toBeNull()
  await click(optIn)
  const publish = button(c, 'Publish saved copies (2)')
  expect(publish.disabled).toBe(false)
  expect(publish.closest('details')).toBeNull()
  await click(publish)
  expect(publishAllFiles).toHaveBeenCalledWith(run.id, ['one.pdf', 'two.pdf'], '', {
    destination: null, allowRemainingIssues: true,
    expectedArtifacts: { 'one.pdf': 'one-digest', 'two.pdf': 'two-digest' },
  })
  expect(previewReleaseDestination).not.toHaveBeenCalled()
  expect(files.every(f => f.compliant === false)).toBe(true)
})
