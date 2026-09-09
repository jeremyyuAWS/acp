import { act, createElement } from 'react'
import { afterEach, expect, it } from 'vitest'
import MatchingReviewPreview from './MatchingReviewPreview.jsx'
import { createTestRoot, unmountAll } from './testRoots.js'

globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(async () => unmountAll())
const findings = Array.from({ length: 12 }, (_, index) => ({ id: `id-${index}`, file: `file-${index}.pdf`, after: `Proposal ${index}`, rationale: `Because ${index}`, severity: index === 8 ? 'CRITICAL' : 'MINOR' }))
async function mount(items = findings) {
  const { root, container } = createTestRoot()
  const render = input => act(async () => root.render(createElement(MatchingReviewPreview, { findings: input })))
  await render(items)
  return { container, render }
}
const button = (container, title) => [...container.querySelectorAll('button')].find(item => item.textContent === title)
it('lets a reviewer inspect every matching proposal and rationale without changing the group scope', async () => {
  const { container } = await mount()
  expect(container.querySelectorAll('li')).toHaveLength(5)
  expect(container.textContent).toContain('Because 0')
  expect(button(container, 'Previous proposals').disabled).toBe(true)
  await act(async () => button(container, 'Next proposals').click())
  expect(container.textContent).toContain('file-8.pdf')
  expect(container.textContent).toContain('Proposal 8')
  expect(container.textContent).toContain('Because 8')
  expect(container.textContent).toContain('CRITICAL')
  expect(container.textContent).toContain('6–10 of 12')
  await act(async () => button(container, 'Next proposals').click())
  expect(container.querySelectorAll('li')).toHaveLength(2)
  expect(container.textContent).toContain('Proposal 11')
  expect(button(container, 'Next proposals').disabled).toBe(true)
  expect(container.textContent).toContain('select proposals separately for batch approval')
  expect([...container.querySelectorAll('button')].map(item => item.textContent)).toEqual(['Previous proposals', 'Next proposals'])
})
it('starts at the first page when the group membership changes', async () => {
  const { container, render } = await mount()
  await act(async () => button(container, 'Next proposals').click())
  await render(findings.map(item => ({ ...item, id: `new-${item.id}` })))
  expect(container.textContent).toContain('1–5 of 12')
})
it('does not mislabel the observed value as a proposal or invent a rationale', async () => {
  const { container } = await mount([{ id: 'missing', file: 'a.pdf', observed: 'Existing content' }])
  expect(container.textContent).toContain('No proposed value recorded')
  expect(container.textContent).toContain('No rationale recorded')
  expect(container.textContent).not.toContain('Existing content')
})
it('renders saved proposals as text, never executable markup', async () => {
  const { container } = await mount([{ id: 'html', file: 'a.pdf', after: '<img src=x onerror=alert(1)>', rationale: '<script>bad()</script>' }])
  expect(container.querySelector('img,script')).toBeNull()
  expect(container.textContent).toContain('<img src=x onerror=alert(1)>')
})
