/**
 * The review queue, PRD §7.4 - and specifically the ways a bulk selection can mean more than
 * the reviewer meant.
 *
 * #1170 made the SERVER refuse a batch that mixes policies, versions or actions. That is the
 * guarantee; this file is about never offering the reviewer a selection the server would have
 * to refuse, because a UI that lets you build an invalid batch and then rejects it has already
 * shown you a number you believed.
 *
 * The grouping key here is deliberately identical to the server's homogeneity rule
 * (policy, policy_version, action). If those two ever drift apart, a selection becomes
 * constructible in the client that is illegal on the server, so the coupling is the point
 * rather than duplication.
 */
import { describe, it, expect, afterEach, vi, beforeEach } from 'vitest'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import DispositionReviewWorkspace from './DispositionReviewWorkspace.jsx'

const approveDispositionBatch = vi.fn()
const getLifecycleFiles = vi.fn()
const getLifecycleFileDetail = vi.fn()
const getLifecycleFileHistory = vi.fn()

vi.mock('./api.js', () => ({
  approveDispositionBatch: (...a) => approveDispositionBatch(...a),
  getLifecycleFiles: (...a) => getLifecycleFiles(...a),
  getLifecycleFileDetail: (...a) => getLifecycleFileDetail(...a),
  // The panel loads a history beside the detail. Omitting it here does not fail a test —
  // the workspace catches it — it fails as an UNHANDLED error, which reddens the run
  // while every test still reports passed. See testRoots.js on why that shape matters.
  getLifecycleFileHistory: (...a) => getLifecycleFileHistory(...a),
}))

afterEach(unmountAll)

const row = (file, over = {}) => ({
  file, owner: 'a@x.com', lifecycle_status: 'Archive Candidate',
  lifecycle_reason: 'older than the cutoff', lifecycle_rule_id: 'retention',
  audit_id: `aud-${file}`, policy_id: 'retention', policy_version: 3, action: 'archive',
  ...over,
})

const ROWS = [
  row('a.docx'),
  row('b.docx'),
  // a different ACTION under the same rule - a separate batch by §8
  row('c.docx', { action: 'delete', lifecycle_status: 'Delete Candidate',
                  audit_id: 'aud-c', lifecycle_reason: 'much older' }),
  // a different VERSION of the same rule - also a separate batch
  row('d.docx', { policy_version: 2, audit_id: 'aud-d' }),
  // nothing pending: shown, never selectable
  row('e.docx', { audit_id: null, policy_version: null, action: null,
                  lifecycle_status: 'Conflict — review required',
                  lifecycle_reason: 'two rules of equal priority disagreed' }),
]

beforeEach(() => {
  approveDispositionBatch.mockReset()
  getLifecycleFiles.mockReset()
  getLifecycleFileDetail.mockReset()
  getLifecycleFileHistory.mockReset()
  getLifecycleFiles.mockResolvedValue({ rows: ROWS })
  getLifecycleFileDetail.mockResolvedValue({ file: 'a.docx', evaluations: [] })
  getLifecycleFileHistory.mockResolvedValue({ events: [] })
  approveDispositionBatch.mockResolvedValue({
    submitted: 2, approved: ['aud-a.docx', 'aud-b.docx'], refused: [],
    already_decided: [], reconciled: true, executed: false,
  })
})

const text = (el) => (el.textContent || '').replace(/\s+/g, ' ').trim()

async function mount(props = {}) {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(DispositionReviewWorkspace, { scanId: 's1', ...props })) })
  await act(async () => {})
  return container
}

const boxes = (c) => [...c.querySelectorAll('input[type=checkbox]')]
const boxFor = (c, file) => boxes(c).find((b) => b.getAttribute('aria-label') === `Select ${file} for batch approval`)
const approveBtn = (c) => [...c.querySelectorAll('button')].find((b) => /^Approve \d/.test(text(b)))
const setControl = async (control, value) => {
  await act(async () => {
    const proto = control instanceof HTMLSelectElement
      ? window.HTMLSelectElement.prototype : window.HTMLInputElement.prototype
    Object.getOwnPropertyDescriptor(proto, 'value').set.call(control, value)
    control.dispatchEvent(new Event(control instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }))
  })
}

describe('grouping mirrors the server homogeneity rule', () => {
  it('splits one rule into a group per (version, action), each with its size', async () => {
    const c = await mount()
    const heads = [...c.querySelectorAll('h3')].map(text)
    expect(heads).toContain('retention · version 3 · archive · 2 files')
    expect(heads).toContain('retention · version 3 · delete · 1 file')
    expect(heads).toContain('retention · version 2 · archive · 1 file')
  })

  it('names the risk of the action rather than leaving it to the verb', async () => {
    const c = await mount()
    expect(text(c)).toContain('Moves files to source trash')
    expect(text(c)).toContain('Recoverable move')
  })
})

describe('the default sort puts what a person must decide first', () => {
  it('orders conflicts before delete, and delete before archive', async () => {
    const c = await mount()
    const order = [...c.querySelectorAll('button')]
      .filter((b) => text(b).includes('.docx'))
      .map((b) => (/^([^\s]+\.docx)/.exec(text(b)) || [])[1])
    expect(order[0]).toBe('e.docx')                       // conflict - no rule won
    expect(order.indexOf('c.docx')).toBeLessThan(order.indexOf('a.docx'))
  })
})

describe('a selection can never cross a batch boundary', () => {
  it('clears the previous group rather than accumulating an illegal batch', async () => {
    const c = await mount()
    await act(async () => { boxFor(c, 'a.docx').click() })
    await act(async () => { boxFor(c, 'b.docx').click() })
    expect(text(c)).toContain('2 selected in this group')

    // Crossing into the delete group: the archive picks must not survive.
    await act(async () => { boxFor(c, 'c.docx').click() })
    expect(boxFor(c, 'a.docx').checked).toBe(false)
    expect(boxFor(c, 'b.docx').checked).toBe(false)
    expect(boxFor(c, 'c.docx').checked).toBe(true)
    expect(text(approveBtn(c))).toBe('Approve 1')
  })

  it('treats a different version of the same rule as a different batch', async () => {
    const c = await mount()
    await act(async () => { boxFor(c, 'a.docx').click() })
    await act(async () => { boxFor(c, 'd.docx').click() })      // retention v2
    expect(boxFor(c, 'a.docx').checked).toBe(false)
    expect(boxFor(c, 'd.docx').checked).toBe(true)
  })

  it('shows a row with no pending decision but does not let it be selected', async () => {
    // Hiding it would make the queue disagree with the estate counts above it; enabling it
    // would build a batch with no audit id for the server to act on.
    const c = await mount()
    expect(text(c)).toContain('e.docx')
    expect(boxFor(c, 'e.docx').disabled).toBe(true)
  })
})

describe('what the approve action actually sends', () => {
  it('sends exactly the picked ids, with the group policy, version and action', async () => {
    const c = await mount()
    await act(async () => { boxFor(c, 'a.docx').click() })
    await act(async () => { boxFor(c, 'b.docx').click() })
    await act(async () => { approveBtn(c).click() })
    await act(async () => {})

    expect(approveDispositionBatch).toHaveBeenCalledTimes(1)
    const sent = approveDispositionBatch.mock.calls[0][0]
    expect(sent.auditIds.sort()).toEqual(['aud-a.docx', 'aud-b.docx'])
    expect(sent.policyId).toBe('retention')
    expect(sent.policyVersion).toBe(3)
    expect(sent.action).toBe('archive')
    // §11: explicit ids, never a filter the server would re-expand at execute time.
    expect(sent).not.toHaveProperty('filter')
    expect(sent).not.toHaveProperty('status')
  })

  it('refuses to submit a delete without a reason, and says why', async () => {
    const c = await mount()
    await act(async () => { boxFor(c, 'c.docx').click() })
    expect(approveBtn(c).disabled).toBe(true)
    expect(text(c)).toContain('A delete approval must state a reason')

    const box = c.querySelector('textarea')
    await act(async () => {
      Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')
        .set.call(box, 'records schedule 7 expired')
      box.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(approveBtn(c).disabled).toBe(false)
    await act(async () => { approveBtn(c).click() })
    await act(async () => {})
    expect(approveDispositionBatch.mock.calls[0][0].reason).toBe('records schedule 7 expired')
  })

  it('reports a partial batch as partial, naming what was refused', async () => {
    approveDispositionBatch.mockResolvedValue({
      submitted: 2, approved: ['aud-a.docx'],
      refused: [{ audit_id: 'aud-b.docx', why: 'document is now Exempted' }],
      already_decided: [], reconciled: true, executed: false,
    })
    const c = await mount()
    await act(async () => { boxFor(c, 'a.docx').click() })
    await act(async () => { boxFor(c, 'b.docx').click() })
    await act(async () => { approveBtn(c).click() })
    await act(async () => {})

    const t = text(c)
    expect(t).toContain('1 approved')
    expect(t).toContain('1 refused')
    expect(t, 'the refusal reason was swallowed').toContain('document is now Exempted')
    expect(t).toContain('No source file was changed')
    // The approved row leaves the queue; the refused one stays to be dealt with.
    expect(t).not.toContain('a.docx')
    expect(t).toContain('b.docx')
  })

  it('says nothing was changed when the request itself fails', async () => {
    approveDispositionBatch.mockRejectedValue(new Error('boom'))
    const c = await mount()
    await act(async () => { boxFor(c, 'a.docx').click() })
    await act(async () => { approveBtn(c).click() })
    await act(async () => {})
    const alert = c.querySelector('[role="alert"]')
    expect(alert).toBeTruthy()
    expect(text(alert)).toContain('Nothing was changed')
  })
})

describe('the approve panel states what recovery would mean', () => {
  it('names the source behaviour and its window when the source is known', async () => {
    const c = await mount({ source: 'drive' })
    await act(async () => { boxFor(c, 'c.docx').click() })     // the delete group
    const t = text(c)
    expect(t).toContain('Recovery:')
    expect(t).toContain('Google Drive trash')
    expect(t).toContain('Recoverable for about 30 days')
  })

  it('says the source is unknown rather than promising a Drive window', async () => {
    // The queue is mounted without a source in most of this suite, and an unstated source must
    // not inherit Drive's 30 days - that is a promise about somebody's estate.
    const c = await mount()
    await act(async () => { boxFor(c, 'c.docx').click() })
    const t = text(c)
    expect(t).toContain('source of this file was not supplied')
    // Scoped to the recovery sentence: a bare /30 days/ also matches the AGE FILTER's own
    // "Older than 30 days" option, so it would fail on an unrelated label and pass on nothing.
    expect(t, 'a retention window was promised for an unstated source')
      .not.toMatch(/Recoverable for/)
  })

  it('offers no undo control, because none can work today', async () => {
    const c = await mount({ source: 'drive' })
    await act(async () => { boxFor(c, 'a.docx').click() })
    expect(text(c)).not.toContain('can be undone')
    expect([...c.querySelectorAll('button')].map(text).some((x) => /undo/i.test(x))).toBe(false)
  })

  it('admits an archive cannot be moved back', async () => {
    const c = await mount({ source: 'drive' })
    await act(async () => { boxFor(c, 'a.docx').click() })     // the archive group
    expect(text(c)).toContain('does not record where it came from')
  })
})

describe('progress and filtering', () => {
  it('requests candidates only by default and shows an honest zero-match empty state', async () => {
    getLifecycleFiles.mockResolvedValue({ rows: [] })
    const c = await mount()

    expect(getLifecycleFiles).toHaveBeenCalledWith('s1', {
      status: '', policyId: '', candidateOnly: true,
    })
    expect(text(c)).toContain('0 files in this view')
    expect(text(c)).toContain('No lifecycle candidates need review')
    expect(text(c)).not.toContain('No rule recorded')
  })

  it('can explicitly broaden to a non-candidate estate segment', async () => {
    await mount({ status: 'Active', candidateOnly: false })
    expect(getLifecycleFiles).toHaveBeenCalledWith('s1', {
      status: 'Active', policyId: '', candidateOnly: false,
    })
  })

  it('reports reviewed and remaining, and advances as files are opened', async () => {
    const c = await mount()
    expect(text(c)).toContain('0 reviewed, 5 remaining')
    const first = [...c.querySelectorAll('button')].find((b) => text(b).includes('a.docx'))
    await act(async () => { first.click() })
    await act(async () => {})
    expect(text(c)).toContain('1 reviewed, 4 remaining')
  })

  it('filters by owner without losing the grouping', async () => {
    getLifecycleFiles.mockResolvedValue({
      rows: [row('a.docx'), row('z.docx', { owner: 'b@x.com', audit_id: 'aud-z' })],
    })
    const c = await mount()
    expect(text(c)).toContain('2 files in this view')
    const select = c.querySelector('select')
    await act(async () => {
      Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value')
        .set.call(select, 'b@x.com')
      select.dispatchEvent(new Event('change', { bubbles: true }))
    })
    expect(text(c)).toContain('1 files in this view')
    expect(text(c)).toContain('z.docx')
    expect(text(c)).not.toContain('a.docx')
  })

  it('searches and filters the queue without hiding the full population', async () => {
    const c = await mount()
    await setControl(c.querySelector('[aria-label="Search disposition review queue"]'), 'much older')
    expect(text(c)).toContain('1 of 5 files match')
    expect(text(c)).toContain('c.docx')
    expect(text(c)).not.toContain('a.docx')

    await setControl(c.querySelector('[aria-label="Filter disposition queue by action"]'), 'archive')
    expect(text(c)).toContain('0 of 5 files match')
    expect(text(c)).toContain('No files match these filters')
  })

  it('paginates large queues while preserving the priority sort', async () => {
    getLifecycleFiles.mockResolvedValue({
      rows: Array.from({ length: 51 }, (_, i) => row(`file-${String(i + 1).padStart(3, '0')}.docx`)),
    })
    const c = await mount()
    expect(boxes(c)).toHaveLength(50)
    expect(text(c)).toContain('Showing 1–50')
    expect(text(c)).toContain('Page 1 of 2')
    expect(text(c)).not.toContain('file-051.docx')

    await act(async () => {
      [...c.querySelectorAll('button')].find((button) => text(button) === 'Next page').click()
    })
    expect(boxes(c)).toHaveLength(1)
    expect(text(c)).toContain('Showing 51–51')
    expect(text(c)).toContain('file-051.docx')
  })
})
