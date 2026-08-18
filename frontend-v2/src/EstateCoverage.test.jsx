import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

const { default: EstateCoverage } = await import('./EstateCoverage.jsx')

const INV = {
  discovered: 30000, assessment_eligible: 18692, truncated: false,
  by_format: { pdf: 8175, image: 7570, docx: 6223, xlsx: 2951, other: 2374, pptx: 1509, av: 1198 },
  by_status: { assessable: 18692, metadata_only: 8768, unsupported: 2374, excluded: 166 },
}

let container, root
beforeEach(() => { ;({ container, root } = createTestRoot()) })
const render = async (props) => { await act(async () => { root.render(createElement(EstateCoverage, props)) }) }

describe('EstateCoverage', () => {
  it('renders the headline denominators from a report scope.inventory', async () => {
    await render({ report: { scope: { inventory: INV } } })
    expect(container.textContent).toContain('30,000 files discovered')
    expect(container.textContent).toContain('62% assessment-eligible')
    // the unsupported blind spot is visible as a status, not hidden
    expect(container.textContent).toContain('Unsupported')
    expect(container.textContent).toContain('Metadata-only')
  })

  it('shows the whole nine-stage funnel; lower stages read pending without scan data', async () => {
    await render({ inventory: INV })
    expect(container.textContent).toContain('All files discovered')
    expect(container.textContent).toContain('Assessment eligible')
    expect(container.textContent).toContain('Published / ready for release')
    expect(container.textContent).toContain('pending')            // assessed/remediated not yet known
  })

  it('fills the lower funnel stages when progress is supplied', async () => {
    await render({ inventory: INV, progress: { assessed: 18692, remediated: 7540, published: 6900 } })
    expect(container.textContent).toContain('7,540')              // remediated
    expect(container.textContent).toContain('6,900')              // published
  })

  it('flags a truncated estate as a floor, never as complete', async () => {
    await render({ inventory: { ...INV, truncated: true } })
    expect(container.textContent).toMatch(/≥\s*30,000/)
    expect(container.textContent).toContain('TRUNCATED')
  })

  it('shows an honest empty state before any scan', async () => {
    await render({ report: { scope: {} } })
    expect(container.textContent).toContain('No estate inventory yet')
  })

  it('drills a capability-status count open to the files behind it, honest about the cap', async () => {
    const inv = { ...INV, samples: { unsupported: [{ id: 'a', name: 'archive.zip', format: 'other' }] } }
    await render({ inventory: inv })
    // the files are not shown until the status is expanded
    expect(container.textContent).not.toContain('archive.zip')
    const btn = [...container.querySelectorAll('button')].find((b) => /Unsupported/.test(b.textContent))
    expect(btn).toBeTruthy()
    await act(async () => { btn.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    expect(container.textContent).toContain('archive.zip')            // the file behind the count
    expect(container.textContent).toMatch(/Showing\s*1\s*of\s*2,374/)  // sample of the true total, said plainly
  })
})
