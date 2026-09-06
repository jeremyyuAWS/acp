import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { createTestRoot, unmountAll } from './testRoots.js'

/**
 * The Section 508 half of the criteria list — Phase 6 workspace work.
 *
 * 6.3 opened the 508 edition, so a report can hold 175 rows: 55 WCAG criteria and 120 requirements
 * from 36 CFR 1194 Appendix C. Two things were owed and are done here.
 *
 * ONE, the rows are grouped into the regulation's own chapters, the same shape
 * api/acr_export_preview.py projects the document in — so the screen a person decides on and the
 * document that ships are organised the same way, rather than by two independent groupings that
 * can quietly disagree.
 *
 * TWO, Chapter 4 is hardware: 69 rows that all end Not Applicable for a hosted web application.
 * `build_matrix` deliberately does not pre-empt that, because PRD §10 makes applicability a human
 * decision with a stated reason, and a system that dropped a chapter would be making it. The bulk
 * control keeps the human deciding — once, with a reason they type — and does the typing. It
 * refuses without a reason, and it will not touch a row somebody already decided.
 */

const api = {
  listAcrReports: vi.fn(),
  getAcrReport: vi.fn(),
  listAcrCriteria: vi.fn(),
  getAcrValidation: vi.fn(),
  getAcrGaps: vi.fn(),
  setAcrApplicability: vi.fn(),
}

vi.mock('./acrApi', () => ({
  getAcrEditions: () => Promise.resolve({ editions: [] }),
  listAcrReports: (...a) => api.listAcrReports(...a),
  createAcrReport: vi.fn(),
  getAcrReport: (...a) => api.getAcrReport(...a),
  patchAcrReport: vi.fn(),
  listAcrCriteria: (...a) => api.listAcrCriteria(...a),
  getAcrCriterion: vi.fn(),
  getAcrValidation: (...a) => api.getAcrValidation(...a),
  getAcrAudit: vi.fn(),
  getAcrPreview: vi.fn(),
  getAcrGaps: (...a) => api.getAcrGaps(...a),
  getAcrDocxGate: vi.fn(async () => ({ ok: true, failures: [], reviews: [] })),
  downloadAcrDocx: vi.fn(),
  downloadAcrPdf: vi.fn(),
  ingestAxe: vi.fn(),
  setAcrApplicability: (...a) => api.setAcrApplicability(...a),
  addAcrEvidence: vi.fn(),
  decideAcrCriterion: vi.fn(),
  approveAcrCriterion: vi.fn(),
  FINAL_STATUSES: ['Supports', 'Partially Supports', 'Does Not Support', 'Not Applicable'],
  REMARKS_REQUIRED: ['Partially Supports', 'Does Not Support', 'Not Applicable'],
}))

const { default: AcrWorkspace, groupCriteria } = await import('./AcrWorkspace.jsx')

// Read from the repo, not copied into the fixture: the point of the drift guard below is that it
// compares against the file the backend actually ships. `process.cwd()` is frontend/ under vitest.
const CATALOG = JSON.parse(readFileSync(
  path.resolve(process.cwd(), '..', 'config', 'section-508.json'), 'utf8'))

const wcagRow = (num, name, level) => ({
  criterion_num: num, criterion_name: name, level, principle: 'Perceivable',
  requirement_set: 'wcag-2.2-aa', chapter: null, applicable: true,
  final_status: null, draft_status: null, approval_state: 'unapproved',
})
const row508 = (num, name, chapter, over = {}) => ({
  criterion_num: num, criterion_name: name, level: null, principle: null,
  requirement_set: 'section-508', chapter, applicable: true,
  final_status: null, draft_status: null, approval_state: 'unapproved', ...over,
})

const MATRIX = [
  wcagRow('1.4.3', 'Contrast (Minimum)', 'AA'),
  row508('302.1', 'Without Vision', '3'),
  row508('402.2', 'Speech-Output Enabled', '4'),
  row508('402.3', 'Volume', '4'),
  row508('502.4', 'Platform Accessibility Features', '5'),
  row508('602.4', 'Alternate Formats for Non-Electronic Support Documentation', '6'),
]

const REPORT = {
  report: {
    id: 'acr_1', product_name: 'ACP by Movate', product_version: '1.4.0',
    vpat_edition: 'VPAT 2.5Rev 508', wcag_version: '2.2', wcag_levels: 'A, AA',
    status: 'draft', report_title: 'ACP ACR',
  },
  roles: ['editor'],
  progress: { total: 175, decided: 0, undecided: 175, approved: 0, evidence_total: 0,
              evidence_stale: 0 },
}
const EMPTY_VALIDATION = {
  summary: { may_publish: false, blocking_count: 0, advisory_count: 0, by_category: {} },
  by_category: {}, category_labels: {},
}
const EMPTY_GAPS = {
  total: 175, with_human_evidence: 0,
  counts: { no_evidence: 175, automated_only: 0, stale_only: 0 },
  buckets: { no_evidence: [], automated_only: [], stale_only: [] },
  note: 'automated evidence alone never establishes conformance',
}

let container
const mount = async (criteria = MATRIX, { roles = ['editor'] } = {}) => {
  api.listAcrReports.mockReset().mockResolvedValue({
    reports: [{ id: 'acr_1', report_title: 'ACP ACR', status: 'draft' }] })
  api.getAcrReport.mockReset().mockResolvedValue({ ...REPORT, roles })
  api.listAcrCriteria.mockReset().mockResolvedValue({ criteria })
  api.getAcrValidation.mockReset().mockResolvedValue(EMPTY_VALIDATION)
  api.getAcrGaps.mockReset().mockResolvedValue(EMPTY_GAPS)
  api.setAcrApplicability.mockReset().mockResolvedValue({})
  const created = createTestRoot()
  container = created.container
  await act(async () => { created.root.render(createElement(AcrWorkspace)) })
  await act(async () => { await Promise.resolve() })
  await act(async () => { await Promise.resolve() })
  return container
}

const text = () => container.textContent
const button = (re) => [...container.querySelectorAll('button')].find((b) => re.test(b.textContent))
const click = async (el) => {
  await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
  await act(async () => { await Promise.resolve() })
}
const type = async (el, value) => {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype, 'value').set
    setter.call(el, value)
    el.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
const tableFor = (caption) => [...container.querySelectorAll('table')]
  .find((t) => t.querySelector('caption') && caption.test(t.querySelector('caption').textContent))
const openCriteria = async () => click(button(/^Criteria$/))

afterEach(unmountAll)

describe('grouping the matrix', () => {
  it('splits WCAG rows from Section 508 rows and orders the chapters', () => {
    const { wcag, chapters } = groupCriteria(MATRIX)
    expect(wcag.map((r) => r.criterion_num)).toEqual(['1.4.3'])
    expect(chapters.map((c) => c.num)).toEqual(['3', '4', '5', '6'])
    expect(chapters[1].rows).toHaveLength(2)
  })

  it('treats a row with no requirement_set as WCAG', () => {
    // A matrix built before Phase 6 carries no requirement_set. Those rows ARE WCAG rows, and
    // dropping them would be worse than mislabelling them.
    const { wcag, chapters } = groupCriteria([{ criterion_num: '1.1.1', criterion_name: 'Non-text' }])
    expect(wcag).toHaveLength(1)
    expect(chapters).toHaveLength(0)
  })

  it('renders an unknown chapter under its number rather than dropping it', () => {
    const { chapters } = groupCriteria([row508('901.1', 'Invented', '9')])
    expect(chapters[0].name).toBe('Chapter 9')
    expect(chapters[0].rows).toHaveLength(1)
  })

  it('names every chapter exactly as the catalog does', () => {
    // The drift guard. The names are repeated in the component so the criteria list does not have
    // to fetch the export projection; this reads config/section-508.json and holds them to it.
    const fromCatalog = Object.fromEntries(
      Object.entries(CATALOG._meta.chapters).map(([num, meta]) => [num, meta.name]))
    const rows = Object.keys(fromCatalog).map((num) => row508(`${num}01.1`, 'x', num))
    const { chapters } = groupCriteria(rows)
    expect(chapters).toHaveLength(Object.keys(fromCatalog).length)
    for (const chapter of chapters) expect(chapter.name).toBe(fromCatalog[chapter.num])
  })
})

describe('the criteria list', () => {
  it('gives each chapter its own captioned table', async () => {
    await mount()
    await openCriteria()
    for (const caption of ['Chapter 3: Functional Performance Criteria', 'Chapter 4: Hardware',
                           'Chapter 5: Software',
                           'Chapter 6: Support Documentation and Services']) {
      expect(text()).toContain(caption)
    }
  })

  it('gives the 508 tables no Level column, because a 508 requirement has no level', async () => {
    await mount()
    await openCriteria()
    const chapter = tableFor(/Chapter 4: Hardware/)
    const headers = [...chapter.querySelectorAll('thead th')].map((th) => th.textContent)
    expect(headers).toEqual(['Requirement', 'Conformance level', 'Approval', 'Open'])
  })

  it('keeps the WCAG table to WCAG rows, with its Level column intact', async () => {
    await mount()
    await openCriteria()
    const wcag = tableFor(/WCAG 2.2 Level A and AA criteria/)
    expect(wcag.textContent).toContain('1.4.3')
    expect(wcag.textContent).not.toContain('302.1')
    expect([...wcag.querySelectorAll('thead th')].map((th) => th.textContent))
      .toContain('Level')
  })

  it('shows a row already marked inapplicable as Not Applicable, not as undecided', async () => {
    await mount([row508('402.2', 'Speech-Output Enabled', '4', { applicable: false })])
    await openCriteria()
    const chapter = tableFor(/Chapter 4: Hardware/)
    expect(chapter.textContent).toContain('Not Applicable')
    expect(chapter.textContent).not.toContain('not yet evaluated')
  })
})

describe('marking a chapter Not Applicable', () => {
  it('will not run without a reason — PRD §10', async () => {
    // The defence is the disabled state, not the guard inside the handler: a disabled button never
    // reaches the handler, so deleting that guard turns nothing red. A bite check established
    // that, and this test was rewritten to exercise what actually gates the action — including
    // the case a naive `disabled={!rationale}` would let through.
    await mount()
    await openCriteria()
    const mark = button(/Mark 2 undecided requirements in Chapter 4/)
    expect(mark.disabled).toBe(true)

    await type(container.querySelector('#acr-bulk-na-4'), '   ')
    expect(button(/Mark 2 undecided requirements in Chapter 4/).disabled).toBe(true)
    await click(button(/Mark 2 undecided requirements in Chapter 4/))
    expect(api.setAcrApplicability).not.toHaveBeenCalled()

    await type(container.querySelector('#acr-bulk-na-4'), 'no hardware')
    expect(button(/Mark 2 undecided requirements in Chapter 4/).disabled).toBe(false)
  })

  it('sends the reason trimmed, so a stray newline is not stored as the rationale', async () => {
    await mount()
    await openCriteria()
    await type(container.querySelector('#acr-bulk-na-4'), '  ACP supplies no hardware.\n')
    await click(button(/Mark 2 undecided requirements in Chapter 4/))
    await act(async () => { await Promise.resolve() })
    expect(api.setAcrApplicability.mock.calls[0][3]).toBe('ACP supplies no hardware.')
  })

  it('marks every undecided row in the chapter, one decision each', async () => {
    await mount()
    await openCriteria()
    await type(container.querySelector('#acr-bulk-na-4'), 'ACP supplies no hardware.')
    await click(button(/Mark 2 undecided requirements in Chapter 4/))
    await act(async () => { await Promise.resolve() })

    expect(api.setAcrApplicability).toHaveBeenCalledTimes(2)
    expect(api.setAcrApplicability.mock.calls.map((c) => c[1])).toEqual(['402.2', '402.3'])
    for (const call of api.setAcrApplicability.mock.calls) {
      expect(call[2]).toBe(false)
      expect(call[3]).toBe('ACP supplies no hardware.')
    }
  })

  it('leaves a row somebody already decided alone', async () => {
    await mount([
      row508('402.2', 'Speech-Output Enabled', '4', { final_status: 'Does Not Support' }),
      row508('402.3', 'Volume', '4'),
    ])
    await openCriteria()
    await type(container.querySelector('#acr-bulk-na-4'), 'no hardware')
    await click(button(/Mark 1 undecided requirement in Chapter 4/))
    await act(async () => { await Promise.resolve() })

    expect(api.setAcrApplicability).toHaveBeenCalledTimes(1)
    expect(api.setAcrApplicability.mock.calls[0][1]).toBe('402.3')
  })

  it('reports the rows it could not mark rather than claiming they were done', async () => {
    await mount()
    api.setAcrApplicability.mockReset()
      .mockResolvedValueOnce({})
      .mockRejectedValueOnce(new Error('403 not an editor'))
    await openCriteria()
    await type(container.querySelector('#acr-bulk-na-4'), 'no hardware')
    await click(button(/Mark 2 undecided requirements in Chapter 4/))
    await act(async () => { await Promise.resolve() })

    const alert = container.querySelector('[role="alert"]')
    expect(alert.textContent).toContain('402.3')
    expect(alert.textContent).toContain('403 not an editor')
  })

  it('says there is nothing to do rather than offering an empty action', async () => {
    await mount([row508('402.2', 'Speech-Output Enabled', '4', { applicable: false })])
    await openCriteria()
    expect(text()).toMatch(/every requirement is decided or already marked Not Applicable/)
    expect(button(/Mark \d+ undecided requirement/)).toBeUndefined()
  })

  it('announces progress, because a 69-request loop otherwise looks like a dead button', async () => {
    await mount()
    await openCriteria()
    await type(container.querySelector('#acr-bulk-na-4'), 'no hardware')
    await click(button(/Mark 2 undecided requirements in Chapter 4/))
    await act(async () => { await Promise.resolve() })

    const live = [...container.querySelectorAll('[role="status"]')]
      .map((n) => n.textContent).join(' ')
    expect(live).toContain('2 of 2 marked.')
  })

  it('offers no bulk control to someone who cannot edit', async () => {
    await mount(MATRIX, { roles: ['viewer'] })
    await openCriteria()
    expect(text()).toContain('Chapter 4: Hardware')
    expect(button(/Mark \d+ undecided requirement/)).toBeUndefined()
  })
})
