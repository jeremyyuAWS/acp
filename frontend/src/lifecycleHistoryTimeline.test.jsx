/**
 * The document history the review panel shows (PRD §7.4).
 *
 * The point of a timeline here is that it crosses scans. "Recommended, kept, recommended again"
 * tells a reviewer the rule is arguing with a person; "recommended" tells them nothing. So the
 * assertions below are about ORDER and PROVENANCE - which scan, which rule version, who acted -
 * rather than about the presence of a list.
 *
 * Three states are kept distinct on purpose: no history asked for, history asked for and
 * unreadable, and genuinely nothing recorded. Collapsing them means an unreadable history looks
 * like a clean one, which is the same class of lie as an empty folder that failed to list.
 */
import { describe, it, expect, afterEach, vi, beforeEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import LifecycleEvidencePanel from './LifecycleEvidencePanel.jsx'
import DispositionReviewWorkspace from './DispositionReviewWorkspace.jsx'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const approveDispositionBatch = vi.fn()
const getLifecycleFiles = vi.fn()
const getLifecycleFileDetail = vi.fn()
const getLifecycleFileHistory = vi.fn()

vi.mock('./api.js', () => ({
  approveDispositionBatch: (...a) => approveDispositionBatch(...a),
  getLifecycleFiles: (...a) => getLifecycleFiles(...a),
  getLifecycleFileDetail: (...a) => getLifecycleFileDetail(...a),
  getLifecycleFileHistory: (...a) => getLifecycleFileHistory(...a),
}))

afterEach(unmountAll)

const EVENTS = [
  { ts: '2026-08-01T09:00:00Z', kind: 'evaluated', scan_id: 'scan-aug', policy_id: 'retention',
    policy_version: 2, result: 'matched', actor: null, detail: 'matched the age condition' },
  { ts: '2026-08-02T10:00:00Z', kind: 'override', scan_id: 'scan-aug', policy_id: null,
    policy_version: null, result: 'kept', actor: 'owner@x.com',
    detail: 'still cited by the 2019 audit' },
  { ts: '2026-09-01T09:00:00Z', kind: 'approval', scan_id: 'scan-sep', policy_id: 'retention',
    policy_version: 3, result: 'approved', actor: null,
    detail: 'signed off for the Q3 records schedule' },
]

const FILE = { file: 'quarterly.docx', lifecycle_status: 'Archive Candidate', evaluations: [] }

const text = (el) => (el.textContent || '').replace(/\s+/g, ' ').trim()

async function mount(Component, props) {
  const { container, root } = createTestRoot()
  await act(async () => { root.render(createElement(Component, props)) })
  await act(async () => {})
  return container
}

describe('the timeline itself', () => {
  it('lists every event in order, as an ordered list', async () => {
    const c = await mount(LifecycleEvidencePanel, { file: { ...FILE, history: EVENTS } })
    const items = [...c.querySelectorAll('ol li')].map(text)
    expect(items).toHaveLength(3)
    // The order IS the information: an ordered list gives a screen reader the sequence and its
    // length without the visual rail that carries it for everyone else.
    expect(items[0]).toContain('Recommended')
    expect(items[1]).toContain('Kept by a reviewer')
    expect(items[2]).toContain('Approval')
  })

  it('names the scan and the rule version each event happened under', async () => {
    // The fixture's detail strings deliberately do NOT repeat the policy or version: an earlier
    // draft did, so deleting the version from the rendered line left this green. It was passing
    // on the detail text, not on the field it names.
    const c = await mount(LifecycleEvidencePanel, { file: { ...FILE, history: EVENTS } })
    const items = [...c.querySelectorAll('ol li')].map(text)
    expect(items[0]).toContain('scan scan-aug')
    expect(items[0]).toContain('retention v2')
    // Collapsing the versions would make August's recommendation look like it was made under
    // the rule as it stands today.
    expect(items[2]).toContain('retention v3')
    expect(items[2]).toContain('scan scan-sep')
  })

  it('names who kept a file and why', async () => {
    const c = await mount(LifecycleEvidencePanel, { file: { ...FILE, history: EVENTS } })
    const kept = [...c.querySelectorAll('ol li')].map(text).find((t) => t.includes('Kept'))
    expect(kept).toContain('owner@x.com')
    expect(kept).toContain('still cited by the 2019 audit')
  })

  it('says an undated event has no date rather than inventing one', async () => {
    const c = await mount(LifecycleEvidencePanel, { file: { ...FILE, history: [
      { ts: null, kind: 'evaluated', scan_id: 'scan-old', policy_id: 'legacy',
        policy_version: 1, detail: 'matched' }] } })
    expect(text(c)).toContain('date not recorded')
  })
})

describe('the three states are never collapsed into one', () => {
  it('says so when nothing was recorded', async () => {
    const c = await mount(LifecycleEvidencePanel, { file: { ...FILE, history: [] } })
    expect(text(c)).toContain('No earlier lifecycle activity was recorded')
    expect(c.querySelector('ol')).toBe(null)
  })

  it('says so when the history could not be read, and keeps the evidence', async () => {
    // The dangerous state. Rendered as "nothing recorded" it would read as a clean document.
    const c = await mount(LifecycleEvidencePanel, {
      file: { ...FILE, lifecycle_reason: 'older than the cutoff', history: null } })
    expect(text(c)).toContain('could not be read')
    expect(text(c), 'an unreadable history blanked the evidence beside it')
      .toContain('older than the cutoff')
  })

  it('renders no history section at all when none was requested', async () => {
    const c = await mount(LifecycleEvidencePanel, { file: FILE })
    expect(c.querySelector('#lifecycle-history-heading')).toBe(null)
  })
})

describe('the queue asks for detail and history together', () => {
  beforeEach(() => {
    approveDispositionBatch.mockReset(); getLifecycleFiles.mockReset()
    getLifecycleFileDetail.mockReset(); getLifecycleFileHistory.mockReset()
    getLifecycleFiles.mockResolvedValue({ rows: [{
      file: 'quarterly.docx', owner: 'a@x.com', lifecycle_status: 'Archive Candidate',
      lifecycle_reason: 'older than the cutoff', lifecycle_rule_id: 'retention',
      audit_id: 'aud-1', policy_id: 'retention', policy_version: 3, action: 'archive' }] })
    getLifecycleFileDetail.mockResolvedValue({ ...FILE })
    getLifecycleFileHistory.mockResolvedValue({ events: EVENTS })
  })

  const open = async (c) => {
    const row = [...c.querySelectorAll('button')].find((b) => text(b).includes('quarterly.docx'))
    await act(async () => { row.click() })
    await act(async () => {})
  }

  it('shows the timeline when a file is opened', async () => {
    const c = await mount(DispositionReviewWorkspace, { scanId: 'scan-sep' })
    await open(c)
    expect(getLifecycleFileHistory).toHaveBeenCalledWith('scan-sep', 'quarterly.docx')
    expect(text(c)).toContain('Kept by a reviewer')
  })

  it('still shows the evidence when only the history fails', async () => {
    // One failing request must not cost the reviewer the panel they opened.
    getLifecycleFileHistory.mockRejectedValue(new Error('boom'))
    const c = await mount(DispositionReviewWorkspace, { scanId: 'scan-sep' })
    await open(c)
    const t = text(c)
    expect(t).toContain('Why this was recommended')
    expect(t).toContain('could not be read')
    expect(c.querySelector('[role="alert"]'), 'a history failure raised a page-level alert')
      .toBe(null)
  })
})
