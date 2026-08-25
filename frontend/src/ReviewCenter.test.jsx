/**
 * I.2 — ReviewCenter previously swallowed all errors from bulk/keyboard approvals.
 *
 * Root cause: doAct() used .catch(() => {}) so any rejection from onAct (e.g. a 401
 * SESSION_EXPIRED after a Google token expiry) was silently discarded. The card collapsed
 * as if the approval succeeded even though nothing was recorded server-side.
 *
 * Fix: doAct() and approveGroup() now show an inline error banner when onAct rejects,
 * matching the pattern EvidenceCard.decide() already used correctly.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

const { default: ReviewCenter } = await import('./ReviewCenter.jsx')

const ITEM = {
  id: 'q1',
  status: 'pending',
  rule_id: '1.1.1',
  file: 'report.pdf',
  proposals: [],
  finding_count: 1,
}

let container, root

const render = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => {
    root.render(
      createElement(ReviewCenter, {
        items: [ITEM],
        onAct: () => Promise.resolve(),
        onClose: () => {},
        onRefresh: () => {},
        ...props,
      })
    )
  })
}

const click = async (el) => {
  await act(async () => { el.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
}

const btnByText = (t) =>
  [...container.querySelectorAll('button')].find((b) => b.textContent.includes(t))

describe('ReviewCenter — approval error display', () => {
  it('shows an error banner when a bulk approval fails', async () => {
    const onAct = vi.fn(() => Promise.reject(new Error('401 SESSION_EXPIRED')))
    await render({ onAct })

    // Expand the item so the keyboard approve path runs via doAct
    const row = container.querySelector('.rc-item-row')
    await click(row)

    // Dispatch keyboard 'a' to trigger doAct via keyboard handler
    await act(async () => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }))
    })
    // Wait for the async doAct promise to settle
    await act(async () => {})

    const alert = container.querySelector('[role="alert"]')
    expect(alert).toBeTruthy()
    expect(alert.textContent).toContain('Not saved')
    expect(alert.textContent).toContain('401 SESSION_EXPIRED')
  })

  it('clears the error banner when Dismiss is clicked', async () => {
    const onAct = vi.fn(() => Promise.reject(new Error('network error')))
    await render({ onAct })

    await act(async () => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }))
    })
    await act(async () => {})

    expect(container.querySelector('[role="alert"]')).toBeTruthy()

    const dismiss = btnByText('Dismiss')
    await click(dismiss)

    expect(container.querySelector('[role="alert"]')).toBeFalsy()
  })

  it('shows no error banner when the approval succeeds', async () => {
    const onAct = vi.fn(() => Promise.resolve())
    await render({ onAct })

    await act(async () => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'a', bubbles: true }))
    })
    await act(async () => {})

    expect(container.querySelector('[role="alert"]')).toBeFalsy()
  })
})
