import { act } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import SignIn from './SignIn.jsx'
vi.mock('./api.js', () => ({ getConfig: vi.fn(async () => ({ auth: 'gis' })), setLangfuseBase: vi.fn() }))
afterEach(unmountAll)
globalThis.IS_REACT_ACT_ENVIRONMENT = true
it('avoids unsupported retention promises and announces a recoverable sign-in error', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(<SignIn onSignedIn={vi.fn()} />))
  expect(container.textContent).not.toContain('documents never retained')
  expect(container.textContent).toContain('Discovery reads metadata only')
  const button = [...container.querySelectorAll('button')].find(b => b.textContent.includes('Sign in with Google'))
  await act(async () => button.click())
  expect(container.querySelector('[role="alert"]')?.textContent).toContain('please refresh')
  expect(button.disabled).toBe(false)
})
