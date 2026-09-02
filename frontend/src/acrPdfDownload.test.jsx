import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

/**
 * The ACR's accessible-PDF download, at the DOM level.
 *
 * WHY DOM AND NOT A BROWSER CHECK. The preview server runs vite with the SHARED CHECKOUT as its
 * root whatever worktree you are in (CLAUDE.md), so a screenshot of this button would be evidence
 * about `main`, not about this branch. Everything below asserts on the rendered tree.
 *
 * The two things worth pinning are the ones a reasonable person would get wrong:
 *
 *   · the file is saved under the name the SERVER chose. It knows the report id and revision;
 *     the client does not, and two reports downloading as one name is the collision
 *     api/acr_export_pdf.py::filename_for exists to prevent.
 *   · a deployment that cannot produce a tagged PDF answers 503 with a sentence naming the
 *     missing renderer, and the screen must show THAT rather than "download failed" — the
 *     server's sentence is the only version an operator can act on.
 */

const api = {
  listAcrReports: vi.fn(),
  getAcrReport: vi.fn(),
  listAcrCriteria: vi.fn(),
  getAcrValidation: vi.fn(),
  getAcrPreview: vi.fn(),
  getAcrGaps: vi.fn(),
  downloadAcrPdf: vi.fn(),
}

vi.mock('./acrApi', () => ({
  listAcrReports: (...a) => api.listAcrReports(...a),
  createAcrReport: vi.fn(),
  getAcrReport: (...a) => api.getAcrReport(...a),
  patchAcrReport: vi.fn(),
  listAcrCriteria: (...a) => api.listAcrCriteria(...a),
  getAcrCriterion: vi.fn(),
  getAcrValidation: (...a) => api.getAcrValidation(...a),
  getAcrAudit: vi.fn(),
  getAcrPreview: (...a) => api.getAcrPreview(...a),
  getAcrGaps: (...a) => api.getAcrGaps(...a),
  downloadAcrPdf: (...a) => api.downloadAcrPdf(...a),
  ingestAxe: vi.fn(),
  setAcrApplicability: vi.fn(),
  addAcrEvidence: vi.fn(),
  decideAcrCriterion: vi.fn(),
  approveAcrCriterion: vi.fn(),
  FINAL_STATUSES: ['Supports', 'Partially Supports', 'Does Not Support', 'Not Applicable'],
  REMARKS_REQUIRED: ['Partially Supports', 'Does Not Support', 'Not Applicable'],
}))

const { default: AcrWorkspace } = await import('./AcrWorkspace.jsx')

const REPORT = {
  report: {
    id: 'acr_1', product_name: 'ACP', product_version: '2026.9.1', wcag_version: '2.2',
    status: 'draft', report_title: 'ACP ACR', build_id: 'b-900',
  },
  roles: ['editor'],
  progress: { total: 55, decided: 12, undecided: 43, approved: 3, evidence_total: 0,
              evidence_stale: 0 },
}

const PREVIEW = {
  template: { note: 'Structural preview only. …not a VPAT.' },
  report: { wcag_version: '2.2' },
  totals: { total: 55, undecided: 43 },
  criteria: [{ criterion_num: '1.4.3', criterion_name: 'Contrast (Minimum)', level: 'AA',
               conformance_level: 'Supports', remarks: '', decided: true, draft_status: null,
               evidence_stale: 0 }],
}

const EMPTY_VALIDATION = {
  summary: { may_publish: false, blocking_count: 0, advisory_count: 0, by_category: {} },
  by_category: {}, category_labels: {},
}
const EMPTY_GAPS = {
  total: 55, with_human_evidence: 0,
  counts: { no_evidence: 55, automated_only: 0, stale_only: 0 },
  buckets: { no_evidence: [], automated_only: [], stale_only: [] },
  note: 'automated evidence alone never establishes conformance',
}

let container
let anchors

beforeEach(() => {
  anchors = []
  // jsdom has neither of these; without them the click handler throws and the test would be
  // measuring the stub rather than the component.
  globalThis.URL.createObjectURL = vi.fn(() => 'blob:acr')
  globalThis.URL.revokeObjectURL = vi.fn()
  const realCreate = document.createElement.bind(document)
  vi.spyOn(document, 'createElement').mockImplementation((tag, ...rest) => {
    const el = realCreate(tag, ...rest)
    if (tag === 'a') {
      anchors.push(el)
      el.click = vi.fn()          // jsdom would try to navigate
    }
    return el
  })
})

const mount = async () => {
  api.listAcrReports.mockReset().mockResolvedValue({
    reports: [{ id: 'acr_1', report_title: 'ACP ACR', status: 'draft' }] })
  api.getAcrReport.mockReset().mockResolvedValue(REPORT)
  api.listAcrCriteria.mockReset().mockResolvedValue({ criteria: [] })
  api.getAcrValidation.mockReset().mockResolvedValue(EMPTY_VALIDATION)
  api.getAcrGaps.mockReset().mockResolvedValue(EMPTY_GAPS)
  api.getAcrPreview.mockReset().mockResolvedValue(PREVIEW)
  const created = createTestRoot()
  container = created.container
  await act(async () => { created.root.render(createElement(AcrWorkspace)) })
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

const openExport = async () => {
  await mount()
  await click(button(/export/i))
  return container
}

afterEach(() => {
  vi.restoreAllMocks()
  unmountAll()
})

describe('the accessible PDF download', () => {
  it('offers the download on the export tab, and says what it produces', async () => {
    await openExport()
    const b = button(/download accessible pdf/i)
    expect(b).toBeTruthy()
    // Naming the standard on the button matters: a reader must not have to open the file to
    // learn whether it is the tagged one.
    expect(container.textContent).toMatch(/PDF\/UA-1/)
  })

  it('saves the file under the name the server chose', async () => {
    await openExport()
    api.downloadAcrPdf.mockResolvedValue({
      blob: new Blob(['%PDF-1.7'], { type: 'application/pdf' }),
      filename: 'acr-acr_1-rev2.pdf',
    })
    await click(button(/download accessible pdf/i))

    expect(api.downloadAcrPdf).toHaveBeenCalledWith('acr_1')
    const a = anchors.find((el) => el.download)
    expect(a).toBeTruthy()
    expect(a.download).toBe('acr-acr_1-rev2.pdf')
    expect(a.click).toHaveBeenCalled()
  })

  it('releases the object URL it created', async () => {
    await openExport()
    api.downloadAcrPdf.mockResolvedValue({
      blob: new Blob(['%PDF-1.7'], { type: 'application/pdf' }), filename: 'acr-acr_1.pdf' })
    await click(button(/download accessible pdf/i))
    expect(globalThis.URL.revokeObjectURL).toHaveBeenCalledWith('blob:acr')
  })

  it("shows the server's own sentence when the renderer is unavailable, and downloads nothing",
     async () => {
       await openExport()
       const err = new Error(
         'the PDF renderer is unavailable — WeasyPrint is not importable in this deployment')
       err.status = 503
       api.downloadAcrPdf.mockRejectedValue(err)
       await click(button(/download accessible pdf/i))

       expect(container.textContent).toMatch(/WeasyPrint is not importable/)
       expect(container.textContent).not.toMatch(/download failed/i)
       expect(anchors.filter((el) => el.download)).toHaveLength(0)
     })

  it('re-enables the button after a failure, so the user can retry', async () => {
    await openExport()
    api.downloadAcrPdf.mockRejectedValue(new Error('boom'))
    await click(button(/download accessible pdf/i))
    const b = button(/download accessible pdf/i)
    expect(b).toBeTruthy()
    expect(b.disabled).toBe(false)
  })
})
