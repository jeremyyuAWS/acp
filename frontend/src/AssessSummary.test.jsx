import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import AssessSummary from './AssessSummary.jsx'

afterEach(unmountAll)

const CRITERIA = new Set(['1.1.1'])
const CAP = { docx: { '1.1.1': 'auto' } }
const ASMT = { docx: { '1.1.1': 'auto' } }
const FILES = [{ file: 'a.docx', name: 'a.docx', status: 'analysed', issues: [] }]

async function render(props) {
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(AssessSummary, { files: FILES, cap: CAP, assessment: ASMT,
                                               criteria: CRITERIA, ...props }))
  })
  return container
}

describe('lifecycle exclusion count in the header', () => {
  it('shows the excluded count when lifecycle_eligible_excluded is non-zero', async () => {
    const run = { status: 'done', scope: { lifecycle_eligible_excluded: 7 } }
    const c = await render({ run })
    expect(c.textContent).toMatch(/7 excluded by lifecycle policy/)
  })

  it('omits the exclusion note when lifecycle_eligible_excluded is zero', async () => {
    const run = { status: 'done', scope: { lifecycle_eligible_excluded: 0 } }
    const c = await render({ run })
    expect(c.textContent).not.toMatch(/excluded by lifecycle policy/)
  })

  it('omits the exclusion note when run has no scope', async () => {
    const c = await render({ run: { status: 'done' } })
    expect(c.textContent).not.toMatch(/excluded by lifecycle policy/)
  })

  it('omits the exclusion note when run is absent', async () => {
    const c = await render({})
    expect(c.textContent).not.toMatch(/excluded by lifecycle policy/)
  })
})
