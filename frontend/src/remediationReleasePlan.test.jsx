import { act, createElement } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import RemediationReleasePlan from './RemediationReleasePlan.jsx'
const planning = { available:true, files:['a'], source_revision:'source', destination:{provider:'drive',folder_id:'root'}, destination_label:'Google Drive / root' }
afterEach(async () => { await unmountAll() })
async function mount(extra={}) {
  const {root,container}=createTestRoot(); const onChange=vi.fn(); const read=vi.fn().mockResolvedValue({planning})
  const props={scanId:'scan',files:['a'],intent:null,onChange,read,...extra}
  const render=async changes=>act(async()=>root.render(createElement(RemediationReleasePlan,{...props,...changes})))
  await render();return {container,onChange,read,render,input:()=>container.querySelector('input')}
}
it('shows a read-only destination and starts unchecked before any accepted run',async()=>{
  const v=await mount();expect(v.input().checked).toBe(false);expect(v.input().disabled).toBe(false)
  expect(v.container.textContent).toContain('Google Drive / root');expect(v.onChange.mock.calls.every(([value])=>value===null)).toBe(true)
  await act(async()=>v.input().click())
  expect(v.onChange).toHaveBeenLastCalledWith(expect.objectContaining({files:['a'],source_revision:'source',destination:planning.destination}))
  expect(v.read).toHaveBeenCalledOnce()
})
it('clears the draft when the displayed scope changes',async()=>{
  const v=await mount();await act(async()=>v.input().click());const selected=v.onChange.mock.calls.at(-1)[0]
  await v.render({intent:selected});expect(v.input().checked).toBe(true)
  await v.render({files:['b'],intent:selected});expect(v.input().checked).toBe(false);expect(v.onChange).toHaveBeenLastCalledWith(null)
})
it('disables unsupported or read-only planning',async()=>{
  const v=await mount({disabled:true});expect(v.input().disabled).toBe(true)
  await v.render({disabled:false,read:async()=>({planning:{available:false,reason:'Select assessed files.'}})})
  expect(v.input().disabled).toBe(true);expect(v.container.textContent).toContain('Select assessed files.')
})
it('keeps the timestamp destination visible and moves explanation behind keyboard-accessible info', async () => {
  const v=await mount()
  expect(v.container.textContent).toContain('Google Drive / root / Remediated / Release date and time')
  expect(v.container.textContent).not.toContain('Off by default')
  const tip=v.container.querySelector('button[aria-label="About automatic release"]')
  expect(tip.closest('label')).toBeNull()
  await act(async()=>tip.focus())
  expect(v.container.querySelector('[role="tooltip"]').textContent).toContain('Off by default')
  expect(v.container.querySelector('[role="tooltip"]').textContent).toContain('originals stay unchanged')
  expect(v.input().checked).toBe(false)
})
