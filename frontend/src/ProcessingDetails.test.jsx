// The expandable Processing-details table: renders live per-file rows, filters narrow them, and it
// stays out of the way (renders nothing) when there is nothing to show.
import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import ProcessingDetails from './ProcessingDetails.jsx'

afterEach(unmountAll)

const FILES = [
  { file: 'Policy.docx', status: 'certifiable', score: 98 },
  { file: 'Report.pdf', status: 'uncertain', score: 72 },
  { file: 'Old.pptx', status: 'error', score: null },
]

async function render(props) {
  const { root, container } = createTestRoot()
  await act(async () => { root.render(createElement(ProcessingDetails, props)) })
  return container
}
const click = async (el) => { await act(async () => { el.click() }) }
const rowFiles = (c) => [...c.querySelectorAll('tbody tr')]
  .map((tr) => tr.querySelector('td')?.textContent).filter(Boolean)
const tab = (c, label) => [...c.querySelectorAll('button[role="tab"]')].find((b) => b.textContent.startsWith(label))

it('renders nothing when there is nothing landed and nothing processing', async () => {
  const c = await render({ files: [], processing: 0 })
  expect(c.querySelector('details')).toBeFalsy()
})

it('lists every landed file with its result, and a filter narrows to that outcome', async () => {
  const c = await render({ files: FILES, processing: 5 })
  expect(rowFiles(c)).toEqual(['Policy.docx', 'Report.pdf', 'Old.pptx'])
  expect(c.textContent).toMatch(/View processing details \(3 landed · 5 processing\)/)

  await click(tab(c, 'Failed'))
  expect(rowFiles(c)).toEqual(['Old.pptx'])                 // only the error row
  await click(tab(c, 'Findings'))
  expect(rowFiles(c)).toEqual(['Report.pdf'])               // only need-review
})

it('shows the still-processing count as a note, never as fabricated rows', async () => {
  const c = await render({ files: FILES, processing: 5 })
  expect(c.textContent).toMatch(/5 more files still processing/)
  expect(rowFiles(c)).toHaveLength(3)                        // only the 3 that actually landed
})
