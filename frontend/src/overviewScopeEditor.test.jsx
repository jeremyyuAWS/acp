/**
 * Overview keeps one audit-grade scope disclosure immediately below Estate progress.
 * The compact AssessmentScopeCard is intentionally absent here because it duplicated
 * AssertionScope. It remains mounted on Remediate, where its reassessment controls belong.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

vi.mock('./api.js', async (importActual) => ({
  ...(await importActual()),
  getSettings: async () => ({ scan_scope: '' }),
  updateSettings: async () => ({}),
  getScanDiff: async () => null,
}))

const { default: Overview } = await import('./Overview.jsx')
const RUN = { id: 'scan-1', certifiable: 1, scope: null, at: '2026-08-08T00:00:00Z' }
const FILES = [{ name: 'a.docx', score: 90, issues: [], department: 'Legal', format: 'docx' }]

async function render() {
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(Overview, {
      run: RUN, files: FILES, trend: [], trendDates: [], onGo: () => {},
      scanList: [RUN], onPickScan: () => {}, me: { email: 'a@b.com' }, onScan: vi.fn(),
    }))
  })
  return container
}

describe('the single Overview scope disclosure', () => {
  it('uses the existing AssertionScope, collapsed by default', async () => {
    const c = await render()
    const scope = c.querySelector('[data-accordion="assertion-scope"]')
    expect(scope).toBeTruthy()
    expect(scope.querySelector('.acc-title').textContent).toBe('SCOPE OF THIS ASSERTION')
    expect(scope.querySelector('button.acc-toggle').getAttribute('aria-expanded')).toBe('false')
  })

  it('sits immediately after Estate progress', async () => {
    const c = await render()
    const estate = c.querySelector('[data-accordion="estate-progress"]')
    const scope = c.querySelector('[data-accordion="assertion-scope"]')
    expect(estate.nextElementSibling).toBe(scope)
  })

  it('does not mount the redundant compact scope card or editable scope controls', async () => {
    const c = await render()
    expect(c.querySelector('[role="note"].scope-card')).toBeNull()
    expect(c.querySelector('[role="radio"]')).toBeNull()
    expect(c.textContent).not.toContain('Scope used for this assessment')
  })

  it('reveals the existing assertion details through its native control', async () => {
    const c = await render()
    const scope = c.querySelector('[data-accordion="assertion-scope"]')
    await act(async () => { scope.querySelector('button.acc-toggle').click() })
    expect(scope.textContent).toContain('Document types')
    expect(scope.textContent).toContain('Criteria')
  })
})
