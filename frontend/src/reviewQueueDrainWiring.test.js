import {expect,it} from 'vitest'
import {readFileSync} from 'node:fs'
it('Remediate supplies confirmed consent and all server progress to its single queue reader',()=>{
 const source=readFileSync('src/Remediate.jsx','utf8')
 const integration=source.slice(source.indexOf('const refreshReviewQueue = useReviewQueueRefresh'),source.indexOf('const hasRemediationResults'))
 expect(integration).toContain('approval: runAiApproval.policy')
 expect(integration).toContain('batchId: acceptedBatchId')
 for(const field of ['snapshot?.revision','snapshot?.review?.items','snapshot?.fixes?.applied','snapshot?.documents?.completed','status?.queued','status?.running','events?.[0]?.id'])expect(integration).toContain(`runStream?.${field}`)
 expect(integration).toContain('applyHitlRows(items)')
 expect(integration).toContain('isAiAssistedDraft(row)')
 expect(source).not.toContain('listHitlQueue(runId)')
})
