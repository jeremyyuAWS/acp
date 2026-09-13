import { act } from 'react'
import { afterEach,expect,it,vi } from 'vitest'
import { createTestRoot,unmountAll } from './testRoots.js'
vi.mock('./api.js',()=>({listHitlQueue:vi.fn(async()=>[{id:1,scan_id:'scan',file:'crop.docx',rule_id:'1.4.5',status:'pending'},{id:2,scan_id:'scan',file:'alt.docx',rule_id:'1.1.1',status:'approved',applied:true,validated:false}]),getRunAiApproval:vi.fn(async()=>({enabled:true,run_id:'repair-run',source_revision:'source'})),getStageProgressQueue:vi.fn()}))
import Workspace,{releaseReviewCount} from './ReleaseReviewWorkspace.jsx'
import Card from './WorkflowStageActivityCard.jsx'
afterEach(async()=>{await unmountAll();vi.useRealTimers();vi.clearAllMocks()})
it('counts only current-scan human items separately from confirmed delivery files in the actual Release card',async()=>{
 const {root,container}=createTestRoot()
 const snapshot={stage:'release',execution_id:'delivery-run',workflow_revision:1,state:'processing',counts:{work_items:{total:3,queued:1,processing:1,completed:1,failed:0,skipped:0,cancelled:0}},reconciliation:{total:3,accounted:3,unaccounted:0,exact:true},integrity:{ok:true},domain_reconciliation:{available:true,total:3,buckets:{waiting:1,processing:1,published:1}}}
 await act(async()=>root.render(<Card snapshot={snapshot} reviewWorkspace={<Workspace scanId="scan" remediationRunId="repair-run"/>}/>))
 const rows=container.querySelectorAll('.workflow-outcome-tiles__grid')
 expect(rows[0].children.length).toBe(3)
 expect(rows[1].children.length).toBe(3)
 expect(rows[1].textContent).toContain('Delivery issues')
 expect(rows[1].textContent).toContain('Skipped')
 expect(rows[1].textContent).toContain('Review workspace1')
 expect(container.querySelectorAll('.remediation-review-workspace')).toHaveLength(1)
})
it('missing scope or unknown rows remain unavailable instead of a fabricated zero',async()=>{
 expect(releaseReviewCount(null,'scan',{enabled:true})).toBeNull()
 expect(releaseReviewCount([{scan_id:'other',rule_id:'1.4.5'}],'scan',{enabled:true})).toBeNull()
 expect(releaseReviewCount([{scan_id:'other',rule_id:'1.4.5'}],'scan',null)).toBeNull()
 const {root,container}=createTestRoot()
 await act(async()=>root.render(<Workspace scanId="scan" remediationRunId={null}/>))
 expect(container.textContent).toContain('Review count unavailable')
 expect(container.querySelector('button').disabled).toBe(true)
})
it('refreshes approval and queue as one confirmed pair when Auto-apply changes elsewhere',async()=>{
 vi.useFakeTimers()
 const {listHitlQueue,getRunAiApproval}=await import('./api.js')
 const row={id:5,scan_id:'scan',file:'alt.docx',rule_id:'1.1.1',status:'pending',proposals:[{proposed_value:'Caption',source:'AI'}]}
 listHitlQueue.mockResolvedValue([row]);getRunAiApproval.mockResolvedValueOnce({enabled:false,run_id:'repair-run',source_revision:'source'}).mockResolvedValue({enabled:true,run_id:'repair-run',source_revision:'source'})
 const {root,container}=createTestRoot()
 await act(async()=>root.render(<Workspace scanId="scan" remediationRunId="repair-run"/>))
 expect(container.textContent).toContain('Review workspace1')
 await act(async()=>{vi.advanceTimersByTime(15000);await Promise.resolve()})
 expect(container.textContent).toContain('Review workspace0')
 expect(container.textContent).toContain('Items needing your input')
})
it('bounds a hung pair and renders unavailable instead of an invented zero',async()=>{
 vi.useFakeTimers()
 const {listHitlQueue,getRunAiApproval}=await import('./api.js')
 listHitlQueue.mockImplementation(()=>new Promise(()=>{}));getRunAiApproval.mockResolvedValue({enabled:true,run_id:'repair-run',source_revision:'source'})
 const {root,container}=createTestRoot()
 await act(async()=>root.render(<Workspace scanId="scan" remediationRunId="repair-run"/>))
 await act(async()=>{vi.advanceTimersByTime(20000);await Promise.resolve()})
 expect(container.textContent).toContain('Review count unavailable')
 expect(container.textContent).not.toContain('Review workspace0')
})
