import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

const { default: ProcessHealthAlert } = await import('./ProcessHealthAlert.jsx')

async function render(props) {
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(ProcessHealthAlert, props))
  })
  return container
}

describe('ProcessHealthAlert', () => {
  describe('role="alert" on all four levels', () => {
    for (const level of ['critical', 'warning', 'info', 'recovered']) {
      it(`renders role="alert" for level="${level}"`, async () => {
        const c = await render({ level, title: 'Test title' })
        expect(c.querySelector('[role="alert"]')).toBeTruthy()
      })
    }
  })

  describe('content rendering', () => {
    it('shows the title text', async () => {
      const c = await render({ level: 'info', title: 'Something went wrong' })
      expect(c.textContent).toContain('Something went wrong')
    })

    it('shows the description when provided', async () => {
      const c = await render({
        level: 'warning',
        title: 'Degraded',
        description: 'The service is running slowly.',
      })
      expect(c.textContent).toContain('The service is running slowly.')
    })

    it('omits the description element when not provided', async () => {
      const c = await render({ level: 'info', title: 'All good' })
      expect(c.querySelector('p')).toBeFalsy()
    })
  })

  describe('level label text', () => {
    it('shows CRITICAL label', async () => {
      const c = await render({ level: 'critical', title: 'x' })
      expect(c.textContent).toContain('CRITICAL')
    })

    it('shows WARNING label', async () => {
      const c = await render({ level: 'warning', title: 'x' })
      expect(c.textContent).toContain('WARNING')
    })

    it('shows INFORMATION label', async () => {
      const c = await render({ level: 'info', title: 'x' })
      expect(c.textContent).toContain('INFORMATION')
    })

    it('shows RECOVERED label', async () => {
      const c = await render({ level: 'recovered', title: 'x' })
      expect(c.textContent).toContain('RECOVERED')
    })
  })

  describe('action buttons', () => {
    it('renders action buttons when provided', async () => {
      const c = await render({
        level: 'critical',
        title: 'Outage',
        actions: [{ label: 'Retry', onClick: () => {} }, { label: 'Dismiss', onClick: () => {} }],
      })
      const buttons = c.querySelectorAll('button')
      expect(buttons.length).toBe(2)
      expect(buttons[0].textContent).toBe('Retry')
      expect(buttons[1].textContent).toBe('Dismiss')
    })

    it('calls onClick when an action button is clicked', async () => {
      const onClick = vi.fn()
      const c = await render({
        level: 'warning',
        title: 'Slow',
        actions: [{ label: 'Fix it', onClick }],
      })
      c.querySelector('button').click()
      expect(onClick).toHaveBeenCalledOnce()
    })

    it('renders no buttons when actions are not provided', async () => {
      const c = await render({ level: 'recovered', title: 'Back online' })
      expect(c.querySelectorAll('button').length).toBe(0)
    })

    it('renders no buttons when actions array is empty', async () => {
      const c = await render({ level: 'info', title: 'Notice', actions: [] })
      expect(c.querySelectorAll('button').length).toBe(0)
    })
  })
})
