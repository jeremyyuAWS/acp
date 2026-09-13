import { expect,it } from 'vitest'
import {automaticReviewResponsibility as responsibility,matchesAutomaticReview} from './automaticReviewResponsibility.js'
const alt={id:1,file:'a.docx',rule_id:'1.1.1',status:'pending'}
it('missing proposals have status checks, never invented automatic jobs or fixed outcomes',()=>{expect(responsibility(alt)).toBe('check');expect(matchesAutomaticReview(alt,'review',{},true)).toBe(false);expect(matchesAutomaticReview(alt,'status-check',{},true)).toBe(true)})
it('same-file manual crop remains an actionable exception and no severity filter applies',()=>{expect(responsibility({...alt,id:2,rule_id:'1.4.5',severity:'MINOR'})).toBe('human');expect(responsibility({...alt,severity:'CRITICAL'})).toBe('check')})
it('admitted application is ACP pending while explicit manual assignment stays human',()=>{expect(responsibility({...alt,automaticQueued:true})).toBe('acp');expect(responsibility(alt,{1:{state:'assigned'}})).toBe('human')})
it('stale or failed admission is a status check rather than false processing',()=>{expect(responsibility({...alt,automaticDisposition:{state:'blocked',responsibility:'check'}})).toBe('check')})
it('provenance judgment and evidence contradiction require human action',()=>{expect(responsibility({...alt,automaticDisposition:{state:'review_required',responsibility:'human'}})).toBe('human')})
it('automatic off keeps the full standard queue reachable',()=>{expect(matchesAutomaticReview(alt,'review',{},false)).toBe(true);expect(matchesAutomaticReview(alt,'all',{},true)).toBe(true)})
it('applied unverified without an active job needs a verification check, never another approval or false processing',()=>{
 const row={...alt,status:'approved',applied:true,validated:false,automaticDisposition:{state:'blocked',responsibility:'check'}}
 expect(responsibility(row)).toBe('check')
 expect(matchesAutomaticReview(row,'review',{},true)).toBe(false)
 expect(matchesAutomaticReview(row,'awaiting-validation',{},true)).toBe(false)
 expect(matchesAutomaticReview(row,'status-check',{},true)).toBe(true)
})
