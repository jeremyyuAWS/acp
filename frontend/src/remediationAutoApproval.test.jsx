import { act, createElement } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import AutoApproval from './RemediationAutoApproval.jsx'
afterEach(unmountAll)
globalThis.IS_REACT_ACT_ENVIRONMENT = true
// The AI reviewer is a precondition for this control, so the baseline policy carries it.
const policy={ai:1,ai_budget_usd:'1.00',ai_review:{enabled:true}}
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

it('requires the AI reviewer, and says so',async()=>{
  // Nothing shows an auto-approved suggestion to a person before it is applied, so the
  // reviewer is the only remaining check on the draft. The server refuses to save a
  // policy without it (remediation_impact_settings.normalize), so the control must not
  // let one be built -- otherwise Save throws an opaque error.
  const {checkbox,container}=await mount({policy:{ai:1,ai_budget_usd:'1.00'}})
  expect(checkbox.disabled).toBe(true)
  expect(container.textContent).toContain('Turn on the AI review below first')
  const on=await mount({policy:{ai:1,ai_budget_usd:'1.00',ai_review:{enabled:true}}})
  expect(on.checkbox.disabled).toBe(false)
})

it('does not call the AI review optional any more',async()=>{
  // Bite check for the copy: the wording tracked a policy option that is now mandatory.
  const {container}=await mount({policy:{...policy,auto_approve_ai:true}})
  expect(container.textContent).not.toContain('optional AI review')
  expect(container.textContent).toContain('never approved this way')
})
