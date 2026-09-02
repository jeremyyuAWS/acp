import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

/**
 * AcrPublish — the screen guarding the one irreversible act in the feature (PRD §16–17, Phase 4).
 *
 * The properties pinned hardest are the ones whose absence would be invisible in review:
 *
 *   · the screen NEVER decides whether publishing is allowed — `may_publish` comes from the
 *     server, which recomputes the whole gate on the request itself,
 *   · irreversibility is stated BEFORE the click, and the publish action is behind an explicit
 *     confirmation that says what becomes true rather than "are you sure",
 *   · the separation-of-duties warning is shown and never blocks (PRD §18 is a recommendation),
 *   · the digest is never presented as a signature.
 */

const api = {
  getAcrPublication: vi.fn(),
  publishAcr: vi.fn(),
  getAcrRevisions: vi.fn(),
  reviseAcr: vi.fn(),
}

vi.mock('./acrApi', () => ({
  getAcrPublication: (...a) => api.getAcrPublication(...a),
  publishAcr: (...a) => api.publishAcr(...a),
  getAcrRevisions: (...a) => api.getAcrRevisions(...a),
  reviseAcr: (...a) => api.reviseAcr(...a),
  getAcrRevision: vi.fn(),
}))

const { default: AcrPublish } = await import('./AcrPublish.jsx')

const READY = {
  report_id: 'acr_1', status: 'draft', revision: 1, may_publish: true, role_refusal: '',
  blocking_count: 0, summary: { may_publish: true, blocking_count: 0, advisory_count: 0 },
  by_category: {}, category_labels: {}, separation_warning: '',
  irreversible_note: 'Publishing freezes this report as an immutable revision. It cannot be '
    + 'edited or withdrawn afterwards — a correction is published as a new revision that '
    + 'supersedes it.',
}

const NO_REVS = { revisions: [], current_report_id: 'acr_1', lineage: [] }

let container
const mount = async (ready = READY, revs = NO_REVS) => {
  api.getAcrPublication.mockReset().mockResolvedValue(ready)
  api.getAcrRevisions.mockReset().mockResolvedValue(revs)
  api.publishAcr.mockReset().mockResolvedValue({ revision: 1, content_digest: 'a'.repeat(64) })
  api.reviseAcr.mockReset().mockResolvedValue(
    { report_id: 'acr_2', revision: 2, reset_criteria: ['1.4.3'], note: 'Every carried criterion re-enters the approval queue.' })
  const created = createTestRoot()
  container = created.container
  await act(async () => { created.root.render(createElement(AcrPublish, { reportId: 'acr_1' })) })
  await act(async () => { await Promise.resolve() })
  await act(async () => { await Promise.resolve() })
  return container
}

const text = () => container.textContent
const button = (re) => [...container.querySelectorAll('button')].find((b) => re.test(b.textContent))
const click = async (el) => {
  await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
  await act(async () => { await Promise.resolve() })
  await act(async () => { await Promise.resolve() })
}

afterEach(unmountAll)

describe('the gate belongs to the server', () => {
  it('offers no publish button when the server says it may not publish', async () => {
    await mount({ ...READY, may_publish: false, blocking_count: 43,
                  by_category: { missing_decision: [{ message: '2.1.1 has not been evaluated' }] },
                  category_labels: { missing_decision: 'Missing decision' } })
    expect(button(/Publish revision/)).toBeFalsy()
    expect(text()).toMatch(/43 blocker\(s\) outstanding/)
    expect(text()).toMatch(/2\.1\.1 has not been evaluated/)
  })

  it("renders the server's role refusal verbatim", async () => {
    await mount({ ...READY, may_publish: false, blocking_count: 0,
                  role_refusal: 'analyst@x.com is not an approver on this report' })
    expect(text()).toMatch(/is not an approver on this report/)
  })

  it('surfaces a server refusal when publishing is rejected anyway', async () => {
    // The gate is recomputed on the request, so a screen that looked ready can still be refused —
    // and the refusal must be shown, not swallowed.
    await mount()
    api.publishAcr.mockRejectedValue(new Error('3 blocker(s) prevent publication'))
    await click(button(/Publish revision/))
    await click(button(/Publish permanently/))
    expect(container.querySelector('[role="alert"]').textContent)
      .toMatch(/3 blocker\(s\) prevent publication/)
  })
})

describe('irreversibility', () => {
  it('states what publishing does before any click', async () => {
    await mount()
    expect(text()).toMatch(/cannot be edited or withdrawn/)
  })

  it('requires an explicit confirmation that says what becomes true', async () => {
    await mount()
    await click(button(/Publish revision/))
    expect(text()).toMatch(/This cannot be undone/)
    expect(text()).toMatch(/frozen as an immutable record/)
    expect(api.publishAcr).not.toHaveBeenCalled()
    await click(button(/Publish permanently/))
    expect(api.publishAcr).toHaveBeenCalledWith('acr_1')
  })

  it('can be cancelled without publishing', async () => {
    await mount()
    await click(button(/Publish revision/))
    await click(button(/Cancel/))
    expect(api.publishAcr).not.toHaveBeenCalled()
  })
})

describe('separation of duties is advisory', () => {
  it('shows the warning and still allows publication', async () => {
    // PRD §18 is a recommendation conditioned on a second reviewer existing. Rendering it as an
    // error would stop a one-person team from ever publishing.
    await mount({ ...READY,
                  separation_warning: 'alice@x.com made 40 of 55 conformance decisions and is '
                                      + 'also the approver.' })
    expect(text()).toMatch(/made 40 of 55 conformance decisions/)
    expect(button(/Publish revision/)).toBeTruthy()
  })
})

describe('revisions', () => {
  it('shows the digest and whether the contents still match it', async () => {
    await mount({ ...READY, status: 'published' }, {
      revisions: [{ snapshot_id: 's1', revision: 1, published_at: '2026-09-01T00:00:00Z',
                    published_by: 'approver@x.com', content_digest: 'b'.repeat(64),
                    digest_verified: true, digest_problem: '' }],
      lineage: [],
    })
    expect(text()).toMatch(/Verified — contents match the recorded digest/)
    expect(text()).toMatch(/bbbbbbbbbbbb/)
  })

  it('says plainly when a snapshot no longer matches its digest', async () => {
    await mount({ ...READY, status: 'published' }, {
      revisions: [{ snapshot_id: 's1', revision: 1, published_at: '2026-09-01T00:00:00Z',
                    published_by: 'approver@x.com', content_digest: 'c'.repeat(64),
                    digest_verified: false,
                    digest_problem: 'it has been altered since publication' }],
      lineage: [],
    })
    expect(text()).toMatch(/Not verified: it has been altered since publication/)
  })

  it('never calls the digest a signature', async () => {
    await mount()
    expect(text()).toMatch(/not a digital signature/)
    expect(text()).not.toMatch(/digitally signed/i)
  })

  it('offers a new revision once published, and reports what must be re-evaluated', async () => {
    await mount({ ...READY, status: 'published' })
    expect(button(/Publish revision/)).toBeFalsy()
    await click(button(/Start a new revision/))
    expect(api.reviseAcr).toHaveBeenCalledWith('acr_1')
    expect(text()).toMatch(/re-enters the approval queue/)
    expect(text()).toMatch(/Re-evaluate: 1\.4\.3/)
  })
})

describe('accessibility', () => {
  it('announces publication state through a live region (4.1.3)', async () => {
    await mount()
    expect(container.querySelector('[role="status"]').getAttribute('aria-live')).toBe('polite')
  })

  it('states revision integrity in words, not by colour alone (1.4.1)', async () => {
    await mount({ ...READY, status: 'published' }, {
      revisions: [{ snapshot_id: 's1', revision: 1, published_at: null, published_by: 'x',
                    content_digest: 'd'.repeat(64), digest_verified: false,
                    digest_problem: 'no digest' }],
      lineage: [],
    })
    const cells = [...container.querySelectorAll('td')].map((td) => td.textContent)
    expect(cells.some((c) => /Not verified/.test(c))).toBe(true)
  })

  it('gives the revisions table header cells and a caption (1.3.1)', async () => {
    await mount({ ...READY, status: 'published' }, {
      revisions: [{ snapshot_id: 's1', revision: 1, published_at: null, published_by: 'x',
                    content_digest: 'e'.repeat(64), digest_verified: true, digest_problem: '' }],
      lineage: [],
    })
    const table = container.querySelector('table')
    expect(table.querySelector('caption')).toBeTruthy()
    expect(table.querySelectorAll('th[scope="col"]').length).toBeGreaterThan(0)
    expect(table.querySelectorAll('th[scope="row"]').length).toBe(1)
  })

  it('groups the confirmation controls under a name (1.3.1)', async () => {
    await mount()
    await click(button(/Publish revision/))
    const group = container.querySelector('[role="group"]')
    expect(group.getAttribute('aria-label')).toBe('Confirm publication')
  })

  it('has no axe-detectable violations', async () => {
    await mount({ ...READY, status: 'published',
                  separation_warning: 'alice made most decisions' }, {
      revisions: [{ snapshot_id: 's1', revision: 1, published_at: '2026-09-01T00:00:00Z',
                    published_by: 'approver@x.com', content_digest: 'f'.repeat(64),
                    digest_verified: true, digest_problem: '' }],
      lineage: [],
    })
    const axe = (await import('axe-core')).default
    const results = await axe.run(container, {
      resultTypes: ['violations'],
      runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
      // jsdom has no layout engine, so contrast is undecidable here; A11ySelfCheck.jsx checks it
      // in a real browser instead. An honest statement of what this environment can decide.
      rules: { 'color-contrast': { enabled: false } },
    })
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([])
  })
})
