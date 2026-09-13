import { expect, it } from 'vitest'
import { normalizeApprovalPolicy, approvalForCriterion, criterionCapabilityDescription } from './assessApprovalPolicy.js'
it('separates approval from scope and filters stale unselected SC overrides',()=>{
 expect(normalizeApprovalPolicy({mode:'custom',review_scs:['1.1.1','1.1.1','2.4.2']},['1.1.1'])).toEqual({mode:'custom',review_scs:['1.1.1']})
 expect(approvalForCriterion({mode:'custom',review_scs:['1.1.1']},'1.1.1')).toBe('review')
 expect(approvalForCriterion({mode:'custom',review_scs:['1.1.1']},'2.4.2')).toBe('automatic')
})
it('unknown saved modes fail closed instead of implying authorization',()=>{
 expect(normalizeApprovalPolicy({mode:'bogus'},['1.1.1']).mode).toBe('review')
 expect(approvalForCriterion(null,'1.1.1')).toBe('review')
})
it('does not promise unsupported PDF tagging because Word supports the same SC',()=>{
 const rows=criterionCapabilityDescription('1.3.1',['docx','pdf'],{docx:{'1.3.1':'auto'},pdf:{'1.3.1':'human'}})
 expect(rows[0].label).toContain('Supported automatic')
 expect(rows[1].label).toContain('Document edit or unsupported')
})

it('switching away from custom clears exceptions before the backend receives the choice', () => {
 const selected=['1.1.1']
 expect(normalizeApprovalPolicy({mode:'automatic',review_scs:selected},selected)).toEqual({mode:'automatic',review_scs:[]})
 expect(normalizeApprovalPolicy({mode:'review',review_scs:selected},selected)).toEqual({mode:'review',review_scs:[]})
})
