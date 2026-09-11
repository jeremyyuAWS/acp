import { act } from 'react'
import { afterEach, expect, it } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import RemediationPlanImpact, { planCategoryCounts } from './RemediationPlanImpact.jsx'
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
