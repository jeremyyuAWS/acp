import { act, createElement, useState } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import RemediationReleasePlan from './RemediationReleasePlan.jsx'
const planning = { available:true, files:['a'], source_revision:'source', destination:{provider:'drive',folder_id:'root'}, destination_label:'Google Drive / root' }
afterEach(async () => { await unmountAll(); vi.useRealTimers() })
async function mount(extra={}) {
  const {root,container}=createTestRoot(); const onChange=vi.fn(); const read=vi.fn().mockResolvedValue({planning})
  function Harness(props) { const [intent,setIntent]=useState(null); return createElement(RemediationReleasePlan,{scanId:'scan',files:['a'],read,...extra,...props,intent,onChange:value=>{onChange(value);setIntent(value)}}) }
  const render=async changes=>act(async()=>root.render(createElement(Harness,changes)))
  await render();return {root,container,onChange,read,render,input:()=>container.querySelector('input'),review:()=>container.querySelectorAll('input')[1]}
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
it('requires a choice in the compact publishing question and explains automatic suggestion application', async () => {
  const onAnswered = vi.fn()
  const v = await mount({ compact: true, requireChoice: true, onAnswered })
  expect(v.container.textContent).toContain('Auto-publish?')
  expect(v.input().checked).toBe(false)
  expect(v.review().checked).toBe(false)
  expect(v.container.textContent).toContain('Automatic publishing applies available fixes and AI suggestions')
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

it('freezes only eligible files when the selection includes blocked files', async () => {
  const v = await mount({files:['a','failed'], read:async()=>({planning:{...planning,
    reason:'1 file can publish. 1 file will be skipped.',
    blocked_files:[{file:'failed',reason:'Assessment failed.'}]}})})
  expect(v.input().disabled).toBe(false)
  expect(v.onChange).toHaveBeenLastCalledWith(expect.objectContaining({files:['a']}))
  expect(v.container.textContent).toContain('1 file will be skipped')
  expect(v.container.querySelector('[aria-label="Files blocking automatic publishing"]').textContent).toContain('failed — Assessment failed.')
})
it('refreshes blocked readiness in the same scope without answering or approving publication', async () => {
  vi.useFakeTimers()
  const files = Array.from({length:147}, (_,i)=>`document-${i}.docx`)
  const read = vi.fn().mockResolvedValueOnce({planning:{available:false,files:[],
    reason:'147 of 147 selected files need attention before automatic publishing.',
    blocked_files:files.map(file=>({file,reason:'Source identity or freshness is missing.'}))}}).mockResolvedValue({planning:{...planning,files}})
  const onAnswered=vi.fn(),v=await mount({files,read,requireChoice:true,onAnswered})
  expect(v.input().disabled).toBe(true)
  expect(v.container.textContent).toContain('Waiting for assessment and source checks')
  await act(async()=>vi.advanceTimersByTimeAsync(5000))
  expect(read).toHaveBeenCalledTimes(2)
  expect(read.mock.calls[1][1]).toEqual(files)
  expect(v.input().disabled).toBe(false);expect(v.input().checked).toBe(false)
  expect(onAnswered).not.toHaveBeenCalledWith(true)
  expect(v.onChange.mock.calls.every(([value])=>value===null)).toBe(true)
  expect(v.container.textContent).toContain('Google Drive / root')
})

it('preserves publish-later choice while blocked readiness refreshes',async()=>{
 vi.useFakeTimers();const onAnswered=vi.fn()
 const read=vi.fn().mockResolvedValueOnce({planning:{available:false,blocked_files:[{file:'a',reason:'Processing'}]}}).mockResolvedValue({planning})
 const v=await mount({read,requireChoice:true,onAnswered});await act(async()=>v.review().click())
 await act(async()=>vi.advanceTimersByTimeAsync(5000))
 expect(v.review().checked).toBe(true);expect(v.input().checked).toBe(false)
 expect(onAnswered).toHaveBeenLastCalledWith(true)
 expect(v.onChange.mock.calls.every(([value])=>value===null)).toBe(true)
})
it('cancels blocked readiness refresh after unmount',async()=>{
 vi.useFakeTimers();const read=vi.fn().mockResolvedValue({planning:{available:false}})
 const v=await mount({read,requireChoice:true});await act(async()=>v.root.unmount())
 await act(async()=>vi.advanceTimersByTimeAsync(10000));expect(read).toHaveBeenCalledTimes(1)
})
it('bounds automatic readiness reads to five minutes',async()=>{
 vi.useFakeTimers();const read=vi.fn().mockResolvedValue({planning:{available:false}})
 await mount({read,requireChoice:true});await act(async()=>vi.advanceTimersByTimeAsync(600000))
 expect(read).toHaveBeenCalledTimes(61)
})
it('ignores and aborts a delayed readiness response from the previous scope',async()=>{
 let old;const read=vi.fn().mockImplementationOnce(()=>new Promise(r=>{old=r})).mockResolvedValue({planning:{...planning,files:['b']}})
 const v=await mount({read,requireChoice:true});const oldSignal=read.mock.calls[0][2].signal
 await v.render({files:['b']});expect(oldSignal.aborted).toBe(true)
 await act(async()=>old({planning}));expect(v.input().checked).toBe(false)
 expect(v.container.textContent).toContain('Google Drive / root');expect(v.onChange.mock.calls.every(([value])=>value===null)).toBe(true)
})
it('does not silently expand a previously chosen eligible subset',async()=>{
 vi.useFakeTimers();const onAnswered=vi.fn()
 const read=vi.fn().mockResolvedValueOnce({planning:{...planning,blocked_files:[{file:'b',reason:'Processing'}]}}).mockResolvedValue({planning:{...planning,files:['a','b'],source_revision:'next'}})
 const v=await mount({files:['a','b'],read,requireChoice:true,onAnswered});await act(async()=>v.input().click())
 expect(v.onChange).toHaveBeenLastCalledWith(expect.objectContaining({files:['a']}))
 await act(async()=>vi.advanceTimersByTimeAsync(5000))
 expect(v.input().checked).toBe(false);expect(onAnswered).toHaveBeenLastCalledWith(false)
 expect(v.onChange).toHaveBeenLastCalledWith(null)
})
it('times out a stalled readiness read and aborts it without approving publication',async()=>{
 vi.useFakeTimers();const read=vi.fn().mockImplementation(()=>new Promise(()=>{}))
 const v=await mount({read,requireChoice:true});await act(async()=>vi.advanceTimersByTimeAsync(20000))
 expect(read.mock.calls[0][2].signal.aborted).toBe(true)
 expect(v.container.querySelector('[role="alert"]').textContent).toContain('could not be checked')
 expect(v.onChange.mock.calls.every(([value])=>value===null)).toBe(true)
})
it('removes spending-limit wording from the publishing question and its explanation',async()=>{
 const v=await mount();expect(v.container.textContent).not.toContain('spending limit')
 await act(async()=>v.container.querySelector('[aria-label="About automatic release"]').focus())
 expect(v.container.textContent).not.toContain('spending limit')
})
it('does not re-read fully ready planning or poll while disabled',async()=>{
 vi.useFakeTimers();const ready=await mount({requireChoice:true})
 await act(async()=>vi.advanceTimersByTimeAsync(10000));expect(ready.read).toHaveBeenCalledTimes(1)
 const read=vi.fn().mockResolvedValue({planning:{available:false}})
 const v=await mount({read,disabled:true,requireChoice:true})
 await act(async()=>vi.advanceTimersByTimeAsync(10000));expect(read).toHaveBeenCalledTimes(1)
 await v.render({disabled:false});await act(async()=>vi.advanceTimersByTimeAsync(5000))
 expect(read).toHaveBeenCalledTimes(2)
})
it('stops background reads after a scope or access rejection',async()=>{
 vi.useFakeTimers();const read=vi.fn().mockResolvedValueOnce({planning:{available:false}}).mockRejectedValue(Object.assign(new Error('Forbidden'),{status:403}))
 const v=await mount({read,requireChoice:true});await act(async()=>vi.advanceTimersByTimeAsync(20000))
 expect(read).toHaveBeenCalledTimes(2);expect(v.input().disabled).toBe(true)
})
it('preserves a publish-later answer during an explicit readiness refresh',async()=>{
 const onAnswered=vi.fn(),read=vi.fn().mockResolvedValueOnce({planning:{available:false,blocked_files:[{file:'a',reason:'Processing'}]}}).mockResolvedValue({planning})
 const v=await mount({read,requireChoice:true,onAnswered});await act(async()=>v.review().click())
 await act(async()=>[...v.container.querySelectorAll('button')].find(b=>b.textContent==='Refresh publishing readiness').click())
 expect(v.review().checked).toBe(true);expect(onAnswered).toHaveBeenLastCalledWith(true)
})
