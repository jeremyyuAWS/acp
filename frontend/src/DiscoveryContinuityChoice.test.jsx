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
    .find((button) => button.textContent === 'Start revised Discovery')
  act(() => replace.click())
  expect(onReplace).toHaveBeenCalledOnce()
})

it('explains why an exact recent workflow should be continued', () => {
  const { container, root } = createTestRoot()
  act(() => root.render(<DiscoveryContinuityChoice
    choice={{ scanId: 'scan-one', workflowRevision: 2, recentCompatible: true }}
    onContinue={() => {}} onReplace={() => {}} onDismiss={() => {}} />))
  expect(container.textContent).toContain('A matching workflow just ran')
  expect(container.textContent).toContain('source, folders, settings, and lifecycle policy match')
  expect(container.textContent).toContain('Workflow revision 2')
  expect(container.textContent).toContain('Start revised Discovery')
})

it('names an active Assessment and requires explicit cancellation before a new Discovery', () => {
  const onReplace = vi.fn()
  const { container, root } = createTestRoot()
  act(() => root.render(<DiscoveryContinuityChoice
    choice={{ scanId: 'scan-assess', workflowRevision: 4, activeStage: 'assess' }}
    onContinue={() => {}} onReplace={onReplace} onDismiss={() => {}} />))

  expect(container.textContent).toContain('Assessment is already running')
  expect(container.textContent).toContain('Continue current Assessment')
  const replace = [...container.querySelectorAll('button')]
    .find((button) => button.textContent === 'Cancel Assessment and start new Discovery')
  expect(replace).toBeTruthy()
  act(() => replace.click())
  expect(onReplace).toHaveBeenCalledOnce()
})
