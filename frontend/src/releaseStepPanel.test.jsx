import React from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act } from 'react-dom/test-utils'
import { createRoot } from 'react-dom/client'
import ReleaseStepPanel from './ReleaseStepPanel.jsx'

describe('ReleaseStepPanel', () => {
  let container
  let root

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
    vi.stubGlobal('requestAnimationFrame', (callback) => { callback(); return 1 })
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
  })

  afterEach(async () => {
    await act(async () => root.unmount())
    container.remove()
    vi.unstubAllGlobals()
  })

  it('exposes a named group without stealing focus on the initial step', async () => {
    const before = document.createElement('button')
    document.body.prepend(before)
    before.focus()

    await act(async () => root.render(
      <ReleaseStepPanel id="release-files" heading="Choose files">
        <button>Choose delivery</button>
      </ReleaseStepPanel>,
    ))

    const panel = container.querySelector('#release-files')
    expect(panel.getAttribute('role')).toBe('group')
    expect(panel.getAttribute('aria-labelledby')).toBe('release-files-heading')
    expect(document.activeElement).toBe(before)
    before.remove()
  })

  it('moves focus to a newly opened step after an operator action', async () => {
    await act(async () => root.render(
      <ReleaseStepPanel id="release-delivery" heading="Choose delivery" focusOnMount>
        <button>Review release</button>
      </ReleaseStepPanel>,
    ))

    expect(document.activeElement).toBe(container.querySelector('#release-delivery'))
    expect(document.activeElement.getAttribute('tabindex')).toBe('-1')
    expect(container.querySelector('#release-delivery-heading').textContent).toBe('Choose delivery')
  })

  it('cancels a pending focus handoff if the step unmounts', async () => {
    let callback
    const cancel = vi.fn()
    vi.stubGlobal('requestAnimationFrame', (next) => { callback = next; return 42 })
    vi.stubGlobal('cancelAnimationFrame', cancel)

    await act(async () => root.render(
      <ReleaseStepPanel id="release-review" heading="Review" focusOnMount />,
    ))
    await act(async () => root.render(<div />))

    expect(cancel).toHaveBeenCalledWith(42)
    callback()
    expect(document.activeElement).not.toBe(container.querySelector('#release-review'))
  })
})
