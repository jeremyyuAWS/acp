/**
 * The Overview tab shows a compact, read-only scope card instead of the full editable ScanSetup.
 *
 * The full editable form (AssessSetup.jsx) lives on the Assess tab, where the operator makes the
 * scope decision before starting a run. Keeping it on the Overview (results) screen forced a
 * configuration interface onto a reporting surface — the two purposes competed for the top of
 * the page. The compact card satisfies both needs: it records what was in scope for reconciling
 * counts, and it offers a "Change scope and reassess" link when rescanning is available.
 *
 * Deliberately tests the ASSESSED state, because the pre-scan case was never broken and testing
 * it would pass against a regression.
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

async function render(props = {}) {
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(Overview, {
      run: RUN, files: FILES, trend: [], trendDates: [], onGo: () => {},
      scanList: [RUN], onPickScan: () => {}, me: { email: 'a@b.com' }, ...props,
    }))
  })
  return container
}

// The scope card is role="note" per AssessmentScopeCard.jsx.
const scopeCard = (c) => c.querySelector('[role="note"].scope-card')

describe('Assessment scope on the Overview tab', () => {
  it('shows the compact scope card (not the full editable ScanSetup)', async () => {
    const c = await render({ onScan: vi.fn() })
    expect(scopeCard(c), 'scope card missing from Overview').toBeTruthy()
    // The old full editor contained profile radio buttons — those must NOT appear here.
    expect(c.querySelector('[role="radio"]'), 'editable profile radios must not appear on results screen').toBeFalsy()
  })

  it('shows "Change scope and reassess" when rescanning is available', async () => {
    const c = await render({ onScan: vi.fn() })
    const btns = [...c.querySelectorAll('button')]
    const changeBtn = btns.find((b) => /change scope/i.test(b.textContent))
    expect(changeBtn, 'no "Change scope and reassess" button when onScan is provided').toBeTruthy()
  })

  it('navigates to the Assess tab when "Change scope and reassess" is clicked', async () => {
    const onGo = vi.fn()
    const c = await render({ onScan: vi.fn(), onGo })
    const btns = [...c.querySelectorAll('button')]
    const changeBtn = btns.find((b) => /change scope/i.test(b.textContent))
    await act(async () => { changeBtn.click() })
    expect(onGo).toHaveBeenCalledWith('assess')
  })

  it('hides "Change scope and reassess" when no onScan is provided', async () => {
    const c = await render({ onScan: undefined })
    const btns = [...c.querySelectorAll('button')]
    const changeBtn = btns.find((b) => /change scope/i.test(b.textContent))
    expect(changeBtn, '"Change scope" button must not appear when rescanning is not available').toBeFalsy()
  })

  it('still shows the scope card even without onScan — it is a read-only record', async () => {
    const c = await render({ onScan: undefined })
    expect(scopeCard(c), 'scope card should show as a read-only record even without onScan').toBeTruthy()
  })

  it('shows the scope summary line (WCAG level · criteria count)', async () => {
    const c = await render({ onScan: vi.fn() })
    const card = scopeCard(c)
    // The card always names the standard: "WCAG 2.1 AA"
    expect(card?.textContent).toMatch(/WCAG 2\.1 AA/)
    // And shows N of 17 (or whatever SCOPE_SIZE / total is).
    expect(card?.textContent).toMatch(/\d+ of \d+ criteria/)
  })
})
