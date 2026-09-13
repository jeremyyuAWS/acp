import { describe, it, expect, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react'
import { createTestRoot, unmountAll } from './testRoots.js'
import RemediationInbox from './RemediationInbox.jsx'
import { reviewQueueAction, reviewQueueActions } from './reviewQueueAction.js'

afterEach(unmountAll)
describe('Review queue action pills', () => {
  it('uses action ownership rather than severity and preserves uncertain automatic work', () => {
    expect(reviewQueueAction({ id:1, severity:'MODERATE' }).key).toBe('edit')
    expect(reviewQueueAction({ id:2, severity:'CRITICAL',hasProposal:true, after:'draft' }).key).toBe('review')
    expect(reviewQueueAction({ id:3,rule_id:'1.1.1',status:'blocked' },{},true).key).toBe('check')
    expect(reviewQueueAction({ id:4,automaticQueued:true },{},true).key).toBe('processing')
    expect(reviewQueueAction({ id:5,applied:true,validated:false },{},true).key).toBe('check')
    expect(reviewQueueAction({ id:6,rule_id:'2.4.2' },{},true).key).toBe('edit')
    expect(reviewQueueAction({ id:7,status:'blocked',hasProposal:true,after:'draft',automaticDisposition:{responsibility:'human',reason:'Manual work or no supported proposal writer'} },{},true).key).toBe('edit')
    expect(reviewQueueActions([{hasProposal:true,after:'draft'},{}]).map(a=>a.label)).toEqual(['Review needed','Edit needed'])
  })
  it('renders admitted automatic work and unknown verification as blue status pills', async () => {
    const {container,root}=createTestRoot()
    await act(async()=>root.render(createElement(RemediationInbox,{queue:[
      {id:81,file:'queued.docx',scanId:'s',rule_id:'1.1.1',hasProposal:true,after:'draft',aiAssisted:true,_raw:{scan_id:'s',source_revision:1,decision_version:0,proposal_snapshot_ids:['p']},proposal_snapshot_ids:['p'],automatic_approval:{state:'queued',run_id:'r',scan_id:'s',source_revision:1,proposal_snapshot_ids:['p'],responsibility:'acp'}},
      {id:82,file:'checking.docx',rule_id:'1.1.1',applied:true,validated:false},
    ],autoApprove:true,automaticApprovalPolicy:{enabled:true,supported:true,run_id:'r',source_revision:1},initialTab:'all',initialGroup:'document',decisions:{}})))
    expect(container.querySelector('#rinbox-row-81 .rinbox-action-chip--processing')?.textContent).toBe('Processing')
    expect(container.querySelector('#rinbox-row-82 .rinbox-action-chip--check')?.textContent).toBe('Status check')
    expect(container.querySelector('.rinbox-row .rinbox-action-chip--edit')).toBeNull()
  })
  it('renders manual red and review amber without severity pills, while retaining priority filters', async () => {
    const {container,root}=createTestRoot()
    await act(async()=>root.render(createElement(RemediationInbox,{ queue:[
      {id:91,file:'manual.pdf',rule_id:'2.4.2',severity:'MODERATE'},
      {id:92,file:'draft.docx',rule_id:'1.1.1',severity:'CRITICAL',hasProposal:true,after:'draft'},
    ],initialTab:'all',initialGroup:'document',decisions:{} })))
    expect(container.querySelector('#rinbox-row-91 .rinbox-action-chip--edit')?.textContent).toBe('Edit needed')
    expect(container.querySelector('#rinbox-row-92 .rinbox-action-chip--review')?.textContent).toBe('Review needed')
    expect(container.querySelector('.rinbox-row .revcard-sev')).toBeNull()
    const priority=container.querySelector('select[aria-label="Filter by priority"]')
    expect([...priority.options].some(o=>o.value==='critical')).toBe(true)
    await act(async()=>{priority.value='critical';priority.dispatchEvent(new Event('change',{bubbles:true}))})
    expect(container.querySelector('#rinbox-row-91')).toBeNull()
    expect(container.querySelector('#rinbox-row-92')).not.toBeNull()
  })
})
