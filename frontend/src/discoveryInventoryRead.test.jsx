/**
 * Discover reads the lifecycle columns from `GET /scans/{id}/inventory` — and a read that did not
 * complete renders NOTHING.
 *
 * This is the file for the failure path, which is the one most likely to regress into a
 * reassuring zero. A 403, a dropped connection and an estate with no tagged files are three
 * different facts; only one of them is "no file needs your decision", and it is the only one
 * allowed to say so. So the assertions here are mostly about what is ABSENT.
 *
 * `api.js` is partially mocked — `importOriginal` keeps every other export real, so DispositionRules
 * and the rest of Discover's module graph behave exactly as they do in the suite's other Discover
 * mounts, and only the one route under test is controlled.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const h = vi.hoisted(() => ({ mode: 'ok', rows: [], calls: [] }))

vi.mock('./api.js', async (importOriginal) => {
  const actual = await importOriginal()
  return {
    ...actual,
    getScanInventory: (scanId, { offset = 0, limit = 1000 } = {}) => {
      h.calls.push({ scanId, offset, limit })
      if (h.mode === 'reject') return Promise.reject(new Error('HTTP 403 — forbidden'))
      // Still in flight: a promise that never settles, so the mount renders the loading state.
      if (h.mode === 'pending') return new Promise(() => {})
      // The truncated read: the route reports more rows than it hands back.
      if (h.mode === 'short') return Promise.resolve({ scan_id: scanId, total: 5000, offset, limit, rows: [] })
      return Promise.resolve({ scan_id: scanId, total: h.rows.length, offset, limit,
                               rows: h.rows.slice(offset, offset + limit) })
    },
  }
})

const { default: Discover } = await import('./Discover.jsx')

let container, root
beforeEach(() => {
  ;({ container, root } = createTestRoot())
  h.mode = 'ok'
  h.calls = []
  h.rows = [
    { file: 'Clinical/old-pathway.docx', path: 'Clinical/old-pathway.docx',
      lifecycle_status: 'Archive Candidate', lifecycle_rule_id: 'p1',
      lifecycle_reason: "matched archive rule 'Legacy clinical policies'" },
    { file: 'Clinical/live.docx', path: 'Clinical/live.docx', lifecycle_status: 'Active' },
  ]
})
afterEach(unmountAll)

const FILES = [
  { file: 'Clinical/old-pathway.docx', type: 'DOCX', tags: [], issues: [], department: 'Clinical', sourceName: 'SharePoint' },
  { file: 'Clinical/live.docx', type: 'DOCX', tags: [], issues: [], department: 'Clinical', sourceName: 'SharePoint' },
]

const render = async (props = {}) => {
  await act(async () => {
    root.render(createElement(Discover, {
      sources: [{ name: 'SharePoint' }], files: FILES, busy: false, onScan: () => {},
      onAdvance: () => {}, scanId: 'scan-1', ...props,
    }))
  })
  // let the inventory read settle
  for (let k = 0; k < 6; k++) await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
  return container
}
const text = () => container.textContent

describe('a completed read fills the recommendation surface', () => {
  it('calls the inventory route for the scan on screen', async () => {
    await render()
    expect(h.calls[0]).toMatchObject({ scanId: 'scan-1', offset: 0 })
  })

  it('shows the tag, the rule that produced it and the recorded reason', async () => {
    await render()
    expect(text()).toContain('tagged for archive review')
    expect(text()).toContain('Legacy clinical policies')
    expect(text()).toContain("matched archive rule 'Legacy clinical policies'")
    expect(text()).toContain('I approve these 1 recommendation.')
  })

  it('reports a MEASURED zero when the rules ran and matched nothing', async () => {
    h.rows = h.rows.map((r) => ({ ...r, lifecycle_status: 'Active', lifecycle_rule_id: null, lifecycle_reason: null }))
    await render()
    // The columns came back, so a zero here is a fact about the estate, not about the read.
    expect(text()).toContain('tagged for archive review')
    // ...and there is nothing to approve.
    expect(text()).not.toContain('I approve')
  })
})

describe('a read that did not complete renders NOTHING — never a zero', () => {
  const absent = () => {
    // Every lifecycle-dependent surface, by the words only it produces.
    expect(text()).not.toContain('tagged for archive review')
    expect(text()).not.toContain('tagged for deletion review')
    expect(text()).not.toContain('RECOMMENDATIONS')
    expect(text()).not.toContain('EVERY DISCOVERED FILE, IN ONE BUCKET')
    expect(text()).not.toContain('I approve')
    // And nothing that would read as "we checked and found none".
    expect(text()).not.toContain('No recommendation')
    expect(text()).not.toContain('matched no file')
  }

  it('is absent when the route rejects', async () => {
    h.mode = 'reject'
    await render()
    // The rest of the screen still works — this is a missing section, not a broken tab.
    expect(text()).toContain('DISCOVERY RESULTS')
    expect(text()).toContain('files discovered')
    absent()
  })

  it('is absent when the read was truncated — a page is not the estate', async () => {
    h.mode = 'short'
    await render()
    expect(text()).toContain('DISCOVERY RESULTS')
    absent()
  })

  it('is absent while the read is still in flight', async () => {
    // The route never answers, so the screen stays in the state it is in before an answer.
    // "Not loaded yet" must look like "we do not know", not like "nothing is tagged".
    h.mode = 'pending'
    await render()
    expect(h.calls).toHaveLength(1)
    expect(text()).toContain('DISCOVERY RESULTS')
    absent()
  })

  it('is absent when there is no scan to read an inventory for', async () => {
    await render({ scanId: null })
    expect(h.calls).toHaveLength(0)
    absent()
  })

  it('does not block Assess on an acknowledgement it cannot show', async () => {
    h.mode = 'reject'
    await render()
    const acceptAll = [...container.querySelectorAll('button')]
      .find((b) => b.textContent.includes('Accept all recommendations'))
    await act(async () => { acceptAll.click() })
    const assess = [...container.querySelectorAll('button')]
      .find((b) => b.textContent.includes('Assess — score vs WCAG'))
    expect(assess.disabled).toBe(false)
  })
})

describe('a file the inventory did not cover is its own bucket, not "no recommendation"', () => {
  it('keeps the partition honest instead of promoting an unread file to checked', async () => {
    h.rows = [h.rows[0]]     // only one of the two files has an inventory row
    await render()
    expect(text()).toContain('No lifecycle record was read for these')
    expect(text()).toContain('The buckets add up to the 2 files discovered')
  })
})
