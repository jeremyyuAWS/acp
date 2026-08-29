import { describe, it, expect, afterEach } from 'vitest'
import { createElement, act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'
import QueueJobDetails from './QueueJobDetails.jsx'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

let container, root
const mount = async (props) => {
  ;({ container, root } = createTestRoot())
  await act(async () => { root.render(createElement(QueueJobDetails, props)) })
  return container
}
afterEach(unmountAll)

describe('QueueJobDetails', () => {
  it('renders nothing with no jobId and no attempts data', async () => {
    const c = await mount({ jobId: null, attempts: null, maxAttempts: null })
    expect(c.textContent).toBe('')
  })

  it('renders collapsed by default, showing only the toggle', async () => {
    const c = await mount({ jobId: 'job-abcdef', attempts: 0, maxAttempts: 5 })
    expect(c.textContent).toMatch(/Processing details/)
    expect(c.textContent).not.toMatch(/Attempt/)
  })

  it('expands to show attempt count (1-indexed) against its ceiling, and a truncated job id', async () => {
    const c = await mount({ jobId: 'job-abcdef', attempts: 2, maxAttempts: 5 })
    const btn = c.querySelector('button')
    await act(async () => { btn.click() })
    expect(c.textContent).toMatch(/Attempt 3 of 5/)
    expect(c.textContent).toMatch(/Job ID …abcdef/)
    expect(btn.getAttribute('aria-expanded')).toBe('true')
  })

  it('collapses again on a second click', async () => {
    const c = await mount({ jobId: 'job-abcdef', attempts: 0, maxAttempts: 5 })
    const btn = c.querySelector('button')
    await act(async () => { btn.click() })
    expect(c.textContent).toMatch(/Attempt/)
    await act(async () => { btn.click() })
    expect(c.textContent).not.toMatch(/Attempt/)
    expect(btn.getAttribute('aria-expanded')).toBe('false')
  })

  it('shows the job id alone when attempts/max_attempts are absent (e.g. SIM mode)', async () => {
    const c = await mount({ jobId: 'job-abcdef', attempts: null, maxAttempts: null })
    const btn = c.querySelector('button')
    await act(async () => { btn.click() })
    expect(c.textContent).toMatch(/Job ID …abcdef/)
    expect(c.textContent).not.toMatch(/Attempt/)
  })

  it('shows attempts alone when there is no jobId', async () => {
    const c = await mount({ jobId: null, attempts: 1, maxAttempts: 5 })
    const btn = c.querySelector('button')
    await act(async () => { btn.click() })
    expect(c.textContent).toMatch(/Attempt 2 of 5/)
    expect(c.textContent).not.toMatch(/Job ID/)
  })

  it('never claims raw queue priority — the design review keeps that admin-only', async () => {
    const c = await mount({ jobId: 'job-abcdef', attempts: 0, maxAttempts: 5 })
    const btn = c.querySelector('button')
    await act(async () => { btn.click() })
    expect(c.textContent.toLowerCase()).not.toMatch(/priority/)
  })
})
