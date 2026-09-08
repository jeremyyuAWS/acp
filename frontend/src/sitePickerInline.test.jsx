import { afterEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react'
import { createElement } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'

vi.mock('./api.js', () => ({
  getConfig: vi.fn(async () => ({ sharepoint_max_sites: 30 })),
  listSharePointSites: vi.fn(async () => ({ sites: [
    { id: 'site-clinical', name: 'Clinical', url: 'https://tenant.sharepoint.com/sites/clinical' },
  ] })),
  listSharePointDrives: vi.fn(async () => ({ drives: [
    { id: 'drive-documents', name: 'Documents' },
  ] })),
}))

const { default: SitePicker } = await import('./SitePicker.jsx')

afterEach(async () => { await unmountAll(); vi.clearAllMocks() })

async function settle() {
  await act(async () => { await Promise.resolve(); await Promise.resolve() })
}

describe('inline SharePoint site listing', () => {
  it('lists SharePoint sites in the scan wizard without the OneDrive root request', async () => {
    const changed = vi.fn()
    const { container, root } = createTestRoot()
    await act(async () => root.render(createElement(SitePicker, {
      layout: 'inline', initial: [], onChange: changed,
    })))
    await settle()

    expect(container.textContent).toContain('Clinical')
    expect(container.textContent).toContain('Select at least one SharePoint site')
    expect(container.querySelector('.setoverlay')).toBeNull()

    await act(async () => container.querySelector('input[type="checkbox"]').click())
    expect(changed).toHaveBeenLastCalledWith([{ id: 'site-clinical', name: 'Clinical' }])
    expect(container.textContent).toContain('1 SharePoint site selected')
    const scope = container.querySelector('[aria-label="Current scope"]')
    expect(scope.textContent).toContain('Clinical')
    expect(container.querySelector('.sp-picker__row.is-selected')).not.toBeNull()
    await act(async () => scope.querySelector('[aria-label="Remove Clinical"]').click())
    expect(changed).toHaveBeenLastCalledWith([])
    expect(container.querySelector('input[type="checkbox"]').checked).toBe(false)
  })

  it('lets the user inspect the document libraries before selecting a site', async () => {
    const { container, root } = createTestRoot()
    await act(async () => root.render(createElement(SitePicker, {
      layout: 'inline', initial: [], onChange: vi.fn(),
    })))
    await settle()
    await act(async () => [...container.querySelectorAll('button')]
      .find((button) => button.getAttribute('aria-label') === 'Show libraries on Clinical').click())
    await settle()
    expect(container.textContent).toContain('1 library: Documents')
    expect(container.querySelector('input[type="checkbox"]').checked).toBe(false)
    expect(container.querySelector('[aria-label="Current scope"]').textContent).toContain('Select at least one')
  })
  it('keeps named scope selections when search results change and clears them together', async () => {
    const { listSharePointSites } = await import('./api.js')
    const changed = vi.fn()
    const { container, root } = createTestRoot()
    await act(async () => root.render(createElement(SitePicker, {
      layout: 'inline', initial: [], onChange: changed,
    })))
    await settle()
    await act(async () => container.querySelector('input[type="checkbox"]').click())
    listSharePointSites.mockResolvedValueOnce({ sites: [] })
    const search = container.querySelector('input[type="search"]')
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(search, 'missing')
      search.dispatchEvent(new Event('input', { bubbles: true }))
    })
    await settle()
    expect(container.textContent).toContain('No site matches')
    expect(changed).toHaveBeenLastCalledWith([{ id: 'site-clinical', name: 'Clinical' }])
    const scope = container.querySelector('[aria-label="Current scope"]')
    expect(scope.textContent).toContain('Clinical')
    await act(async () => [...scope.querySelectorAll('button')].find(b => b.textContent === 'Clear all').click())
    expect(changed).toHaveBeenLastCalledWith([])
  })

})
