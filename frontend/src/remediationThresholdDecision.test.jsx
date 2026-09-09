import { act, createElement } from 'react'
import { afterEach, expect, it } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import Decision from './RemediationThresholdDecision.jsx'
afterEach(unmountAll)
globalThis.IS_REACT_ACT_ENVIRONMENT = true

it('never turns missing evidence into an approval or invented reliability', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(Decision)))
  expect(container.textContent).toContain('Eligibility not yet known')
  expect(container.textContent).not.toContain('%')
})
it('distinguishes policy approval from verification and shows every gate in text', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(Decision, {decision:{approval_kind:'policy',status:'approved_awaiting_completion',
    minimum_reliability:96,reliability_lower_bound:.97,evaluation_version:'eval1',checks:[{gate:'source_unchanged',passed:true},{gate:'objective_validation_passed',passed:false}]}})))
  expect(container.textContent).toContain('Approved under your policy — awaiting completion')
  expect(container.textContent).toContain('Passed: The source has not changed')
  expect(container.textContent).toContain('Not passed: Objective checks')
  expect(container.textContent).toContain('does not guarantee')
})
it('human approval is explicitly distinct', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(Decision,{decision:{approval_kind:'human'}})))
  expect(container.textContent).toContain('Approved by you')
  expect(container.textContent).not.toContain('Approved under your policy')
})
it('explains why an expired evaluation cannot authorize automatic approval', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(Decision, {decision:{approval_kind:'human',
    calibration_reason:'calibration_expired_or_future', checks:[{gate:'applicable_fresh_calibration',passed:false}]}})))
  expect(container.textContent).toContain('Automatic approval remains unavailable')
  expect(container.textContent).toContain('The evaluation is expired or its timestamp is in the future.')
})
