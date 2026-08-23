/**
 * FileDrawer's Assessment Timeline, at the DOM level: a failed read must not read as an empty one.
 *
 * `api.getDocumentTimeline` rejects on a transport failure rather than resolving to [], so this
 * panel has two distinct things to say. Before that change it had one, and the panel's own
 * "No recorded events for this document yet" answered both — a sentence about the DOCUMENT
 * standing in for a fact about the REQUEST.
 *
 * DOM-level, not source-level: the sibling assessmentTimeline.test.js reads FileDrawer.jsx as
 * text, which cannot show that the catch is wired to the render. This mounts the drawer, opens
 * the panel, and reads what a person would see. (This repo's preview server runs vite rooted at
 * the SHARED checkout whatever worktree you are in — CLAUDE.md — so a browser check would
 * exercise code without this change in it.)
 */
import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
import { createElement } from 'react'
import { act } from 'react-dom/test-utils'
import { createTestRoot, unmountAll } from './testRoots.js'

afterEach(unmountAll)

const getDocumentTimeline = vi.fn()
const inert = async () => null

// A REAL status model — a null one renders very little, and the panel assertions below would then
// pass for the wrong reason. Same shape drawerErrorReason.test.jsx uses.
const STATUS_MODEL = {
  available: true, state: 'ready_after_review', needs_review: 8, resolved: 4, in_scope: 38,
  documents: 1, not_automatically_assessable: 26, est_review_secs: 360,
  coverage: { evaluable: 12, total: 38 },
  segments: {}, criteria: [],
}
vi.mock('./api.js', () => ({
  SIM: false,
  listScanDecisions: inert,
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
  getCapability: inert, getConfig: inert, getDigest: inert,
  getDocumentTimeline: (...a) => getDocumentTimeline(...a),
  getEstate: inert, getExamined: inert, getFileContent: inert, getFileContrast: inert,
  getFileGeometry: inert, getFilePage: inert, getFilePdfContrast: inert,
  getFileRemediationDiffs: inert, getFileRemediationState: inert, getFileResize: inert,
  getFileStatus: async () => STATUS_MODEL, getFileThumbnail: inert, getFileTraceData: inert,
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
  getWorkerReplicas: inert, setWorkerReplicas: inert,
  updateHitlItem: inert, updateSettings: inert, uploadToDrive: inert,
  uploadToSharePoint: inert, validateAlt: inert,
}))

const { default: FileDrawer } = await import('./FileDrawer.jsx')

const doc = { file: 'a.docx', status: 'analysed', score: 90, compliant: false, issues: [] }

beforeEach(() => { getDocumentTimeline.mockReset() })

const flush = async () => { await act(async () => { await Promise.resolve(); await Promise.resolve() }) }

// The timeline only fetches once its <details> is opened, so the panel must actually be opened
// rather than assumed present.
async function openTimeline() {
  const { root, container } = createTestRoot()
  await act(async () => {
    root.render(createElement(FileDrawer, { file: doc, scanId: 'scan-1', onClose: () => {} }))
  })
  await flush()
  const summary = [...container.querySelectorAll('summary')]
    .find((s) => /Assessment Timeline/.test(s.textContent))
  expect(summary, 'the Assessment Timeline panel should be present').toBeTruthy()
  const details = summary.closest('details')
  await act(async () => {
    details.open = true
    details.dispatchEvent(new Event('toggle'))
  })
  await flush()
  return details
}

describe('Assessment Timeline — a failed read is not an empty history', () => {
  it('a rejected read says it could not be loaded, and carries the reason', async () => {
    getDocumentTimeline.mockRejectedValue(new Error('timeline unavailable'))
    const details = await openTimeline()
    expect(details.textContent).toMatch(/could not be loaded/i)
    expect(details.textContent).toMatch(/timeline unavailable/)
  })

  it('a rejected read does NOT claim the document has no recorded events', async () => {
    // The substitution this file exists to prevent.
    getDocumentTimeline.mockRejectedValue(new Error('timeline unavailable'))
    const details = await openTimeline()
    expect(details.textContent).not.toMatch(/No recorded events/i)
  })

  it('a rejected read does not sit on "loading…" forever', async () => {
    // Without the catch the promise never settles into state and the panel stays mid-load, which
    // is how this would have regressed silently once the api layer stopped swallowing.
    getDocumentTimeline.mockRejectedValue(new Error('boom'))
    const details = await openTimeline()
    expect(details.textContent).not.toMatch(/loading/i)
  })

  it('a genuinely empty history still reads as an empty history', async () => {
    getDocumentTimeline.mockResolvedValue([])
    const details = await openTimeline()
    expect(details.textContent).toMatch(/No recorded events/i)
    expect(details.textContent).not.toMatch(/could not be loaded/i)
  })

  it('recorded events still render', async () => {
    getDocumentTimeline.mockResolvedValue([
      { ts: '2026-08-20T10:00:00Z', kind: 'scan', title: 'Scan started (drive)' },
    ])
    const details = await openTimeline()
    // The panel groups events into pipeline stages and shows each event's own title only once its
    // stage is expanded, so the read-succeeded signal is the stage going from ⬜ pending to a
    // counted, timestamped node — not the event title being on screen.
    expect(details.textContent).toMatch(/1 recorded events/)
    expect(details.textContent).toMatch(/Scanned/)
    expect(details.textContent).toMatch(/1 event/)
    expect(details.textContent).not.toMatch(/could not be loaded/i)
    expect(details.textContent).not.toMatch(/No recorded events/i)
  })
})
