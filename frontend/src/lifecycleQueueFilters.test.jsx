/**
 * The review queue's filters (PRD §7.4: status, rule, owner, department, source, age, file type).
 *
 * Status and rule are server-side and arrive as props. Owner, file type and age are client-side
 * over the rows in hand. The interesting two are the ones NOT offered:
 *
 *   department - not collected by the Drive or SharePoint scan (api/documents.py cites ADR
 *     0003's own Costs/risks). PRD §6.2 is explicit that a signal needing connector work is
 *     labelled "Unavailable until connected", NEVER rendered as false. An empty-but-enabled
 *     Department filter is exactly that lie: it looks like it works and silently matches
 *     nothing, so a reviewer concludes the department has no candidates.
 *
 *   source - every file in this queue came from one scan, and a scan has a single source. A
 *     control that can only select all-or-nothing is worse than its absence, because using it
 *     teaches you something untrue about what it did.
 *
 * The age filter's trap is undated rows. Treating "no recorded date" as "not old" would shrink
 * the queue without saying so, and the count above the list is the number a reviewer trusts.
 */
import { describe, it, expect, afterEach, vi, beforeEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import DispositionReviewWorkspace, { ageInDays } from './DispositionReviewWorkspace.jsx'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const getLifecycleFiles = vi.fn()
const getLifecycleFileDetail = vi.fn()
const getLifecycleFileHistory = vi.fn()
const approveDispositionBatch = vi.fn()

vi.mock('./api.js', () => ({
  approveDispositionBatch: (...a) => approveDispositionBatch(...a),
  getLifecycleFiles: (...a) => getLifecycleFiles(...a),
  getLifecycleFileDetail: (...a) => getLifecycleFileDetail(...a),
  getLifecycleFileHistory: (...a) => getLifecycleFileHistory(...a),
}))

afterEach(unmountAll)

const DAY = 86400000
const ago = (days) => new Date(Date.now() - days * DAY).toISOString()

const row = (file, over = {}) => ({
  file, owner: 'a@x.com', format: 'docx', source_modified: ago(10),
  lifecycle_status: 'Archive Candidate', lifecycle_reason: 'older than the cutoff',
  lifecycle_rule_id: 'retention', audit_id: `aud-${file}`, policy_id: 'retention',
  policy_version: 3, action: 'archive', ...over,
})

const ROWS = [
  row('recent.docx', { source_modified: ago(10) }),
  row('old.docx', { source_modified: ago(400) }),
  row('ancient.pdf', { format: 'pdf', source_modified: ago(1500) }),
  row('sheet.xlsx', { format: 'xlsx', owner: 'b@x.com', source_modified: ago(200) }),
  row('undated.docx', { source_modified: null, created_at: null }),
]

beforeEach(() => {
  getLifecycleFiles.mockReset(); getLifecycleFileDetail.mockReset()
  getLifecycleFileHistory.mockReset(); approveDispositionBatch.mockReset()
  getLifecycleFiles.mockResolvedValue({ rows: ROWS })
  getLifecycleFileDetail.mockResolvedValue({ file: 'recent.docx', evaluations: [] })
  getLifecycleFileHistory.mockResolvedValue({ events: [] })
})

const text = (el) => (el.textContent || '').replace(/\s+/g, ' ').trim()

async function mount(props = {}) {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(DispositionReviewWorkspace, { scanId: 's1', ...props })) })
  await act(async () => {})
  return container
}

const selectByLabel = (c, label) => [...c.querySelectorAll('label')]
  .find((l) => text(l).startsWith(label))?.querySelector('select')

async function choose(select, value) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value')
      .set.call(select, value)
    select.dispatchEvent(new Event('change', { bubbles: true }))
  })
}

describe('the age helper', () => {
  it('measures from the source modification date', () => {
    expect(ageInDays({ source_modified: ago(30) })).toBe(30)
  })

  it('falls back to created_at when nothing modified it', () => {
    expect(ageInDays({ source_modified: null, created_at: ago(5) })).toBe(5)
  })

  it('returns null rather than 0 when no date was recorded', () => {
    // 0 would read as "brand new", which is a claim about the file. null is the truth: unknown.
    expect(ageInDays({ source_modified: null, created_at: null })).toBe(null)
    expect(ageInDays({ source_modified: 'not a date' })).toBe(null)
  })
})

describe('file type', () => {
  it('offers only the types actually present, derived not hardcoded', async () => {
    const c = await mount()
    const options = [...selectByLabel(c, 'File type').options].map((o) => o.value)
    expect(options).toEqual(['', 'docx', 'pdf', 'xlsx'])
  })

  it('narrows the queue and the count together', async () => {
    const c = await mount()
    expect(text(c)).toContain('5 files in this view')
    await choose(selectByLabel(c, 'File type'), 'pdf')
    expect(text(c)).toContain('1 files in this view')
    expect(text(c)).toContain('ancient.pdf')
    expect(text(c)).not.toContain('old.docx')
  })
})

describe('age', () => {
  it('keeps only files at least that old', async () => {
    const c = await mount()
    await choose(selectByLabel(c, 'Age'), '365')
    const t = text(c)
    expect(t).toContain('old.docx')          // 400 days
    expect(t).toContain('ancient.pdf')       // 1500 days
    expect(t).not.toContain('recent.docx')   // 10 days
    expect(t).not.toContain('sheet.xlsx')    // 200 days
  })

  it('excludes an undated file rather than treating it as new', async () => {
    // Both directions are defensible; silently picking one is not. Excluded, and the count
    // moves with it, so the queue never claims to show more than it does.
    const c = await mount()
    expect(text(c)).toContain('undated.docx')
    await choose(selectByLabel(c, 'Age'), '30')
    expect(text(c)).not.toContain('undated.docx')
    expect(text(c)).toContain('3 files in this view')
  })

  it('restores everything when the filter is cleared', async () => {
    const c = await mount()
    await choose(selectByLabel(c, 'Age'), '1095')
    expect(text(c)).toContain('1 files in this view')
    await choose(selectByLabel(c, 'Age'), '')
    expect(text(c)).toContain('5 files in this view')
  })
})

describe('filters compose', () => {
  it('applies owner and file type together', async () => {
    const c = await mount()
    await choose(selectByLabel(c, 'Owner'), 'b@x.com')
    expect(text(c)).toContain('1 files in this view')
    await choose(selectByLabel(c, 'File type'), 'docx')
    // b@x.com owns only the xlsx, so the intersection is empty - and says so.
    expect(text(c)).toContain('0 files in this view')
    expect(text(c)).toContain('No files match these filters')
  })

  it('blames the filters for an empty list, not the rules', async () => {
    // #1175 says "the enabled rules ran and matched no files" when the queue is empty. That
    // became untrue once a filter could empty it: the rules DID match, and the filter hid the
    // result. A zero that names the wrong cause sends someone to edit a policy that is working.
    const c = await mount()
    await choose(selectByLabel(c, 'File type'), 'pdf')
    await choose(selectByLabel(c, 'Owner'), 'b@x.com')
    const t = text(c)
    expect(t).toContain('No files match these filters')
    expect(t).toContain('5 file(s) are in this queue before filtering')
    expect(t, 'a filter result was blamed on the lifecycle rules')
      .not.toContain('matched no files')
  })

  it('still blames the rules when the queue really is empty', async () => {
    getLifecycleFiles.mockResolvedValue({ rows: [] })
    const c = await mount()
    expect(text(c)).toContain('The enabled rules ran and matched no files')
  })
})

describe('the two filters that are deliberately not offered', () => {
  it('says department is unavailable rather than showing an empty filter', async () => {
    const c = await mount()
    const dept = selectByLabel(c, 'Department')
    expect(dept, 'no Department control at all - a reader cannot tell it was considered').toBeTruthy()
    expect(dept.disabled, 'an enabled Department filter matches nothing and looks like it works')
      .toBe(true)
    expect(text(c)).toContain('Unavailable until connected')
    expect(text(c)).toContain('not collected by the Drive or SharePoint scan')
  })

  it('explains why source is absent instead of leaving a gap', async () => {
    const c = await mount()
    expect(selectByLabel(c, 'Source'), 'a source control can only select all or nothing here')
      .toBeFalsy()
    expect(text(c)).toContain('a scan has a single source')
  })

  it('points the department explanation at the control that needs it', async () => {
    const c = await mount()
    const dept = selectByLabel(c, 'Department')
    const described = dept.getAttribute('aria-describedby')
    expect(described, 'the disabled control does not reference its own explanation').toBeTruthy()
    expect(c.querySelector(`#${described}`), 'aria-describedby points at nothing').toBeTruthy()
  })
})
