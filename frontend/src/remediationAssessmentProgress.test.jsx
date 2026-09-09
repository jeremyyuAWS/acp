import { it, expect, vi, afterEach } from 'vitest'
import { act } from 'react'
import axe from 'axe-core'
import { createTestRoot, unmountAll } from './testRoots.js'
import Progress, { findingMath, automaticResolved } from './RemediationAssessmentProgress.jsx'
import { assessMetrics } from './assessMetrics.js'
import { getFindingDispositions } from './api.js'
vi.mock('./api.js', () => ({ getFindingDispositions: vi.fn() }))
afterEach(async () => { await unmountAll(); vi.clearAllMocks(); vi.useRealTimers() })
const context = {
  files: [{ file: 'a.docx', status: 'analysed', issues: ['1.3.1','1.3.1','1.1.1'].map(sc => ({ wcag: `SC_${sc.replaceAll('.', '_')}`, severity: 'SERIOUS' })) }],
  cap: { docx: { '1.3.1': 'auto', '1.1.1': 'assisted' } },
  assessment: { docx: { '1.3.1': 'auto' } }, criteria: new Set(['1.3.1','1.1.1']),
}
const original = [{ file: 'a.docx', rule_id: 'SC_1_3_1', finding_count: 2, fix_mode: 'auto' }, { file: 'a.docx', rule_id: 'SC_1_1_1', finding_count: 1, fix_mode: 'assisted' }]
const rec = { original_assessment: original, exact: true, assessed: 3, resolved_verified: 0, awaiting_review: 1, approved_pending_verification: 0, unchanged_no_fix: 2, failed: 0, excluded: 0, superseded: 0 }
const snap = r => ({ scan_id: 's', batch_id: 'b', finding_reconciliation: { ...rec, ...r }, fixes: { verified: 339 }, review: { items: 1 }, documents: { processing: 0 } })
const item = (id, rule = '1.3.1') => ({ finding_id: id, file: 'a.docx', rule_id: `SC_${rule.replaceAll('.', '_')}`, verified_at: '2026-09-09' })
async function mount(snapshot = snap(), ctx = context) {
  const { root, container } = createTestRoot()
  const render = async (next = snapshot, identity = 's:b', paused = false) => act(async () => root.render(<Progress snapshot={next} assessmentContext={ctx} identity={identity} paused={paused} />))
  await render()
  return { container, render }
}
it('keeps the screenshot units separate: 339 changes cannot drain a 330 automatic finding baseline', () => {
  const result = findingMath(snap({ assessed: 920, unchanged_no_fix: 919 }))
  expect(result).toMatchObject({ exact: true, total: 920, fixed: 0, remaining: 920 })
  expect(findingMath(snap({ resolved_verified: 339 })).exact).toBe(false)
})
it('shows readable original, current and outcome equations and clickable unfinished checks', async () => {
  const { container } = await mount()
  expect(container.textContent).toContain('0 fixed + 3 not yet verified fixed = 3 starting findings')
  expect(container.textContent).toContain('2 automatic + 1 other = 3 findings')
  expect(container.textContent).toContain('1 + 0 + 2 + 0 + 0 + 0 = 3')
  expect(container.textContent).toContain('339')
  await act(async () => container.querySelector('button[aria-controls]').click())
  expect(container.querySelectorAll('tbody tr')).toHaveLength(1)
  expect(container.textContent).toContain('WCAG 1.1.1')
  const result = await axe.run(container, { rules: { 'color-contrast': { enabled: false } } })
  expect(result.violations).toEqual([])
})
it('drains only matching verified original findings and freezes the starting automatic count', async () => {
  getFindingDispositions.mockResolvedValue({ available: true, batch_id: 'b', items: [item('one')] })
  const { container, render } = await mount()
  await render(snap({ resolved_verified: 1, unchanged_no_fix: 1 }))
  expect(container.textContent).toContain('1 fixed + 2 not yet verified fixed = 3 starting findings')
  expect(container.textContent).toContain('2 originally eligible · 1 verified resolved')
  expect(container.querySelector('progress').value).toBe(1)
  expect(container.querySelector('progress').max).toBe(2)
  expect(container.textContent).toContain('Remaining: 1 automatic + 1 other = 2 findings')
  expect([...container.querySelectorAll('.rap-tile')].find(tile => tile.textContent.startsWith('Automatic fixes remaining')).querySelector('.wf-delta').textContent).toBe('−1')
})
it('rejects duplicate, unverified, out-of-scope and excess finding links', () => {
  const metrics = assessMetrics(context.files, context)
  expect(automaticResolved(metrics, [item('a'), item('b', '1.1.1')], 2)).toBe(1)
  expect(automaticResolved(metrics, [item('a'), item('a')], 2)).toBeNull()
  expect(automaticResolved(metrics, [{ ...item('a'), verified_at: null }], 1)).toBeNull()
  expect(automaticResolved(metrics, [{ ...item('a'), file: 'other.docx' }], 1)).toBeNull()
  expect(automaticResolved(metrics, [item('a'), item('b'), item('c')], 3)).toBeNull()
  expect(automaticResolved(metrics, [item('a')], 2)).toBeNull()
})
it('does not invent a split for mismatched populations or incomplete outcomes', async () => {
  const { container } = await mount(snap({ exact: false, assessed: 100 }))
  expect(container.textContent).toContain('outcome breakdown unavailable')
  expect(container.textContent).not.toContain('Automatic fixes remaining')
  expect(container.querySelector('progress')).toBeNull()
})
it('does not use stale batch links or replay paused animation', async () => {
  getFindingDispositions.mockResolvedValue({ available: true, batch_id: 'old', items: [item('a')] })
  const { container, render } = await mount()
  await render(snap({ resolved_verified: 1, unchanged_no_fix: 1 }), 's:b', true)
  expect(container.querySelector('progress')).toBeNull()
  expect(container.querySelector('.wf-delta')).toBeNull()
  await render(snap(), 'new:b')
  expect(container.querySelector('.wf-delta')).toBeNull()
})

it('uses sealed eligibility after reload even when current findings and capability change with the same total', async () => {
  const changed = { ...context, files: [{ ...context.files[0], issues: Array.from({ length: 3 }, () => ({ wcag: 'SC_1_1_1', severity: 'SERIOUS' })) }], cap: { docx: { '1.1.1': 'auto', '1.3.1': 'human' } } }
  const { container } = await mount(snap(), changed)
  expect(container.textContent).toContain('Originally: 2 automatic + 1 other = 3 findings')
})
it('refreshes matching evidence when the verified count stays the same but the revision changes', async () => {
  getFindingDispositions.mockResolvedValueOnce({ available: true, batch_id: 'b', items: [item('auto')] })
    .mockResolvedValueOnce({ available: true, batch_id: 'b', items: [item('human', '1.1.1')] })
  const first = { ...snap({ resolved_verified: 1, unchanged_no_fix: 1 }), revision: 1 }
  const { container, render } = await mount(first)
  expect(container.querySelector('progress').value).toBe(1)
  await render({ ...first, revision: 2 })
  expect(getFindingDispositions).toHaveBeenCalledTimes(2)
  expect(container.querySelector('progress').value).toBe(2)
})
it('does not infer original eligibility for historical runs without sealed groups', async () => {
  const { container } = await mount(snap({ original_assessment: undefined }))
  expect(container.textContent).not.toContain('Automatic fixes remaining')
  expect(container.textContent).toContain('3 starting findings')
})
