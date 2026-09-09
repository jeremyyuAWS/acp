import { act, createElement } from 'react'
import { afterEach, expect, it } from 'vitest'
import axe from 'axe-core'
import AssessSummary from './AssessSummary.jsx'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)
const criteria = new Set(['1.1.1', '1.3.1'])
const assessment = { pdf: { '1.3.1': 'auto' }, docx: { '1.1.1': 'auto', '1.3.1': 'auto' } }
const files = [
  ...Array.from({ length: 31 }, (_, i) => ({ file: `report-${i}.pdf`, status: 'analysed', issues: [] })),
  { file: 'fully-checked.docx', status: 'analysed', issues: [] },
  { file: 'unreadable.pdf', status: 'error', error: 'Password protected', issues: [] },
]
async function mount(extra = {}) {
  const view = createTestRoot()
  const render = async props => act(async () => view.root.render(createElement(AssessSummary, {
    files, assessment, criteria, run: { id: 'scan-1' }, ...extra, ...props,
  })))
  await render()
  return { ...view, render }
}
const tile = c => [...c.querySelectorAll('button')].find(el => el.textContent.startsWith('Checks not completed'))
const click = async el => act(async () => el.click())
const breakdown = c => c.querySelector('section[role=region]')

it('opens all 31 document/criterion checks behind the tile, without including evaluated or unopened files', async () => {
  const { container } = await mount()
  expect(tile(container).textContent).toContain('31 checks')
  expect(tile(container).getAttribute('aria-expanded')).toBe('false')
  expect(breakdown(container)).toBeNull()
  await click(tile(container))
  const region = breakdown(container)
  expect(tile(container).getAttribute('aria-expanded')).toBe('true')
  expect(tile(container).getAttribute('aria-controls')).toBe(region.id)
  expect(region.querySelectorAll('tbody tr')).toHaveLength(31)
  expect(region.textContent).toContain('31 checks across 31 documents')
  expect(region.textContent).toContain('WCAG 1.1.1')
  expect(region.textContent).toContain('Non-text Content')
  expect(region.textContent).toContain('report-30.pdf')
  expect(region.textContent).toContain('No ACP assessment method is recorded')
  expect(region.textContent).not.toContain('WCAG 1.3.1')
  expect(region.textContent).not.toContain('fully-checked.docx')
  expect(region.textContent).not.toContain('unreadable.pdf')
  expect(document.activeElement).toBe(region.querySelector('h3'))
  const results = await axe.run(region, { rules: { 'color-contrast': { enabled: false } } })
  expect(results.violations).toEqual([])
})

it('distinguishes manual assessment from absent methods and uses only selected criteria', async () => {
  const { container } = await mount({ files: [files[0], files[31]],
    criteria: new Set(['1.1.1']), assessment: { docx: { '1.1.1': 'human' } } })
  await click(tile(container))
  const rows = [...breakdown(container).querySelectorAll('tbody tr')]
  expect(rows).toHaveLength(2)
  expect(rows.find(row => row.textContent.includes('fully-checked.docx')).textContent).toContain('Manual assessment required')
  expect(rows.find(row => row.textContent.includes('report-0.pdf')).textContent).toContain('No ACP assessment method is recorded')
})

it('closes with Escape or Close and restores focus to the tile; a different run starts collapsed', async () => {
  const { container, render } = await mount()
  await click(tile(container))
  await act(async () => document.activeElement.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
  expect(breakdown(container)).toBeNull()
  expect(document.activeElement).toBe(tile(container))
  await click(tile(container))
  await click([...breakdown(container).querySelectorAll('button')].find(el => el.textContent === 'Close breakdown'))
  expect(breakdown(container)).toBeNull()
  expect(document.activeElement).toBe(tile(container))
  await click(tile(container))
  await render({ run: { id: 'scan-2' } })
  expect(breakdown(container)).toBeNull()
  expect(tile(container).getAttribute('aria-expanded')).toBe('false')
})

it('omits the incomplete-check tile when all selected checks ran', async () => {
  const { container } = await mount({ files: [files[31]] })
  expect(tile(container)).toBeUndefined()
  expect(container.textContent).toContain('2 checks evaluated + 0 unable to assess = 2 selected checks')
  expect(breakdown(container)).toBeNull()
})

it('keeps the numeric count readable on a light clickable card', async () => {
  const { container } = await mount()
  const count = tile(container).children[1]
  expect(count.style.color).toBe('var(--ink, #2b2330)')
})

it('removes an open breakdown when the incomplete count becomes zero', async () => {
  const { container, render } = await mount()
  await click(tile(container))
  await render({ files: [files[31]] })
  expect(tile(container)).toBeUndefined()
  expect(breakdown(container)).toBeNull()
})
