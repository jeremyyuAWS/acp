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

function AccountMenu({ visible = true }) {
  const ref = useRef(null)
  useAutoDismissDetails(ref, 3000)
  return visible ? <details ref={ref}><summary>Account</summary><div className="header-menu-panel"><button>Settings</button></div></details> : null
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

  it('dismisses an idle account panel after three seconds', async () => {
    vi.useFakeTimers()
    const { container, root } = createTestRoot()
    await act(async () => root.render(createElement(AccountMenu)))
    const details = container.querySelector('details')
    await act(async () => { details.open = true; details.dispatchEvent(new Event('toggle')) })
    await act(async () => vi.advanceTimersByTime(2999))
    expect(details.open).toBe(true)
    await act(async () => vi.advanceTimersByTime(1))
    expect(details.open).toBe(false)
  })

  it('dismisses after three idle seconds even with a stationary pointer over the panel', async () => {
    vi.useFakeTimers()
    const { container, root } = createTestRoot()
    await act(async () => root.render(createElement(AccountMenu)))
    const details = container.querySelector('details')
    await act(async () => { details.open = true; details.dispatchEvent(new Event('toggle')) })
    details.dispatchEvent(new Event('pointerenter'))
    await act(async () => vi.advanceTimersByTime(6000))
    expect(details.open).toBe(false)
  })
})


it('attaches when authentication mounts the menu later and does not reset on refresh', async () => {
  vi.useFakeTimers()
  const {container,root}=createTestRoot()
  await act(async()=>root.render(<AccountMenu visible={false} />))
  await act(async()=>root.render(<AccountMenu />))
  const details=container.querySelector('details')
  await act(async()=>{details.open=true;details.dispatchEvent(new Event('toggle'))})
  await act(async()=>vi.advanceTimersByTime(1000))
  await act(async()=>root.render(<AccountMenu />))
  await act(async()=>vi.advanceTimersByTime(2000))
  expect(details.open).toBe(false)
})
it('keeps keyboard controls available until focus leaves the panel', async () => {
  vi.useFakeTimers()
  const {container,root}=createTestRoot()
  await act(async()=>root.render(<AccountMenu />))
  const details=container.querySelector('details')
  await act(async()=>{details.open=true;details.dispatchEvent(new Event('toggle'));container.querySelector('button').focus()})
  await act(async()=>vi.advanceTimersByTime(6000))
  expect(details.open).toBe(true)
  await act(async()=>container.querySelector('summary').focus())
  await act(async()=>vi.advanceTimersByTime(3000))
  expect(details.open).toBe(false)
})
