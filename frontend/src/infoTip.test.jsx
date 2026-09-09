import { act, createElement } from 'react'
import { afterEach, expect, it } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import InfoTip from './InfoTip.jsx'
globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(unmountAll)

async function mount(props = {}) {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(InfoTip,
    { label: 'subfolders', ...props }, 'Subfolders are included unless you exclude them.')))
  return { container, button: container.querySelector('button') }
}

it('hides the detail until asked, and names what the detail is about', async () => {
  const { container, button } = await mount()
  expect(container.textContent).not.toContain('Subfolders are included')
  expect(button.getAttribute('aria-label')).toBe('About subfolders')
  expect(button.getAttribute('aria-expanded')).toBe('false')
})

it('opens on KEYBOARD focus, not only on hover', async () => {
  // The pattern this replaces used a `title` attribute, which never appears on focus — so the
  // text was unreachable for anyone who cannot use a pointer, on an accessibility product.
  const { container, button } = await mount()
  await act(async () => button.focus())
  const tip = container.querySelector('[role=tooltip]')
  expect(tip).not.toBeNull()
  expect(tip.textContent).toContain('Subfolders are included unless you exclude them.')
  expect(button.getAttribute('aria-expanded')).toBe('true')
})

it('describes the button by the open tooltip, so a screen reader reads them together', async () => {
  const { container, button } = await mount()
  await act(async () => button.focus())
  const tip = container.querySelector('[role=tooltip]')
  expect(button.getAttribute('aria-describedby')).toBe(tip.id)
  expect(tip.id).toBeTruthy()
})

it('closes on Escape while focus stays put', async () => {
  const { container, button } = await mount()
  await act(async () => button.focus())
  expect(container.querySelector('[role=tooltip]')).not.toBeNull()
  await act(async () => { document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })) })
  expect(container.querySelector('[role=tooltip]')).toBeNull()
})

it('is a real button, so click works where hover does not exist', async () => {
  const { container, button } = await mount()
  expect(button.type).toBe('button')
  await act(async () => button.click())
  expect(container.querySelector('[role=tooltip]')).not.toBeNull()
})
