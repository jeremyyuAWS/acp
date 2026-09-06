import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

/**
 * The ACR's accessible WORD download and its accessibility gate, at the DOM level.
 *
 * WHY THIS EXISTS, AND WHY IT IS A SECOND FILE RATHER THAN MORE CASES IN acrPdfDownload.
 * The route serving this shipped one change ago, and until now no screen offered it — the same
 * orphan the route fix itself closed one layer down, repeated at the UI. `api/acr_export_docx.py`
 * was reachable by nobody; then it was reachable only by an API caller who knew the query
 * parameter existed. A component test is the only thing that can tell those apart from a passing
 * suite, because every layer below this one is already green in both worlds.
 *
 * THE GATE IS THE INTERESTING HALF. The server refuses to serve a Word document that FAILs ACP's
 * own docx analyser, so the download's failure path is a real product decision rather than an
 * error case. And the gate is "no FAIL", not "all PASS" — PASS is unreachable for any Word
 * document in this repo because no docx registration declares `Coverage.FULL`. That makes REVIEW
 * mean "ACP could not decide, a person must", which is a sentence that has to reach the approver
 * BEFORE they circulate the document. It cannot reach them from inside a .docx.
 *
 * The three states a reasonable person would collapse into one, and which this file keeps apart:
 *
 *   · gate not checked yet          — unknown, and must not read as "fine"
 *   · gate passed with reviews      — downloads, but something is outstanding
 *   · gate passed with nothing      — the only state that may read as clean
 *
 * DOM AND NOT A BROWSER CHECK, for the reason acrPdfDownload gives: the preview server runs vite
 * with the SHARED CHECKOUT as its root whatever worktree you are in (CLAUDE.md), so a screenshot
 * of this button would be evidence about `main` rather than about this branch.
 */

const api = {
  listAcrReports: vi.fn(),
  getAcrReport: vi.fn(),
  listAcrCriteria: vi.fn(),
  getAcrValidation: vi.fn(),
  getAcrPreview: vi.fn(),
  getAcrGaps: vi.fn(),
  downloadAcrPdf: vi.fn(),
  downloadAcrDocx: vi.fn(),
  getAcrDocxGate: vi.fn(),
}

vi.mock('./acrApi', () => ({
  // AcrMetadataForm fetches the VPAT editions on mount. This mock is NON-PARTIAL, so an export
  // the component imports and this object omits is `undefined` at the call site and throws from
  // inside an effect — which surfaces as every test in the file failing on unrelated assertions.
  // Resolving to an empty list keeps the edition field a plain text input here, which is what
  // these tests were written against; the select itself is covered in acrMetadataForm.test.jsx.
  getAcrEditions: () => Promise.resolve({ editions: [] }),
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
  downloadAcrDocx: (...a) => api.downloadAcrDocx(...a),
  getAcrDocxGate: (...a) => api.getAcrDocxGate(...a),
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
const CLEAN_GATE = { ok: true, failures: [], reviews: [] }

// FINDING SHAPE — copied from api/office_structure.py, not invented.
//
//   _finding(rule_id, wcag, severity)        -> {ruleId, wcag, severity}
//   _review_finding(rule_id, wcag, detail)   -> {ruleId, wcag, severity: 'REVIEW',
//                                                advisory: true, detail}
//
// There is no `rule`, no `criterion` and no `message`. The first version of this file used all
// three, and that is exactly why the bug shipped: a mock is a claim about what the other side
// sends, and when the same wrong guess writes the mock AND the component, the test agrees with
// the code about a world neither of them lives in. A FAIL finding carries no prose at all, which
// is why the component needs a fallback rather than a missing sentence.
const FAIL_FINDING = { ruleId: '1.3.1', wcag: '1.3.1', severity: 'FAIL' }
const REVIEW_FINDING = { ruleId: '1.1.1', wcag: '1.1.1', severity: 'REVIEW', advisory: true,
                         detail: 'image alt text needs a human' }

let container
let anchors

beforeEach(() => {
  // Call HISTORY only. `vi.restoreAllMocks()` in afterEach restores spies, not plain vi.fn()
  // mocks, so without this a "was never called" assertion sees the previous test's clicks — which
  // is how `checks the gate WITHOUT being asked to download` failed while the code was correct.
  // clearAllMocks (not resetAllMocks) keeps implementations, which each test sets after this runs.
  vi.clearAllMocks()
  anchors = []
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

const mount = async (gate = CLEAN_GATE) => {
  api.listAcrReports.mockReset().mockResolvedValue({
    reports: [{ id: 'acr_1', report_title: 'ACP ACR', status: 'draft' }] })
  api.getAcrReport.mockReset().mockResolvedValue(REPORT)
  api.listAcrCriteria.mockReset().mockResolvedValue({ criteria: [] })
  api.getAcrValidation.mockReset().mockResolvedValue(EMPTY_VALIDATION)
  api.getAcrGaps.mockReset().mockResolvedValue(EMPTY_GAPS)
  api.getAcrPreview.mockReset().mockResolvedValue(PREVIEW)
  api.getAcrDocxGate.mockReset()
  if (gate instanceof Error) api.getAcrDocxGate.mockRejectedValue(gate)
  else api.getAcrDocxGate.mockResolvedValue(gate)
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
const openExport = async (gate = CLEAN_GATE) => {
  await mount(gate)
  await click(button(/export/i))
  return container
}
const wordButton = () => button(/Word document/i)

afterEach(() => {
  vi.restoreAllMocks()
  unmountAll()
})

// ── the wiring ────────────────────────────────────────────────────────────────

describe('the accessible Word download', () => {
  it('is offered on the export tab at all — which it was not before this change', async () => {
    await openExport()
    expect(wordButton(), 'no Word download button on the export tab').toBeTruthy()
  })

  it('says what it produces, including that it is not a VPAT', async () => {
    // The licensing position is the single most consequential thing on this screen to get wrong.
    // A button labelled only "Download Word" invites the reader to assume the official template.
    await openExport()
    expect(container.textContent).toMatch(/not a VPAT/i)
    expect(container.textContent).toMatch(/\.docx/)
  })

  it('saves the file under the name the SERVER chose', async () => {
    // The server knows the report id and revision; the client does not, and two reports
    // downloading under one name is the collision acr_export_docx.filename_for exists to prevent.
    api.downloadAcrDocx.mockResolvedValue({
      blob: new Blob(['x']), filename: 'acr-acr_1-rev3.docx' })
    await openExport()
    await click(wordButton())
    expect(anchors.at(-1).download).toBe('acr-acr_1-rev3.docx')
  })

  it('releases the object URL it created', async () => {
    api.downloadAcrDocx.mockResolvedValue({ blob: new Blob(['x']), filename: 'a.docx' })
    await openExport()
    await click(wordButton())
    expect(globalThis.URL.revokeObjectURL).toHaveBeenCalledWith('blob:acr')
  })

  it('leaves the PDF download alone', async () => {
    // The regression this change could most easily cause is breaking the download that already
    // worked, by sharing state between the two buttons.
    await openExport()
    expect(button(/accessible PDF/i)).toBeTruthy()
  })
})

// ── the gate, which is why the download can refuse ────────────────────────────

describe('the export accessibility gate', () => {
  it('shows the failing checks and disables the download when ACP fails its own document', async () => {
    // The server would answer 500 here. Letting the user press a button that cannot succeed, to
    // be told afterwards, is worse than saying so up front — and the reason is the actionable part.
    await openExport({ ok: false, reviews: [], failures: [FAIL_FINDING] })
    expect(container.textContent).toMatch(/Word export is blocked/i)
    // The criterion, from `ruleId`. The first version of this test invented `rule` and
    // `message`, the component read the same invented keys, and both agreed — so it shipped
    // rendering the literal "check: failed" for every finding. See FINDING SHAPE above.
    expect(container.textContent).toContain('1.3.1')
    expect(wordButton().disabled).toBe(true)
  })

  it('never renders a finding as the literal word "check"', async () => {
    // The regression this whole change exists for, stated as the thing a reader would see. A FAIL
    // finding carries no prose — only ruleId, wcag and severity — so if the name is read from the
    // wrong key there is nothing left on the line but "check: failed", for every finding, and the
    // screen looks populated while saying nothing.
    await openExport({ ok: false, reviews: [], failures: [FAIL_FINDING] })
    expect(container.textContent).not.toMatch(/\bcheck: failed\b/)
    expect(container.textContent).toContain('1.3.1: failed')
  })

  it('surfaces REVIEW findings and still allows the download', async () => {
    // REVIEW is "a human has to look", not "approved" and not "broken". Blocking on it would
    // train people to ignore it; hiding it would turn "ACP could not decide" into "ACP approved".
    await openExport({ ok: true, failures: [], reviews: [REVIEW_FINDING] })
    expect(container.textContent).toMatch(/need a person to look/i)
    expect(container.textContent).toContain('1.1.1')
    expect(container.textContent).toContain('image alt text needs a human')
    expect(wordButton().disabled).toBe(false)
  })

  it('does not call a clean gate and an unchecked one the same thing', async () => {
    // The failure this test exists for: rendering nothing when the gate has not answered looks
    // exactly like rendering nothing when it answered "no findings".
    await openExport(CLEAN_GATE)
    expect(container.textContent).toMatch(/nothing outstanding/i)
  })

  it('says the verdict is unknown when the gate itself could not be reached', async () => {
    // Not an error banner: a gate that failed to answer tells us nothing about the document, and
    // the server still refuses on FAIL. Claiming either "fine" or "broken" here would be invented.
    await openExport(new Error('502 upstream'))
    expect(container.textContent).toMatch(/could not be checked/i)
    expect(wordButton().disabled).toBe(false)
  })

  it('checks the gate WITHOUT being asked to download', async () => {
    // The whole point of a pre-download check: AcrExportAssurance's premise is that the limits
    // are visible before a document is circulated.
    await openExport()
    expect(api.getAcrDocxGate).toHaveBeenCalledWith('acr_1')
    expect(api.downloadAcrDocx).not.toHaveBeenCalled()
  })
})

// ── failure of the download itself ────────────────────────────────────────────

describe('when the download fails', () => {
  it("shows the server's own sentence rather than 'download failed'", async () => {
    // A 503 names the missing renderer and a 500 names the failed checks. Either is the only
    // thing an operator can act on; "download failed" is not.
    api.downloadAcrDocx.mockRejectedValue(new Error(
      'the Word renderer is unavailable — python-docx is not importable in this deployment'))
    await openExport()
    await click(wordButton())
    expect(container.textContent).toMatch(/python-docx is not importable/)
    expect(anchors.filter((a) => a.download)).toHaveLength(0)
  })

  it('re-enables the button after a failure, so the user can retry', async () => {
    api.downloadAcrDocx.mockRejectedValue(new Error('503 renderer unavailable'))
    await openExport()
    await click(wordButton())
    expect(wordButton().disabled).toBe(false)
  })
})
