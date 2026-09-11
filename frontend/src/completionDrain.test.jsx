import { it, expect, vi } from 'vitest'
import { createElement, act } from 'react'
import { createRoot } from 'react-dom/client'
import CompletionDrain from './CompletionDrain.jsx'
import { workflowStatusOf, matchesWorkflow, autoFixRows } from './remediationInboxModel.js'
it('keeps applied work pending until verification, then removes it from remaining', () => {
  const applied={id:'a',autoApplied:true}
  expect(workflowStatusOf(applied)).toBe('awaiting-validation')
  expect(matchesWorkflow(applied,'active')).toBe(true)
  const verified={...applied,validated:true}
  expect(workflowStatusOf(verified)).toBe('completed')
  expect(matchesWorkflow(verified,'active')).toBe(false)
  expect(matchesWorkflow(verified,'completed')).toBe(true)
})
it('announces a newly completed row briefly, never preexisting completions', async () => {
  vi.useFakeTimers()
  const host=document.createElement('div');document.body.appendChild(host);const root=createRoot(host)
  const show=async queue=>act(async()=>root.render(createElement(CompletionDrain,{queue,decisions:{},scanId:'s',active:true})))
  await show([{id:'a',status:'applied',title:'Image alt'}])
  expect(host.textContent).toBe('')
  await show([{id:'a',status:'verified',title:'Image alt'}])
  expect(host.textContent).toContain('moved to Completed')
  await act(async()=>vi.advanceTimersByTime(650))
  expect(host.textContent).toBe('')
  await act(async()=>root.unmount());host.remove();vi.useRealTimers()
})

it('preserves verification proof when adapting change records', () => {
  const [verified,pending]=autoFixRows([{file:'a.docx',sc:'1.1.1',verified:true},{file:'b.docx',sc:'1.1.1'}])
  expect(workflowStatusOf(verified)).toBe('completed')
  expect(workflowStatusOf(pending)).toBe('awaiting-validation')
})

it('does not hide a blocker or manual handoff just because a write occurred', () => {
  expect(workflowStatusOf({id:'a',autoApplied:true,status:'blocked'})).toBe('blocked')
  expect(workflowStatusOf({id:'a',autoApplied:true,rejectedFix:true})).toBe('manual')
  expect(workflowStatusOf({id:'a',autoApplied:true},{a:{state:'assigned'}})).toBe('manual')
})
