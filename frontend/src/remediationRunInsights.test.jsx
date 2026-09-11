import { act, createElement } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import Insights from './RemediationRunInsights.jsx'
import { getRunInsights } from './remediationRunInsightsClient.js'
vi.mock('./remediationRunInsightsClient.js',()=>({ getRunInsights:vi.fn() }))
afterEach(unmountAll)
beforeEach(()=>vi.resetAllMocks())
globalThis.IS_REACT_ACT_ENVIRONMENT = true
const view = {coverage:'complete',contribution:{draft:1,fallback:1,unattributed:0},attempts:[{attempt_id:'a',purpose:'draft',file:'file.html',model:'actual-model',provider:'anthropic',output_retention:'full',result:{text:'<script>bad()</script>'}}],review_receipts:[],proposals:[],estimate:{available:false}}
async function open(container) { await act(async()=>{ const el=container.querySelector('details'); el.open=true; el.dispatchEvent(new Event('toggle')) }) }

it('loads only on expansion and renders saved output as text with truthful units', async()=>{
  getRunInsights.mockResolvedValue(view)
  const {root,container}=createTestRoot()
  await act(async()=>root.render(createElement(Insights,{scanId:'s1',batchId:'b1'})))
  expect(getRunInsights).not.toHaveBeenCalled()
  await open(container)
  expect(getRunInsights.mock.calls[0].slice(0,2)).toEqual(['s1','b1'])
  expect(container.textContent).toContain('actual-model')
  expect(container.textContent).toContain('<script>bad()</script>')
  expect(container.querySelector('script')).toBeNull()
  expect(container.textContent).toContain('not findings or verified fixes')
  expect(container.textContent).toContain('An estimate is not available')
})

it('drops old run responses and offers retry after failure',async()=>{
  let resolveOld
  getRunInsights.mockImplementationOnce(()=>new Promise(resolve=>{resolveOld=resolve})).mockRejectedValue(new Error('offline'))
  const {root,container}=createTestRoot()
  await act(async()=>root.render(createElement(Insights,{scanId:'s1',batchId:'b1'})))
  await open(container)
  await act(async()=>root.render(createElement(Insights,{scanId:'s2',batchId:'b2'})))
  await act(async()=>resolveOld(view))
  expect(container.textContent).not.toContain('actual-model')
  expect(container.querySelector('[role=alert]').textContent).toContain('could not be loaded')
  getRunInsights.mockResolvedValue({...view,attempts:[]})
  await act(async()=>container.querySelector('button').click())
  expect(container.textContent).toContain('No retained model attempts')
})

it('pages saved records and resets the page when the run changes', async()=>{
  getRunInsights.mockImplementation(async(scan,batch,signal,offset)=>({...view,attempts:[],pagination:{offset,limit:100,has_more:offset===0}}))
  const {root,container}=createTestRoot()
  await act(async()=>root.render(createElement(Insights,{scanId:'s1',batchId:'b1'})))
  await open(container)
  const button=label=>Array.from(container.querySelectorAll('button')).find(el=>el.textContent===label)
  expect(button('Previous records').disabled).toBe(true)
  await act(async()=>button('Next records').click())
  expect(getRunInsights.mock.calls.at(-1)[3]).toBe(100)
  expect(button('Next records').disabled).toBe(true)
  await act(async()=>root.render(createElement(Insights,{scanId:'s2',batchId:'b2'})))
  expect(getRunInsights.mock.calls.at(-1).slice(0,2)).toEqual(['s2','b2'])
  expect(getRunInsights.mock.calls.at(-1)[3]).toBe(0)
})

it('shows a concise AI activity summary from saved records, provider and model included', async()=>{
  getRunInsights.mockResolvedValue({...view, activity_summary:{
    by_model:[{provider:'ollama',model:'llama3.1',attempts:3,completed:2}],
    attempted:3, completed:2, suggestions_generated:3, suggestions_applied:2, suggestions_needs_input:1,
    verified:1, ai_policy:{level:1,zone:'local',budget_usd:null}, not_used_reason:null}})
  const {root,container}=createTestRoot()
  await act(async()=>root.render(createElement(Insights,{scanId:'s1',batchId:'b1'})))
  await open(container)
  expect(container.textContent).toContain('Ollama · llama3.1: 3 requests attempted, 2 completed')
  expect(container.textContent).toContain('3 suggestions generated; 2 applied; 1 needs input')
  expect(container.textContent).toContain('1 verified so far')
})

it('explains why AI was not used rather than showing an empty activity summary', async()=>{
  getRunInsights.mockResolvedValue({...view, activity_summary:{
    by_model:[], attempted:0, completed:0, suggestions_generated:0, suggestions_applied:0,
    suggestions_needs_input:0, verified:null, ai_policy:{level:1,zone:'any',budget_usd:'0.00'},
    not_used_reason:'Cloud AI not used: the run spending limit prevents a request.'}})
  const {root,container}=createTestRoot()
  await act(async()=>root.render(createElement(Insights,{scanId:'s1',batchId:'b1'})))
  await open(container)
  expect(container.textContent).toContain('Cloud AI not used: the run spending limit prevents a request.')
})

it('identifies saved run authorization and system decisions without claiming human review',async()=>{
  getRunInsights.mockResolvedValue({...view,standing_approval:{enabled:true,authorized_by:'owner@example.test'},
    review_receipts:[{operation_id:'r',review:{verdict:'accept'}}],
    proposals:[{snapshot_id:'p',system_approvals:[{id:'e'}],proposal:{proposed_value:'Title'},verification_reason:'Not verified'}]})
  const {root,container}=createTestRoot()
  await act(async()=>root.render(createElement(Insights,{scanId:'s',batchId:'b'})))
  await open(container)
  expect(container.textContent).toContain('Auto-approval on for this run')
  expect(container.textContent).toContain('Approved automatically by the system')
  expect(container.textContent).toContain('owner@example.test')
  expect(container.textContent).not.toContain('Human approval still required')
})
