import { expect, it } from 'vitest'
import { reviewWorkBreakdown } from './reviewWorkBreakdown.js'

it('partitions every recorded row once and never mistakes human judgment for a document edit',()=>{
 const rows=[
  {id:1,status:'verified'},
  {id:2,status:'approved'},
  {id:3,status:'verification_failed'},
  {id:4,status:'pending',aiDraftable:true,rule_id:'1.1.1'},
  {id:5,status:'pending',hasProposal:true,after:'Caption',automaticDisposition:{responsibility:'human'}},
  {id:6,status:'pending',manual:true},
  {id:7,status:'blocked'},
  {id:8,status:'pending',aiDraftable:true,_raw:{reason_code:'vision_pricing_not_verified'}},
 ]
 const counts=reviewWorkBreakdown(rows)
 expect(Object.values(counts).reduce((a,b)=>a+b,0)).toBe(rows.length)
 expect(counts).toEqual({results:1,processing:1,'failed-checks':1,'missing-proposals':1,review:1,manual:1,'status-checks':1,'blocked-ai':1})
})
it('partial proposal coverage is missing draft work rather than a decision-ready suggestion',()=>{
 expect(reviewWorkBreakdown([{id:1,status:'pending',hasProposal:true,after:'Caption',_raw:{finding_count:2},proposals:[{proposed_value:'Caption'}]}])['missing-proposals']).toBe(1)
})
