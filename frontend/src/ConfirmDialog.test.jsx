import React, { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import ConfirmDialog, { confirm } from './ConfirmDialog.jsx'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

describe('ConfirmDialog toast presentation', () => {
  let host
  let root

  beforeEach(() => {
    host = document.createElement('div')
    document.body.appendChild(host)
    root = createRoot(host)
    act(() => root.render(<ConfirmDialog />))
  })

  afterEach(() => {
    act(() => root.unmount())
    host.remove()
  })

  it('shows an actionable, non-modal toast and resolves from its action', async () => {
    let answer
    await act(async () => {
      answer = confirm({
        title: 'Enable "Last 30 days"?',
        message: 'Enabling adds recommendations only; it never moves source files.',
        facts: [{ label: 'Files currently in scope', value: '0 files' }],
        presentation: 'toast',
        variant: 'activation',
        confirmLabel: 'Enable rule',
      })
    })

    const toast = host.querySelector('[role="alertdialog"]')
    expect(toast).not.toBeNull()
    expect(toast.getAttribute('aria-modal')).toBe('false')
    expect(toast.textContent).toContain('Files currently in scope')
    expect(toast.textContent).toContain('never moves source files')
    expect(host.querySelector('[role="dialog"]')).toBeNull()

    await act(async () => {
      [...host.querySelectorAll('button')].find((button) => button.textContent === 'Enable rule').click()
    })
    await expect(answer).resolves.toBe(true)
    expect(host.querySelector('[role="alertdialog"]')).toBeNull()
  })
})
