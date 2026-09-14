import { expect, it } from 'vitest'
import { savedCopyVerificationStatus as status } from './savedCopyVerificationStatus.js'
const file = {remediated_at:'now', corrected_sha256:'abc', compliant:false}
const result = value => ({corrected_copy_assessment:{artifact_sha256:'abc',remediated_at:'now',assessment_ok:true,assessment_status:'analysed',remaining_criteria:[],remaining_issues:[],...value}})
it('distinguishes checked remaining findings from missing and failed checks',()=>{
 expect(status(file,result({remaining_criteria:['1.1.1']}))).toMatchObject({key:'remaining',reason:'Remaining criteria: 1.1.1.'})
 expect(status(file,result({assessment_ok:false,reason:'engine unavailable'}))).toMatchObject({key:'failed',reason:'engine unavailable'})
 expect(status(file,{}).key).toBe('unconfirmed')
 expect(status(file,result({})).key).toBe('passed')
})
it('never uses stale or malformed checks or delivery checksums as accessibility evidence',()=>{
 expect(status(file,result({artifact_sha256:'old'})).key).toBe('unconfirmed')
 expect(status(file,result({remediated_at:'old'})).key).toBe('unconfirmed')
 expect(status(file,result({remaining_issues:undefined})).key).toBe('unconfirmed')
 expect(status(file,{verification:'checksum verified',status:'published'}).key).toBe('unconfirmed')
})

it("does not call unavailable checks passed",()=>expect(status(file,result({skipped_rules:2}))).toMatchObject({key:"unconfirmed",label:"Checks incomplete"}))

it('does not apply an old delivered-copy assessment to newer saved bytes',()=>{
 const oldReceipt = {...result({artifact_sha256:'old'}), status:'published', artifact_digest:'sha256:old'}
 expect(status(file,oldReceipt).key).toBe('unconfirmed')
})
