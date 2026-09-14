import { expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { checkSelfRemediation } from './checkSelfRemediation.js'
const item = { id: 'item', file: 'brief.docx', rule_id: '1.1.1' }
it('does not certify a manual fix when verification transport fails', async () => {
  expect(await checkSelfRemediation(item, vi.fn().mockRejectedValue(new Error('Connection lost')))).toMatchObject({status:'error',verificationMessage:'Connection lost'})
})
it('keeps the failed criterion visible after a successful saved-copy assessment', async () => {
  expect(await checkSelfRemediation(item, vi.fn().mockResolvedValue({assessment_ok:true,remaining_criteria:['1.1.1']}))).toMatchObject({status:'checked',verificationMessage:expect.stringContaining('still reports WCAG 1.1.1')})
})
it('does not turn absence of a detector finding into semantic approval', async () => {
  expect(await checkSelfRemediation(item, vi.fn().mockResolvedValue({assessment_ok:true,remaining_criteria:[]}))).toMatchObject({status:'checked',verificationMessage:expect.stringContaining('does not approve')})
})
it('refuses incomplete assessments and successful job status without measured findings', async () => {
  expect(await checkSelfRemediation(item, vi.fn().mockResolvedValue({status:'done'}))).toMatchObject({status:'error'})
})
it('the live self-remediation action checks saved bytes instead of certifying rescore job completion', () => {
  const source=readFileSync('src/Remediate.jsx','utf8')
  const action=source.slice(source.indexOf('const rescan ='),source.indexOf('const verified ='))
  expect(action).not.toContain('rescoreFile(')
  expect(action).not.toContain("status: 'verified'")
  expect(action).toContain('checkSelfRemediation(item, verifySaved)')
})
