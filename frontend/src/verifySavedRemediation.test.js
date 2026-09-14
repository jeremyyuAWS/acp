import { expect, it, vi } from 'vitest'
import { verifySavedRemediation } from './verifySavedRemediation.js'
const setup = () => ({runId:'scan',item:{file:'brief.docx',scanId:'scan'},canAct:()=>true,
  getReleaseStatus:vi.fn().mockResolvedValue({documents:[{file:'brief.docx',corrected_sha256:'current-digest',artifact_digest:'old-delivery',remediated_at:'saved-version'}]}),
  getScan:vi.fn().mockResolvedValue({run:{id:'scan'},files:[]}),
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

it('verifies a saved copy before a release plan supplies any documents', async () => {
  const args=setup();args.getReleaseStatus.mockResolvedValue({documents:[]})
  args.getScan.mockResolvedValue({run:{id:'scan'},files:[{file:'brief.docx',corrected_sha256:'pre-release-digest',remediated_at:'pre-release-version'}]})
  await verifySavedRemediation(args)
  expect(args.getScan).toHaveBeenCalledWith('scan')
  expect(args.verifySavedCopy).toHaveBeenCalledWith('scan',{file:'brief.docx',corrected_sha256:'pre-release-digest',remediated_at:'pre-release-version'})
})

it('keeps a release identity authoritative without an unnecessary scan read', async () => {
  const args=setup();await verifySavedRemediation(args)
  expect(args.getScan).not.toHaveBeenCalled()
})
it('does not mix a partial release identity with a scan version', async () => {
  const args=setup();args.getReleaseStatus.mockResolvedValue({documents:[{file:'brief.docx',corrected_sha256:'partial-release'}]})
  args.getScan.mockResolvedValue({run:{id:'scan'},files:[{file:'brief.docx',corrected_sha256:'whole-scan-version',remediated_at:'whole-scan-time'}]})
  await verifySavedRemediation(args)
  expect(args.verifySavedCopy).toHaveBeenCalledWith('scan',{file:'brief.docx',corrected_sha256:'whole-scan-version',remediated_at:'whole-scan-time'})
})
it('refuses a different scan returned by the fallback', async () => {
  const args=setup();args.getReleaseStatus.mockResolvedValue({documents:[]})
  args.getScan.mockResolvedValue({run:{id:'other'},files:[{file:'brief.docx',corrected_sha256:'foreign',remediated_at:'time'}]})
  await expect(verifySavedRemediation(args)).rejects.toThrow('current run')
  expect(args.verifySavedCopy).not.toHaveBeenCalled()
})
it('preserves the owner-scoped scan read error without issuing verification', async () => {
  const args=setup();args.getReleaseStatus.mockResolvedValue({documents:[]});args.getScan.mockRejectedValue(new Error('Not found'))
  await expect(verifySavedRemediation(args)).rejects.toThrow('Not found')
  expect(args.verifySavedCopy).not.toHaveBeenCalled()
})
it('refuses ambiguous saved records rather than choosing a version', async () => {
  const args=setup();args.getReleaseStatus.mockResolvedValue({documents:[]})
  const record={file:'brief.docx',corrected_sha256:'digest',remediated_at:'time'}
  args.getScan.mockResolvedValue({run:{id:'scan'},files:[record,record]})
  await expect(verifySavedRemediation(args)).rejects.toThrow('saved copy version is unavailable')
  expect(args.verifySavedCopy).not.toHaveBeenCalled()
})
it('does not verify when the user switches to history during the scan read', async () => {
  const args=setup();let current=true;args.canAct=()=>current;args.getReleaseStatus.mockResolvedValue({documents:[]})
  args.getScan.mockImplementation(async()=>{current=false;return {run:{id:'scan'},files:[{file:'brief.docx',corrected_sha256:'digest',remediated_at:'time'}]}})
  await expect(verifySavedRemediation(args)).rejects.toThrow('current run')
  expect(args.verifySavedCopy).not.toHaveBeenCalled()
})
