// @vitest-environment jsdom
import React from 'react'
import { act } from 'react-dom/test-utils'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import DiscoveryContinuityChoice from './DiscoveryContinuityChoice.jsx'

afterEach(unmountAll)

it('makes continuing the active workflow the primary safe action', () => {
  const onContinue = vi.fn()
  const onReplace = vi.fn()
  const { container, root } = createTestRoot()
  act(() => root.render(<DiscoveryContinuityChoice
    choice={{ scanId: 'scan-123' }} onContinue={onContinue}
    onReplace={onReplace} onDismiss={() => {}} />))

  expect(container.textContent).toContain('Discovery is already running')
  expect(container.textContent).toContain('Scan scan-123')
  const buttons = [...container.querySelectorAll('button')]
  expect(buttons[0].textContent).toBe('Continue current Discovery')
  act(() => buttons[0].click())
  expect(onContinue).toHaveBeenCalledOnce()
  expect(onReplace).not.toHaveBeenCalled()
})

it('requires a separately labelled replacement action', () => {
  const onReplace = vi.fn()
  const { container, root } = createTestRoot()
  act(() => root.render(<DiscoveryContinuityChoice
    choice={{ scanId: 'scan-456' }} onContinue={() => {}}
    onReplace={onReplace} onDismiss={() => {}} />))
  const replace = [...container.querySelectorAll('button')]
    .find((button) => button.textContent === 'Replace with new revision')
  act(() => replace.click())
  expect(onReplace).toHaveBeenCalledOnce()
})
