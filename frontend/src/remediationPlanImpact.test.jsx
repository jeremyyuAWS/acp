import { readFileSync } from 'node:fs'
import { act } from 'react'
import { afterEach, expect, it } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import RemediationPlanImpact, { planCategoryCounts } from './RemediationPlanImpact.jsx'
const css = name => readFileSync(new URL(name, import.meta.url), 'utf8')
globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(unmountAll)
const data = (automatic, manual) => ({ open: { findings: automatic + manual }, findings: [
  { lane: 'automatic', finding_count: automatic }, { lane: 'manual', finding_count: manual },
] })
it('reconciles every category and rejects incomplete counts rather than showing misleading zeroes', () => {
  expect(planCategoryCounts(data(15, 17))).toMatchObject({ automatic: 15, manual: 17, verified: 0 })
  expect(planCategoryCounts({ ...data(15, 17), open: { findings: 33 } })).toBeNull()
  expect(planCategoryCounts({ open: { findings: 1 }, findings: [{}] })).toBeNull()
})
it('compares only settled selections in the same scope, announces changes and clears unavailable counts', async () => {
  const { root, container } = createTestRoot()
  const render = async (policyKey, value, extra = {}) => act(async () => root.render(<RemediationPlanImpact identity="scan-one" policyKey={policyKey} data={value} ready loading={false} {...extra} />))
  await render('rules', data(4, 7))
  expect(container.querySelectorAll('.plan-impact__tile')).toHaveLength(8)
  expect(container.querySelector('.plan-impact__delta')).toBeNull()
  await render('cloud', data(4, 7), { ready: false, loading: true })
  expect(container.textContent).toContain('Updating…')
  expect(container.querySelector('.plan-impact__delta')).toBeNull()
  await render('cloud', data(7, 4))
  expect([...container.querySelectorAll('.plan-impact__delta')].map(n => n.textContent)).toEqual(['+3', '−3'])
  expect(container.querySelectorAll('.positive')).toHaveLength(2)
  expect(container.querySelector('[role=status]').textContent).toContain('Fully automated: +3')
  await render('rules', data(4, 7), { identity: 'scan-two' })
  expect(container.querySelector('.plan-impact__delta')).toBeNull()
  await render('cloud', null, { ready: false })
  expect(container.textContent).toContain('Preview unavailable')
})
it('adds the unclassified remainder to reconcile the plan with Assess without counting incomplete checks', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(<RemediationPlanImpact identity="scan" policyKey="cloud" ready
    assessmentTotal={32} data={data(17,12)} />))
  expect(container.querySelector('.plan-impact__outside strong').textContent).toBe('3')
  expect([...container.querySelectorAll('.plan-impact__tile > strong')].reduce((sum, n) => sum + Number(n.textContent), 0)).toBe(32)
  expect(container.textContent).toContain('29 in this plan + 3 outside this plan = 32 assessed findings.')
  expect(container.textContent).toContain('without a current plan classification')
  expect(container.textContent).toContain('not counted as fixed')
  await act(async () => root.render(<RemediationPlanImpact identity="scan" policyKey="cloud" ready
    assessmentTotal={29} data={data(17,12)} />))
  expect(container.querySelector('.plan-impact__outside')).toBeNull()
  await act(async () => root.render(<RemediationPlanImpact identity="scan" policyKey="cloud" ready={false}
    assessmentTotal={32} data={data(17,12)} />))
  expect(container.querySelector('.plan-impact__outside')).toBeNull()
})
it('offers explanation and examples for every tile by hover, keyboard and click', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(<RemediationPlanImpact identity="help" policyKey="cloud" ready
    assessmentTotal={32} data={data(17,12)} />))
  const buttons = [...container.querySelectorAll('.plan-impact__tile button')]
  expect(buttons).toHaveLength(9)
  for (const button of buttons) {
    await act(async () => button.focus())
    const tip = container.querySelector('[role=tooltip]')
    expect(tip.textContent).toMatch(/Example/)
    expect(button.getAttribute('aria-describedby')).toBe(tip.id)
    await act(async () => button.click())
    expect(container.querySelector('[role=tooltip]')).not.toBeNull()
    await act(async () => document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape',bubbles:true})))
    expect(container.querySelector('[role=tooltip]')).toBeNull()
  }
  const outside = buttons.at(-1)
  await act(async () => outside.blur())
  await act(async () => outside.dispatchEvent(new MouseEvent('mouseover', {bubbles:true})))
  expect(container.querySelector('[role=tooltip]').textContent).toContain('a review finding omitted from the preview')
  expect(container.querySelector('[role=tooltip]').textContent).toContain('possible reasons, not confirmed')
})


it('keeps tile info controls centered and transparent inside the plan card', async () => {
  const style = document.createElement('style')
  style.textContent = css('./info-tip.css') + css('./remediation-impact-card.css') + css('./remediation-plan-impact.css')
  document.head.append(style)
  try {
    const { root, container } = createTestRoot()
    await act(async () => root.render(<div className="remediation-impact remediation-plan-choices__grid">
      <RemediationPlanImpact identity="layout" policyKey="rules" ready data={data(8,0)} />
    </div>))
    for (const button of container.querySelectorAll('.plan-impact__help button')) {
      const control = getComputedStyle(button)
      expect(control.backgroundColor).toBe('rgba(0, 0, 0, 0)')
      expect(parseFloat(control.padding)).toBe(0)
      expect(parseFloat(control.margin)).toBe(0)
      expect(control.width).toBe('24px')
      expect(control.height).toBe('24px')
      expect(control.display).toBe('grid')
      expect(control.placeItems).toBe('center')
      const icon = getComputedStyle(button.firstElementChild)
      expect(icon.display).toBe('grid')
      expect(icon.width).toBe('14px')
      expect(icon.height).toBe('14px')
      expect(icon.lineHeight).toBe('1')
    }
  } finally { style.remove() }
})
