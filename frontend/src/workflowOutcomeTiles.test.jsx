import { renderToStaticMarkup } from 'react-dom/server'
import { expect, it } from 'vitest'
import Card from './WorkflowStageActivityCard.jsx'
import Tiles, { outcomeTileModel } from './WorkflowOutcomeTiles.jsx'
const findingDomain = { total:30,accounted:30,exact:true,buckets:{resolved_verified:12,awaiting_review:5,approved_pending_verification:3,unchanged_no_fix:2,failed:1,excluded:1,superseded:1,awaiting_recorded_outcome:5} }
it('groups every finding once with verified separate from approved work',()=> {
 const result=outcomeTileModel('remediate',findingDomain)
 expect(result.tiles.map(tile=>[tile.label,tile.value])).toEqual([['Queued',5],['Applying & checking',3],['Needs attention',8],['Verified fixes',12],['Excluded',2]])
 expect(result.tiles.reduce((sum,tile)=>sum+tile.value,0)).toBe(30)
})
it('removes both stage bars and exposes large tiles with collapsed outcome details',()=> {
 for(const stage of ['remediate','release']) {
 const domain=stage==='remediate'?findingDomain:{total:4,accounted:4,buckets:{waiting:1,processing:1,published:1,completed_unverified:1}}
 const html=renderToStaticMarkup(<Card snapshot={{stage,execution_id:'run',domain_reconciliation:domain}} />)
 expect(html).not.toContain('role="progressbar"')
 expect(html).toContain('workflow-outcome-tiles__grid')
 expect(html).toContain('<summary>Outcome details</summary>')
 expect(html).not.toContain('<details open')
 expect(html).toContain('Before unavailable')
 }
})
it('counts delivered unverified copies as published without implying verification',()=> {
 const result=outcomeTileModel('release',{total:7,buckets:{waiting:1,processing:1,published:1,completed_unverified:1,failed:1,cancelled:1,skipped:1}})
 expect(result.tiles.map(tile=>tile.value)).toEqual([1,1,2,2,1])
 const html=renderToStaticMarkup(<Tiles stage="release" domain={{total:2,buckets:{published:1,completed_unverified:1}}} />)
 expect(html).toContain('delivered copies with remaining issues')
})
it('withholds misleading counts when the partition does not balance',()=> {
 expect(outcomeTileModel('remediate',{total:2,buckets:{resolved_verified:3}}).tiles.every(tile=>tile.value===null)).toBe(true)
})
it('shows only admission baselines bound to the same run and scope',()=> {
 const baseline={available:true,run_id:'run',findings:{queued:30,processing:0,attention:0,verified:0,excluded:0}}
 const html=renderToStaticMarkup(<Tiles stage="remediate" domain={findingDomain} executionId="run" baseline={baseline} />)
 expect(html).toContain('Before: 30')
 expect(html).toContain('−25 since starting')
 expect(html).toContain('+12 since starting')
 const other=renderToStaticMarkup(<Tiles stage="remediate" domain={findingDomain} executionId="other" baseline={baseline} />)
 expect(other).toContain('Before unavailable')
 expect(other).not.toContain('since starting')
})
it('keeps publication failures visible as Delivery issues without duplicating finding attention',()=>{
 const model=outcomeTileModel('release',{total:2,buckets:{published:1,failed:1}})
 expect(model.tiles.find(tile=>tile.key==='attention')).toMatchObject({label:'Delivery issues',value:1})
 expect(model.tiles.some(tile=>tile.label==='Needs attention')).toBe(false)
})
