import { act } from 'react'
import { afterEach, expect, it, vi } from 'vitest'
import { createTestRoot, unmountAll } from './testRoots.js'
import ActivityEventDetails from './ActivityEventDetails.jsx'
import { activityEvidenceModel } from './activityEventDetails.js'
const hash = 'a'.repeat(64), other = 'b'.repeat(64)
const event = {key:'12',id:'12',evidenceIds:['record'],snapshotSha256:hash,activityDetails:{criterion:'1.1.1, 1.3.1',nextAction:'Check the saved result.'}}
const evidence = () => ({available:true,artifact_sha256:hash,changes:[{criterion:'1.3.1',location:'Section 2, paragraph 4',before:'Body text',after:'Heading 1',verification:'verified'}],verification:{status:'verified',artifact_sha256:hash},saved_copy:{matches_event:true,download_url:'/scans/scan/remediation/activity/12/copy'}})
afterEach(() => { unmountAll(); vi.restoreAllMocks() })
async function mount(props={}) {
  const view=createTestRoot()
  await act(async()=>view.root.render(<ActivityEventDetails event={event} {...props}/>))
  return view
}
async function toggle(container,open=true) {
  await act(async()=>{const details=container.querySelector('details');details.open=open;details.dispatchEvent(new Event('toggle',{bubbles:false}))})
}
it('loads exact-version evidence only on expansion, with explicit missing location',async()=>{
  const loadEvidence=vi.fn().mockResolvedValue(evidence())
  const {container}=await mount({loadEvidence})
  expect(container.textContent).toContain('SC 1.1.1 · SC 1.3.1')
  expect(container.textContent).toContain('Location Unavailable')
  expect(loadEvidence).not.toHaveBeenCalled()
  await toggle(container)
  expect(loadEvidence).toHaveBeenCalledWith('12')
  expect(container.textContent).toContain('Section 2, paragraph 4')
  expect(container.textContent).toContain('Body text')
  expect(container.textContent).toContain('Heading 1')
  expect(container.textContent).toContain('Recorded Check Passed')
  await toggle(container,false);await toggle(container)
  expect(loadEvidence).toHaveBeenCalledTimes(1)
})
it('never substitutes current-file evidence for unbound historical events',async()=>{
  const loadEvidence=vi.fn().mockResolvedValue(evidence())
  const {container}=await mount({event:{id:'old',activityDetails:{criterion:'1.3.1'}},loadEvidence})
  await toggle(container)
  expect(loadEvidence).not.toHaveBeenCalled()
  expect(container.textContent).toContain('Earlier activity is retained')
  expect(container.textContent).not.toContain('Body text')
})
it('rejects mismatched saved hashes and cannot infer verification from successful AI or application',()=>{
  expect(activityEvidenceModel(evidence(),{...event,snapshotSha256:other}).available).toBe(false)
  const response={...evidence(),verification:{status:'verified',artifact_sha256:other}}
  expect(activityEvidenceModel(response,event).verificationLabel).toContain('Unavailable')
  expect(activityEvidenceModel(response,event).changes[0].verified).toBe(false)
  expect(activityEvidenceModel({...evidence(),verification:{}},{...event,kind:'remediate.fix_applied',status:'success'}).verificationLabel).toContain('Unavailable')
})
it('retains immutable check evidence but hides a changed saved-copy download',async()=>{
  const payload={...evidence(),saved_copy:{matches_event:false,download_url:null,reason:'saved_version_changed'}}
  const {container}=await mount({loadEvidence:vi.fn().mockResolvedValue(payload),downloadSavedCopy:vi.fn()})
  await toggle(container)
  expect(container.textContent).toContain('Recorded Check Passed')
  expect(container.textContent).toContain('no newer copy is linked here')
  expect(container.textContent).not.toContain('Download This Saved Copy')
})
it('uses authenticated download callbacks and keeps failure visible inside the open record',async()=>{
  const downloadSavedCopy=vi.fn().mockRejectedValue(new Error('401 private provider detail'))
  const downloadEvidence=vi.fn().mockResolvedValue(undefined)
  const {container}=await mount({loadEvidence:vi.fn().mockResolvedValue(evidence()),downloadSavedCopy,downloadEvidence})
  await toggle(container)
  const buttons=[...container.querySelectorAll('button')]
  await act(async()=>buttons.find(b=>b.textContent.includes('Saved Copy')).click())
  expect(downloadSavedCopy).toHaveBeenCalledWith('12')
  expect(container.querySelector('details').open).toBe(true)
  expect(container.querySelector('[role="alert"]').textContent).toContain('could not be completed')
  expect(container.textContent).not.toContain('private provider detail')
  expect(container.querySelector('a[href]')).toBeNull()
  await act(async()=>buttons.find(b=>b.textContent.includes('Verification Evidence')).click())
  expect(downloadEvidence).toHaveBeenCalledWith('12')
})
it('discards a delayed previous-event response and suppressed document details',async()=>{
  let resolve
  const loadEvidence=vi.fn().mockImplementation(()=>new Promise(r=>{resolve=r}))
  const {container,root}=await mount({loadEvidence})
  await toggle(container)
  await act(async()=>root.render(<ActivityEventDetails event={{...event,key:'13',id:'13',snapshotSha256:other}} loadEvidence={loadEvidence}/>))
  await act(async()=>resolve(evidence()))
  expect(container.textContent).not.toContain('Body text')
  await act(async()=>root.render(<ActivityEventDetails event={{...event,documentSuppressed:true}} loadEvidence={loadEvidence}/>))
  expect(container.textContent).toBe('')
})
it('labels truncated recorded excerpts and change coverage without presenting them as complete',async()=>{
  const payload=evidence();payload.changes[0].text_truncated=true;payload.changes_truncated=true;payload.change_count=18
  const {container}=await mount({loadEvidence:vi.fn().mockResolvedValue(payload)})
  await toggle(container)
  expect(container.textContent).toContain('Excerpt shown')
  expect(container.textContent).toContain('Showing 1 of 18 changes')
})
it('lets a temporary evidence-read failure retry the same event without switching versions',async()=>{
  const loadEvidence=vi.fn().mockRejectedValueOnce(new Error('503')).mockResolvedValue(evidence())
  const {container}=await mount({loadEvidence})
  await toggle(container)
  await act(async()=>container.querySelector('button').click())
  expect(loadEvidence.mock.calls).toEqual([['12'],['12']])
  expect(container.textContent).toContain('Recorded Check Passed')
})
