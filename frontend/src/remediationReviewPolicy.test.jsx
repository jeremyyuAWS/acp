import { act, createElement } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import Policy from './RemediationReviewPolicy.jsx'
afterEach(unmountAll)
globalThis.IS_REACT_ACT_ENVIRONMENT = true

it('defaults to review and emits a bounded preference when turned off', async () => {
  const onChange = vi.fn(); const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(Policy, { supported: true, onChange })))
  expect(container.querySelector('input').checked).toBe(true)
  await act(async () => container.querySelector('input').click())
  expect(onChange).toHaveBeenCalledWith({ enabled:false, mode:'review_all', minimum_reliability:null, max_review_attempts:1, review_model:'strong', permitted_families:[], evaluation_versions:{} })
})

it('makes unsupported controls unavailable and explains human approval is retained', async () => {
  const onChange = vi.fn(); const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(Policy, { onChange, supported:false })))
  expect(container.querySelector('fieldset').disabled).toBe(true)
  expect(container.textContent).toContain('not available on this server')
  await act(async () => container.querySelector('input').click())
  expect(onChange).not.toHaveBeenCalled()
})

it('bounds review attempts and leaves uncalibrated reliability blank', async () => {
  const onChange = vi.fn(); const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(Policy, { onChange, supported:true, value:{enabled:true} })))
  expect([...container.querySelector('select').options].map(o=>o.value)).toEqual(['1','2'])
  expect(container.textContent).toContain('Review all AI changes — default')
  expect(container.textContent).toContain('Calibration-based automatic application is not available for this run.')
  expect(container.querySelector('input[type=number]').value).toBe('')
  expect(container.textContent).not.toContain('95%')
  expect(container.querySelector('input[type=number]').min).toBe('0')
  expect(container.querySelector('input[type=number]').max).toBe('100')
})

it('lets a calibrated execution path choose validated automatic approval and threshold', async () => {
  const onChange = vi.fn(); const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(Policy, { onChange, supported:true,
    automaticSupported:true, administratorFloor:97, eligibleFamilies:[{change_family:'objective-fixture',format:'html',evaluation_version:'v1',minimum_reliability:97,reviewer_model:'reviewer',reviewer_provider:'provider'}], value:{enabled:true} })))
  const threshold = container.querySelector('input[value="threshold"]')
  await act(async () => threshold.click())
  expect(onChange).toHaveBeenCalledWith({ enabled:true, mode:'threshold', minimum_reliability:null, max_review_attempts:1, review_model:'strong', permitted_families:[], evaluation_versions:{} })
  expect(container.querySelector('input[type=number]').disabled).toBe(false)
})

it('keeps the validated automatic option unavailable until calibration and independent checks exist', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(Policy, { onChange: vi.fn(), supported:true, value:{enabled:true} })))
  expect(container.querySelector('input[value="threshold"]').disabled).toBe(true)
  expect(container.textContent).toContain('Calibration-based automatic application is not available for this run.')
  expect(container.textContent).toContain('AI suggestions will remain drafts for your approval.')
})

it('shows the server readiness reason when automatic approval is unavailable', async () => {
  const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(Policy, {
    onChange: vi.fn(), supported: true, automaticSupported: false,
    automaticReason: 'Automatic application is disabled until a supported writer is configured.',
    value: { enabled: true },
  })))
  expect(container.textContent).toContain('Automatic application is disabled until a supported writer is configured.')
})


it('keeps review-all available when a saved threshold is no longer supported', async () => {
  const onChange = vi.fn(); const { root, container } = createTestRoot()
  await act(async () => root.render(createElement(Policy,{onChange,supported:true,value:{enabled:true,mode:'threshold'}})))
  const reviewAll=container.querySelector('input[value="review_all"]')
  expect(reviewAll.disabled).toBe(false)
  await act(async () => reviewAll.click())
  expect(onChange.mock.calls[0][0].mode).toBe('review_all')
})

it('requires an explicit family and pins its evaluation without inventing a threshold', async () => {
  const onChange=vi.fn(); const {root,container}=createTestRoot()
  await act(async () => root.render(createElement(Policy,{onChange,supported:true,automaticSupported:true,value:{enabled:true},
    eligibleFamilies:[{change_family:'fixture',format:'html',evaluation_version:'v1',minimum_reliability:97,reviewer_model:'r',reviewer_provider:'p'}]})))
  await act(async () => container.querySelectorAll('input[type=checkbox]')[1].click())
  expect(onChange.mock.calls[0][0]).toMatchObject({permitted_families:['fixture'],evaluation_versions:{fixture:'v1'},minimum_reliability:null})
})

it('does not display an old uncalibrated default percentage as current configuration', async () => {
  const {root,container}=createTestRoot()
  await act(async () => root.render(createElement(Policy,{supported:true,onChange:vi.fn(),
    value:{enabled:true,minimum_reliability:95}})))
  expect(container.querySelector('input[type=number]').value).toBe('')
  expect(container.textContent).not.toContain('95%')
})


it('distinguishes unavailable calibration from an explicit advance approval choice',async()=>{
  const {root,container}=createTestRoot()
  await act(async()=>root.render(createElement(Policy,{onChange:vi.fn(),supported:true,value:{enabled:true},standingApprovalEnabled:true})))
  expect(container.textContent).toContain('Calibration-based automatic application is not available')
  expect(container.textContent).toContain('This does not change the advance approval choice above')
  expect(container.textContent).not.toContain('AI suggestions will remain drafts for your approval')
  expect(container.textContent).not.toContain('Review all AI changes — default')
})
