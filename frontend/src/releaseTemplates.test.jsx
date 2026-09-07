import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { Simulate } from 'react-dom/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import ReleaseTemplates from './ReleaseTemplates.jsx'

let node
afterEach(() => { node?.remove(); node = null })
async function mount(props) {
  node = document.createElement('div'); document.body.appendChild(node)
  await act(async () => createRoot(node).render(<ReleaseTemplates {...props} />))
  return node
}

it('applies, saves, and deletes named delivery plans', async () => {
  const onApply = vi.fn(), onSave = vi.fn(), onDelete = vi.fn()
  const template = { name: 'Finance ZIP', method: 'download', preserve_hierarchy: false }
  const view = await mount({ templates: [template], currentPlan: { method: 'publish' },
    provider: 'drive', onApply, onSave, onDelete })
  view.querySelector('details').open = true
  await act(async () => [...view.querySelectorAll('button')].find((b) => b.textContent === 'Apply').click())
  expect(onApply).toHaveBeenCalledWith(template)
  const input = view.querySelector('input')
  await act(async () => Simulate.change(input, { target: { value: 'Board delivery' } }))
  await act(async () => [...view.querySelectorAll('button')].find((b) => b.textContent === 'Save current setup').click())
  expect(onSave).toHaveBeenCalledWith({ name: 'Board delivery', method: 'publish' })
  await act(async () => view.querySelector('[aria-label="Delete Finance ZIP"]').click())
  expect(onDelete).toHaveBeenCalledWith(template)
})

it('disables a provider-specific template on a different source', async () => {
  const template = { name: 'SharePoint board', method: 'publish',
    destination: { provider: 'sharepoint', folder_id: 'drive/item', folder_name: 'Board' } }
  const view = await mount({ templates: [template], currentPlan: {}, provider: 'drive' })
  expect([...view.querySelectorAll('button')].find((b) => b.textContent === 'Apply').disabled).toBe(true)
})
