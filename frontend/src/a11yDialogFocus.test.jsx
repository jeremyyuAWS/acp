import { createElement, useRef } from 'react'
import { act } from 'react-dom/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import { useAutoDismissDetails, useDialog } from './a11y.js'

afterEach(() => { vi.useRealTimers(); unmountAll() })

function Dialog({ tick, onClose }) {
  const ref = useRef(null)
  useDialog(ref, onClose)
  return <div ref={ref} tabIndex={-1}><button>First</button><input aria-label="Confirmation" value={tick} readOnly /></div>
}

function AccountMenu() {
  const ref = useRef(null)
  useAutoDismissDetails(ref, 5000)
  return <details ref={ref}><summary>Account</summary><div className="header-menu-panel"><button>Settings</button></div></details>
}

describe('stable dialog focus', () => {
  it('does not steal focus again when a parent refresh recreates onClose', async () => {
    const { container, root } = createTestRoot()
    await act(async () => root.render(createElement(Dialog, { tick: 'R', onClose: () => {} })))
    const input = container.querySelector('input')
    input.focus()
    await act(async () => root.render(createElement(Dialog, { tick: 'RE', onClose: () => {} })))
    expect(document.activeElement).toBe(input)
  })

  it('dismisses an idle account panel after five seconds', async () => {
    vi.useFakeTimers()
    const { container, root } = createTestRoot()
    await act(async () => root.render(createElement(AccountMenu)))
    const details = container.querySelector('details')
    await act(async () => { details.open = true; details.dispatchEvent(new Event('toggle')) })
    await act(async () => vi.advanceTimersByTime(5000))
    expect(details.open).toBe(false)
  })

  it('does not dismiss while the user is interacting with the panel', async () => {
    vi.useFakeTimers()
    const { container, root } = createTestRoot()
    await act(async () => root.render(createElement(AccountMenu)))
    const details = container.querySelector('details')
    await act(async () => { details.open = true; details.dispatchEvent(new Event('toggle')) })
    details.dispatchEvent(new Event('pointerenter'))
    await act(async () => vi.advanceTimersByTime(6000))
    expect(details.open).toBe(true)
  })
})
