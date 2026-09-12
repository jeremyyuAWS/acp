import { expect, it } from 'vitest'
import { liveDocumentCounts, materialKey, releaseProgressState, confirmedReleaseProgress } from './remediationLiveDocumentState.js'
const docs=[{file:'one.docx',totalFindings:2,findings:[{sc:'1.1.1',fixMode:'assisted'},{sc:'1.1.1',fixMode:'assisted'}]}]
const ledger={available:true,batch_id:'batch',items:[{file:'one.docx',finding_id:'a',rule_id:'1.1.1',disposition:'resolved_verified'},{file:'one.docx',finding_id:'b',rule_id:'1.1.1',disposition:'approved_pending_verification'}]}
it('partitions findings and never calls approval an applied edit',()=>{
  const rows=liveDocumentCounts(docs,ledger,[],'batch')
  expect(rows[0].liveCounts).toEqual({verified:1,approved:1})
  expect(Object.values(rows[0].liveCounts).reduce((a,b)=>a+b,0)).toBe(2)
})
it('rejects duplicate identities, mismatched batches and missing instances',()=>{
  expect(liveDocumentCounts(docs,{...ledger,items:[ledger.items[0],ledger.items[0]]},[],'batch')).toBeNull()
  expect(liveDocumentCounts(docs,ledger,[],'other')).toBeNull()
  expect(liveDocumentCounts(docs,{...ledger,items:[ledger.items[0]]},[],'batch')).toBeNull()
})
it('does not refetch for heartbeats or another scans material event',()=>{
  const key=materialKey('scan',{batch_id:'batch',documents:{processing:1}})
  expect(materialKey('scan',{batch_id:'batch',documents:{processing:1},received_at:'later'},[{id:1,kind:'heartbeat'},{id:2,scan_id:'other',kind:'fix_applied'}])).toBe(key)
})
it('recognizes the persisted integer applied flag without guessing from proposals',()=>{
  const data={...ledger,items:ledger.items.map(r=>({...r,disposition:'approved_pending_verification',review_item_id:r.finding_id}))}
  const queue=[{id:'a',file:'one.docx',applied:1,proposals:[{model:'model',model_call_id:'call'}]},{id:'b',file:'one.docx',applied:0,proposals:[{model:'model',model_call_id:'call'}]}]
  expect(liveDocumentCounts(docs,data,queue,'batch')[0].liveCounts).toEqual({ai_applied:1,approved:1})
})
it('uses remaining outcomes rather than original AI capability and keeps verified counts exclusive',()=>{
  const current={...ledger,items:ledger.items.map((r,i)=>({...r,disposition:i===0?'resolved_verified':'pending'}))}
  expect(liveDocumentCounts(docs,current,[],'batch')[0].liveCounts).toEqual({verified:1,remaining:1})
})

it('shares Release readiness mapping without equating attention with processing',()=>{
  expect(releaseProgressState({status:'ready'})).toBe('ready')
  expect(releaseProgressState({status:'released'})).toBe('published')
  expect(releaseProgressState({status:'delivering'})).toBe('processing')
  expect(releaseProgressState({status:'failed'})).toBe('attention')
})
it('requires endpoints, corrected evidence and current artifact receipt for release overlay',()=>{
  const file={file:'a.docx',compliant:true,remediated_at:'2026-09-11T12:00:00Z',corrected_sha256:'new',published_url:'url'}
  const source={files:[]},release={documents:[]}
  expect(confirmedReleaseProgress(file,release,null)).toBeUndefined()
  expect(confirmedReleaseProgress({...file,corrected_sha256:null},release,source)).toBeUndefined()
  expect(confirmedReleaseProgress(file,release,source)).toBe('ready')
  expect(confirmedReleaseProgress(file,{documents:[{file:file.file,status:'published',artifact_digest:'sha256:old'}]},source)).toBe('ready')
  expect(confirmedReleaseProgress(file,{documents:[{file:file.file,status:'published',artifact_digest:'sha256:new'}]},source)).toBe('published')
  expect(confirmedReleaseProgress(file,release,{files:[{file:file.file,state:'conflict'}]})).toBe('attention')
  expect(confirmedReleaseProgress(file,release,source,[{file:file.file,status:'pending'}])).toBe('attention')
})
