import { expect, it } from 'vitest'
import { remediationWorkRunning as running } from './remediationWorkRunning.js'
const snapshot = { batch_id:'current', total_documents:4, state:'completing',
  documents:{completed:2,processing:0,waiting:0,review:2,failed:0,skipped:0},
  delivery:{pending:3}, finding_accounting:{unaccounted:11} }
it('ends the applying indicator when document work drains even while delivery and accounting remain', () => {
  expect(running(snapshot,'current',true,{done:0,total:4})).toBe(false)
})
it('keeps applying for active work and never lets an old or incomplete snapshot end a new batch', () => {
  expect(running({...snapshot,documents:{...snapshot.documents,completed:1,processing:1}},'current',true,null)).toBe(true)
  expect(running(snapshot,'new',true,null)).toBe(true)
  expect(running({...snapshot,documents:{completed:4}},'current',true,null)).toBe(true)
  expect(running({...snapshot,total_documents:5},'current',true,null)).toBe(true)
  expect(running(null,null,false,{done:2,total:4})).toBe(true)
})
