import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

/**
 * AcrWorkspace — the ACR list and report workspace (ADR 0047, PRD §15).
 *
 * The assertions that matter most are about what this screen must NOT show:
 *
 *   · no compliance score or percentage (PRD §4.4, and api/accessibility_status.py's house rule
 *     "counts only, never a percentage of an invented denominator"),
 *   · no internal workflow state rendered where a VPAT conformance level goes (PRD §9),
 *   · no suggestion that the draft export is a real VPAT (PRD §4.6 — the ITI template is Phase 5).
 *
 * Each of those is a thing a reasonable person would add without noticing it was forbidden, which
 * is exactly why they are pinned rather than left to review.
 */

const api = {
  listAcrReports: vi.fn(),
  createAcrReport: vi.fn(),
  getAcrReport: vi.fn(),
  listAcrCriteria: vi.fn(),
  getAcrValidation: vi.fn(),
  getAcrPreview: vi.fn(),
  getAcrGaps: vi.fn(),
}

vi.mock('./acrApi', () => ({
  listAcrReports: (...a) => api.listAcrReports(...a),
  createAcrReport: (...a) => api.createAcrReport(...a),
  getAcrReport: (...a) => api.getAcrReport(...a),
  patchAcrReport: vi.fn(),
  listAcrCriteria: (...a) => api.listAcrCriteria(...a),
  getAcrCriterion: vi.fn(),
  getAcrValidation: (...a) => api.getAcrValidation(...a),
  getAcrAudit: vi.fn(),
  getAcrPreview: (...a) => api.getAcrPreview(...a),
  getAcrGaps: (...a) => api.getAcrGaps(...a),
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
    id: 'acr_1', product_name: 'ACP by Movate', product_version: '1.4.0',
    vpat_edition: 'VPAT 2.5Rev WCAG', wcag_version: '2.2', wcag_levels: 'A, AA',
    status: 'draft', report_title: 'ACP ACR', build_id: 'b-900',
  },
  roles: ['editor'],
  progress: { total: 55, decided: 12, undecided: 43, approved: 3, evidence_total: 20,
              evidence_stale: 2 },
}

const CRITERIA = [
  { criterion_num: '1.4.3', criterion_name: 'Contrast (Minimum)', level: 'AA',
    final_status: 'Supports', draft_status: null, approval_state: 'approved' },
  { criterion_num: '2.1.1', criterion_name: 'Keyboard', level: 'A',
    final_status: null, draft_status: 'Supports', approval_state: 'unapproved' },
]

// Every fetcher gets a resolved default, not just the one a given test exercises. The Overview
// tab now fetches validation as well (the metadata form marks a field required from the publish
// gate's own blockers rather than a second hardcoded list), so a mock left returning `undefined`
// throws inside an effect and surfaces as an unrelated-looking React error.
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
const mount = async ({
  reports = [{ id: 'acr_1', report_title: 'ACP ACR', status: 'draft' }],
  gaps = EMPTY_GAPS,
} = {}) => {
  api.listAcrReports.mockReset().mockResolvedValue({ reports })
  api.getAcrReport.mockReset().mockResolvedValue(REPORT)
  api.listAcrCriteria.mockReset().mockResolvedValue({ criteria: CRITERIA })
  if (!api.getAcrValidation.getMockImplementation()) api.getAcrValidation.mockResolvedValue(EMPTY_VALIDATION)
  api.getAcrGaps.mockReset().mockResolvedValue(gaps)
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

afterEach(unmountAll)

describe('what the screen must not claim', () => {
  it('reports counts, never a percentage or a score', async () => {
    await mount()
    expect(text()).toMatch(/12 of 55 criteria decided/)
    // The exact thing PRD §4.4 forbids: a headline number that reads as a compliance grade.
    expect(text()).not.toMatch(/%/)
    expect(text()).not.toMatch(/\bscore\b/i)
    expect(text()).not.toMatch(/\bcompliant\b/i)
  })

  it('shows an undecided criterion as not evaluated, never as a VPAT level', async () => {
    await mount()
    await click(button(/^Criteria$/))
    expect(text()).toMatch(/not yet evaluated/)
  })

  it('labels a draft suggestion as ACP\'s, not as a decision', async () => {
    await mount()
    await click(button(/^Criteria$/))
    expect(text()).toMatch(/ACP draft suggestion: Supports/)
  })

  it('says the draft export is not a VPAT', async () => {
    api.getAcrPreview.mockResolvedValue({
      template: { is_official_iti_template: false,
                  note: 'Structural preview only. The official ITI VPAT® template is integrated in Phase 5; this output mirrors the VPAT table shape and is not a VPAT.' },
      report: { wcag_version: '2.2' },
      criteria: [{ criterion_num: '1.4.3', criterion_name: 'Contrast (Minimum)', level: 'AA',
                   conformance_level: 'Supports', remarks: '' }],
      totals: { total: 55, undecided: 54, Supports: 1 },
    })
    await mount()
    await click(button(/^Draft export$/))
    expect(text()).toMatch(/Draft structural preview/)
    expect(text()).toMatch(/is not a VPAT/)
  })
})

describe('the empty state explains the feature honestly', () => {
  it('says automated results alone do not establish conformance', async () => {
    await mount({ reports: [] })
    expect(text()).toMatch(/Automated results alone never establish conformance/)
    expect(button(/Create Accessibility Conformance Report/)).toBeTruthy()
  })

  it('shows the exported PDF validation limits before a report exists', async () => {
    await mount({ reports: [] })
    expect(text()).toMatch(/Machine-checked, with validation still outstanding/)
    expect(text()).toMatch(/PAC 2024Independent PDF accessibility validationNot run/)
    expect(text()).toMatch(/Screen-reader reviewNVDA or VoiceOver reading passNot run/)
    expect(text()).toMatch(/machine-validated draft/i)
  })

  it('shows the report journey before asking the user to create a workspace', async () => {
    await mount({ reports: [] })
    expect(text()).toMatch(/1\. Describe/)
    expect(text()).toMatch(/2\. Evaluate/)
    expect(text()).toMatch(/3\. Approve/)
    expect(text()).toMatch(/4\. Publish/)
    expect(button(/Create Accessibility Conformance Report/)).toBeTruthy()
  })
})

describe('report readiness', () => {
  it('turns real validation, evidence, decision, and approval counts into a guided checklist', async () => {
    api.getAcrValidation.mockResolvedValue({
      summary: { may_publish: false, blocking_count: 44, advisory_count: 0 },
      by_category: {
        incomplete_metadata: [{ message: 'vendor name is required to publish', blocking: true }],
      },
      category_labels: {},
    })
    await mount({ gaps: {
      ...EMPTY_GAPS,
      counts: { no_evidence: 30, automated_only: 5, stale_only: 2 },
    } })

    expect(text()).toMatch(/Report readiness/)
    expect(text()).toMatch(/44 publication blockers remain/)
    expect(text()).toMatch(/1 required field missing/)
    expect(text()).toMatch(/37 criteria still need live human evidence/)
    expect(text()).toMatch(/12 of 55 decided · 3 approved/)
    expect(text()).toMatch(/Publication stays locked/)
    expect(text()).not.toMatch(/%/)
  })

  it('takes the user directly from a readiness item to the work that resolves it', async () => {
    api.getAcrValidation.mockResolvedValue({
      summary: { may_publish: false, blocking_count: 1, advisory_count: 0 },
      by_category: {}, category_labels: {},
    })
    await mount({ gaps: {
      ...EMPTY_GAPS,
      counts: { no_evidence: 1, automated_only: 0, stale_only: 0 },
    } })
    await click(button(/^Review gaps$/))
    expect(button(/^Evidence gaps$/).getAttribute('aria-current')).toBe('page')
  })

  it('says ready without publishing automatically when every gate passes', async () => {
    api.getAcrReport.mockReset().mockResolvedValue({
      ...REPORT,
      progress: { total: 55, decided: 55, undecided: 0, approved: 55,
                  evidence_total: 80, evidence_stale: 0 },
    })
    api.getAcrValidation.mockResolvedValue({
      summary: { may_publish: true, blocking_count: 0, advisory_count: 0 },
      by_category: {}, category_labels: {},
    })
    await mount({ gaps: {
      ...EMPTY_GAPS,
      with_human_evidence: 55,
      counts: { no_evidence: 0, automated_only: 0, stale_only: 0 },
    } })
    expect(text()).toMatch(/Ready for authorised publication/)
    expect(text()).toMatch(/An authorised approver still controls publication/)
    expect(button(/^Open publication$/)).toBeTruthy()
  })
})

describe('export assurance', () => {
  it('makes the PDF gates visible in the workspace overview', async () => {
    await mount()
    expect(text()).toMatch(/PDF\/UA-1 and structure-tree checksChecked/)
    expect(text()).toMatch(/do not prove that a person using a screen reader/i)
  })

  it('turns an API failure into an explicit unavailable state instead of an empty tab', async () => {
    api.listAcrReports.mockReset().mockRejectedValue(new Error('403 Forbidden'))
    const created = createTestRoot()
    container = created.container
    await act(async () => { created.root.render(createElement(AcrWorkspace)) })
    await act(async () => { await Promise.resolve() })
    expect(text()).toMatch(/Conformance reports are unavailable/)
    expect(text()).toMatch(/403 Forbidden/)
    expect(container.querySelector('[role="alert"]')).toBeTruthy()
  })
})

describe('validation', () => {
  it('states whether the report may publish, and why not', async () => {
    api.getAcrValidation.mockResolvedValue({
      summary: { may_publish: false, blocking_count: 43, advisory_count: 2,
                 by_category: { missing_decision: 43 } },
      by_category: { missing_decision: [{ message: '2.1.1 has not been evaluated',
                                          criterion_num: '2.1.1', blocking: true }] },
      category_labels: { missing_decision: 'Missing decision' },
    })
    await mount()
    await click(button(/^Validation$/))
    expect(text()).toMatch(/43 blocker\(s\) prevent publication/)
    expect(text()).toMatch(/Missing decision/)
    expect(text()).toMatch(/2\.1\.1 has not been evaluated/)
  })
})

describe('accessibility', () => {
  it('exposes the section switcher as a named navigation landmark (1.3.1, 2.4.6)', async () => {
    await mount()
    const nav = container.querySelector('nav')
    expect(nav.getAttribute('aria-label')).toBe('Report sections')
  })

  it('marks the current section with aria-current (4.1.2)', async () => {
    await mount()
    const current = [...container.querySelectorAll('button[aria-current="page"]')]
    expect(current).toHaveLength(1)
    expect(current[0].textContent).toBe('Overview')
  })

  it('announces progress through a live region (4.1.3)', async () => {
    await mount()
    const status = container.querySelector('[role="status"]')
    expect(status.getAttribute('aria-live')).toBe('polite')
  })

  it('gives the criteria table header cells and a caption (1.3.1)', async () => {
    await mount()
    await click(button(/^Criteria$/))
    const table = container.querySelector('table')
    expect(table.querySelector('caption')).toBeTruthy()
    expect(table.querySelectorAll('th[scope="col"]').length).toBeGreaterThan(0)
    expect(table.querySelectorAll('th[scope="row"]').length).toBe(CRITERIA.length)
  })

  it('gives each row action a unique accessible name (2.4.4)', async () => {
    // Every row's button reads "Open" visually; without the visually-hidden criterion name a
    // screen-reader user gets a list of identical "Open" buttons.
    await mount()
    await click(button(/^Criteria$/))
    const opens = [...container.querySelectorAll('tbody button')]
    expect(opens.length).toBe(CRITERIA.length)
    const names = opens.map((b) => b.textContent)
    expect(new Set(names).size).toBe(names.length)
    expect(names[0]).toMatch(/1\.4\.3/)
  })

  it('starts headings at h2 and never skips a level (1.3.1)', async () => {
    await mount()
    const levels = [...container.querySelectorAll('h1,h2,h3,h4,h5,h6')]
      .map((h) => Number(h.tagName[1]))
    expect(levels[0]).toBe(2)
    for (let i = 1; i < levels.length; i++) {
      expect(levels[i] - levels[i - 1]).toBeLessThanOrEqual(1)
    }
  })

  it('has no axe-detectable violations on any section', async () => {
    api.getAcrValidation.mockResolvedValue({
      summary: { may_publish: true, blocking_count: 0, advisory_count: 0, by_category: {} },
      by_category: {}, category_labels: {},
    })
    await mount()
    const axe = (await import('axe-core')).default
    for (const section of [/^Overview$/, /^Criteria$/, /^Validation$/]) {
      await click(button(section))
      const results = await axe.run(container, {
        resultTypes: ['violations'],
        runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
        // See acrCriterionDetail.test.jsx — jsdom has no layout engine, so contrast is
        // undecidable here and is checked in a real browser by A11ySelfCheck.jsx instead.
        rules: { 'color-contrast': { enabled: false } },
      })
      expect(results.violations.map((v) => `${section}: ${v.id}`)).toEqual([])
    }
  })
})
