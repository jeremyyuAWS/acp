import { describe, expect, it } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'
import ReleasePlanSummary, { formatReleaseBytes } from './ReleasePlanSummary.jsx'

describe('ReleasePlanSummary', () => {
  it('keeps the user-facing plan and safety consequence visible', async () => {
    const { container, root } = createTestRoot()
    await act(async () => root.render(createElement(ReleasePlanSummary, {
      count: 12, excluded: 3, method: 'publish', provider: 'SharePoint',
      destination: 'Finance › Documents › Remediated', estimatedBytes: 1536,
    })))
    expect(container.textContent).toMatch(/12 selected/)
    expect(container.textContent).toMatch(/Publish to SharePoint/)
    expect(container.textContent).toMatch(/Finance › Documents › Remediated/)
    expect(container.textContent).toMatch(/Original files stay unchanged/)
    expect(container.textContent).toMatch(/3 excluded for safety or review/)
    unmountAll()
  })

  it('formats known sizes and stays honest when size is unavailable', () => {
    expect(formatReleaseBytes(1536)).toBe('1.5 KB')
    expect(formatReleaseBytes(undefined)).toBe('Size calculated before delivery')
  })
})
