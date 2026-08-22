// The expandable Processing-details table: renders live per-file rows, filters narrow them,
// and columns carry the right language so "Failed" cannot be mistaken for a WCAG result.
import { describe, it, expect, afterEach, vi } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import ProcessingDetails from './ProcessingDetails.jsx'

afterEach(unmountAll)

const FILES = [
  { file: 'docs/Policy.docx', status: 'certifiable', score: 98, owner: 'Alice', parent_folder: 'Drive / Compliance' },
  { file: 'docs/Report.pdf', status: 'uncertain', score: 72, issues: [{ sc: '1.1.1' }, { sc: '1.4.3' }], owner: 'Alice' },
  { file: 'docs/Old.pptx', status: 'error', score: null, owner: 'Alice' },
]

async function render(props) {
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(ProcessingDetails, props)) })
  return container
}
const click = async (el) => { await act(async () => { el.click() }) }

// Filename from first span in first <td> (not the folder secondary text).
const rowNames = (c) => [...c.querySelectorAll('tbody tr')]
  .map((tr) => tr.querySelector('td span')?.textContent).filter(Boolean)

// Filter buttons are now aria-pressed toggles, not tabs.
const btn = (c, label) => [...c.querySelectorAll('button[aria-pressed]')]
  .find((b) => b.textContent.includes(label))

it('renders nothing when there is nothing landed and nothing processing', async () => {
  const c = await render({ files: [], processing: 0 })
  expect(c.querySelector('details')).toBeFalsy()
})

it('lists every landed file; clicking a filter narrows to that outcome', async () => {
  const c = await render({ files: FILES, processing: 5 })
  expect(rowNames(c)).toEqual(['Policy.docx', 'Report.pdf', 'Old.pptx'])
  expect(c.textContent).toMatch(/View processing details \(3 landed · 5 processing\)/)

  await click(btn(c, "Couldn't assess"))
  expect(rowNames(c)).toEqual(['Old.pptx'])

  await click(btn(c, 'Findings'))
  expect(rowNames(c)).toEqual(['Report.pdf'])
})

it('shows the still-processing count as a note, never as fabricated rows', async () => {
  const c = await render({ files: FILES, processing: 5 })
  expect(c.textContent).toMatch(/5 more files still processing/)
  expect(rowNames(c)).toHaveLength(3)
})

it('uses unambiguous status labels — "Couldn\'t assess" not "Failed"', async () => {
  const c = await render({ files: FILES })
  // "Failed" must not appear anywhere — it is ambiguous between ACP failure and WCAG failure.
  const text = c.textContent
  expect(text).not.toMatch(/\bFailed\b/)
  expect(text).toMatch(/Couldn't assess/)
  expect(text).toMatch(/Assessed — no issues/)
})

it('shows the Issues count once a file is assessed', async () => {
  const c = await render({ files: FILES })
  const rows = c.querySelectorAll('tbody tr')
  // Report.pdf has 2 issues (explicit array from backend)
  const reportRow = [...rows].find((tr) => tr.textContent.includes('Report.pdf'))
  expect(reportRow?.textContent).toMatch(/2/)
  // Old.pptx (error) — no score, no issues count; both cells show —
  const oldRow = [...rows].find((tr) => tr.textContent.includes('Old.pptx'))
  expect(oldRow?.textContent).toMatch(/—/)
  // Policy.docx — certifiable but no issues array from backend → shows — (not 0; absence ≠ zero)
  const policyRow = [...rows].find((tr) => tr.textContent.includes('Policy.docx'))
  expect(policyRow?.textContent).not.toMatch(/Couldn't assess/)
  expect(policyRow?.textContent).toMatch(/Assessed/)
})

it('hides Owner when every row has the same owner', async () => {
  // All three files have owner: 'Alice' — column should be absent.
  const c = await render({ files: FILES })
  const headers = [...c.querySelectorAll('th')].map((th) => th.textContent.trim())
  expect(headers).not.toContain('Owner')
})

it('shows Owner when files have different owners', async () => {
  const mixed = [
    { file: 'a.docx', status: 'certifiable', score: 90, owner: 'Alice' },
    { file: 'b.pdf', status: 'certifiable', score: 85, owner: 'Bob' },
  ]
  const c = await render({ files: mixed })
  const headers = [...c.querySelectorAll('th')].map((th) => th.textContent.trim())
  expect(headers).toContain('Owner')
})

it('shows the folder as secondary text below the filename, not as a column', async () => {
  const c = await render({ files: FILES })
  const headers = [...c.querySelectorAll('th')].map((th) => th.textContent.trim())
  expect(headers).not.toContain('Location')
  // The folder value appears inside the Document cell, not in a separate column.
  expect(c.textContent).toMatch(/Drive \/ Compliance/)
})

it('calls onSelect with the row when an action button is clicked', async () => {
  const onSelect = vi.fn()
  const c = await render({ files: FILES, onSelect })
  const actionBtns = [...c.querySelectorAll('button:not([aria-pressed])')]
  expect(actionBtns.length).toBeGreaterThan(0)
  await click(actionBtns[0])
  expect(onSelect).toHaveBeenCalledOnce()
  expect(onSelect.mock.calls[0][0]).toMatchObject({ file: expect.stringContaining('.') })
})

it('filter buttons use aria-pressed, not aria-selected', async () => {
  const c = await render({ files: FILES })
  expect(c.querySelector('button[aria-pressed]')).toBeTruthy()
  expect(c.querySelector('button[aria-selected]')).toBeFalsy()
})
