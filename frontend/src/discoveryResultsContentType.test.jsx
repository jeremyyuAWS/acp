import { describe, it, expect, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

// BY CONTENT TYPE, on the screen that already has a BY FILE TYPE panel beside it.
//
// Absent on every source but SharePoint, and absent there too unless the tenant actually returned
// one — never a chart of a single grey "not returned" bar over an estate the feature never fired
// on. Separate from and never conflated with the department/tag classification honesty panel
// (#585): a Content Type column is a real thing a library may configure, not the same axis as
// "which department" or "under legal hold".

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const { default: DiscoveryResults } = await import('./DiscoveryResults.jsx')

const withCT = (n, ct) => Array.from({ length: n }, (_, i) => ({
  file: `f${i}.docx`, name: `f${i}.docx`, status: 'done', content_type: ct,
}))

let container, root
const mount = async (files) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(DiscoveryResults, { files })) })
  return container.textContent
}
afterEach(() => unmountAll())

describe('BY CONTENT TYPE', () => {
  it('is absent when nothing in the estate carries one', async () => {
    const t = await mount(withCT(5, undefined))
    expect(t).not.toContain('BY CONTENT TYPE')
  })

  it('renders when the source returned real content types', async () => {
    const files = [...withCT(2, 'Policy'), ...withCT(1, 'Contract')]
    const t = await mount(files)
    expect(t).toContain('BY CONTENT TYPE')
    expect(t).toMatch(/Policy/)
    expect(t).toMatch(/Contract/)
  })

  it('says which files the source did not classify, honestly, not as a defect', async () => {
    const files = [...withCT(1, 'Policy'), ...withCT(2, undefined)]
    const t = await mount(files)
    expect(t).toContain('Not returned by the source')
    expect(t).toContain('not a gap in the scan')
  })
})
