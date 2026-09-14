import { createElement } from 'react'
import { act } from 'react'
import { describe, it, expect, afterEach, vi } from 'vitest'
import axe from 'axe-core'
import { createTestRoot, unmountAll } from './testRoots.js'
import BalancedSummary, { ScanActivityCalendar } from './BalancedSummary.jsx'

globalThis.IS_REACT_ACT_ENVIRONMENT = true

const props = {
  run: { id: 'chosen', files: 2, scope: { scan_scope: { '1.3.1': true, '1.1.1': true }, inventory: { discovered: 2, assessment_eligible: 2, by_format: { docx: 2 } } } },
  files: [{ file: 'finance.docx', type: 'DOCX', score: 45, status: 'analysed', department: 'Finance', issues: [{ wcag: '1.3.1', severity: 'SERIOUS' }, { wcag: '1.1.1', severity: 'MODERATE', has_proposal: true }] }],
  cap: { docx: { '1.3.1': 'auto', '1.1.1': 'assisted' } },
}
const render = async (p = props) => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(BalancedSummary, p)))
  return { root, container }
}
afterEach(unmountAll)

describe('balanced summary approved dashboard', () => {
  it('renders the five selected charts with real Assess/Remediate tags, not severity columns', async () => {
    const { container: c } = await render()
    expect([...c.querySelectorAll('.balanced-grid h2')].map(h => h.textContent)).toEqual(['Estate coverage by file type', 'Document formats', 'Remediation opportunities', 'Finding categories', 'Human review age'])
    expect(c.querySelector('.balanced-heatmap').textContent).toContain('Auto')
    expect(c.querySelector('.balanced-heatmap').textContent).toContain('Approve')
    expect(c.querySelector('.balanced-heatmap').textContent).not.toContain('Serious')
    expect(c.querySelector('.balanced-review').textContent).toContain('Not recorded')
    expect(c.querySelectorAll('table')).toHaveLength(5)
  })
  it('opens the exact contributing findings from a department/tag cell and clears details on scan change', async () => {
    const { root, container: c } = await render()
    await act(async () => c.querySelector('[aria-label="Finance, Auto: 1 findings"]').click())
    expect(c.querySelector('.balanced-evidence').textContent).toContain('finance.docx')
    expect(c.querySelector('.balanced-evidence').textContent).toContain('1.3.1')
    expect(c.querySelector('.balanced-evidence').textContent).not.toContain('1.1.1')
    await act(async () => root.render(createElement(BalancedSummary, { ...props, run: { id: 'other' }, files: [] })))
    expect(c.querySelector('.balanced-evidence')).toBeNull()
    expect(c.querySelector('.balanced-findings').textContent).toContain('not available')
  })
  it('has keyboard-operable charts and accessible table semantics', async () => {
    const { container: c } = await render()
    expect(c.querySelector('.balanced-tile').tagName).toBe('BUTTON')
    const result = await axe.run(c, { rules: { 'color-contrast': { enabled: false }, region: { enabled: false } } })
    expect(result.violations.map(v => ({ id: v.id, nodes: v.nodes.map(n => n.html) }))).toEqual([])
  })
  it('puts the activity calendar alongside all selected-scan charts and preserves UTC drill-down values', async () => {
    const onDay = vi.fn(), day = { date: '2026-09-14', attempts: 22, statuses: { done: 19, failed: 3 } }
    const { container: c } = await render({ ...props, calendar: createElement(ScanActivityCalendar, { activity: [day], onDay }) })
    expect(c.querySelectorAll('.balanced-grid h2')).toHaveLength(6)
    expect(c.textContent).toContain('selected scan chosen')
    expect(c.textContent).toContain('22 dated attempts')
    await act(async () => c.querySelector('[aria-label="2026-09-14: 22 attempts. Show matching scans"]').click())
    expect(onDay).toHaveBeenCalledWith(day)
    expect(c.querySelector('[aria-label="2026-09-13: no activity row recorded"]').textContent).toContain('—')
  })
  it('renders missing assessment results as unknown rather than measured zero findings', async () => {
    const { container: c } = await render({ run: { id: 'discovery', files: 1 }, files: [{ file: 'waiting.docx', type: 'DOCX', status: 'discovered', score: null, issues: [] }] })
    const tile = [...c.querySelectorAll('.balanced-metric')].find(t => t.textContent.includes('Total findings'))
    expect(tile.querySelector('strong').textContent).toBe('—')
    expect(c.querySelector('.balanced-remediation').textContent).toContain('not produced findings')
  })
})
