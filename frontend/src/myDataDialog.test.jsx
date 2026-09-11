import { describe, it, expect, vi, afterEach } from 'vitest'
import { act } from 'react'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { createTestRoot, unmountAll } from './testRoots.js'
const reset = vi.hoisted(() => vi.fn(async () => ({ owner: 'me@example.com', cleared_tables: [] })))
vi.mock('./api.js', () => ({ resetMyData: reset }))
import MyDataDialog from './MyDataDialog.jsx'
afterEach(() => { unmountAll(); reset.mockClear(); vi.restoreAllMocks() })
describe('personal data outside administrative Settings', () => {
  it('offers only the caller-scoped reset without an admin role', async () => {
    const { container, root } = createTestRoot()
    await act(async () => root.render(<MyDataDialog onClose={() => {}} />))
    expect(container.querySelector('[role="dialog"]').getAttribute('aria-label')).toBe('My data')
    expect(container.querySelector('[role="tablist"]')).toBeNull()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const button = [...container.querySelectorAll('button')].find((b) => /Reset my/.test(b.textContent))
    expect(button.disabled).toBe(false)
    await act(async () => button.click())
    expect(reset).toHaveBeenCalledWith()
  })
  it('exposes My data independently of the Settings role gate', () => {
    const app = readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'App.jsx'), 'utf8')
    expect(app).toContain('<button className="menu-action" onClick={() => setMyDataOpen(true)}>Reset my data</button>')
    expect(app).toContain('{myDataOpen && <MyDataDialog')
  })
})
