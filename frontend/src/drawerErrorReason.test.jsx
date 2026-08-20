/**
 * The drawer shows the reason a document failed, from the record — at the DOM level.
 *
 * The unit cases in fileErrorReason.test.js prove the sentences are right. They cannot prove the
 * drawer asks for them, or that it only asks when it should. That is what this file is for, and
 * the split matters: the original defect was not a wrong string, it was a screen that never looked
 * up an answer it already had.
 *
 * Guarded here:
 *   · a failed document shows the RECORDED reason, not the old guess
 *   · a healthy document does not fetch the log at all — it is a per-scan list, and one request
 *     per drawer open to answer a question almost no document is asking is a real cost
 *   · a document whose failure was never logged says so, rather than falling back to "unreadable"
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

const listScanDecisions = vi.fn(async () => ([
  { action: 'scan.file_error', file: 'broken.docx', ts: '2026-08-19T23:00:00Z',
    detail: "HttpError: <HttpError 404 when requesting files/01ABC returned 'File not found'>" },
]))

// FileDrawer imports a long tail of api functions and calls several on mount, and a partial mock
// fails at the FIRST unmocked call inside an effect rather than at import — so every name it
// imports is stubbed inert, and the one under test is spied. Enumerated rather than proxied:
// vitest inspects the module namespace, which a Proxy cannot stand in for.
const inert = async () => null
vi.mock('./api.js', () => ({
  SIM: false,
  listScanDecisions: (...a) => listScanDecisions(...a),
  openTraceUrl: () => {},
  // Every other api export the drawer's TRANSITIVE tree touches, stubbed inert. Enumerated
  // because a partial mock throws at the first unmocked call inside an effect — Thumbnail's
  // getFileThumbnail was the one that surfaced first — and because vitest inspects the module
  // namespace, so a Proxy cannot stand in for it.
  aiProvenance: inert, approveDisposition: inert, assessScan: inert,
  autoPopulateHitlQueue: inert, clearDeadJobs: inert, clearMyScope: inert,
  confirmCriterion: inert, createCampaign: inert, createDispositionPolicy: inert,
  createScopeRule: inert, deleteScopeRule: inert, disposeCriterion: inert,
  downloadRemediated: inert, executeDispositionPolicy: inert, explainFinding: inert,
  fetchCodeset: inert, fetchEligibility: inert, fetchScopeRules: inert,
  fetchScopeSelectors: inert, fetchScopedEligibility: inert, getAiCosts: inert,
  getAiProviders: inert, getAiStatus: inert, getAllowlist: inert, getAppliedFixes: inert,
  getCapability: inert, getConfig: inert, getDigest: inert, getDocumentTimeline: inert,
  getEstate: inert, getExamined: inert, getFileContent: inert, getFileContrast: inert,
  getFileGeometry: inert, getFilePage: inert, getFilePdfContrast: inert,
  getFileRemediationDiffs: inert, getFileRemediationState: inert, getFileResize: inert,
  getFileStatus: inert, getFileThumbnail: inert, getFileTraceData: inert,
  getHitlAnalytics: inert, getInventoryDiff: inert, getJob: inert, getJobs: inert,
  getMyScope: inert, getQueueJob: inert, getRemediationStatus: inert, getRubric: inert,
  getRules: inert, getScan: inert, getScanAiCalls: inert, getScanDiff: inert,
  getScanLocations: inert, getScanPii: inert, getScanRemediationDiffs: inert,
  getScanStatus: inert, getScanTraces: inert, getSchedule: inert, getSessionTraceData: inert,
  getSettings: inert, getSourceStatus: inert, getTraceStatus: inert, inviteTester: inert,
  listAllHitl: inert, listCampaigns: inert, listDispositionApprovals: inert,
  listDispositionAudit: inert, listDispositionPolicies: inert, listDispositions: inert,
  listFolders: inert, listHitlQueue: inert, listSharePointDrives: inert,
  listSharePointSites: inert, listSpFolders: inert, markRemediated: inert, openReport: inert,
  previewDispositionPolicy: inert, publishAllFiles: inert, publishFile: inert,
  putAiProvider: inert, putMyScope: inert, putSchedule: inert, queueHitlReview: inert,
  queueHitlVerify: inert, refreshScanDriveToken: inert, rejectDisposition: inert,
  remediateScan: inert, rescoreFile: inert, resetDemoData: inert, setAllowlist: inert,
  setCampaignStatus: inert, setDispositionPolicyEnabled: inert, setLangfuseBase: inert,
  setScanLocations: inert, setScopeRuleEnabled: inert, setWorkers: inert, suggestFix: inert,
  updateHitlItem: inert, updateSettings: inert, uploadToDrive: inert,
  uploadToSharePoint: inert, validateAlt: inert,
}))

const { default: FileDrawer } = await import('./FileDrawer.jsx')

const failed = { file: 'broken.docx', status: 'error', score: null, issues: [] }
const healthy = { file: 'fine.docx', status: 'analysed', score: 100, compliant: true, issues: [] }

async function open(file, scanId = 'scan-1') {
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(FileDrawer, { file, scanId, onClose: () => {} }))
  })
  return container
}

describe('a document that failed', () => {
  it('shows the reason the scan actually recorded', async () => {
    listScanDecisions.mockClear()
    const c = await open(failed)
    expect(c.textContent).toMatch(/Could not process this file/)
    expect(c.textContent, 'the recorded reason is not on screen').toMatch(/404 when requesting/)
  })

  it('no longer claims the file is unreadable', async () => {
    // The old sentence asserted the file had been READ and was at fault. Both may be false:
    // status='error' is handlers' catch-all over the whole download+analyse block.
    const c = await open(failed)
    expect(c.textContent, 'the "unreadable" guess is back').not.toMatch(/unreadable/i)
  })

  it('orients the reader when the failure was about reaching the source', async () => {
    const c = await open(failed)
    expect(c.textContent).toMatch(/problem reaching the source, not with the document itself/)
  })

  it('says the reason was not recorded rather than inventing one', async () => {
    // A scan that produced no log row for this file — the honest answer is a stated gap.
    listScanDecisions.mockResolvedValueOnce([])
    const c = await open(failed)
    expect(c.textContent).toMatch(/No reason was recorded/)
    expect(c.textContent).not.toMatch(/unreadable/i)
  })

  it('survives the lookup failing, without inventing a cause', async () => {
    listScanDecisions.mockRejectedValueOnce(new Error('network'))
    const c = await open(failed)
    expect(c.textContent).toMatch(/No reason was recorded/)
  })
})

describe('a document that did not fail', () => {
  it('keeps the plain no-findings line', async () => {
    const c = await open(healthy)
    expect(c.textContent).toMatch(/No findings — clean\./)
  })

  it('does not fetch the decision log at all', async () => {
    // The guard that keeps this cheap: the log is per-scan, so an unguarded fetch would cost one
    // request per drawer open across an entire estate to answer a question that only applies to
    // the failures.
    listScanDecisions.mockClear()
    await open(healthy)
    expect(listScanDecisions, 'the decision log was fetched for a healthy document')
      .not.toHaveBeenCalled()
  })

  it('does not fetch without a scan id either', async () => {
    listScanDecisions.mockClear()
    await open(failed, null)
    expect(listScanDecisions).not.toHaveBeenCalled()
  })
})
