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

  it('drill-down shows size/owner, flags shared files, and re-sorts', async () => {
    const inv = { ...INV, samples: { unsupported: [
      { id: 'a', name: 'small.txt', format: 'other', size: 1024, owner: 'Ann', shared: false },
      { id: 'b', name: 'huge.mov', format: 'av', size: 500000000, owner: 'Bo', shared: true },
    ] } }
    await render({ inventory: inv })
    const chip = [...container.querySelectorAll('button')].find((b) => /Unsupported/.test(b.textContent))
    await act(async () => { chip.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    // triage metadata is visible: owner, a human size, and the SHARED flag
    expect(container.textContent).toContain('Bo')
    expect(container.textContent).toContain('477 MB')     // 500,000,000 bytes, humanised
    expect(container.textContent).toContain('SHARED')
    // default sort is largest-first → huge.mov before small.txt
    const order = () => [...container.querySelectorAll('li')].map((li) => li.textContent)
    let items = order()
    expect(items.findIndex((t) => /huge\.mov/.test(t))).toBeLessThan(items.findIndex((t) => /small\.txt/.test(t)))
    // re-sort by Name — 'huge' still sorts before 'small' alphabetically, but via a different path
    const nameBtn = [...container.querySelectorAll('button')].find((b) => b.textContent.trim() === 'Name')
    await act(async () => { nameBtn.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    items = order()
    expect(items.findIndex((t) => /huge\.mov/.test(t))).toBeLessThan(items.findIndex((t) => /small\.txt/.test(t)))
  })
})
