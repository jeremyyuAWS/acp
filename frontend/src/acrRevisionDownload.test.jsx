import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

/**
 * Downloading a PUBLISHED revision from the publication screen, at the DOM level.
 *
 * WHY DOM AND NOT A BROWSER CHECK. `preview_start` runs vite with the SHARED CHECKOUT as its root
 * whatever worktree you are in (CLAUDE.md), so a screenshot of this table would be evidence about
 * `main` rather than about this branch. Everything below asserts on the rendered tree.
 *
 * WHAT IS WORTH PINNING HERE, as distinct from the draft download one tab over:
 *
 *   · a revision whose digest did NOT verify offers no download at all, and says why. The server
 *     refuses it too (409); this is the belt to that braces, because an altered record must not be
 *     one click from becoming a PDF in a procurement file.
 *   · the button asks for the revision it sits beside. A table of revisions all downloading
 *     revision 1 would look completely correct and send the wrong document.
 *   · the failure text is the SERVER's sentence. A 409 says the snapshot no longer matches its
 *     digest and a 503 names the missing renderer; both are things a person can act on, and
 *     neither survives being flattened into "download failed".
 */

const api = {
  getAcrPublication: vi.fn(),
  getAcrRevisions: vi.fn(),
  downloadAcrRevisionPdf: vi.fn(),
}

vi.mock('./acrApi', () => ({
  getAcrPublication: (...a) => api.getAcrPublication(...a),
  publishAcr: vi.fn(),
  getAcrRevisions: (...a) => api.getAcrRevisions(...a),
  reviseAcr: vi.fn(),
  getAcrRevision: vi.fn(),
  downloadAcrRevisionPdf: (...a) => api.downloadAcrRevisionPdf(...a),
}))

const { default: AcrPublish } = await import('./AcrPublish.jsx')

const READY = {
  report_id: 'acr_1', status: 'published', revision: 2, may_publish: false, role_refusal: '',
  blocking_count: 0, summary: { may_publish: false, blocking_count: 0, advisory_count: 0 },
  by_category: {}, category_labels: {}, separation_warning: '',
  irreversible_note: 'Publishing freezes this report as an immutable revision.',
}

const REV = (n, over = {}) => ({
  snapshot_id: `snap_${n}`, report_id: 'acr_1', revision: n,
  published_at: '2026-08-31T10:00:00Z', published_by: 'approver@acp.test',
  content_digest: String(n).repeat(64), catalog_hash: 'cat',
  digest_verified: true, digest_problem: '', ...over,
})

let container
let anchors

beforeEach(() => {
  anchors = []
  // jsdom has neither; without them the click handler throws and the test would be measuring the
  // stub rather than the component.
  globalThis.URL.createObjectURL = vi.fn(() => 'blob:acr')
  globalThis.URL.revokeObjectURL = vi.fn()
  const realCreate = document.createElement.bind(document)
  vi.spyOn(document, 'createElement').mockImplementation((tag, ...rest) => {
    const el = realCreate(tag, ...rest)
    if (tag === 'a') {
      anchors.push(el)
      el.click = vi.fn()            // jsdom would try to navigate
    }
    return el
  })
})

afterEach(() => {
  vi.restoreAllMocks()
  unmountAll()
})

const mount = async (revisions) => {
  api.getAcrPublication.mockReset().mockResolvedValue(READY)
  api.getAcrRevisions.mockReset().mockResolvedValue(
    { revisions, current_report_id: 'acr_1', lineage: [] })
  api.downloadAcrRevisionPdf.mockReset().mockResolvedValue({
    blob: new Blob(['%PDF-1.7'], { type: 'application/pdf' }),
    filename: 'acr-acr_1-rev1.pdf',
  })
  const created = createTestRoot()
  container = created.container
  await act(async () => { created.root.render(createElement(AcrPublish, { reportId: 'acr_1' })) })
  await act(async () => { await Promise.resolve() })
  await act(async () => { await Promise.resolve() })
  return container
}

const button = (re) => [...container.querySelectorAll('button')].find((b) => re.test(b.textContent))
const click = async (el) => {
  await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
  await act(async () => { await Promise.resolve() })
  await act(async () => { await Promise.resolve() })
}

describe('downloading a published revision', () => {
  it('offers a download beside each verified revision', async () => {
    await mount([REV(2), REV(1)])
    expect(button(/download revision 1/i)).toBeTruthy()
    expect(button(/download revision 2/i)).toBeTruthy()
  })

  it('asks for the revision the button sits beside', async () => {
    await mount([REV(2), REV(1)])
    await click(button(/download revision 1/i))
    expect(api.downloadAcrRevisionPdf).toHaveBeenCalledWith('acr_1', 1)

    await click(button(/download revision 2/i))
    expect(api.downloadAcrRevisionPdf).toHaveBeenLastCalledWith('acr_1', 2)
  })

  it('saves the file under the name the server chose', async () => {
    await mount([REV(1)])
    await click(button(/download revision 1/i))
    const a = anchors.find((el) => el.download)
    expect(a).toBeTruthy()
    // The server knows the report id and the revision; the client's fallback name is only for a
    // response with no Content-Disposition, and overwriting the server's is how two revisions
    // land in a procurement file under one name.
    expect(a.download).toBe('acr-acr_1-rev1.pdf')
    expect(a.click).toHaveBeenCalled()
  })

  it('releases the object URL it created', async () => {
    await mount([REV(1)])
    await click(button(/download revision 1/i))
    expect(globalThis.URL.revokeObjectURL).toHaveBeenCalledWith('blob:acr')
  })

  it('offers no download for a revision whose digest did not verify, and says why', async () => {
    await mount([REV(1, {
      digest_verified: false,
      digest_problem: "this snapshot's contents do not match its recorded digest",
    })])
    expect(button(/download revision 1/i)).toBeFalsy()
    expect(container.textContent).toMatch(/failed verification/i)
    // Stated in words rather than left as a control that does nothing — a disabled button with no
    // explanation reads as a bug in the page, not as a refusal about the document.
    expect(container.textContent).toMatch(/do not match its recorded digest/)
  })

  it("shows the server's own sentence when the export is refused, and downloads nothing",
     async () => {
       await mount([REV(1)])
       const err = new Error(
         'refusing to export revision 1: this snapshot\'s contents do not match its recorded '
         + 'digest — it has been altered since publication')
       err.status = 409
       api.downloadAcrRevisionPdf.mockRejectedValue(err)
       await click(button(/download revision 1/i))

       expect(container.textContent).toMatch(/altered since publication/)
       expect(container.textContent).not.toMatch(/download failed/i)
       expect(anchors.filter((el) => el.download)).toHaveLength(0)
     })

  it('re-enables the button after a failure, so the user can retry', async () => {
    await mount([REV(1)])
    api.downloadAcrRevisionPdf.mockRejectedValue(new Error('boom'))
    await click(button(/download revision 1/i))
    const b = button(/download revision 1/i)
    expect(b).toBeTruthy()
    expect(b.disabled).toBe(false)
  })
})
