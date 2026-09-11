import { act, createElement, useState } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import RemediationReleasePlan from './RemediationReleasePlan.jsx'
const planning = { available:true, files:['a'], source_revision:'source', destination:{provider:'drive',folder_id:'root'}, destination_label:'Google Drive / root' }
afterEach(async () => { await unmountAll() })
async function mount(extra={}) {
  const {root,container}=createTestRoot(); const onChange=vi.fn(); const read=vi.fn().mockResolvedValue({planning})
  function Harness(props) { const [intent,setIntent]=useState(null); return createElement(RemediationReleasePlan,{scanId:'scan',files:['a'],read,...extra,...props,intent,onChange:value=>{onChange(value);setIntent(value)}}) }
  const render=async changes=>act(async()=>root.render(createElement(Harness,changes)))
  await render();return {container,onChange,read,render,input:()=>container.querySelector('input'),review:()=>container.querySelectorAll('input')[1]}
}
it('defaults a ready draft to automatic publishing and allows review opt out',async()=>{
  const v=await mount();expect(v.input().checked).toBe(true)
  expect(v.onChange).toHaveBeenLastCalledWith(expect.objectContaining({allow_remaining_issues:true,include_reports:true,source_revision:'source'}))
  await act(async()=>v.review().click());expect(v.input().checked).toBe(false);expect(v.review().checked).toBe(true);expect(v.onChange).toHaveBeenLastCalledWith(null)
})
it('defaults new scope to automatic publishing with fresh consent',async()=>{
  const v=await mount();await act(async()=>v.review().click())
  await v.render({files:['b'],read:async()=>({planning:{...planning,files:['b'],source_revision:'next'}})})
  expect(v.input().checked).toBe(true);expect(v.onChange).toHaveBeenLastCalledWith(expect.objectContaining({files:['b'],source_revision:'next'}))
})
it('disables unsupported or read-only planning',async()=>{
  const v=await mount({disabled:true});expect(v.input().disabled).toBe(true)
  await v.render({disabled:false,read:async()=>({planning:{available:false,reason:'Select assessed files.'}})})
  expect(v.input().disabled).toBe(true);expect(v.container.textContent).toContain('Select assessed files.')
})
it('keeps the timestamp destination visible and moves explanation behind keyboard-accessible info', async () => {
  const v=await mount()
  expect(v.container.textContent).toContain('Google Drive / root / Remediated / Timestamp + user email')
  expect(v.container.textContent).not.toContain('Human inspection is optional')
  const tip=v.container.querySelector('button[aria-label="About automatic release"]')
  expect(tip.closest('label')).toBeNull()
  await act(async()=>tip.focus())
  expect(v.container.querySelector('[role="tooltip"]').textContent).toContain('Human inspection is optional')
  expect(v.container.querySelector('[role="tooltip"]').textContent).toContain('Original files stay unchanged')
  expect(v.input().checked).toBe(true)
})

it('preserves a review choice made while the destination is loading',async()=>{
 let resolve;const read=()=>new Promise(r=>{resolve=r});const v=await mount({read})
 await act(async()=>v.review().click())
 await act(async()=>resolve({planning}))
 expect(v.review().checked).toBe(true);expect(v.input().checked).toBe(false);expect(v.onChange).toHaveBeenLastCalledWith(null)
})

it('requires a publishing answer in the mandatory plan and resets it for a new scope', async () => {
  const onAnswered = vi.fn()
  const v = await mount({ requireChoice: true, onAnswered })
  expect(v.input().checked).toBe(false)
  expect(v.review().checked).toBe(false)
  expect(onAnswered).toHaveBeenLastCalledWith(false)
  await act(async () => v.input().click())
  expect(onAnswered).toHaveBeenLastCalledWith(true)
  expect(v.onChange).toHaveBeenLastCalledWith(expect.objectContaining({ files: ['a'] }))
  await v.render({ files: ['b'] })
  expect(v.input().checked).toBe(false)
  expect(v.review().checked).toBe(false)
  expect(onAnswered).toHaveBeenLastCalledWith(false)
})
it('requires a choice in the compact publishing question and preserves approval boundaries', async () => {
  const onAnswered = vi.fn()
  const v = await mount({ compact: true, requireChoice: true, onAnswered })
  expect(v.container.textContent).toContain('Auto-publish?')
  expect(v.input().checked).toBe(false)
  expect(v.review().checked).toBe(false)
  expect(v.container.textContent).toContain('Unapproved suggestions remain unapplied')
  expect(v.container.querySelector('[aria-label="About automatic release"]')).toBeNull()
  await act(async () => v.input().click())
  expect(onAnswered).toHaveBeenLastCalledWith(true)
  expect(v.onChange).toHaveBeenLastCalledWith(expect.objectContaining({ allow_remaining_issues: true, include_reports: true }))
})

it('explains blocked files and refreshes readiness without blaming the connection', async () => {
  const read = vi.fn().mockResolvedValueOnce({planning:{available:false,
    reason:'1 of 1 selected files need attention before automatic publishing.',
    blocked_files:[{file:'a',reason:'Assessment is still queued or running.'}]}})
    .mockResolvedValueOnce({planning})
  const v = await mount({read,requireChoice:true})
  expect(v.input().disabled).toBe(true)
  expect(v.container.querySelector('[aria-label="Files blocking automatic publishing"]').textContent).toContain('a — Assessment')
  expect(v.container.textContent).not.toContain('Connect an authorized destination')
  const refresh = [...v.container.querySelectorAll('button')].find(b=>b.textContent==='Refresh publishing readiness')
  await act(async()=>refresh.click())
  expect(read).toHaveBeenCalledTimes(2)
  expect(v.input().disabled).toBe(false)
  expect(v.input().checked).toBe(false)
})
