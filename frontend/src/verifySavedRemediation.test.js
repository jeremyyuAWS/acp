import { expect, it, vi } from 'vitest'
import { verifySavedRemediation } from './verifySavedRemediation.js'
const setup = () => ({runId:'scan',item:{file:'brief.docx',scanId:'scan'},canAct:()=>true,
  getReleaseStatus:vi.fn().mockResolvedValue({documents:[{file:'brief.docx',corrected_sha256:'current-digest',artifact_digest:'old-delivery',remediated_at:'saved-version'}]}),
  verifySavedCopy:vi.fn().mockResolvedValue({corrected_copy_assessment:{assessment_ok:true,remaining_issues:[]}})})
it('binds verification to the current saved version rather than the delivery digest', async () => {
  const args=setup()
  await verifySavedRemediation(args)
  expect(args.verifySavedCopy).toHaveBeenCalledWith('scan',{file:'brief.docx',corrected_sha256:'current-digest',remediated_at:'saved-version'})
})
it('refuses absent saved lineage without issuing a verification request', async () => {
  const args=setup();args.getReleaseStatus.mockResolvedValue({documents:[]})
  await expect(verifySavedRemediation(args)).rejects.toThrow('saved copy version is unavailable')
  expect(args.verifySavedCopy).not.toHaveBeenCalled()
})
it('refuses a different run before reading or writing', async () => {
  const args=setup();args.item.scanId='other'
  await expect(verifySavedRemediation(args)).rejects.toThrow('current run')
  expect(args.getReleaseStatus).not.toHaveBeenCalled()
})
it('does not issue a write when the user switches into history during the read', async () => {
  const args=setup();let current=true;args.canAct=()=>current
  args.getReleaseStatus.mockImplementation(async()=>{current=false;return{documents:[{file:'brief.docx',corrected_sha256:'digest',remediated_at:'version'}]}})
  await expect(verifySavedRemediation(args)).rejects.toThrow('current run')
  expect(args.verifySavedCopy).not.toHaveBeenCalled()
})
