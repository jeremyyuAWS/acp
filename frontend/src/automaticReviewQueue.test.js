import { expect, it } from 'vitest'
import { automaticReviewQueue } from './automaticReviewQueue.js'
import { workflowCounts } from './remediationInboxModel.js'
import { remediationReviewCounts } from './remediationCountSummary.js'
const policy={enabled:true,supported:true,run_id:'run',source_revision:'source'}
const row={id:'proposal',file:'a.docx',status:'pending',hasProposal:true,after:'Alternative text',proposals:[{proposed_value:'Alternative text',source:'AI',model:'vision',model_call_id:'call'}],_raw:{finding_count:1,proposal_snapshot_ids:['snapshot'],source_revision:'source',decision_version:0,automatic_approval:{run_id:'run',source_revision:'source',state:'queued'}}}
it('moves only exact admitted automatic proposals out of human review into Processing, never Completed',()=>{
 const queue=automaticReviewQueue([row],policy)
 expect(queue[0].automaticQueued).toBe(true)
 expect(workflowCounts(queue)).toMatchObject({'needs-review':0,'awaiting-validation':1,completed:0})
 expect(remediationReviewCounts(queue).pendingItems).toBe(0)
 expect(row.automaticQueued).toBeUndefined()
 expect(row.status).toBe('pending')
})
it('retains manual, failed, rejected, stale and unadmitted work requiring input',()=>{
 const rows=[{...row,id:'manual',hasProposal:false,after:'',proposals:[]},{...row,id:'failed',status:'verification_failed'},{...row,id:'stale',stale:true},{...row,id:'missing',_raw:{...row._raw,proposal_snapshot_ids:[]}},{...row,id:'other',_raw:{...row._raw,automatic_approval:{...row._raw.automatic_approval,run_id:'other'}}}]
 expect(automaticReviewQueue(rows,policy).every(row=>!row.automaticQueued)).toBe(true)
 expect(automaticReviewQueue([row],{...policy,enabled:false})[0].automaticQueued).toBeUndefined()
 expect(automaticReviewQueue([row],null)[0].automaticQueued).toBeUndefined()
 expect(automaticReviewQueue([row],policy,{proposal:{state:'rejected'}})[0].automaticQueued).toBeUndefined()
})
it('does not put optional auto/verify inspections back into the actionable human queue',()=>{
 const queue=automaticReviewQueue([{...row,rule_id:'auto/verify',inspectionOnly:true}],policy)
 expect(workflowCounts(queue)).toMatchObject({completed:1,'needs-review':0,'awaiting-validation':0})
})
