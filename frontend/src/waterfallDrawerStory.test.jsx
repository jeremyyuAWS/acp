import { act } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import { RecordedModelJourney, RunBudgetMeter, RunEvidenceSummary } from './WaterfallDrawerStory.jsx'
globalThis.IS_REACT_ACT_ENVIRONMENT = true
afterEach(async () => { await unmountAll() })
it('navigates exact saved model position without claiming inferred transitions', async () => {
 const onSelectStage=vi.fn(); const {root,container}=createTestRoot()
 await act(async()=>root.render(<RecordedModelJourney graph={{contract_version:'remediation-run-graph.v1',chain_version:1,coverage:'complete',steps:[{step_id:'fallback_2',position:2,configured:true,enabled:true,provider:'p',model:'m',state:'outcome_unknown',reason:'No saved result'}]}} selectedModel={{stepId:'fallback_2'}} onSelectStage={onSelectStage}/>))
 expect(container.querySelector('[aria-current=step]')).not.toBeNull()
 expect(container.textContent).toContain('Sequence alone does not prove a fallback occurred')
 await act(async()=>container.querySelector('button').click())
 expect(onSelectStage).toHaveBeenCalledWith('next',expect.objectContaining({stepId:'fallback_2',model:'m'}))
})
it('shows balanced run budget and uncertain charges', async () => {
 const {root,container}=createTestRoot()
 await act(async()=>root.render(<RunBudgetMeter spending={{currency:'USD',cap_units:10000000,spent_units:2000000,held_units:3000000,available_units:5000000,unknown_charges:1}}/>))
 expect(container.querySelector('.wds-budget')).not.toBeNull()
 expect(container.querySelector('.wds-spent_units').style.width).toBe('20%')
 expect(container.textContent).toContain('1 uncertain charge(s)')
 expect(container.textContent).toContain('All models and documents')
})
it('does not normalize breached or incomplete budgets', async () => {
 const {root,container}=createTestRoot()
 await act(async()=>root.render(<RunBudgetMeter spending={{currency:'USD',cap_units:10,spent_units:20,held_units:0,available_units:0}}/>))
 expect(container.querySelector('.wds-budget')).toBeNull()
 expect(container.textContent).toContain('exceed the saved allowance')
 await act(async()=>root.render(<RunBudgetMeter spending={{currency:'USD',cap_units:10}}/>))
 expect(container.textContent).toContain('Not recorded')
 expect(container.querySelector('.wds-budget')).toBeNull()
})
it('separates all-origins run evidence from model contribution and missing from zero', async () => {
 const selectTab=vi.fn(); const {root,container}=createTestRoot()
 await act(async()=>root.render(<RunEvidenceSummary snapshot={{fixes:{verified:0,applied:3},review:{}}} selectTab={selectTab}/>))
 expect(container.querySelector('.wds-verified dd').textContent).toBe('0')
 expect(container.querySelector('.wds-review dd').textContent).toBe('Not recorded')
 expect(container.textContent).toContain('all origins')
 expect(container.textContent).toContain('counts overlap')
 await act(async()=>container.querySelector('button').click())
 expect(selectTab).toHaveBeenCalledWith('Evidence')
})
it('rejects malformed generation positions and disabled unused steps', async () => {
 const {root,container}=createTestRoot()
 await act(async()=>root.render(<RecordedModelJourney graph={{contract_version:'remediation-run-graph.v1',chain_version:2,coverage:'complete',steps:[{step_id:'primary',configured:true,enabled:true,position:0}]}}/>))
 expect(container.querySelector('li')).toBeNull()
 await act(async()=>root.render(<RecordedModelJourney graph={{contract_version:'remediation-run-graph.v1',chain_version:1,coverage:'complete',steps:[{step_id:'primary',configured:true,enabled:false,position:0}]}}/>))
 expect(container.querySelector('li')).toBeNull()
})
it('retains exact attempt identities when navigating a saved generation position', async () => {
 const onSelectStage=vi.fn();const {root,container}=createTestRoot()
 const graph={contract_version:'remediation-run-graph.v1',chain_version:1,coverage:'complete',steps:[{step_id:'primary',configured:true,enabled:true,position:0,attempt_ids:['a']}],attempts:[{attempt_id:'a',step_id:'primary',generation_position:0,lineage_available:true,purpose:'draft'}]}
 await act(async()=>root.render(<RecordedModelJourney graph={graph} onSelectStage={onSelectStage}/>))
 await act(async()=>container.querySelector('button').click())
 expect(onSelectStage).toHaveBeenCalledWith('first',expect.objectContaining({identityKind:'configured',attemptIds:['a']}))
})
