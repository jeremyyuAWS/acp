import { useEffect,useState } from 'react'
import InfoTip from './InfoTip.jsx'
import { listHitlQueue,getRunAiApproval } from './api.js'
import { authEpoch } from './apiIdentity.js'
import { automaticReviewQueue } from './automaticReviewQueue.js'
import { remediationReviewCounts } from './remediationCountSummary.js'
import './workflow-outcome-tiles.css'

export function releaseReviewCount(rows,scanId,policy) {
  if (!Array.isArray(rows) || !policy || policy.scan_id && policy.scan_id!==scanId || rows.some(row=>row.scan_id!==scanId)) return null
  const mapped=rows.filter(row=>row.scan_id===scanId && !row.superseded).map(row=>({...row,_raw:row,scanId:row.scan_id,hasProposal:(row.proposals||[]).some(p=>p.proposed_value),after:(row.proposals||[]).find(p=>p.proposed_value)?.proposed_value || row.approved_value || null,inspectionOnly:row.inspection_only===true || row.rule_id==='auto/verify',autoApplied:row.rule_id==='auto/verify'}))
  return remediationReviewCounts(automaticReviewQueue(mapped,policy),{}, {},policy.enabled===true && policy.supported!==false).pendingItems
}
// Release uses the remediation execution for review consent, independently of
// its delivery execution. Missing scope/data is unavailable, never zero items.
export default function ReleaseReviewWorkspace({scanId,remediationRunId,refreshRevision,onOpenReview}) {
  const epoch=authEpoch(),identity=`${epoch}:${scanId}:${remediationRunId}`
  const [result,setResult]=useState(null)
  useEffect(()=>{
    if (!scanId || !remediationRunId) return undefined
    let current=true,pending=false,controller=null,deadline=null
    const load=async()=>{
      if (pending) return
      pending=true
      controller=new AbortController()
      try {
        const timeout=new Promise((_,reject)=>{deadline=setTimeout(()=>{controller.abort();reject(new Error('Review status timed out'))},20000)})
        const [rows,policy]=await Promise.race([Promise.all([listHitlQueue(scanId,null,{signal:controller.signal}),getRunAiApproval(scanId,remediationRunId,{signal:controller.signal})]),timeout])
        if(current && authEpoch()===epoch)setResult({identity,rows,policy})
      }
      catch {if(current && authEpoch()===epoch)setResult({identity,rows:null,policy:null})}
      finally {clearTimeout(deadline);deadline=null;pending=false}
    }
    load()
    const refresh=load
    const timer=setInterval(refresh,15000)
    window.addEventListener('acp:hitl-changed',refresh)
    return()=>{current=false;controller?.abort();clearTimeout(deadline);clearInterval(timer);window.removeEventListener('acp:hitl-changed',refresh)}
  },[identity,refreshRevision])
  const count=result?.identity===identity && remediationRunId && result.policy?.run_id===remediationRunId && result.policy.source_revision!=null ? releaseReviewCount(result.rows,scanId,result.policy) : null
  return <div className="workflow-outcome-tiles__cell tone-amber remediation-review-workspace">
    <button type="button" className="workflow-outcome-tiles__tile" onClick={onOpenReview} disabled={!onOpenReview || !scanId || !remediationRunId}>
      <span className="workflow-outcome-tiles__label">Review workspace</span><strong>{count===null ? '—' : count.toLocaleString()}</strong>
      <span className="workflow-outcome-tiles__definition">{count===null ? 'Review count unavailable' : result?.policy?.enabled===true && result.policy.supported!==false ? 'Items needing your input' : 'Unresolved review items'}</span><span className="workflow-outcome-tiles__definition">Open review items →</span>
    </button>
    <InfoTip label="Review workspace">Review items from this scan’s current remediation run. One item can cover multiple findings. This item count is separate from publication file totals and does not mean delivery failed.</InfoTip>
  </div>
}
