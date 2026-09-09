import { act, createElement } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import AutoApproval from './RemediationAutoApproval.jsx'
afterEach(unmountAll)
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const policy={ai:1,ai_budget_usd:'1.00'}
async function mount(props={}) {
  const {root,container}=createTestRoot()
  await act(async()=>root.render(createElement(AutoApproval,{policy,supported:true,onChange:vi.fn(),...props})))
  return {root,container,checkbox:container.querySelector('input')}
}
it('keeps advance approval visible and off by default with separate publishing',async()=>{
  const onChange=vi.fn();const {container,checkbox}=await mount({onChange})
  expect(checkbox.checked).toBe(false)
  expect(checkbox.closest('details')).toBeNull()
  expect(checkbox.disabled).toBe(false)
  expect(container.textContent).toContain('Publishing is a separate action')
  expect(container.querySelector('details').open).toBe(false)
  await act(async()=>checkbox.click())
  expect(onChange).toHaveBeenCalledWith('auto_approve_ai',true)
})
it.each([{ai:0,ai_budget_usd:'1.00'},{ai:1,ai_budget_usd:'0.00'}])('requires AI and a positive spending limit: %j',async value=>{
  const {checkbox}=await mount({policy:value})
  expect(checkbox.disabled).toBe(true)
})
it('keeps an unavailable saved choice removable',async()=>{
  const onChange=vi.fn();const {checkbox}=await mount({supported:false,policy:{...policy,auto_approve_ai:true},onChange})
  expect(checkbox.disabled).toBe(false)
  await act(async()=>checkbox.click())
  expect(onChange).toHaveBeenCalledWith('auto_approve_ai',false)
})
it('explains accepted scope including later fallbacks without another dialog',async()=>{
  const {container}=await mount({policy:{...policy,auto_approve_ai:true}})
  expect(container.textContent).toContain('Approve plan and start authorizes')
  expect(container.textContent).toContain('including fallbacks, without more approval dialogs')
  expect(container.textContent).toContain('does not authorize existing runs')
  expect(container.textContent).toContain('Google Drive or SharePoint')
})
