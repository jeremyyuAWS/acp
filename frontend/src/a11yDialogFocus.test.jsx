import { readFileSync } from 'node:fs'
import { createElement, useRef } from 'react'
import { act } from 'react-dom/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import { ACCOUNT_MENU_DISMISS_MS, useAutoDismissDetails, useDialog } from './a11y.js'

afterEach(() => { vi.useRealTimers(); unmountAll() })

function Dialog({ tick, onClose }) {
  const ref = useRef(null)
  useDialog(ref, onClose)
  return <div ref={ref} tabIndex={-1}><button>First</button><input aria-label="Confirmation" value={tick} readOnly /></div>
}

function AccountMenu({ visible = true }) {
  const ref = useRef(null)
  useAutoDismissDetails(ref, ACCOUNT_MENU_DISMISS_MS)
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

  it('dismisses an idle account panel after two seconds', async () => {
    vi.useFakeTimers()
    const { container, root } = createTestRoot()
    await act(async () => root.render(createElement(AccountMenu)))
    const details = container.querySelector('details')
    await act(async () => { details.open = true; details.dispatchEvent(new Event('toggle')) })
    await act(async () => vi.advanceTimersByTime(1999))
    expect(details.open).toBe(true)
    await act(async () => vi.advanceTimersByTime(1))
    expect(details.open).toBe(false)
  })

  it('dismisses after two idle seconds even with a stationary pointer over the panel', async () => {
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
  await act(async()=>vi.advanceTimersByTime(2000))
  expect(details.open).toBe(false)
})

it('uses the two-second delay in the live account menu', () => {
  expect(ACCOUNT_MENU_DISMISS_MS).toBe(2000)
  const app = readFileSync('src/App.jsx', 'utf8')
  expect(app).toContain('useAutoDismissDetails(accountMenuRef, ACCOUNT_MENU_DISMISS_MS)')
})
